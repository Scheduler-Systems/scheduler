"""Per-agent + fleet spend/health MONITOR — the structural backstop for the metering-bug
class the CFO caught by hand (enforcement ran on a local ledger ~1000x too low vs LangSmith's
real numbers).

This module is OBSERVABILITY, not enforcement. The kill-switch lives in
``payroll.is_over_budget`` / ``budget.check_clocked_in``; what was missing was a *sweep* that
watches the REAL burn for the whole fleet and SHOUTS when an agent blows past its salary or the
fleet blows past ``policy.team_token_budget`` — so a 1000x metering gap can never sit silent again.

Design contract
---------------
- ``check_fleet(roster=None, *, usage_reader=None) -> list[alert]`` is PURE: it reads each agent's
  REAL burn through an INJECTABLE ``usage_reader`` (so unit tests need no network), compares it to
  the agent's salary, and sums real burn vs ``policy.team_token_budget``. It returns a list of alert
  dicts. It NEVER raises and it NEVER benches/blocks — report-only.

- FAIL-SAFE: any per-agent error, or ``None``/missing usage for an agent, SKIPS that agent (no
  false alert, no crash). One bad agent never aborts the sweep, and a fleet total is only computed
  from the agents that actually reported usage.

- An alert is a plain dict::

      {"level": "warn"|"critical", "agent": <slug>|"FLEET", "real_tokens": int,
       "limit": int, "pct": float, "message": str}

- DEDUP: ``deliver`` / ``run_once`` only fire an alert when its *state bucket* changes (a small
  on-disk last-state file). The same over-budget condition sweep-after-sweep posts ONCE, not every
  sweep — until it crosses a new threshold band or clears.

- ``deliver`` posts via ``slack_tool.post_digest`` (keeps the injection-defense strip) and
  ``run_once`` / ``run_loop`` are the runnable wiring, kept SEPARATE from the pure ``check_fleet``.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from . import payroll
from .policy import ModelWorkBlocked, assert_not_model_work
from .slack_tool import post_digest

# --- Tunables ----------------------------------------------------------------
# Fraction of salary/budget at which we start warning (below this = silent/healthy).
WARN_PCT = 0.90
# At/over salary or budget = critical.
CRITICAL_PCT = 1.00
# Absolute fallback ceiling (tokens) used to judge an agent whose salary is TBD/null
# (``payroll.salary`` returns 0). Without this, a salary<=0 agent would be dropped from
# per-agent evaluation entirely and a runaway burn could sit SILENT — the exact metering
# gap this module exists to prevent. Sourced from ``policy.per_run_token_ceiling`` when set,
# else this default. New/probation hires (most prone to runaway burn) are the ones onboarded
# with a TBD salary, so they MUST still be watched.
DEFAULT_TBD_SALARY_CEILING = 1_000_000

_REPO_ROOT = Path(__file__).resolve().parent.parent
# Last-state file for dedup (which alert "bucket" each subject was last seen in).
STATE_DIR = _REPO_ROOT / ".payroll"
STATE_PATH = STATE_DIR / "budget_monitor_state.json"

# A usage reader maps an agent slug → its REAL cumulative tokens, or None if unavailable.
UsageReader = Callable[[str], Optional[int]]


# --- Default usage reader (real LangSmith burn, fail-safe) -------------------
def _default_usage_reader(agent: str) -> Optional[int]:
    """Real cumulative LangSmith tokens for ``agent`` (cached, fail-safe). None if unavailable.

    Delegates to payroll's reconciliation so the monitor watches the SAME authoritative number
    the kill-switch enforces on. Never raises.
    """
    try:
        return payroll._real_spent(agent)
    except Exception:
        return None


# --- Pure check --------------------------------------------------------------
def _band(pct: float) -> Optional[str]:
    """Severity band for a usage fraction, or None when healthy (no alert)."""
    if pct >= CRITICAL_PCT:
        return "critical"
    if pct >= WARN_PCT:
        return "warn"
    return None


def _agent_salary(agent: str, roster: dict) -> int:
    """Agent's salary, fail-safe (0 if unknown / not in roster)."""
    try:
        return payroll.salary(agent, roster=roster)
    except Exception:
        return 0


def _tbd_salary_ceiling(policy: dict) -> int:
    """Absolute token ceiling used when an agent's salary is TBD/null (salary<=0).

    Prefers ``policy.per_run_token_ceiling`` (the same hard cap the kill-switch uses) when it is
    a positive int, else ``DEFAULT_TBD_SALARY_CEILING``. Fail-safe. Guarantees a TBD-salary agent
    is still judged against SOME ceiling rather than silently dropped.
    """
    try:
        ceiling = int((policy or {}).get("per_run_token_ceiling") or 0)
    except (TypeError, ValueError):
        ceiling = 0
    return ceiling if ceiling > 0 else DEFAULT_TBD_SALARY_CEILING


def check_fleet(
    roster: Optional[dict] = None,
    *,
    usage_reader: Optional[UsageReader] = None,
) -> list[dict[str, Any]]:
    """Compare every agent's REAL burn to its salary, and fleet real burn to the team budget.

    PURE + FAIL-SAFE: never raises, never benches. Returns a list of alert dicts (possibly empty).

    Args:
        roster: a loaded roster (``payroll.load_roster()`` shape: ``{"policy":..,"agents":..}``).
            Defaults to ``payroll.load_roster()``.
        usage_reader: ``agent -> Optional[int]`` returning the agent's REAL cumulative tokens.
            INJECTABLE so tests run without network. ``None``/missing usage → that agent is SKIPPED
            (no false alert), and it does NOT contribute to the fleet total. Defaults to the real
            LangSmith reader.

    Each alert::
        {"level", "agent"|"FLEET", "real_tokens", "limit", "pct", "message"}
    """
    try:
        roster = roster if roster is not None else payroll.load_roster()
    except Exception:
        return []  # no roster, nothing we can responsibly check — fail safe, no alerts.

    reader: UsageReader = usage_reader if usage_reader is not None else _default_usage_reader
    agents = (roster.get("agents") or {}) if isinstance(roster, dict) else {}
    policy = (roster.get("policy") or {}) if isinstance(roster, dict) else {}

    alerts: list[dict[str, Any]] = []
    fleet_real = 0
    fleet_has_data = False

    for agent in agents:
        # Anthropic-terms boundary: never cost/alert on a model-dev (denylisted) role, and never
        # let its burn inflate the fleet total. Mirrors the CFO roll-up (graphs/exec/cfo.py) so the
        # two fleet numbers agree and the monitor never reasons about model-dev spend.
        try:
            assert_not_model_work(agent)
        except ModelWorkBlocked:
            continue

        # Per-agent fail-safe: one bad agent never aborts the sweep.
        try:
            real = reader(agent)
        except Exception:
            real = None
        if real is None:
            # Missing/None usage → SKIP (don't false-alert, don't crash).
            continue
        try:
            real = int(real)
        except (TypeError, ValueError, ArithmeticError):
            # int(nan) -> ValueError; int(inf)/int(-inf) -> OverflowError (an ArithmeticError, NOT a
            # ValueError) — without ArithmeticError here a non-finite reading would propagate out of
            # check_fleet and abort the WHOLE sweep, losing every other agent's alert. Skip cleanly.
            continue

        fleet_real += real
        fleet_has_data = True

        salary = _agent_salary(agent, roster)
        if salary <= 0:
            # TBD/null salary (payroll.salary -> 0): DON'T drop the agent — that would let a runaway
            # burn sit silent (the exact gap this module exists to close). Judge it against an
            # absolute fallback ceiling instead, so a new/probation hire is still watched.
            limit = _tbd_salary_ceiling(policy)
            limit_label = "fallback ceiling"
        else:
            limit = salary
            limit_label = "salary"

        pct = real / limit
        band = _band(pct)
        if band is None:
            continue  # under limit → silent (healthy).

        over = real - limit
        msg = (
            f"{agent} burned {real:,} tokens vs {limit_label} {limit:,} "
            f"({pct * 100:.0f}% of budget"
            + (f", {over:,} over" if over > 0 else "")
            + ")."
        )
        alerts.append(
            {
                "level": band,
                "agent": agent,
                "real_tokens": real,
                "limit": limit,
                "pct": pct,
                "message": msg,
            }
        )

    # Fleet-level: sum of REAL burn (only from agents that reported) vs team_token_budget.
    try:
        team_budget = int(policy.get("team_token_budget") or 0)
    except (TypeError, ValueError):
        team_budget = 0

    if fleet_has_data and team_budget > 0:
        fleet_pct = fleet_real / team_budget
        fleet_band = _band(fleet_pct)
        if fleet_band is not None:
            over = fleet_real - team_budget
            msg = (
                f"FLEET burned {fleet_real:,} tokens vs team budget {team_budget:,} "
                f"({fleet_pct * 100:.0f}% of budget"
                + (f", {over:,} over" if over > 0 else "")
                + ")."
            )
            alerts.append(
                {
                    "level": fleet_band,
                    "agent": "FLEET",
                    "real_tokens": fleet_real,
                    "limit": team_budget,
                    "pct": fleet_pct,
                    "message": msg,
                }
            )

    return alerts


# --- Dedup state -------------------------------------------------------------
def _subject(alert: dict) -> str:
    """Dedup key for an alert: the subject it is about (agent slug or 'FLEET')."""
    return str(alert.get("agent", "FLEET"))


def _state_bucket(alert: dict) -> str:
    """The state we compare for dedup — the severity band. Only a band CHANGE re-fires."""
    return str(alert.get("level", "warn"))


def _read_state(path: Optional[Path] = None) -> dict[str, str]:
    """Load the {subject: last_band} dedup state; absent/corrupt reads as empty. Fail-safe."""
    path = path or STATE_PATH
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _write_state(state: dict[str, str], path: Optional[Path] = None) -> bool:
    """Persist the dedup state atomically. Fail-safe — a write error never breaks a sweep.

    Returns True if the state was persisted to disk, False if the write failed (so callers can
    fall back to an in-memory copy and avoid re-firing the SAME alert every sweep — Slack spam).
    """
    path = path or STATE_PATH
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2, sort_keys=True)
        os.replace(tmp, path)
        return True
    except OSError:
        return False


def dedup(
    alerts: Iterable[dict],
    *,
    last_state: Optional[dict[str, str]] = None,
) -> tuple[list[dict], dict[str, str]]:
    """Filter ``alerts`` down to those whose state band CHANGED vs ``last_state``.

    PURE (no I/O): pass in the prior ``{subject: band}`` map, get back ``(fresh_alerts, new_state)``.
    Same condition twice in a row → fires once (first time), silent the second. A subject that
    *clears* (no longer alerting) is dropped from the new state so it can re-fire if it recurs.

    Returns:
        (alerts_to_fire, new_state)
    """
    prior = dict(last_state or {})
    new_state: dict[str, str] = {}
    fresh: list[dict] = []
    for alert in alerts:
        subj = _subject(alert)
        band = _state_bucket(alert)
        new_state[subj] = band
        if prior.get(subj) != band:
            fresh.append(alert)
    return fresh, new_state


# --- Delivery (Slack) --------------------------------------------------------
def deliver(
    alerts: Iterable[dict],
    *,
    poster: Callable[..., dict] = post_digest,
    monitor_agent: str = "cfo",
) -> list[dict]:
    """Post each alert to Slack via ``post_digest`` (keeps the injection-defense strip). FAIL-SAFE.

    Reuses the CFO persona/channel by default (budget is the CFO's beat). ``poster`` is injectable
    for tests. Each post is independent — one failure never stops the rest. Returns the poster
    results.
    """
    results: list[dict] = []
    for alert in alerts:
        level = str(alert.get("level", "warn")).upper()
        subject = str(alert.get("agent", "FLEET"))
        title = f"Budget {level}: {subject}"
        body = str(alert.get("message", ""))
        try:
            results.append(poster(monitor_agent, title, body))
        except Exception as exc:  # noqa: BLE001 — delivery must never crash the sweep
            results.append({"status": "error", "detail": str(exc)[:200]})
    return results


# --- Runnable wiring (check → dedup → deliver), separate from the pure check --
def run_once(
    roster: Optional[dict] = None,
    *,
    usage_reader: Optional[UsageReader] = None,
    poster: Callable[..., dict] = post_digest,
    state_path: Optional[Path] = None,
    monitor_agent: str = "cfo",
    prior_state: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    """One sweep: check the fleet, dedup vs the last-state, deliver only the fresh alerts.

    Dedup state is read from disk; if ``prior_state`` is supplied (an in-memory fallback carried by
    ``run_loop``) it is preferred whenever the on-disk read is empty — so an unwritable state file
    can't make every sweep re-fire the SAME alert (Slack spam at the poll interval).

    FAIL-SAFE end to end. Returns a summary dict::
        {"alerts": [...all current...], "fired": [...newly delivered...],
         "delivered": [...results...], "state": {subject: band}, "state_persisted": bool}
    """
    path = state_path or STATE_PATH
    alerts = check_fleet(roster, usage_reader=usage_reader)
    on_disk = _read_state(path)
    # If the disk read is empty but we hold an in-memory fallback, trust the fallback. This is what
    # defeats the spam: when the state file can't persist, _read_state returns {} every sweep, but
    # the loop's carried state still suppresses the repeat.
    prior = on_disk if on_disk else dict(prior_state or {})
    fired, new_state = dedup(alerts, last_state=prior)
    persisted = _write_state(new_state, path)
    delivered = deliver(fired, poster=poster, monitor_agent=monitor_agent) if fired else []
    return {
        "alerts": alerts,
        "fired": fired,
        "delivered": delivered,
        "state": new_state,
        "state_persisted": persisted,
    }


def run_loop(
    *,
    interval_s: float = 300.0,
    iterations: Optional[int] = None,
    roster: Optional[dict] = None,
    usage_reader: Optional[UsageReader] = None,
    poster: Callable[..., dict] = post_digest,
    state_path: Optional[Path] = None,
    monitor_agent: str = "cfo",
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Run ``run_once`` forever (or ``iterations`` times) every ``interval_s`` seconds. FAIL-SAFE.

    ``iterations``/``sleep`` are injectable so tests can drive a bounded loop without real waits.
    A single sweep error never kills the loop.
    """
    count = 0
    carried_state: dict[str, str] = {}  # in-memory dedup fallback when the state file can't persist
    while iterations is None or count < iterations:
        try:
            summary = run_once(
                roster=roster,
                usage_reader=usage_reader,
                poster=poster,
                state_path=state_path,
                monitor_agent=monitor_agent,
                prior_state=carried_state,
            )
            # Carry the new state in memory so a failed disk write still dedups next sweep.
            carried_state = summary.get("state") or {}
        except Exception:  # noqa: BLE001 — a bad sweep must not stop the monitor
            pass
        count += 1
        if iterations is not None and count >= iterations:
            break
        sleep(interval_s)


if __name__ == "__main__":  # pragma: no cover — operational entry point
    import sys

    summary = run_once()
    fired = summary.get("fired", [])
    print(f"budget_monitor: {len(summary.get('alerts', []))} active alert(s), "
          f"{len(fired)} newly fired.")
    for a in fired:
        print(f"  [{a.get('level')}] {a.get('agent')}: {a.get('message')}")
    sys.exit(0)
