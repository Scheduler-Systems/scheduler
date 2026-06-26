"""cmo — the Chief Marketing Officer.

Runtime: cloud/CI (LangGraph Platform managed Cloud SaaS); register-able in
``langgraph.json`` (the orchestrator owns that file — not this module).

MISSION: own GROWTH OUTPUT + FUNNEL OVERSIGHT. The CMO is an EXECUTIVE: it CONSUMES the
growth team's latest digests rather than re-doing their work, reads the RevenueCat funnel
signal, and PROPOSES a small set of growth priorities for the org. It does NOT execute
campaigns, change store listings, or move money — every action lands as a PROPOSAL.

What it reads (all BEST-EFFORT / FAIL-SAFE — a missing report is never an error):
  - ``read_local_digest`` for the three growth subordinates:
      * conversion-growth-analyst — the funnel/conversion analysis,
      * aso-store-listing-agent   — the store-listing / ASO drafts,
      * content-campaign-drafter  — the content/campaign drafts.
    A missing file is reported as "(no digest yet)", never an error.
  - ``revenuecat.metrics_overview`` — the funnel money signal (MRR / active subs / trials /
    revenue). Already FAIL-SAFE: returns ``{"ok": bool, "metrics": ..., "error": ...}``.

LOAD-BEARING DECISIONS (match the ops-fleet house style — see revenue_reporter,
daily_digest, hr_ops_manager):

  * PROPOSE-ONLY. Every growth priority is a PROPOSAL with an ``escalate_to`` tag. The org
    resolves everything inside itself ("org") EXCEPT capital / irreversible / legal / paid /
    live moves, which are flagged "shay" (an investor escalation = an ask for Shay). Delivery
    goes through ``file_digest_issue(..., report_only=_report_only())``.

  * NEVER HANG. There is NO reachable ``request_approval``/interrupt on the scheduled path.
    On probation (the default) delivery is an honest report-only plan dict — NO GitHub write
    and NO approval interrupt — so an unattended scheduled run can never hang or write.

  * FAIL-SAFE. Every digest read / RC call / model call is wrapped; a missing key / offline
    backend / SDK drift returns a structured result and the run still completes. The model is
    used ONLY to phrase the already-gathered facts; on ANY model failure we fall back to a
    DETERMINISTIC priority list + report built directly from the gathered dicts, so a digest
    is always produced. A telemetry/network problem never crashes a node.

  * SECRETS env-only; error strings are type/status only. ANTHROPIC-TERMS / ML BOUNDARY:
    ``assert_not_model_work`` guards every outward target string (the subordinate slugs and
    the digest repo); gal-model / denylisted ids are skipped, never read or reported.

  * CLOCK-IN: ``budget_gate`` runs first; over-salary / globally-disabled => terminal report.
    Every node body is wrapped in ``span("cmo.<node>", ...)``; governance is captured at the
    end (report_only=True). Compiles WITHOUT a checkpointer/store (the platform injects
    Postgres).
"""
from __future__ import annotations

import os

from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END

from agent_toolkit import (
    budget_guard,
    check_clocked_in,
    span,
    governance_capture,
    assert_not_model_work,
    read_local_digest,
    write_local_digest,
    file_digest_issue,
    TIER_DEFAULT,
)
from agent_toolkit import revenuecat
from agent_toolkit.policy import ModelWorkBlocked

# Where the CMO's growth + funnel proposal issue is filed (allow-listed, no-prod-deploy).
DIGEST_REPO = "Scheduler-Systems/qa-agent-platform"

# The growth subordinates whose latest digests the CMO consumes (slug -> path segment under
# <WORKSPACE_ROOT>/.tmp/<slug>/latest.md). Officers CONSUME reports — they do not re-do work.
GROWTH_DIGESTS = (
    "conversion-growth-analyst",
    "aso-store-listing-agent",
    "content-campaign-drafter",
)


def _report_only() -> bool:
    """Report-only default for the probation officer: truthy/unset env => True.

    Only an explicit ``OPS_REPORT_ONLY`` of "0"/"false"/"no" turns delivery into a real
    (gated) GitHub write. Everything else — including the env being unset — keeps the officer
    in honest report-only mode (no GitHub call, no approval interrupt).
    """
    return os.environ.get("OPS_REPORT_ONLY", "").lower() not in ("0", "false", "no")


class State(TypedDict, total=False):
    mode: str            # reserved for future read-only/observe variants
    digests: dict        # slug -> subordinate digest text (or "(no digest yet)")
    funnel: dict         # RevenueCat metrics_overview() result (fail-safe)
    analysis: dict       # which growth drafts exist + funnel-conversion read
    proposals: list      # growth priorities, each tagged escalate_to: "org" | "shay"
    summary: str         # composed CMO report text
    report: dict         # terminal verdict
    report_only: bool    # whether delivery stayed report-only


def budget_gate(state: State) -> dict:
    """CLOCK-IN gate — STOP before any work if over salary or globally disabled.

    Runs FIRST. If clocked in, control passes to ``gather``; if not, we capture governance
    (report-only) and route to END. No digest reads, no RC calls, no model spend, no writes
    on the clocked-out path.
    """
    with span("cmo.budget_gate"):
        if check_clocked_in("cmo"):
            return {}
        governance_capture(
            "cmo",
            {
                "clocked_in": False,
                "delivery": "skipped",
                "report_only": True,
            },
        )
        return {"report": {"clocked_in": False}}


def gather(state: State) -> dict:
    """Consume the growth subordinates' digests + read the RevenueCat funnel. Every read FAIL-SAFE.

    - ``digests`` : per growth slug, guard the slug string (Anthropic terms) then read its
                    latest local digest via ``read_local_digest`` (already fail-safe — a
                    missing file becomes "(no digest yet)"). A slug that trips the model-work
                    denylist is skipped, never read.
    - ``funnel``  : ``revenuecat.metrics_overview()`` already returns a structured
                    ``{"ok": bool, "metrics": ..., "error": ...}`` dict; it never raises.
    """
    with span("cmo.gather", slugs=len(GROWTH_DIGESTS)):
        # 1) Subordinate growth digests — officers consume, never re-do.
        digests: dict = {}
        for slug in GROWTH_DIGESTS:
            try:
                assert_not_model_work(slug)  # never consume/report a model-dev target
            except ModelWorkBlocked:
                continue  # skip a denylisted slug entirely
            digests[slug] = read_local_digest(slug)  # fail-safe: "(no digest yet)" on miss

        # 2) Funnel money signal — already fail-safe.
        funnel = revenuecat.metrics_overview()

        return {"digests": digests, "funnel": funnel}


def analyze(state: State) -> dict:
    """Determine which growth drafts EXIST and read the funnel conversion. Deterministic, FAIL-SAFE.

    "Exists" = the subordinate produced a non-placeholder digest (not "(no digest yet)" /
    empty). The funnel read pulls the well-known conversion metrics out of the RC overview
    when present, degrading to None per-metric when the funnel was unavailable — never raises.
    """
    digests = state.get("digests") or {}
    funnel = state.get("funnel") or {}

    with span("cmo.analyze", funnel_ok=bool(funnel.get("ok"))):
        drafts: dict = {}
        for slug in GROWTH_DIGESTS:
            text = digests.get(slug)
            drafts[slug] = bool(text) and text.strip() not in ("", "(no digest yet)")

        metrics = funnel.get("metrics") or {} if funnel.get("ok") else {}
        conversion = {
            "ok": bool(funnel.get("ok")),
            "mrr": metrics.get("mrr"),
            "active_subscriptions": metrics.get("active_subscriptions"),
            "active_trials": metrics.get("active_trials"),
            "revenue": metrics.get("revenue"),
            "error": None if funnel.get("ok") else (funnel.get("error") or "funnel unavailable"),
        }

        return {
            "analysis": {
                "drafts": drafts,
                "drafts_present": sum(1 for v in drafts.values() if v),
                "drafts_missing": [s for s, present in drafts.items() if not present],
                "conversion": conversion,
            }
        }


def propose(state: State) -> dict:
    """Assemble growth priorities as PROPOSALS — all "org" unless paid/live (=> "shay").

    Deterministic so a priority list is ALWAYS produced even with zero data:
      - For each growth area WITHOUT a current draft, propose commissioning it ("org").
      - When the funnel signal is missing, propose restoring funnel instrumentation ("org").
      - A standing funnel-conversion review of any present analysis ("org").
    Anything that would spend money or touch a LIVE surface (a paid campaign, a live store
    listing change) is capital/irreversible => ``escalate_to: "shay"``. Nothing here executes.
    """
    analysis = state.get("analysis") or {}
    drafts = analysis.get("drafts") or {}
    conversion = analysis.get("conversion") or {}

    with span("cmo.propose", missing=len(analysis.get("drafts_missing") or [])):
        proposals: list = []

        # 1) Commission any missing growth draft — staffed work, resolved inside the org.
        for slug in GROWTH_DIGESTS:
            if not drafts.get(slug):
                proposals.append(
                    {
                        "action": "commission_growth_draft",
                        "area": slug,
                        "why": f"no current {slug} digest — growth output gap",
                        "escalate_to": "org",
                    }
                )

        # 2) Funnel oversight — restore instrumentation if the money signal is dark.
        if not conversion.get("ok"):
            proposals.append(
                {
                    "action": "restore_funnel_instrumentation",
                    "area": "funnel",
                    "why": f"RevenueCat funnel unavailable ({conversion.get('error')})",
                    "escalate_to": "org",
                }
            )
        else:
            proposals.append(
                {
                    "action": "review_funnel_conversion",
                    "area": "funnel",
                    "why": (
                        f"funnel signal present (mrr={conversion.get('mrr')}, "
                        f"trials={conversion.get('active_trials')}, "
                        f"subs={conversion.get('active_subscriptions')}) — review conversion"
                    ),
                    "escalate_to": "org",
                }
            )

        # 3) Launch-readiness PROPOSAL: when every growth draft exists, the org is ready to
        #    propose a paid/live push. That spends money / touches a LIVE surface, so it is an
        #    investor escalation — NOT resolved inside the org.
        if drafts and all(drafts.get(s) for s in GROWTH_DIGESTS):
            proposals.append(
                {
                    "action": "approve_paid_growth_push",
                    "area": "campaign",
                    "why": "all growth drafts ready — paid/live push spends money (capital)",
                    "escalate_to": "shay",  # paid/live => investor escalation
                }
            )

        return {"proposals": proposals}


def compose(state: State) -> dict:
    """Phrase the analysis + proposals as a concise CMO report. FAIL-SAFE.

    The model (TIER_DEFAULT, metered via ``budget_guard``) is used ONLY to summarize the
    already-gathered facts. On ANY failure (no key, budget, SDK drift) we fall back to a
    DETERMINISTIC text report built directly from analysis/proposals, so a digest is always
    produced. No model train/eval/distill — phrasing only.
    """
    analysis = state.get("analysis") or {}
    proposals = state.get("proposals") or []

    with span("cmo.compose", proposals=len(proposals)):
        facts = _deterministic_report(analysis, proposals)
        summary = ""
        try:
            model = budget_guard("cmo", TIER_DEFAULT)
            prompt = (
                "You are the Chief Marketing Officer for the Scheduler product fleet. You "
                "CONSUME the growth team's reports — you do NOT re-do their work. Write a "
                "CONCISE growth + funnel update for the org from the gathered facts below. "
                "Cover, in order: (1) which growth drafts exist vs are missing, (2) the funnel "
                "conversion signal (MRR / trials / active subs — or clearly note when "
                "unavailable), (3) the proposed growth priorities, separating org-resolved "
                "items from the ones escalated to Shay (paid/live/capital). Do NOT invent "
                "numbers; only report what the facts show. Be direct and skimmable.\n\n"
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
    """Write a local digest artifact and file the CMO proposal issue (report-only on probation).

    - ``write_local_digest`` always runs (succeeds-or-"" ; never raises) so there is a local
      artifact even with zero credentials.
    - ``file_digest_issue(..., report_only=_report_only())`` delivers the issue. On probation
      (the default) this returns an honest report-only plan dict with NO GitHub call and NO
      approval interrupt — an unattended run can never hang or write.
    """
    summary = state.get("summary") or ""
    analysis = state.get("analysis") or {}
    proposals = state.get("proposals") or []
    report_only = _report_only()

    with span("cmo.deliver", report_only=report_only):
        assert_not_model_work(DIGEST_REPO)  # never file into a model-dev repo

        body = summary + "\n\n---\n\n## Raw facts\n\n" + _facts_appendix(analysis, proposals)

        # Local artifact first — always, fail-safe.
        digest_path = write_local_digest("cmo", "CMO: growth + funnel", body)

        # GitHub issue delivery — report-only by default (no write, no interrupt).
        res = file_digest_issue(
            DIGEST_REPO,
            "CMO: growth + funnel (proposal)",
            body,
            labels=["exec:cmo"],
            report_only=report_only,
            agent="cmo",
            slack_title="📢 CMO: growth + funnel (proposal)",
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
    prior = state.get("report") or {}
    delivery = prior.get("delivery")
    asks_for_shay = sum(1 for p in proposals if p.get("escalate_to") == "shay")

    with span("cmo.finalize", delivery=delivery, proposals=len(proposals)):
        governance_capture(
            "cmo",
            {
                "funnel_ok": (analysis.get("conversion") or {}).get("ok"),
                "drafts_present": analysis.get("drafts_present"),
                "proposals": len(proposals),
                "asks_for_shay": asks_for_shay,
                "delivery": delivery,
                "report_only": True,
            },
        )
        return {
            "report": {
                "funnel_ok": (analysis.get("conversion") or {}).get("ok"),
                "drafts_present": analysis.get("drafts_present"),
                "proposals": len(proposals),
                "asks_for_shay": asks_for_shay,
                "delivery": delivery,
                "digest": prior.get("digest"),
                "report_only": True,
            }
        }


def _budget_route(state: State) -> str:
    """Route past the clock-in gate: clocked in -> gather; clocked out -> END."""
    return "gather" if check_clocked_in("cmo") else "clocked_out"


# --- Deterministic report helpers (used by compose fallback + the issue appendix) --------
def _fmt_drafts(analysis: dict) -> list[str]:
    drafts = analysis.get("drafts") or {}
    if not drafts:
        return ["- Growth drafts: (none checked)"]
    lines = ["- Growth drafts:"]
    for slug in GROWTH_DIGESTS:
        present = drafts.get(slug)
        lines.append(f"    - {slug}: {'present' if present else 'MISSING'}")
    return lines


def _fmt_funnel(analysis: dict) -> list[str]:
    conversion = analysis.get("conversion") or {}
    if not conversion.get("ok"):
        return [f"- Funnel: unavailable ({conversion.get('error') or 'no metrics'})"]
    return [
        "- Funnel conversion:",
        f"    - mrr: {conversion.get('mrr')}",
        f"    - active_subscriptions: {conversion.get('active_subscriptions')}",
        f"    - active_trials: {conversion.get('active_trials')}",
        f"    - revenue: {conversion.get('revenue')}",
    ]


def _fmt_proposals(proposals: list) -> list[str]:
    if not proposals:
        return ["- Proposals: (none)"]
    lines = ["- Growth priority proposals:"]
    for p in proposals:
        lines.append(
            f"    - [{p.get('escalate_to')}] {p.get('action')} ({p.get('area')}): {p.get('why')}"
        )
    return lines


def _deterministic_report(analysis: dict, proposals: list) -> str:
    """A skimmable plain-text report built ENTIRELY from the gathered dicts (no model)."""
    lines = ["CMO: growth + funnel (proposal)", ""]
    lines += _fmt_drafts(analysis)
    lines += _fmt_funnel(analysis)
    lines += _fmt_proposals(proposals)
    return "\n".join(lines)


def _facts_appendix(analysis: dict, proposals: list) -> str:
    """The raw gathered facts, appended verbatim to the digest body for auditability."""
    return _deterministic_report(analysis, proposals)


# --- Graph wiring ------------------------------------------------------------------------
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
