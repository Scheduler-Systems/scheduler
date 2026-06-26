"""growth_director — the BOARD officer for revenue/funnel oversight.

Runtime: cloud/CI (LangGraph Platform managed Cloud SaaS); register-able in
``langgraph.json`` (the orchestrator owns that file — not this module).

The board sits ABOVE the CEO and its product is OVERSIGHT, not re-doing the work. The growth
director CONSUMES the subordinate reports (the CMO's marketing digest + the CEO's executive
digest) plus the headline money number (RevenueCat), forms a revenue/funnel VERDICT, and
PROPOSES growth-oversight notes. It never re-runs a campaign or a funnel experiment — it reads
what growth already shipped and asks the board's question: is the revenue trajectory healthy,
and is growth actually shipping (drafts/experiments), measured against the ~0.4% conversion
baseline this fleet anchors on.

LOAD-BEARING DECISIONS (match the ops-fleet house style — see revenue_reporter, daily_digest,
hr_ops_manager):

  * OFFICERS CONSUME REPORTS. ``read_local_digest("cmo")`` / ``read_local_digest("ceo")`` read
    the subordinate digests fail-safe ("(no digest yet)" when missing); ``revenuecat.
    metrics_overview()`` is already fail-safe. No work is re-done.

  * PROBATION / REPORT-ONLY by default. The oversight digest is delivered via
    ``file_digest_issue(..., report_only=_report_only())`` where ``_report_only()`` defaults
    True (env ``OPS_REPORT_ONLY``; only "0"/"false"/"no" turns it off). On probation the
    delivery is an honest ``{"status": "report_only", ...}`` plan dict — NO GitHub write and,
    critically, NO approval interrupt — so a scheduled unattended run can never hang or write.

  * EVERYTHING RESOLVES INSIDE THE ORG. Growth oversight notes are board guidance to the org;
    none of them are capital/irreversible/legal, so every proposal is marked
    ``escalate_to: "org"`` — there is NO "ask for Shay" here. (A capital/legal item would be
    the only thing escalated to "shay", and growth oversight never produces one.)

  * NEVER HANG. With zero credentials the run still completes: every digest read / RC call /
    model call is wrapped so a missing key / offline / SDK drift returns a structured result
    and the node moves on. A telemetry/network problem never crashes a node. There is NO
    reachable ``request_approval``/interrupt on the scheduled path.

  * FAIL-SAFE compose. The model is used ONLY to phrase the gathered facts + the deterministic
    verdict; on ANY model failure (no key, budget, SDK drift) we fall back to a DETERMINISTIC
    text report built directly from the gathered dicts, so a digest is always produced.

  * ANTHROPIC-TERMS / ML BOUNDARY. ``assert_not_model_work`` guards every outward target string
    (the subordinate slugs and the digest repo). No model train/eval/distill; gal-model and the
    policy denylist are never read or reported.

  * Compiles WITHOUT a checkpointer/store (the platform injects Postgres). Every node body is
    wrapped in ``span("growth_director.<node>", ...)``; governance is captured at the end.
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

# Where the board's growth-oversight digest is filed (a no-prod-deploy, allow-listed repo).
DIGEST_REPO = "Scheduler-Systems/qa-agent-platform"

# The subordinate reports this officer CONSUMES (slug -> .tmp/<slug>/latest.md). The board
# reads the CMO's growth/marketing digest and the CEO's executive digest — it does NOT re-run
# the underlying work.
SUBORDINATE_DIGESTS = ("cmo", "ceo")

# The conversion baseline this fleet anchors on (~0.4%). Revenue/funnel health is judged
# against it: at/above baseline is "healthy"; clearly below is a "watch" signal. Env override
# ``GROWTH_CONVERSION_BASELINE`` (a fraction, e.g. 0.004) for tuning.
def _conversion_baseline() -> float:
    try:
        return max(0.0, float(os.environ.get("GROWTH_CONVERSION_BASELINE", "0.004")))
    except (TypeError, ValueError):
        return 0.004


def _report_only() -> bool:
    """Report-only default for the probation officer: truthy/unset env => True.

    Only an explicit ``OPS_REPORT_ONLY`` of "0"/"false"/"no" turns delivery into a real
    (gated) GitHub write. Everything else — including the env being unset — keeps the officer
    in honest report-only mode (no GitHub call, no approval interrupt).
    """
    return os.environ.get("OPS_REPORT_ONLY", "").lower() not in ("0", "false", "no")


class State(TypedDict, total=False):
    mode: str            # reserved for future read-only/observe variants
    rc: dict             # RevenueCat metrics_overview() result (fail-safe)
    digests: dict        # slug -> subordinate digest text ("(no digest yet)" when missing)
    analysis: dict       # revenue/funnel verdict (deterministic, model-free)
    proposals: list      # growth-oversight notes (all escalate_to="org")
    summary: str         # composed oversight narrative
    report: dict         # terminal verdict
    report_only: bool    # whether delivery stayed report-only


def budget_gate(state: State) -> dict:
    """CLOCK-IN gate — STOP before any work if over salary or globally disabled.

    Runs FIRST. If clocked in, control passes to ``gather``; if not, we capture governance
    (report-only) and route to END. No digest reads, no RC calls, no model spend, no writes on
    the clocked-out path.
    """
    with span("growth_director.budget_gate"):
        if check_clocked_in("growth_director"):
            return {}
        governance_capture(
            "growth_director",
            {
                "clocked_in": False,
                "delivery": "skipped",
                "report_only": True,
            },
        )
        return {"report": {"clocked_in": False}}


def gather(state: State) -> dict:
    """CONSUME the subordinate reports + the money number. Every read FAIL-SAFE.

    - ``digests`` : the CMO and CEO local digests via ``read_local_digest`` (guarded against
                    model-dev slugs first); a missing file degrades to "(no digest yet)".
    - ``rc``      : ``revenuecat.metrics_overview()`` — already a structured fail-safe dict
                    (``{"ok": bool, "metrics": ..., "error": ...}``); it never raises.

    The board does NOT re-run growth's work; it reads what growth already produced.
    """
    with span("growth_director.gather", subordinates=len(SUBORDINATE_DIGESTS)):
        digests: dict = {}
        for slug in SUBORDINATE_DIGESTS:
            assert_not_model_work(slug)  # never read/report a model-dev slug
            digests[slug] = read_local_digest(slug)  # fail-safe "(no digest yet)" when missing

        rc = revenuecat.metrics_overview()  # already fail-safe
        return {"rc": rc, "digests": digests}


def analyze(state: State) -> dict:
    """Form the revenue/funnel VERDICT — deterministic, model-free. FAIL-SAFE.

    Two board questions, answered ONLY from the gathered facts:
      1. REVENUE TRAJECTORY — is the money number present and non-trivial? We read the
         flattened RC metrics (mrr / active_subscriptions / active_trials / revenue). RC
         unavailable => "unknown" (not "bad" — missing data is never an adverse verdict).
      2. IS GROWTH SHIPPING? — do the subordinate digests show real growth output (drafts /
         experiments / campaigns), or are they empty placeholders? An empty/"(no digest yet)"
         CMO digest is the board's "growth is not shipping" signal.
    Conversion is judged against the ~0.4% baseline when a conversion metric is present.
    """
    rc = state.get("rc") or {}
    digests = state.get("digests") or {}
    baseline = _conversion_baseline()

    with span("growth_director.analyze", rc_ok=bool(rc.get("ok"))):
        metrics = rc.get("metrics") or {} if rc.get("ok") else {}

        # 1) Revenue trajectory.
        if not rc.get("ok"):
            revenue_verdict = "unknown"
            revenue_note = f"RevenueCat unavailable ({rc.get('error') or 'no metrics'})"
        elif not metrics:
            revenue_verdict = "unknown"
            revenue_note = "RevenueCat ok but returned no metrics"
        else:
            mrr = _num(metrics.get("mrr"))
            subs = _num(metrics.get("active_subscriptions"))
            if (mrr or 0) > 0 or (subs or 0) > 0:
                revenue_verdict = "tracking"
                revenue_note = f"mrr={metrics.get('mrr')} active_subscriptions={metrics.get('active_subscriptions')}"
            else:
                revenue_verdict = "flat"
                revenue_note = "no MRR and no active subscriptions in the headline metrics"

        # Conversion vs the ~0.4% baseline (only when a conversion metric is actually present).
        conversion = _num(metrics.get("conversion") or metrics.get("conversion_rate"))
        if conversion is None:
            conversion_verdict = "unknown"
            conversion_note = f"no conversion metric (baseline {_pct(baseline)})"
        elif conversion >= baseline:
            conversion_verdict = "at_or_above_baseline"
            conversion_note = f"conversion {_pct(conversion)} ≥ baseline {_pct(baseline)}"
        else:
            conversion_verdict = "below_baseline"
            conversion_note = f"conversion {_pct(conversion)} < baseline {_pct(baseline)}"

        # 2) Is growth shipping? — driven by the subordinate digests.
        shipping: dict = {}
        for slug in SUBORDINATE_DIGESTS:
            text = digests.get(slug) or ""
            shipping[slug] = _digest_has_output(text)
        growth_shipping = bool(shipping.get("cmo"))  # the CMO digest is the growth signal

        return {
            "analysis": {
                "baseline": baseline,
                "revenue_verdict": revenue_verdict,
                "revenue_note": revenue_note,
                "conversion_verdict": conversion_verdict,
                "conversion_note": conversion_note,
                "growth_shipping": growth_shipping,
                "shipping": shipping,
                "metrics": metrics,
            }
        }


def propose(state: State) -> dict:
    """Assemble growth-oversight notes. Propose-only; EVERY note escalates to the org.

    Growth oversight is board guidance to the org — never capital/irreversible/legal — so each
    proposal is marked ``escalate_to: "org"``. There is no "ask for Shay" on this path.
    """
    analysis = state.get("analysis") or {}

    with span("growth_director.propose"):
        proposals: list[dict] = []

        # Revenue trajectory note.
        if analysis.get("revenue_verdict") == "flat":
            proposals.append(
                _note(
                    "revenue",
                    "Revenue trajectory is flat — no MRR / active subscriptions in the headline "
                    "metrics. Direct growth + the CEO to focus the next cycle on the activation "
                    "→ paid funnel before new surface area.",
                )
            )
        elif analysis.get("revenue_verdict") == "unknown":
            proposals.append(
                _note(
                    "revenue",
                    "Revenue trajectory is UNKNOWN — the money number was unavailable this run "
                    f"({analysis.get('revenue_note')}). Restore RevenueCat reporting so the board "
                    "can judge trajectory; treat as a reporting gap, not a result.",
                )
            )

        # Conversion vs baseline note.
        if analysis.get("conversion_verdict") == "below_baseline":
            proposals.append(
                _note(
                    "conversion",
                    f"Conversion is BELOW the ~{_pct(analysis.get('baseline'))} baseline "
                    f"({analysis.get('conversion_note')}). Ask growth to ship a funnel experiment "
                    "targeting the activation step before any acquisition spend.",
                )
            )

        # Is growth shipping?
        if not analysis.get("growth_shipping"):
            proposals.append(
                _note(
                    "shipping",
                    "Growth does not appear to be SHIPPING — the CMO digest is empty / "
                    "'(no digest yet)'. The board's expectation is a steady stream of drafts and "
                    "funnel experiments; ask the CMO/CEO for the next cycle's growth output.",
                )
            )

        # Healthy-state note (still oversight: confirm and hold the bar).
        if not proposals:
            proposals.append(
                _note(
                    "steady",
                    "Revenue/funnel oversight: trajectory is tracking and growth is shipping. "
                    f"Hold the ~{_pct(analysis.get('baseline'))} conversion bar and keep the draft "
                    "/ experiment cadence; no board intervention required this cycle.",
                )
            )

        return {"proposals": proposals}


def compose(state: State) -> dict:
    """Phrase the verdict + proposals as a concise board oversight note. FAIL-SAFE.

    The model (TIER_DEFAULT, metered via ``budget_guard``) is used ONLY to summarize the
    already-formed verdict + proposals. On ANY failure (no key, budget, SDK drift) we fall back
    to a DETERMINISTIC text report built directly from the gathered facts, so a digest is always
    produced. No model train/eval/distill — phrasing only.
    """
    analysis = state.get("analysis") or {}
    proposals = state.get("proposals") or []
    rc = state.get("rc") or {}

    with span("growth_director.compose", proposals=len(proposals)):
        facts = _deterministic_report(rc, analysis, proposals)
        summary = ""
        try:
            model = budget_guard("growth_director", TIER_DEFAULT)
            prompt = (
                "You are the BOARD's growth director for the Scheduler product fleet. You do NOT "
                "re-do growth's work; you OVERSEE it. From the verdict + oversight notes below, "
                "write a CONCISE board oversight note covering, in order: (1) the revenue "
                "trajectory (and whether the money number was even available), (2) conversion vs "
                f"the ~{_pct(analysis.get('baseline'))} baseline, (3) whether growth is shipping "
                "drafts/experiments. Do NOT invent numbers; only report what the facts show. "
                "These are oversight notes for the org — be direct and skimmable.\n\n"
                f"{facts}"
            )
            resp = model.invoke(prompt)
            summary = getattr(resp, "content", str(resp)) or ""
        except Exception as exc:  # model unavailable — deterministic fallback (never empty)
            summary = (
                f"(model summary unavailable: {type(exc).__name__}) — deterministic oversight:\n\n"
                f"{facts}"
            )

        if not summary.strip():  # belt-and-suspenders: never deliver an empty summary
            summary = facts
        return {"summary": summary}


def deliver(state: State) -> dict:
    """Write a local digest artifact and file the oversight issue (report-only on probation).

    - ``write_local_digest`` always runs (succeeds-or-"" ; never raises) so there is a local
      artifact even with zero credentials.
    - ``file_digest_issue(..., report_only=_report_only())`` delivers the issue. On probation
      (the default) this returns an honest report-only plan dict with NO GitHub call and NO
      approval interrupt — an unattended run can never hang or write.
    """
    summary = state.get("summary") or ""
    rc = state.get("rc") or {}
    analysis = state.get("analysis") or {}
    proposals = state.get("proposals") or []
    report_only = _report_only()

    with span("growth_director.deliver", report_only=report_only):
        assert_not_model_work(DIGEST_REPO)  # never file into a model-dev repo
        body = summary + "\n\n---\n\n## Raw facts\n\n" + _facts_appendix(rc, analysis, proposals)

        # Local artifact first — always, fail-safe.
        digest_path = write_local_digest(
            "growth-director", "Board — Growth (oversight)", body
        )

        # GitHub issue delivery — report-only by default (no write, no interrupt).
        res = file_digest_issue(
            DIGEST_REPO,
            "Board — Growth (oversight)",
            body,
            labels=["board:growth"],
            report_only=report_only,
            agent="growth_director",
            slack_title="📈 Board — Growth (oversight)",
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

    with span("growth_director.finalize", delivery=delivery):
        governance_capture(
            "growth_director",
            {
                "revenue_verdict": analysis.get("revenue_verdict"),
                "conversion_verdict": analysis.get("conversion_verdict"),
                "growth_shipping": analysis.get("growth_shipping"),
                "proposals": len(proposals),
                "escalations": [p.get("escalate_to") for p in proposals],
                "delivery": delivery,
                "report_only": True,
            },
        )
        return {
            "report": {
                "revenue_verdict": analysis.get("revenue_verdict"),
                "conversion_verdict": analysis.get("conversion_verdict"),
                "growth_shipping": analysis.get("growth_shipping"),
                "proposals": len(proposals),
                "delivery": delivery,
                "digest": prior.get("digest"),
                "report_only": True,
            }
        }


def _budget_route(state: State) -> str:
    """Route past the clock-in gate: clocked in -> gather; clocked out -> END."""
    return "gather" if check_clocked_in("growth_director") else "clocked_out"


# --- Helpers (deterministic; no model) ---------------------------------------------------
def _note(area: str, text: str) -> dict:
    """A single growth-oversight proposal. ALWAYS escalate_to='org' (never an ask for Shay).

    Growth oversight is board guidance to the org — never capital/irreversible/legal — so it is
    resolved inside the org. The only thing that would be ``escalate_to: "shay"`` is a
    capital/irreversible/legal item, which growth oversight does not produce.
    """
    return {"area": area, "note": text, "escalate_to": "org"}


def _num(value) -> float | None:
    """Best-effort numeric coercion (RC values may be strings/None). None on any failure."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pct(value) -> str:
    try:
        return f"{float(value) * 100:.2f}%"
    except (TypeError, ValueError):
        return "0%"


def _digest_has_output(text: str) -> bool:
    """True when a subordinate digest shows REAL output (not a missing/placeholder digest)."""
    t = (text or "").strip().lower()
    if not t or t == "(no digest yet)":
        return False
    # A header-only digest with no body is still "no output".
    return len(t) > len("(no digest yet)")


def _fmt_rc(rc: dict) -> list[str]:
    if not rc.get("ok"):
        return [f"- RevenueCat: unavailable ({rc.get('error') or 'no metrics'})"]
    metrics = rc.get("metrics") or {}
    if not metrics:
        return ["- RevenueCat: ok, but no metrics returned"]
    return ["- RevenueCat metrics:"] + [
        f"    - {key}: {value}" for key, value in sorted(metrics.items())
    ]


def _fmt_analysis(analysis: dict) -> list[str]:
    return [
        "- Verdict:",
        f"    - revenue trajectory: {analysis.get('revenue_verdict')} "
        f"({analysis.get('revenue_note')})",
        f"    - conversion: {analysis.get('conversion_verdict')} "
        f"({analysis.get('conversion_note')})",
        f"    - growth shipping: {analysis.get('growth_shipping')}",
    ]


def _fmt_proposals(proposals: list) -> list[str]:
    if not proposals:
        return ["- Oversight notes: (none)"]
    lines = ["- Oversight notes (all resolved inside the org):"]
    for p in proposals:
        lines.append(f"    - [{p.get('area')}] (escalate_to={p.get('escalate_to')}) {p.get('note')}")
    return lines


def _deterministic_report(rc: dict, analysis: dict, proposals: list) -> str:
    """A skimmable plain-text oversight report built ENTIRELY from the gathered dicts (no model)."""
    lines = ["Board — Growth (oversight)", ""]
    lines += _fmt_rc(rc)
    lines += _fmt_analysis(analysis)
    lines += _fmt_proposals(proposals)
    return "\n".join(lines)


def _facts_appendix(rc: dict, analysis: dict, proposals: list) -> str:
    """The raw gathered facts, appended verbatim to the digest body for auditability."""
    return _deterministic_report(rc, analysis, proposals)


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
