"""coo — the Chief Operating Officer over the OPS fleet (propose-only).

Runtime: cloud/CI (LangGraph Platform managed Cloud SaaS); register-able in
``langgraph.json`` (the orchestrator owns that file — not this module).

MISSION: ops fleet health. An OFFICER does NOT re-do the subordinate agents' work — it
CONSUMES their latest reports and the roster, judges whether the fleet is actually running,
and lands ops fixes as PROPOSALS in a digest. Concretely:

  1. gather   — read the latest local digests of the ops subordinates
                (``git-sync-auditor``, ``memory-sync``, ``store-health-checker``,
                ``daily-digest``) via ``read_local_digest`` (FAIL-SAFE; a missing file reads
                as "(no digest yet)"), and the roster's OPS class (``org.ops``) via payroll.
  2. analyze  — split the ops agents into FRESH (produced a real digest) vs STALE/MISSING
                (digest is "(no digest yet)" / empty), and surface the known launchd /
                substrate failure mode (the LOCAL schedules — git-sync-auditor + memory-sync —
                not firing => no fresh digest) as an explicit ops RISK.
  3. propose  — assemble structured ops-fix proposals. Each carries ``escalate_to``: "org" by
                default (resolved inside the org), or "shay" ONLY when the fix needs infra
                SPEND (capital / irreversible / legal is the investor's desk).
  4. compose  — phrase the findings as a concise officer report (model where available,
                DETERMINISTIC fallback when not — a digest is always produced).
  5. deliver  — ``file_digest_issue(..., report_only=_report_only())``: on probation (the
                default) an honest report-only plan dict, NO GitHub write and NO approval
                interrupt, so an unattended scheduled run can never hang or write.
  6. finalize — terminal ``governance_capture(..., {"report_only": True})`` + verdict.

LOAD-BEARING DECISIONS (match the ops-fleet house style — see revenue_reporter, daily_digest,
hr_ops_manager):

  * PROPOSE-ONLY / REPORT-ONLY by default. Every action is a PROPOSAL; delivery is report-only
    (env ``OPS_REPORT_ONLY`` truthy/unset => True; only "0"/"false"/"no" opts out). NEVER HANGS:
    there is no reachable ``request_approval``/interrupt on the scheduled path.
  * FAIL-SAFE. Every read (digest / payroll / model) is wrapped; missing data degrades to a
    deterministic fallback; a node never crashes.
  * SECRETS env-only; error strings are type-only. ANTHROPIC-TERMS / ML BOUNDARY:
    ``assert_not_model_work`` guards every outward target string (subordinate agent names, the
    digest repo); gal-model / denylisted ids are skipped, never read or reported.
  * Compiles WITHOUT a checkpointer/store (the platform injects Postgres). Every node body is
    wrapped in ``span("coo.<node>", ...)``; budget_gate clock-in runs first.
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
    write_local_digest,
    file_digest_issue,
    read_local_digest,
    TIER_DEFAULT,
)
from agent_toolkit import payroll
from agent_toolkit.policy import ModelWorkBlocked

# Where the officer digest issue is filed (a no-prod-deploy, allow-listed repo).
DIGEST_REPO = "Scheduler-Systems/qa-agent-platform"

# The OPS subordinate agents whose latest digests the COO consumes (slug = .tmp/<slug>/latest.md).
# These map to the roster ``org.ops`` roles (underscored role -> hyphenated digest slug).
OPS_SUBORDINATES = (
    "git-sync-auditor",
    "memory-sync",
    "store-health-checker",
    "daily-digest",
)

# The LOCAL launchd schedules (vs. the CLOUD agents). When these don't fire there is no fresh
# digest — the known launchd/substrate failure mode the COO must surface as an ops risk.
LOCAL_SCHEDULED = ("git-sync-auditor", "memory-sync")

# The sentinel a missing/empty local digest reads as (from read_local_digest).
_NO_DIGEST = "(no digest yet)"


def _report_only() -> bool:
    """Report-only default: env ``OPS_REPORT_ONLY`` truthy/unset => True; '0'/'false'/'no' => False.

    On probation the fleet must take NO mutating/outward action without a human gate, so the
    safe default is True. Only an explicit falsey value opts out.
    """
    return os.environ.get("OPS_REPORT_ONLY", "").lower() not in ("0", "false", "no")


def _is_stale(text: str) -> bool:
    """True when a subordinate's digest is missing/empty (= no fresh output). Defensive.

    ``read_local_digest`` already returns "(no digest yet)" for a missing/empty file; we also
    treat any falsy/whitespace-only text the same way so a partial read can't masquerade as fresh.
    """
    return not (text or "").strip() or (text or "").strip() == _NO_DIGEST


class State(TypedDict, total=False):
    mode: str            # reserved for future read-only/observe variants
    digests: dict        # subordinate slug -> latest digest text (or "(no digest yet)")
    ops_roster: dict     # roster ops-class facts (members, statuses)
    analysis: dict       # fresh vs stale split + the surfaced ops risks
    proposals: list      # structured ops-fix proposals (each tagged escalate_to org|shay)
    summary: str         # composed officer report text
    report: dict         # terminal verdict
    report_only: bool    # whether delivery stayed report-only


# =============================================================================
# Nodes
# =============================================================================
def budget_gate(state: State) -> dict:
    """CLOCK-IN gate — STOP before any work if over salary or globally disabled.

    Runs FIRST. Clocked in => proceed to ``gather``; clocked out => governance (report-only)
    + terminal report, route to END. No digest/roster reads, no model spend, no writes on the
    clocked-out path.
    """
    with span("coo.budget_gate"):
        if check_clocked_in("coo"):
            return {}
        report = {
            "status": "skipped",
            "detail": "coo over token salary or globally disabled",
            "report_only": True,
        }
        governance_capture(
            "coo",
            {"clocked_in": False, "report_only": True, "report": report},
        )
        return {"report": report, "report_only": True}


def gather(state: State) -> dict:
    """Consume the OPS subordinates' latest digests + the roster ops class. Every read FAIL-SAFE.

    - ``digests``    : per subordinate, guard the agent name (Anthropic terms) then
                       ``read_local_digest`` (which never raises — missing => "(no digest yet)").
                       A denylisted agent is skipped (recorded, never read/reported).
    - ``ops_roster`` : the roster ``org.ops`` group + each member's status, read fail-safe; a
                       missing/corrupt roster degrades to an empty ops class.
    """
    with span("coo.gather", subordinates=len(OPS_SUBORDINATES)):
        # 1) Subordinate digests — guard + read each.
        digests: dict = {}
        for slug in OPS_SUBORDINATES:
            try:
                assert_not_model_work(slug)  # never read/report a model-dev agent's digest
            except ModelWorkBlocked:
                continue  # skip denylisted — do not consume its output
            digests[slug] = read_local_digest(slug)

        # 2) Roster ops class — who is staffed and their status (fail-safe).
        try:
            roster = payroll.load_roster()
        except Exception:
            roster = {"org": {}, "agents": {}}
        org = roster.get("org", {}) or {}
        agents = roster.get("agents", {}) or {}

        members: list = []
        ops_group = org.get("ops")
        if isinstance(ops_group, (list, tuple)):
            ops_names = [str(x) for x in ops_group]
        elif isinstance(ops_group, str) and ops_group:
            ops_names = [ops_group]
        else:
            ops_names = []
        for name in ops_names:
            try:
                assert_not_model_work(name)  # never count a model-dev role
            except ModelWorkBlocked:
                continue
            record = agents.get(name, {}) or {}
            members.append(
                {
                    "agent": name,
                    "role": record.get("role"),
                    "status": record.get("status") or "unknown",
                }
            )

        ops_roster = {"members": members, "count": len(members)}
        return {"digests": digests, "ops_roster": ops_roster}


def analyze(state: State) -> dict:
    """Split subordinates into FRESH vs STALE/MISSING and surface the ops RISKS. FAIL-SAFE.

    FRESH  = the subordinate produced a real digest.
    STALE  = its digest is "(no digest yet)" / empty (= no fresh output this cycle).

    The headline ops risk is the known launchd/substrate failure: when a LOCAL-scheduled agent
    (git-sync-auditor / memory-sync) is stale, its schedule likely did not fire — surfaced as a
    ``schedule_not_firing`` risk so the COO can propose a fix.
    """
    digests = state.get("digests") or {}

    with span("coo.analyze", subordinates=len(digests)):
        fresh: list = []
        stale: list = []
        for slug in OPS_SUBORDINATES:
            if slug not in digests:  # skipped (denylisted) — neither fresh nor stale
                continue
            if _is_stale(digests.get(slug, "")):
                stale.append(slug)
            else:
                fresh.append(slug)

        risks: list = []
        for slug in stale:
            if slug in LOCAL_SCHEDULED:
                risks.append(
                    {
                        "risk": "schedule_not_firing",
                        "agent": slug,
                        "detail": (
                            f"{slug} is a LOCAL launchd schedule with no fresh digest — the "
                            "schedule/substrate likely did not fire (known launchd failure mode)."
                        ),
                    }
                )
            else:
                risks.append(
                    {
                        "risk": "stale_digest",
                        "agent": slug,
                        "detail": f"{slug} produced no fresh digest this cycle.",
                    }
                )

        analysis = {
            "fresh": fresh,
            "stale": stale,
            "risks": risks,
            "all_fresh": not stale,
        }
        return {"analysis": analysis}


def propose(state: State) -> dict:
    """Assemble structured ops-fix PROPOSALS. Proposes only — never executes.

    Escalation routing (per the investor-escalation rule): a fix is resolved inside the org
    (``escalate_to: "org"``) UNLESS it needs infra SPEND (capital / irreversible / legal), which
    is the investor's desk (``escalate_to: "shay"``). Re-provisioning local launchd substrate is
    an org-internal fix; only moving the schedules onto PAID always-on infra is a Shay ask.
    """
    analysis = state.get("analysis") or {}
    risks = analysis.get("risks") or []

    with span("coo.propose", risks=len(risks)):
        proposals: list = []
        recurring_local_failures = 0

        for risk in risks:
            agent = risk.get("agent")
            try:
                assert_not_model_work(agent or "")  # never propose acting on a model-dev role
            except ModelWorkBlocked:
                continue
            if risk.get("risk") == "schedule_not_firing":
                recurring_local_failures += 1
                proposals.append(
                    {
                        "action": "fix_local_schedule",
                        "agent": agent,
                        "reason": risk.get("detail"),
                        "remedy": (
                            "Re-provision the local launchd job (load/kickstart the agent) and "
                            "add a recency/unpushed guard so the schedule fires reliably."
                        ),
                        "escalate_to": "org",  # org-internal substrate fix — no spend
                    }
                )
            else:
                proposals.append(
                    {
                        "action": "investigate_stale_agent",
                        "agent": agent,
                        "reason": risk.get("detail"),
                        "remedy": "Check the agent's last run/logs; re-run its shift.",
                        "escalate_to": "org",
                    }
                )

        # If the LOCAL substrate keeps failing, the durable fix is to move those schedules onto
        # paid always-on infra (Stratus/cloud cron) — that needs SPEND, so it is a Shay ask.
        if recurring_local_failures >= len(LOCAL_SCHEDULED):
            proposals.append(
                {
                    "action": "migrate_local_schedules_to_paid_infra",
                    "agent": ", ".join(LOCAL_SCHEDULED),
                    "reason": (
                        "All LOCAL launchd schedules are stale — the local substrate is an "
                        "unreliable single point of failure for ops freshness."
                    ),
                    "remedy": (
                        "Move git-sync-auditor + memory-sync onto always-on infra "
                        "(Stratus/cloud cron). Requires infra spend."
                    ),
                    "escalate_to": "shay",  # capital / infra spend — the investor's desk
                }
            )

        return {"proposals": proposals}


def compose(state: State) -> dict:
    """Phrase the findings as a concise officer report. FAIL-SAFE.

    The model (TIER_DEFAULT, metered via ``budget_guard``) is used ONLY to phrase the already-
    gathered facts. On ANY failure (no key, budget, SDK drift) we fall back to a DETERMINISTIC
    text report built directly from the analysis/proposals, so a digest is always produced. No
    model train/eval/distill — phrasing only.
    """
    analysis = state.get("analysis") or {}
    proposals = state.get("proposals") or []
    ops_roster = state.get("ops_roster") or {}

    with span("coo.compose", risks=len(analysis.get("risks") or [])):
        facts = _deterministic_report(analysis, proposals, ops_roster)
        summary = ""
        try:
            model = budget_guard("coo", TIER_DEFAULT)
            prompt = (
                "You are the Chief Operating Officer over a small fleet of ops agents. From the "
                "facts below, write a CONCISE officer report: (1) which ops agents produced fresh "
                "output vs are stale/missing, (2) the ops risks — especially any LOCAL launchd "
                "schedules that did not fire, (3) the proposed fixes, noting which are resolved "
                "inside the org vs escalated to Shay (infra spend). Do NOT invent facts; only "
                "report what is shown. Be direct and skimmable.\n\n"
                f"{facts}"
            )
            resp = model.invoke(prompt)
            summary = getattr(resp, "content", str(resp)) or ""
        except Exception as exc:  # model unavailable — deterministic fallback (never empty)
            summary = (
                f"(model summary unavailable: {type(exc).__name__}) — deterministic report:\n\n"
                f"{facts}"
            )

        if not summary.strip():  # belt-and-suspenders: never deliver an empty summary
            summary = facts
        return {"summary": summary}


def deliver(state: State) -> dict:
    """Write a local digest artifact and file the officer digest issue (report-only on probation).

    - ``write_local_digest`` always runs (succeeds-or-"" ; never raises) so there is a local
      artifact even with zero credentials.
    - ``file_digest_issue(..., report_only=_report_only())`` delivers the issue. On probation
      (the default) this returns an honest report-only plan dict with NO GitHub call and NO
      approval interrupt — an unattended run can never hang or write.
    """
    summary = state.get("summary") or ""
    analysis = state.get("analysis") or {}
    proposals = state.get("proposals") or []
    ops_roster = state.get("ops_roster") or {}
    report_only = _report_only()

    with span("coo.deliver", report_only=report_only):
        assert_not_model_work(DIGEST_REPO)  # never file into a model-dev repo

        body = summary + "\n\n---\n\n## Raw facts\n\n" + _deterministic_report(
            analysis, proposals, ops_roster
        )

        # Local artifact first — always, fail-safe.
        digest_path = write_local_digest("coo", "COO: ops fleet health", body)

        # GitHub issue delivery — report-only by default (no write, no interrupt).
        res = file_digest_issue(
            DIGEST_REPO,
            "COO: ops fleet health (proposal)",
            body,
            labels=["exec:coo"],
            report_only=report_only,
            agent="coo",
            slack_title="⚙️ COO: ops fleet health (proposal)",
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
    """Terminal node — capture governance (report-only) and emit the verdict."""
    analysis = state.get("analysis") or {}
    proposals = state.get("proposals") or []
    prior = state.get("report") if isinstance(state.get("report"), dict) else {}
    delivery = prior.get("delivery")

    with span("coo.finalize", delivery=delivery):
        governance_capture(
            "coo",
            {
                "fresh": len(analysis.get("fresh") or []),
                "stale": len(analysis.get("stale") or []),
                "risks": len(analysis.get("risks") or []),
                "proposals": len(proposals),
                "delivery": delivery,
                "report_only": True,
            },
        )
        return {
            "report": {
                "fresh": len(analysis.get("fresh") or []),
                "stale": len(analysis.get("stale") or []),
                "risks": len(analysis.get("risks") or []),
                "proposals": len(proposals),
                "delivery": delivery,
                "digest": prior.get("digest"),
                "report_only": True,
            }
        }


# =============================================================================
# Routing
# =============================================================================
def _budget_route(state: State) -> str:
    """Route past the clock-in gate: clocked in -> gather; clocked out -> END."""
    return "gather" if check_clocked_in("coo") else "clocked_out"


# =============================================================================
# Deterministic report helpers (used by compose fallback + the issue appendix)
# =============================================================================
def _fmt_roster(ops_roster: dict) -> list:
    members = (ops_roster or {}).get("members") or []
    if not members:
        return ["- OPS class: (no roster ops agents)"]
    lines = [f"- OPS class ({len(members)} agents):"]
    for member in members:
        lines.append(
            f"    - {member.get('agent')} [{member.get('status')}] — {member.get('role')}"
        )
    return lines


def _fmt_freshness(analysis: dict) -> list:
    fresh = analysis.get("fresh") or []
    stale = analysis.get("stale") or []
    lines = ["- Subordinate digest freshness:"]
    lines.append(f"    - fresh ({len(fresh)}): " + (", ".join(fresh) or "none"))
    lines.append(f"    - stale/missing ({len(stale)}): " + (", ".join(stale) or "none"))
    return lines


def _fmt_risks(analysis: dict) -> list:
    risks = analysis.get("risks") or []
    if not risks:
        return ["- Ops risks: none (all subordinates fresh)"]
    lines = [f"- Ops risks ({len(risks)}):"]
    for risk in risks:
        lines.append(f"    - {risk.get('risk')} [{risk.get('agent')}]: {risk.get('detail')}")
    return lines


def _fmt_proposals(proposals: list) -> list:
    if not proposals:
        return ["- Proposed fixes: none"]
    lines = [f"- Proposed fixes ({len(proposals)}):"]
    for prop in proposals:
        lines.append(
            f"    - {prop.get('action')} [{prop.get('agent')}] "
            f"(escalate_to: {prop.get('escalate_to')}): {prop.get('remedy')}"
        )
    return lines


def _deterministic_report(analysis: dict, proposals: list, ops_roster: dict) -> str:
    """A skimmable plain-text officer report built ENTIRELY from the gathered facts (no model)."""
    lines = ["COO: ops fleet health", ""]
    lines += _fmt_roster(ops_roster)
    lines += _fmt_freshness(analysis)
    lines += _fmt_risks(analysis)
    lines += _fmt_proposals(proposals)
    return "\n".join(lines)


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
# CLOCK-IN gate runs first: clocked out -> governance + END; otherwise enter the pipeline.
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
