"""hr_ops_manager — the HR-manager for the deployed agent workforce.

The org chart (``roster.yaml``) treats every deployed agent as an *employee*: a salary
(token budget), a status, and a performance scorecard. This graph is the HR/People-Ops
manager that runs **performance reviews** and **PROPOSES** workforce changes — hire, fire,
and raise — but **NEVER auto-executes** any of them. Every consequential decision is held
at the human-in-the-loop ``request_approval`` gate (roster policy:
``hire_fire_requires_approval: true``). Hiring an agent (deploying a new graph), firing one
(decommissioning a graph), and granting a raise (a bigger token budget) are all
consequential, so the human approves — there is NO silent hiring/firing.

Pipeline (each node wrapped in ``span()``; cost-first model via ``get_model(TIER_DEFAULT)``):
  1. gather_scorecards — per-agent scorecard: payroll salary/spent/remaining +
                         payroll.reconcile_with_langsmith (errors/cost, FAIL-SAFE) +
                         roster status. Covers EVERY agent in the roster.
  2. review            — the model scores each agent against ``policy.firing_criteria`` and
                         returns keep | probation | fire_candidate (with a reason).
  3. staffing          — read the JOB BOARD (``docs/audit/catalog.json`` — the broader
                         ~81-process workforce; NOT shipped in the OSS tree, so the board
                         is empty unless you supply it) -> the prioritized open roles NOT
                         yet staffed = HIRE candidates; also flag over-budget / overloaded
                         agents.
  4. propose           — assemble structured hire / fire / raise proposals.
  5. gate              — ``request_approval(action="hr_decisions", risk="high")``. Hire/fire/
                         raise are consequential; NEVER auto-execute.
  6. finalize          — terminal report + ``governance_capture``. v1: approved actions are
                         recorded as "would-hire / would-fire / would-raise" (the actual
                         deploy/decommission tooling is a later phase).

Anthropic-terms guard: ``assert_not_model_work`` is applied to every outward target string
(agent names, candidate role names). HR accounting is orchestration only — no model
train/eval/distill (see AGENTS.md; the denylist also blocks gal-model / eval-worker).

Runtime: cloud/CI. Compiles WITHOUT a checkpointer/store (the platform injects Postgres).
"""
from __future__ import annotations

import json
import os
from typing import Any

from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END

from agent_toolkit import (
    get_model,
    request_approval,
    is_approved,
    span,
    governance_capture,
    assert_not_model_work,
    TIER_DEFAULT,
)
from agent_toolkit import payroll

# --- Recon constants ----------------------------------------------------------
# THE JOB BOARD: the full audit catalog (~81 processes) = the broader workforce beyond
# the handful of built workers. Its prioritized roles are the open positions to hire into.
# The catalog is NOT shipped in the OSS tree; when absent, _load_job_board() fails safe and
# returns an empty board (no open roles proposed). Override via JOB_BOARD_PATH env.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
JOB_BOARD_PATH = os.environ.get(
    "JOB_BOARD_PATH", os.path.join(_REPO_ROOT, "docs", "audit", "catalog.json")
)
# The directory of BUILT worker graphs — a role is "staffed" if a graph already exists.
GRAPHS_QA_DIR = os.path.abspath(os.path.dirname(__file__))

# Valid per-agent review verdicts (deterministic; the model picks one per agent).
_VERDICTS = ("keep", "probation", "fire_candidate")


class State(TypedDict, total=False):
    # Inputs (all optional; the graph reviews the WHOLE roster by default).
    roster_path: str                 # override path to roster.yaml (else toolkit default)
    period_key: str                  # payroll period key (default "current")
    # Intermediate
    scorecards: dict                 # agent -> {salary, spent, remaining, status, reconciled, ...}
    reviews: dict                    # agent -> {verdict, reason}
    open_roles: list                 # unstaffed roles from the job board = HIRE candidates
    flags: list                      # over-budget / overloaded agents (HR flags)
    # Proposals (the consequential, approval-gated output)
    proposals: dict                  # {hire: [...], fire: [...], raise: [...]}
    approved: bool                   # human approval of the HR decisions
    report: str                      # terminal human-readable report


# =============================================================================
# 1. gather_scorecards
# =============================================================================
def gather_scorecards(state: State) -> dict:
    """Build a per-agent scorecard for EVERY agent in the roster.

    Each scorecard = payroll math (salary / spent / remaining) + a FAIL-SAFE LangSmith
    reconciliation (real errors/cost) + the roster status. Reconciliation returning None
    (no creds / API down) is expected and handled — the review still runs on payroll +
    roster alone.
    """
    roster_path = state.get("roster_path") or None
    period_key = state.get("period_key") or "current"

    with span("hr_ops_manager.gather_scorecards", period_key=period_key):
        try:
            roster = payroll.load_roster(roster_path)
        except Exception as exc:  # missing/corrupt roster — degrade, don't crash
            return {"scorecards": {}, "_roster_error": f"roster load failed: {exc}"}

        agents = roster.get("agents", {}) or {}
        scorecards: dict[str, dict] = {}
        for agent in agents:
            # Guard every agent name we act on (Anthropic-terms denylist).
            assert_not_model_work(agent)

            record = agents.get(agent, {}) or {}
            try:
                sal = payroll.salary(agent, roster=roster)
                sp = payroll.spent(agent, period_key=period_key)
                rem = payroll.remaining(agent, period_key=period_key, roster=roster)
                over = payroll.is_over_budget(agent, period_key=period_key, roster=roster)
            except Exception:
                sal, sp, rem, over = 0, 0, 0, False

            # FAIL-SAFE reconciliation against LangSmith run telemetry (errors/cost).
            reconciled = payroll.reconcile_with_langsmith(agent)  # None when unavailable

            scorecards[agent] = {
                "role": record.get("role"),
                "grade": record.get("grade"),
                "status": record.get("status") or "unknown",
                "salary_tokens": sal,
                "spent_tokens": sp,
                "remaining_tokens": rem,
                "over_budget": over,
                # roster's own (review-written) scorecard, if any:
                "roster_scorecard": record.get("scorecard", {}) or {},
                # independent LangSmith reconciliation (errors/cost) or None:
                "langsmith": reconciled,
            }
        return {"scorecards": scorecards}


# =============================================================================
# 2. review
# =============================================================================
def review(state: State) -> dict:
    """Score each agent against ``policy.firing_criteria`` -> keep|probation|fire_candidate.

    The model reasons over each scorecard + the firing criteria and emits a structured
    verdict per agent. Model output is parsed defensively; any agent the model omits or
    mis-labels defaults to the conservative ``keep`` (HR changes are gated regardless, and
    a spurious fire is worse than a missed one at the review stage).
    """
    scorecards = state.get("scorecards", {}) or {}
    if not scorecards:
        return {"reviews": {}}

    try:
        roster = payroll.load_roster(state.get("roster_path") or None)
        firing_criteria = (roster.get("policy", {}) or {}).get("firing_criteria", {}) or {}
        review_window = (roster.get("policy", {}) or {}).get("review_window")
    except Exception:
        firing_criteria, review_window = {}, None

    with span("hr_ops_manager.review", num_agents=len(scorecards)):
        reviews: dict[str, dict] = {}
        # Deterministic default: keep everyone until the model says otherwise.
        for agent in scorecards:
            reviews[agent] = {"verdict": "keep", "reason": "default (no adverse signal)"}

        try:
            model = get_model(TIER_DEFAULT)
            prompt = (
                "You are the HR / People-Ops manager for a fleet of deployed software QA "
                "agents. Each agent is an 'employee' with a salary (token budget), a status "
                "(probation|active|...), and a performance scorecard.\n\n"
                "Score EACH agent against the firing criteria below. Many scorecard metrics "
                "may be null/TBD (the fleet is new and still on probation) — when a metric "
                "is unknown, do NOT fire on it; prefer 'keep' or 'probation'. Only choose "
                "'fire_candidate' when a metric CLEARLY and measurably trips a criterion.\n\n"
                f"REVIEW WINDOW: {review_window}\n"
                f"FIRING CRITERIA: {json.dumps(firing_criteria, indent=2)}\n\n"
                f"SCORECARDS:\n{json.dumps(scorecards, indent=2, default=str)}\n\n"
                "Return ONLY a JSON object mapping each agent name to "
                '{"verdict": "keep|probation|fire_candidate", "reason": "<short reason>"}. '
                "No prose, no code fences."
            )
            resp = model.invoke(prompt)
            content = getattr(resp, "content", str(resp)) or ""
            parsed = _parse_json_object(content)
            for agent, verdict in (parsed or {}).items():
                if agent not in scorecards or not isinstance(verdict, dict):
                    continue
                v = str(verdict.get("verdict", "")).strip().lower()
                if v not in _VERDICTS:
                    v = "keep"
                reviews[agent] = {
                    "verdict": v,
                    "reason": str(verdict.get("reason", "")).strip() or "(no reason given)",
                }
        except Exception as exc:  # model/key unavailable — keep the deterministic defaults
            for agent in reviews:
                reviews[agent]["reason"] = f"keep (model review unavailable: {exc})"

        return {"reviews": reviews}


# =============================================================================
# 3. staffing
# =============================================================================
def staffing(state: State) -> dict:
    """Read the JOB BOARD -> open roles NOT yet staffed = HIRE candidates; flag overload.

    A role is "staffed" if its name maps to an agent already in the roster OR to a built
    worker graph module under ``graphs/qa/``. Everything else on the prioritized job board
    is an OPEN role to hire into. Also flags over-budget / overloaded current agents.
    """
    scorecards = state.get("scorecards", {}) or {}

    with span("hr_ops_manager.staffing"):
        # Who is already on staff: roster agents + built graphs.
        staffed = set(scorecards.keys())
        for built in _built_graph_names():
            staffed.add(built)

        open_roles: list[dict] = []
        for role in _load_job_board():
            name = role.get("agent_name", "")
            if not name:
                continue
            try:
                assert_not_model_work(name)  # never propose hiring into a model-dev role
            except Exception:
                continue  # skip any job-board entry that trips the denylist
            if _role_is_staffed(name, staffed):
                continue
            open_roles.append(
                {
                    "role": name,
                    "area": role.get("area"),
                    "priority": role.get("priority"),
                    "why": role.get("why"),
                }
            )

        # HR flags: agents that are over budget or otherwise overloaded.
        flags: list[dict] = []
        for agent, card in scorecards.items():
            ls = card.get("langsmith") or {}
            if card.get("over_budget"):
                flags.append(
                    {
                        "agent": agent,
                        "flag": "over_budget",
                        "detail": (
                            f"spent={card.get('spent_tokens')} / "
                            f"salary={card.get('salary_tokens')} "
                            f"(remaining={card.get('remaining_tokens')})"
                        ),
                    }
                )
            # Reconciled real cost over the salary is an independent overload signal.
            real_tokens = ls.get("total_tokens") if isinstance(ls, dict) else None
            if real_tokens and card.get("salary_tokens") and real_tokens > card["salary_tokens"]:
                flags.append(
                    {
                        "agent": agent,
                        "flag": "overloaded",
                        "detail": (
                            f"LangSmith tokens={real_tokens} exceed "
                            f"salary={card.get('salary_tokens')}"
                        ),
                    }
                )

        return {"open_roles": open_roles, "flags": flags}


# =============================================================================
# 4. propose
# =============================================================================
def propose(state: State) -> dict:
    """Assemble structured hire / fire / raise proposals. Proposes only — never executes."""
    scorecards = state.get("scorecards", {}) or {}
    reviews = state.get("reviews", {}) or {}
    open_roles = state.get("open_roles", []) or []
    flags = state.get("flags", []) or []

    with span("hr_ops_manager.propose", open_roles=len(open_roles), flags=len(flags)):
        hires: list[dict] = []
        for role in open_roles:
            hires.append(
                {
                    "action": "hire",
                    "role": role.get("role"),
                    "area": role.get("area"),
                    "priority": role.get("priority"),
                    "justification": role.get("why"),
                    "mode": "report_only_until_2_clean_reviews",  # roster probation policy
                }
            )

        fires: list[dict] = []
        for agent, r in reviews.items():
            if r.get("verdict") == "fire_candidate":
                fires.append(
                    {
                        "action": "fire",
                        "agent": agent,
                        "reason": r.get("reason"),
                        "scorecard": scorecards.get(agent, {}),
                    }
                )

        # Raises: over-budget / overloaded agents the review did NOT mark for firing.
        raises: list[dict] = []
        fire_set = {f["agent"] for f in fires}
        seen: set[str] = set()
        for f in flags:
            agent = f.get("agent")
            if not agent or agent in fire_set or agent in seen:
                continue
            seen.add(agent)
            card = scorecards.get(agent, {})
            raises.append(
                {
                    "action": "raise",
                    "agent": agent,
                    "reason": f.get("detail"),
                    "current_salary_tokens": card.get("salary_tokens"),
                    "spent_tokens": card.get("spent_tokens"),
                }
            )

        proposals = {"hire": hires, "fire": fires, "raise": raises}
        return {"proposals": proposals}


# =============================================================================
# 5. gate (human-in-the-loop — hire/fire/raise are consequential)
# =============================================================================
def gate(state: State) -> dict:
    """Hold ALL hire/fire/raise proposals at the approval gate. NEVER auto-execute."""
    proposals = state.get("proposals", {}) or {}
    total = sum(len(proposals.get(k, [])) for k in ("hire", "fire", "raise"))
    if total == 0:
        # No workforce changes proposed — nothing to approve.
        return {"approved": False}

    with span(
        "hr_ops_manager.gate",
        hires=len(proposals.get("hire", [])),
        fires=len(proposals.get("fire", [])),
        raises=len(proposals.get("raise", [])),
    ):
        decision = request_approval(
            action="hr_decisions",
            payload=proposals,
            risk="high",  # hiring/firing/raises are consequential — never silent
        )
        return {"approved": is_approved(decision)}


# =============================================================================
# 6. finalize (terminal report + governance capture)
# =============================================================================
def finalize(state: State) -> dict:
    """Emit the verdict and capture governance.

    v1: even when approved, the actual deploy/decommission/budget tooling is a LATER phase.
    Approved actions are recorded as 'would-hire / would-fire / would-raise'.
    """
    proposals = state.get("proposals", {}) or {}
    approved = state.get("approved", False)
    reviews = state.get("reviews", {}) or {}

    with span("hr_ops_manager.finalize", approved=approved):
        verb = {"hire": "would-hire", "fire": "would-fire", "raise": "would-raise"}
        executed: dict[str, list] = {"hire": [], "fire": [], "raise": []}
        for kind in ("hire", "fire", "raise"):
            for item in proposals.get(kind, []):
                subject = item.get("agent") or item.get("role") or "?"
                status = (
                    f"{verb[kind]} (approved)" if approved else f"{kind} skipped (not approved)"
                )
                executed[kind].append({"subject": subject, "status": status})

        n_hire = len(proposals.get("hire", []))
        n_fire = len(proposals.get("fire", []))
        n_raise = len(proposals.get("raise", []))
        report = (
            "hr_ops_manager performance review:\n"
            f"  reviewed agents : {len(reviews)}\n"
            f"  proposals       : hire={n_hire}, fire={n_fire}, raise={n_raise}\n"
            f"  approved        : {approved}\n"
            f"  outcome         : "
            + (
                "report-only (no workforce changes proposed)"
                if (n_hire + n_fire + n_raise) == 0
                else json.dumps(executed)
            )
        )

        governance_capture(
            "hr_ops_manager",
            {
                "reviews": reviews,
                "proposals": proposals,
                "approved": approved,
                "executed": executed,
                "report_only": True,  # v1: deploy/decommission tooling is a later phase
            },
        )
        return {"report": report}


# =============================================================================
# Helpers
# =============================================================================
def _parse_json_object(text: str) -> dict | None:
    """Best-effort parse of a JSON object from model output (tolerates code fences/prose)."""
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    # Fall back to the first {...} span in the text.
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except Exception:
            return None
    return None


def _load_job_board() -> list[dict]:
    """Read the prioritized open roles from the audit catalog (the job board). Fail-safe."""
    try:
        with open(JOB_BOARD_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        roles = data.get("prioritized_agents", []) if isinstance(data, dict) else []
        return [r for r in roles if isinstance(r, dict)]
    except Exception:
        return []


def _built_graph_names() -> set[str]:
    """Names of built worker graphs under graphs/qa/ (a built module == a staffed role)."""
    names: set[str] = set()
    try:
        for fn in os.listdir(GRAPHS_QA_DIR):
            if fn.endswith(".py") and not fn.startswith("_"):
                names.add(fn[:-3])
    except Exception:
        pass
    # The HR manager and the canary are not "hireable" worker roles.
    names.discard("hr_ops_manager")
    names.discard("canary")
    return names


def _role_is_staffed(role_name: str, staffed: set[str]) -> bool:
    """A job-board role is staffed if any current agent/built-graph token appears in its name.

    Job-board entries are descriptive ("vitest-gatekeeper + node-unit-test-guardian ...");
    a role counts as filled if an existing agent's identity is clearly part of it. We match
    on normalized tokens so 'web_automation_engineer' matches a role mentioning
    'web automation' or 'vitest'/'playwright' only via the explicit agent name, not fuzzy
    keywords (conservative: prefer surfacing an open role over hiding it).
    """
    low = role_name.lower()
    for staff in staffed:
        norm = staff.lower()
        if norm in low or norm.replace("_", " ") in low or norm.replace("_", "-") in low:
            return True
    return False


# =============================================================================
# Graph wiring
# =============================================================================
builder = StateGraph(State)
builder.add_node("gather_scorecards", gather_scorecards)
builder.add_node("review", review)
builder.add_node("staffing", staffing)
builder.add_node("propose", propose)
builder.add_node("gate", gate)
builder.add_node("finalize", finalize)
builder.add_edge(START, "gather_scorecards")
builder.add_edge("gather_scorecards", "review")
builder.add_edge("review", "staffing")
builder.add_edge("staffing", "propose")
builder.add_edge("propose", "gate")
builder.add_edge("gate", "finalize")
builder.add_edge("finalize", END)

graph = builder.compile()  # NO checkpointer/store — injected by the platform
