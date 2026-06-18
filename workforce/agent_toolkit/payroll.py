"""Payroll layer — enforces the token-budget "salaries" defined in roster.yaml.

Each agent is an "employee" with a salary: a token budget per `policy.budget_period`.
This module is the HR/payroll ledger that tracks what each worker has spent against its
salary, decides whether it is over budget, and — when a worker wants to keep working past
its budget — routes a "raise request" through the human-in-the-loop approval gate.

Design notes:
- The ledger is a tiny on-disk JSON keyed by (agent, period_key). `period_key` is an
  EXPLICIT parameter (default "current") and never embeds wall-clock time, so unit tests
  are deterministic.
- LangSmith reconciliation is FAIL-SAFE: it returns None on any error (missing creds,
  network, SDK shape drift) and NEVER crashes a run.
- Hiring/firing and raises are CONSEQUENTIAL → they go through `request_approval`. No silent
  budget overrides (roster policy: hire_fire_requires_approval).
- NEVER hardcode secrets: all credentials are read from the environment.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Optional

import yaml

from .approval import request_approval

# --- Paths -------------------------------------------------------------------
# roster.yaml lives at the repo root (two levels up from this file:
# agent_toolkit/payroll.py -> agent_toolkit/ -> <repo root>/).
_REPO_ROOT = Path(__file__).resolve().parent.parent
ROSTER_PATH = _REPO_ROOT / "roster.yaml"
LEDGER_DIR = _REPO_ROOT / ".payroll"
LEDGER_PATH = LEDGER_DIR / "ledger.json"

# Serialize ledger read-modify-write so concurrent agents don't clobber the file.
_LEDGER_LOCK = threading.Lock()


class BudgetExceeded(Exception):
    """Raised when a worker tries to spend past its salary without an approved raise."""


# --- Roster ------------------------------------------------------------------
def load_roster(path: str | os.PathLike[str] | None = None) -> dict:
    """Parse roster.yaml and return the org/payroll record.

    Returns a dict with:
      - ``policy``: {budget_period, firing_criteria, hire_fire_requires_approval, ...}
      - ``org``:    the raw org chart (hr/team_lead/workers)
      - ``agents``: {agent_name: {role, grade, schedule, salary_tokens_per_week, status, ...}}

    Raises FileNotFoundError if the roster is missing (configuration error, not a runtime
    fail-safe path).
    """
    roster_path = Path(path) if path is not None else ROSTER_PATH
    with open(roster_path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}

    policy = data.get("policy", {}) or {}
    agents = data.get("agents", {}) or {}

    # Surface the policy fields the payroll layer cares about explicitly (with the rest of
    # the policy carried through untouched).
    exposed_policy = dict(policy)
    exposed_policy.setdefault("budget_period", policy.get("budget_period"))
    exposed_policy.setdefault("firing_criteria", policy.get("firing_criteria", {}) or {})
    exposed_policy.setdefault(
        "hire_fire_requires_approval", policy.get("hire_fire_requires_approval", True)
    )

    normalized_agents: dict[str, dict] = {}
    for name, record in (agents or {}).items():
        record = record or {}
        normalized_agents[name] = {
            "role": record.get("role"),
            "grade": record.get("grade"),
            "schedule": record.get("schedule"),
            "salary_tokens_per_week": record.get("salary_tokens_per_week"),
            "status": record.get("status"),
            # Keep the scorecard (and any extra fields) available to callers.
            "scorecard": record.get("scorecard", {}) or {},
        }

    return {
        "policy": exposed_policy,
        "org": data.get("org", {}) or {},
        "agents": normalized_agents,
    }


def _agent_record(agent: str, *, roster: dict | None = None) -> dict:
    roster = roster if roster is not None else load_roster()
    record = roster.get("agents", {}).get(agent)
    if record is None:
        raise KeyError(f"Unknown agent '{agent}' — not in roster.yaml")
    return record


# --- Ledger ------------------------------------------------------------------
def _read_ledger() -> dict:
    """Load the JSON ledger from disk; an absent/corrupt file reads as empty."""
    try:
        with open(LEDGER_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _write_ledger(data: dict) -> None:
    """Persist the ledger, creating the .payroll directory on demand."""
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    tmp = LEDGER_PATH.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
    os.replace(tmp, LEDGER_PATH)  # atomic on POSIX


def _ledger_key(agent: str, period_key: str) -> str:
    return f"{agent}::{period_key}"


def record_spend(agent: str, tokens: int, *, period_key: str = "current") -> int:
    """Add ``tokens`` to ``agent``'s spend for ``period_key``. Returns the new total.

    Negative ``tokens`` (e.g. a correction/refund) are allowed but the running total is
    floored at 0.
    """
    key = _ledger_key(agent, period_key)
    with _LEDGER_LOCK:
        ledger = _read_ledger()
        current = int(ledger.get(key, 0))
        ledger[key] = max(0, current + int(tokens))
        _write_ledger(ledger)
        return ledger[key]


def spent(agent: str, *, period_key: str = "current") -> int:
    """Tokens ``agent`` has spent in ``period_key`` (0 if no entry)."""
    ledger = _read_ledger()
    return int(ledger.get(_ledger_key(agent, period_key), 0))


def salary(agent: str, *, roster: dict | None = None) -> int:
    """The agent's salary (token budget) per the roster's budget_period.

    Returns 0 if no salary is configured (e.g. TBD / null in the roster).
    """
    record = _agent_record(agent, roster=roster)
    value = record.get("salary_tokens_per_week")
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def remaining(
    agent: str, *, period_key: str = "current", roster: dict | None = None
) -> int:
    """Salary minus spend for the period (can go negative if over budget)."""
    return salary(agent, roster=roster) - spent(agent, period_key=period_key)


def is_over_budget(
    agent: str, *, period_key: str = "current", roster: dict | None = None
) -> bool:
    """True when the agent has spent at least its full salary for the period."""
    return remaining(agent, period_key=period_key, roster=roster) <= 0


# --- LangSmith reconciliation (fail-safe) ------------------------------------
def reconcile_with_langsmith(
    agent: str, *, limit: int = 100
) -> Optional[dict]:
    """Read the agent's recent LangSmith run token/cost totals. FAIL-SAFE.

    Returns a dict like
        {"agent": ..., "run_count": N, "total_tokens": T, "total_cost": C}
    or ``None`` if credentials are absent or anything goes wrong. NEVER raises.

    Credentials are read from the environment (never hardcoded):
      - LANGSMITH_API_KEY
      - LANGSMITH_WORKSPACE_ID
    The LangSmith project searched defaults to the agent name, overridable via
    LANGSMITH_PROJECT.
    """
    api_key = os.environ.get("LANGSMITH_API_KEY")
    workspace_id = os.environ.get("LANGSMITH_WORKSPACE_ID")
    if not api_key or not workspace_id:
        return None

    try:
        from langsmith import Client  # imported lazily so the toolkit imports without it

        client = Client(api_key=api_key)
        project = os.environ.get("LANGSMITH_PROJECT", agent)

        total_tokens = 0
        total_cost = 0.0
        run_count = 0
        for run in client.list_runs(project_name=project, limit=limit):
            run_count += 1
            tokens = getattr(run, "total_tokens", None)
            if tokens is None:
                # Fall back to prompt+completion if the aggregate field is absent.
                prompt = getattr(run, "prompt_tokens", 0) or 0
                completion = getattr(run, "completion_tokens", 0) or 0
                tokens = prompt + completion
            total_tokens += int(tokens or 0)
            cost = getattr(run, "total_cost", None)
            if cost is not None:
                total_cost += float(cost)

        return {
            "agent": agent,
            "project": project,
            "workspace_id": workspace_id,
            "run_count": run_count,
            "total_tokens": total_tokens,
            "total_cost": total_cost,
        }
    except Exception:
        return None  # fail-safe: payroll reconciliation must never break a run


# --- Raise requests (human-approved) -----------------------------------------
def request_raise(
    agent: str,
    needed_tokens: int,
    *,
    period_key: str = "current",
    roster: dict | None = None,
    reason: str | None = None,
) -> dict:
    """A worker over (or about to exceed) budget "clocks out" or asks for a raise.

    Routes through the human-in-the-loop approval gate (`request_approval`). Hiring, firing,
    and salary changes are consequential per roster policy, so a human must approve. Returns
    the approval gate's resume value (treat anything that is not an explicit approve as a
    reject — see `agent_toolkit.is_approved`).
    """
    roster = roster if roster is not None else load_roster()
    record = _agent_record(agent, roster=roster)
    payload = {
        "agent": agent,
        "role": record.get("role"),
        "grade": record.get("grade"),
        "status": record.get("status"),
        "period_key": period_key,
        "salary_tokens_per_period": salary(agent, roster=roster),
        "spent_tokens": spent(agent, period_key=period_key),
        "remaining_tokens": remaining(agent, period_key=period_key, roster=roster),
        "needed_tokens": int(needed_tokens),
        "budget_period": roster.get("policy", {}).get("budget_period"),
        "reason": reason,
    }
    return request_approval("payroll.raise", payload, risk="high")


def charge(
    agent: str,
    tokens: int,
    *,
    period_key: str = "current",
    roster: dict | None = None,
) -> int:
    """Record a spend, but refuse to push the agent over budget without an approved raise.

    Raises ``BudgetExceeded`` if the agent is already over budget (the caller should
    `request_raise` and only proceed on an approved decision). Otherwise records the spend
    and returns the new total. This is the enforcing entry point; `record_spend` is the raw
    bookkeeping primitive.
    """
    if is_over_budget(agent, period_key=period_key, roster=roster):
        raise BudgetExceeded(
            f"{agent} is over budget for period '{period_key}' "
            f"(salary={salary(agent, roster=roster)}, "
            f"spent={spent(agent, period_key=period_key)}). "
            "Call request_raise() and proceed only on an approved decision."
        )
    return record_spend(agent, tokens, period_key=period_key)
