"""audit_risk_director — the BOARD's Audit & Risk officer (oversight, propose-only).

The board sits above the CEO and produces OVERSIGHT, not work. This director's product is a
risk assessment of the fleet along three axes, assembled by READING subordinate officers'
latest digests (officers consume reports — they do NOT re-do the work):

  1. SPEND vs BUDGET   — read the CFO's digest (the money/budget signal) and the roster's
                         budget caps (``policy.team_token_budget`` / per-agent salaries). Is
                         the fleet within budget, or is it (or any agent) over?
  2. SAFETY-GATE       — compliance: are mutating/outward actions still held behind a human
                         gate? On probation the whole fleet must be report-only/propose-only,
                         so the control here is "report-only is still in force".
  3. SECURITY POSTURE  — read the CTO's digest for open security risks (e.g. the live Scheduler
                         Firestore IDOR) and surface them as risk flags.

It then PROPOSES risk flags + controls. Escalation discipline (the board only bothers the
investor with material risk): ``escalate_to: "shay"`` is reserved for MATERIAL risk
(over-budget, an open security risk, a broken safety gate); everything else is resolved
inside the org (``escalate_to: "org"``). Delivery is the board Audit & Risk digest, filed via
``file_digest_issue(..., report_only=_report_only())`` — report-only by default.

House style (same seams as revenue_reporter / daily_digest — the cloud template):
  * REPORT-ONLY on probation: delivery goes through ``file_digest_issue(..., report_only=
    _report_only())``; the default (env ``OPS_REPORT_ONLY`` truthy/unset) is True. Report-only
    NEVER contacts GitHub and NEVER enters the approval interrupt, so an unattended scheduled
    run always finishes and never hangs.
  * NEVER HANGS: there is no reachable ``request_approval``/interrupt on the scheduled path.
  * FAIL-SAFE: every read (digest / roster / model) is wrapped — a missing digest, an
    unreadable roster, or an absent model key degrades to a deterministic fallback and the run
    still completes. A telemetry/network problem never crashes a node.
  * SECRETS: env only, never logged; error strings are type-only.
  * ANTHROPIC-TERMS / ML boundary: ``assert_not_model_work`` guards every outward target string
    (the digest repo, the subordinate slugs); gal-model / denylisted ids are skipped.
  * CLOCK-IN: ``budget_gate`` runs first; over salary / globally disabled => terminal report.
  * governance_capture(..., {"report_only": True}) is terminal.
  * Compiles WITHOUT a checkpointer/store (the platform injects Postgres).
"""
from __future__ import annotations

import os

from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END

from agent_toolkit import (
    span,
    governance_capture,
    assert_not_model_work,
    budget_guard,
    check_clocked_in,
    read_local_digest,
    write_local_digest,
    file_digest_issue,
    TIER_DEFAULT,
)
from agent_toolkit import payroll
from agent_toolkit import lanes
from agent_toolkit.policy import ModelWorkBlocked

# Where the board Audit & Risk digest is filed (a no-prod-deploy, allow-listed repo).
DIGEST_REPO = "Scheduler-Systems/qa-agent-platform"

# Subordinate officers this director CONSUMES (it reads their digests, never re-does work).
CFO_SLUG = "cfo"   # spend / budget signal
CTO_SLUG = "cto"   # security posture signal

# The placeholder ``read_local_digest`` returns when an officer has not reported yet.
_NO_DIGEST = "(no digest yet)"


def _report_only() -> bool:
    """Report-only default: env ``OPS_REPORT_ONLY`` truthy/unset => True; '0'/'false'/'no' => False.

    On probation the board must take NO mutating/outward action without a human gate, so the
    safe default is True. Only an explicit falsey value opts out.
    """
    return os.environ.get("OPS_REPORT_ONLY", "").lower() not in ("0", "false", "no")


# --- State -------------------------------------------------------------------------------
class State(TypedDict, total=False):
    mode: str
    cfo: str              # the CFO's latest digest text (or "(no digest yet)")
    cto: str              # the CTO's latest digest text (or "(no digest yet)")
    budget: dict          # spend-vs-budget analysis (team caps + per-agent over-budget)
    findings: dict        # {budget: [...], safety: [...], security: [...]}
    proposals: list       # risk flags + controls (each carries escalate_to: org|shay)
    summary: str          # composed oversight narrative
    body: str             # the assembled markdown digest body
    report: dict          # terminal verdict
    report_only: bool


# =============================================================================
# Nodes
# =============================================================================
def budget_gate(state: State) -> dict:
    """CLOCK-IN gate — STOP before any work if over salary or globally disabled.

    Runs FIRST. Clocked in => proceed to gather; clocked out => terminal report + governance,
    no digest reads, no model spend, no writes.
    """
    with span("audit_risk_director.budget_gate"):
        if check_clocked_in("audit_risk_director"):
            return {}
        report = {
            "status": "skipped",
            "detail": "audit_risk_director over token salary or globally disabled",
            "report_only": True,
        }
        governance_capture(
            "audit_risk_director",
            {"clocked_in": False, "report_only": True, "report": report},
        )
        return {"report": report, "report_only": True}


def gather(state: State) -> dict:
    """CONSUME the subordinate officers' latest digests + the roster budget caps. FAIL-SAFE.

    Officers do NOT re-do the underlying work — they read reports. We read:
      - ``cfo``    : the CFO's spend/budget digest (``read_local_digest`` is already fail-safe;
                     a missing file returns "(no digest yet)").
      - ``cto``    : the CTO's security-posture digest (same fail-safe read).
      - ``budget`` : the roster's budget caps + a per-agent over-budget scan via ``payroll``.
                     A missing/unreadable roster degrades to an empty, structured result.

    Every outward slug/string is guarded with ``assert_not_model_work`` (Anthropic terms); a
    denylisted slug is skipped rather than read.
    """
    with span("audit_risk_director.gather"):
        # 1) Subordinate digests — guarded then read (read is itself fail-safe).
        cfo = _read_officer(CFO_SLUG)
        cto = _read_officer(CTO_SLUG)

        # 2) Budget caps + per-agent over-budget scan — fail-safe roster read.
        budget = _budget_analysis()

        return {"cfo": cfo, "cto": cto, "budget": budget}


def analyze(state: State) -> dict:
    """Turn the gathered signals into RISK FINDINGS along the three axes. Deterministic.

    - budget   : the fleet is "over budget" if the CFO digest reports an over-budget signal
                 OR the roster scan finds any over-budget agent OR fleet spend exceeds the
                 team cap. Each over-budget agent is a finding.
    - safety   : compliance — mutating/outward actions must still be gated. On probation
                 report-only must be in force; if it is NOT, that is a (material) safety
                 finding.
    - security : any open security risk surfaced by the CTO digest (e.g. an IDOR) is a finding.

    No model call here — findings are derived deterministically so they are ALWAYS produced.
    """
    cfo = state.get("cfo") or _NO_DIGEST
    cto = state.get("cto") or _NO_DIGEST
    budget = state.get("budget") or {}

    with span("audit_risk_director.analyze"):
        findings = {
            "budget": _budget_findings(cfo, budget),
            "safety": _safety_findings(),
            "security": _security_findings(cto),
        }
        return {"findings": findings}


def propose(state: State) -> dict:
    """Assemble RISK FLAGS + CONTROLS as proposals. Propose-only — never executes.

    Each proposal carries ``escalate_to``: ``"shay"`` for MATERIAL risk (over-budget, an open
    security risk, a broken safety gate), ``"org"`` for everything resolved inside the org.
    The board only escalates material risk to the investor.
    """
    findings = state.get("findings") or {}

    with span("audit_risk_director.propose"):
        proposals: list[dict] = []

        # Budget findings — over-budget is MATERIAL (capital/irreversible) => escalate to Shay.
        for f in findings.get("budget", []) or []:
            proposals.append(
                {
                    "axis": "budget",
                    "flag": f.get("flag"),
                    "detail": f.get("detail"),
                    "control": "freeze/raise review: cap or re-approve the agent's salary",
                    "escalate_to": "shay" if f.get("material") else "org",
                }
            )

        # Safety-gate findings — a broken gate is MATERIAL (compliance) => escalate to Shay.
        for f in findings.get("safety", []) or []:
            proposals.append(
                {
                    "axis": "safety",
                    "flag": f.get("flag"),
                    "detail": f.get("detail"),
                    "control": "restore report-only / human-gate before any mutating action",
                    "escalate_to": "shay" if f.get("material") else "org",
                }
            )

        # Security findings — an open security risk (IDOR) is MATERIAL => escalate to Shay.
        for f in findings.get("security", []) or []:
            proposals.append(
                {
                    "axis": "security",
                    "flag": f.get("flag"),
                    "detail": f.get("detail"),
                    "control": "remediate + verify the access-control fix before next release",
                    "escalate_to": "shay" if f.get("material") else "org",
                }
            )

        return {"proposals": proposals}


def compose(state: State) -> dict:
    """Phrase the findings + proposals as a concise oversight narrative. FAIL-SAFE.

    The body is built DETERMINISTICALLY from the findings/proposals so it is ALWAYS produced.
    An optional budget-metered model adds a one-paragraph board-voice narrative at the top; on
    ANY model failure (no key, budget, SDK drift) the deterministic body stands — never empty.
    No model train/eval/distill — phrasing only.
    """
    findings = state.get("findings") or {}
    proposals = state.get("proposals") or []
    budget = state.get("budget") or {}

    with span("audit_risk_director.compose", proposals=len(proposals)):
        body = _render_body(findings, proposals, budget)

        narrative = ""
        try:
            model = budget_guard("audit_risk_director", TIER_DEFAULT)
            prompt = (
                "You are the Board's Audit & Risk director for a revenue-first founder. In 2-3 "
                "sentences, give an oversight read on the fleet's RISK: is it within budget, are "
                "mutating actions still gated (compliance), and is there any open security risk. "
                "Be factual; do NOT invent numbers. Call out only MATERIAL risk as an ask for "
                "Shay.\n\n"
                f"{body}"
            )
            resp = model.invoke(prompt)
            content = getattr(resp, "content", str(resp)) or ""
            narrative = content.strip()
        except Exception as exc:  # model/key unavailable — deterministic body stands
            narrative = f"_(model narrative unavailable: {type(exc).__name__})_"

        summary = f"{narrative}\n\n{body}" if narrative else body
        if not summary.strip():  # belt-and-suspenders: never deliver an empty summary
            summary = body or "(no risk signal)"
        return {"summary": summary, "body": body}


def deliver(state: State) -> dict:
    """Write the local digest + file the board Audit & Risk issue (report-only on probation).

    ``write_local_digest`` always runs (succeeds-or-"" ; never raises). ``file_digest_issue(...,
    report_only=_report_only())`` delivers the issue — on probation (the default) it returns an
    honest report-only plan dict with NO GitHub call and NO approval interrupt, so an unattended
    run can never hang or write.
    """
    summary = state.get("summary") or "(no risk signal)"
    report_only = _report_only()

    with span("audit_risk_director.deliver", report_only=report_only):
        try:
            assert_not_model_work(DIGEST_REPO)  # never file into a model-dev repo
        except ModelWorkBlocked:
            return {
                "report": {"delivery": "blocked", "report_only": report_only},
                "report_only": report_only,
            }

        digest_path = write_local_digest(
            "audit-risk-director", "Board — Audit & Risk (oversight)", summary
        )

        res = file_digest_issue(
            DIGEST_REPO,
            "Board — Audit & Risk (oversight)",
            summary,
            labels=["board:audit-risk"],
            report_only=report_only,
            agent="audit_risk_director",
            slack_title="🛡️ Board — Audit & Risk (oversight)",
        )
        delivery = res.get("status") if isinstance(res, dict) else None
        return {
            "report": {
                "delivery": delivery,
                "digest": digest_path,
                "report_only": report_only,
            },
            "report_only": report_only,
        }


def finalize(state: State) -> dict:
    """Terminal node — capture governance (report_only=True) and emit the final verdict."""
    findings = state.get("findings") or {}
    proposals = state.get("proposals") or []
    prior = state.get("report") if isinstance(state.get("report"), dict) else {}
    delivery = prior.get("delivery")
    asks = sum(1 for p in proposals if p.get("escalate_to") == "shay")

    with span("audit_risk_director.finalize", delivery=delivery, asks=asks):
        governance_capture(
            "audit_risk_director",
            {
                "findings": {k: len(v or []) for k, v in findings.items()},
                "proposals": len(proposals),
                "asks_for_shay": asks,
                "delivery": delivery,
                "report_only": True,
            },
        )
        return {
            "report": {
                "findings": {k: len(v or []) for k, v in findings.items()},
                "proposals": len(proposals),
                "asks_for_shay": asks,
                "delivery": delivery,
                "digest": prior.get("digest"),
                "report_only": True,
            }
        }


# =============================================================================
# Helpers
# =============================================================================
def _read_officer(slug: str) -> str:
    """Guard then read a subordinate officer's latest digest. FAIL-SAFE.

    The slug is guarded against the model-dev denylist (never consume a model-dev role's
    output); a denylisted slug degrades to the no-digest placeholder. ``read_local_digest`` is
    itself fail-safe — a missing/unreadable file returns "(no digest yet)".
    """
    try:
        assert_not_model_work(slug)
    except ModelWorkBlocked:
        return _NO_DIGEST
    try:
        return read_local_digest(slug)
    except Exception:
        return _NO_DIGEST


def _budget_analysis() -> dict:
    """Roster budget caps + a per-agent over-budget scan. FAIL-SAFE.

    Reads ``policy.team_token_budget`` (the fleet cap) and scans every roster agent for an
    over-budget condition via ``payroll.is_over_budget`` (the deterministic ledger check).
    A missing/unreadable roster degrades to an empty, structured result (no crash). Every
    agent name is guarded (Anthropic terms) — a denylisted name is skipped.
    """
    try:
        roster = payroll.load_roster()
    except Exception:
        return {"team_cap": None, "over_budget_agents": [], "note": "roster unavailable"}

    policy = roster.get("policy", {}) or {}
    try:
        team_cap = int(policy.get("team_token_budget"))
    except (TypeError, ValueError):
        team_cap = None

    agents = roster.get("agents", {}) or {}
    over: list[dict] = []
    fleet_spent = 0
    for name in agents:
        try:
            assert_not_model_work(name)
        except ModelWorkBlocked:
            continue
        try:
            sp = payroll.spent(name)
            sal = payroll.salary(name, roster=roster)
            is_over = payroll.is_over_budget(name, roster=roster)
        except Exception:
            sp, sal, is_over = 0, 0, False
        fleet_spent += sp
        if is_over:
            over.append(
                {
                    "agent": name,
                    "spent_tokens": sp,
                    "salary_tokens": sal,
                }
            )

    return {
        "team_cap": team_cap,
        "fleet_spent": fleet_spent,
        "fleet_over_cap": bool(team_cap is not None and fleet_spent > team_cap),
        "over_budget_agents": over,
        "note": None,
    }


def _digest_signals_over_budget(cfo: str) -> bool:
    """True if the CFO digest text signals an over-budget condition. Conservative per-LINE scan.

    The CFO reports spend vs budget; we look for the explicit over-budget vocabulary
    ("over budget" / "over-budget" / "over salary" / "exceeded budget"). A missing/placeholder
    digest never trips this (no false alarm on "(no digest yet)").

    NEGATION-AWARE: a line that NEGATES the condition ("none — every agent is within its salary",
    "no agent over salary", "under cap", "within budget") must NOT trip the alarm — otherwise the
    CFO's all-clear ("no agent over salary / overloaded") would be misread as an over-budget signal
    (the exact spend-vs-allocation conflation this fleet is being hardened against). We scan
    per-line and skip negated lines so only a POSITIVE over-budget statement signals.
    """
    text = (cfo or "")
    low = text.lower()
    if not low or low == _NO_DIGEST:
        return False
    tokens = ("over budget", "over-budget", "over salary", "exceeded budget")
    negations = (
        "no agent", "none", "not over", "within", "under cap", "under the cap",
        "no overage", "within budget", "within its salary", "within their salary",
    )
    for raw in text.splitlines():
        line = raw.lower()
        if not any(tok in line for tok in tokens):
            continue
        if any(neg in line for neg in negations):
            continue  # the line negates the condition — not an over-budget signal
        return True
    return False


def _budget_findings(cfo: str, budget: dict) -> list[dict]:
    """Spend-vs-budget findings: per over-budget agent + a fleet-cap breach + a CFO signal.

    ESCALATION DISCIPLINE (the budget-correctness fix). An agent/fleet running OVER its weekly
    token salary/cap is an OPERATIONAL burn condition, NOT a bright-line founder decision. Per
    the delegation mandate (docs/governance/delegation.yaml) ``set_budget`` is decided by the
    BOARD; only ``bet_the_company_spend`` (a single spend ABOVE ``max_board_spend_usd``) is
    ``owner_reserved``. So detecting an over-spend is org-internal (the CFO/board cap, bench, or
    re-grade the agent) — ``material: False`` => ``escalate_to: "org"``. It must NOT be pushed at
    an unreachable founder as "Shay, urgent". This matches the CFO graph, which routes an
    over-budget agent to "org" and reserves "shay" only for a budget INCREASE (capital). The
    genuinely bright-line axes (an open security IDOR, a broken report-only safety gate) are
    handled in ``_security_findings`` / ``_safety_findings`` and DO still reach Shay.
    """
    findings: list[dict] = []

    for a in budget.get("over_budget_agents", []) or []:
        findings.append(
            {
                "flag": "agent_over_budget",
                "detail": (
                    f"{a.get('agent')} spent={a.get('spent_tokens')} "
                    f"> salary={a.get('salary_tokens')}"
                ),
                # Operational burn condition — the CFO/board cap/bench/re-grade it inside the org.
                "material": False,
            }
        )

    if budget.get("fleet_over_cap"):
        findings.append(
            {
                "flag": "fleet_over_team_cap",
                "detail": (
                    f"fleet spent={budget.get('fleet_spent')} "
                    f"> team cap={budget.get('team_cap')}"
                ),
                # The board re-balances the team cap inside the org — only a spend ABOVE
                # max_board_spend_usd is owner-reserved; an over-cap burn is not.
                "material": False,
            }
        )

    # A CFO over-budget signal corroborates even when the local ledger is empty (e.g. spend
    # is tracked off-box). Surface it, but don't double-count if the scan already flagged.
    if _digest_signals_over_budget(cfo) and not budget.get("over_budget_agents") \
            and not budget.get("fleet_over_cap"):
        findings.append(
            {
                "flag": "cfo_reports_over_budget",
                "detail": "CFO digest reports an over-budget condition",
                # Same operational burn condition — resolved by the money owner inside the org.
                "material": False,
            }
        )

    return findings


def _safety_findings() -> list[dict]:
    """Compliance: mutating/outward actions must stay gated. On probation report-only is law.

    If report-only is NOT in force (an explicit ``OPS_REPORT_ONLY=0/false/no``) the fleet could
    take outward action unattended — a MATERIAL safety-gate finding. When report-only is in
    force, there is no finding (the control is holding).
    """
    if not _report_only():
        return [
            {
                "flag": "report_only_disabled",
                "detail": (
                    "OPS_REPORT_ONLY is disabled — mutating/outward actions are NOT held "
                    "behind the report-only gate while the fleet is on probation"
                ),
                "material": True,
            }
        ]
    return []


def _security_findings(cto: str) -> list[dict]:
    """Open security risks for the risk-oversight lens. FAIL-SAFE, deterministic.

    RELOCATED OWNERSHIP (step-3 simplify): the STANDING held IDOR posture is now owned by the lane
    registry (``agent_toolkit.lanes``), NOT by the CTO digest. So the director surfaces the IDOR
    risk from ``lanes`` DIRECTLY — it no longer returns ``[]`` just because the CTO has not filed a
    digest yet. This makes the IDOR oversight survive the CTO agent's eventual offboard: even with
    ``cto == "(no digest yet)"`` the live #1487 IDOR is still flagged as a material risk.

    Two sources, deduped:
      1. The STANDING IDOR dossier from ``lanes`` (always surfaced while it is held/open) — the
         authoritative relocation that no longer depends on the CTO digest being present.
      2. ANY ADDITIONAL open security risk the CTO digest reports in prose (a NEW vulnerability
         beyond the standing IDOR) — a conservative substring scan, so a benign "all clear" CTO
         report does not trip a false alarm, and the standing IDOR is not double-counted.
    """
    findings: list[dict] = []

    # 1) STANDING IDOR — read from the AUTHORITATIVE lanes source, independent of the CTO digest.
    if lanes.idor_is_open():
        dossier = lanes.idor_security_item()
        findings.append(
            {
                "flag": "open_security_risk",
                "detail": (
                    f"standing held IDOR (lanes): {dossier.get('title')} — {dossier.get('detail')}"
                ),
                "material": True,
                "systemic": dossier.get("systemic_key"),
            }
        )

    # 2) Any ADDITIONAL security risk the CTO digest flags in prose (a NEW one beyond the IDOR).
    low = (cto or "").lower()
    if low and low != _NO_DIGEST:
        # The IDOR vocabulary is already covered by the standing finding above — don't re-flag it.
        idor_aliases = lanes.SYSTEMIC_ITEMS.get("security_idor_1487", {}).get("aliases", ())
        other_risk_tokens = (
            "insecure direct object",
            "vulnerab",
            "security risk",
            "open security",
            "cve-",
            "exploit",
        )
        hit = next((t for t in other_risk_tokens if t in low), None)
        # Only an IDOR mention => already covered by (1); a DISTINCT risk vocab => a new finding.
        if hit and not any(alias in low for alias in idor_aliases):
            findings.append(
                {
                    "flag": "open_security_risk",
                    "detail": f"CTO digest reports an additional open security risk (matched '{hit}')",
                    "material": True,
                }
            )

    return findings


# --- Render helpers (deterministic, no model) -------------------------------------------
def _render_findings(axis: str, items: list) -> list:
    if not items:
        return [f"- **{axis}**: no findings"]
    lines = [f"- **{axis}**: {len(items)} finding(s)"]
    for f in items:
        lines.append(f"    - {f.get('flag')}: {f.get('detail')}")
    return lines


def _render_proposals(proposals: list) -> list:
    if not proposals:
        return ["_(no risk flags — controls holding)_"]
    lines: list = []
    for p in proposals:
        lines.append(
            f"- [{p.get('axis')}] **{p.get('flag')}** — {p.get('detail')} "
            f"· control: {p.get('control')} · escalate_to: **{p.get('escalate_to')}**"
        )
    return lines


def _render_body(findings: dict, proposals: list, budget: dict) -> str:
    asks = sum(1 for p in proposals if p.get("escalate_to") == "shay")
    lines = ["# Board — Audit & Risk (oversight)", ""]

    lines += ["## 🛡️ Risk posture", ""]
    lines += _render_findings("budget", findings.get("budget", []) or [])
    lines += _render_findings("safety", findings.get("safety", []) or [])
    lines += _render_findings("security", findings.get("security", []) or [])

    lines += ["", "## 🚩 Risk flags + controls (proposals)", ""]
    lines += _render_proposals(proposals)

    cap = budget.get("team_cap")
    spent = budget.get("fleet_spent")
    lines += [
        "",
        "## 📒 Budget caps",
        "",
        f"- team cap: {cap if cap is not None else 'unavailable'} · "
        f"fleet spent: {spent if spent is not None else 'unavailable'}",
        "",
        f"## 📨 Asks for Shay (material risk only): {asks}",
    ]
    return "\n".join(lines)


# =============================================================================
# Routing
# =============================================================================
def _budget_route(state: State) -> str:
    """Clocked in -> gather; clocked out -> END (terminal report already set)."""
    return "gather" if check_clocked_in("audit_risk_director") else "clocked_out"


# =============================================================================
# Graph wiring
# =============================================================================
builder = StateGraph(State)
builder.add_node("budget_gate", budget_gate)
builder.add_node("gather", gather)
builder.add_node("analyze", analyze)
builder.add_node("propose", propose)
builder.add_node("compose", compose)
builder.add_node("deliver", deliver)
builder.add_node("finalize", finalize)

builder.add_edge(START, "budget_gate")
builder.add_conditional_edges(
    "budget_gate",
    _budget_route,
    {"gather": "gather", "clocked_out": END},
)
builder.add_edge("gather", "analyze")
builder.add_edge("analyze", "propose")
builder.add_edge("propose", "compose")
builder.add_edge("compose", "deliver")
builder.add_edge("deliver", "finalize")
builder.add_edge("finalize", END)

graph = builder.compile()  # NO checkpointer/store — injected by the platform
