"""board_chair — the BOARD officer that hands Shay THE INVESTOR UPDATE.

Shay is the founder + investor; the board meets on cadence (daily while the fleet is young),
reviews the CEO's report and the directors' oversight, and hands Shay ONE short investor
update. The chair does NOT re-do anyone's work — it CONSUMES the subordinate agents' latest
local digests and synthesizes them:

  - ``ceo``                 — company priorities synthesized from the exec suite,
  - ``audit-risk-director`` — spend-vs-budget / safety-gate / security oversight,
  - ``growth-director``     — revenue / funnel oversight,
  - ``daily-digest``        — the fleet autonomy scoreboard (staffed/active/coverage),
  - ``cfo``                 — burn vs budget + revenue/cost.

The update is tight (a board report, not a data dump) and has exactly three parts:
  (a) KPIs        — staffed/active, burn vs budget, revenue/MRR, tests landed / drafts produced,
  (b) DECISIONS   — what the org RESOLVED inside itself this cadence (escalate_to "org"),
  (c) ASKS        — ONLY capital / irreversible / legal items go to Shay (escalate_to "shay");
                    everything else is resolved inside the org, so if there are no shay-level
                    items the asks section reads "no asks".

LOAD-BEARING DECISIONS (match the ops-fleet house style — revenue_reporter, daily_digest,
hr_ops_manager):

  * PROPOSE-ONLY / REPORT-ONLY. The investor update is delivered via
    ``file_digest_issue(..., report_only=_report_only())`` where ``_report_only()`` defaults
    True (env ``OPS_REPORT_ONLY``; only "0"/"false"/"no" turns it off). On probation the
    delivery is an honest report-only plan dict — NO GitHub write and, critically, NO approval
    interrupt — so a scheduled unattended cadence run can never hang or write. Every escalation
    is a PROPOSAL tagged ``escalate_to`` "org" | "shay"; nothing mutating happens here.

  * NEVER HANGS unattended. There is no reachable ``request_approval``/interrupt on the path.

  * FAIL-SAFE. Every subordinate digest / RC / payroll / LangSmith / model read is wrapped via
    the toolkit's own fail-safe helpers (``read_local_digest`` returns "(no digest yet)" when a
    file is missing); a missing digest degrades the update, it never crashes a node. The model
    only PHRASES the assembled facts — on ANY model failure we keep the DETERMINISTIC update.

  * SECRETS env-only; error strings are type-only. ML BOUNDARY: ``assert_not_model_work`` guards
    the digest repo (the outward target); gal-model / denylisted ids are never touched.

  * CLOCK-IN first (``budget_gate``); ``governance_capture("board_chair", {..., "report_only":
    True})`` is terminal; every node body is wrapped in ``span("board_chair.<node>", ...)``.

  * Compiles WITHOUT a checkpointer/store (the platform injects Postgres).
"""
from __future__ import annotations

import json
import os

from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END

from agent_toolkit import (
    budget_guard,
    check_clocked_in,
    span,
    governance_capture,
    assert_not_model_work,
    write_local_digest,
    file_digest_issue,
    read_local_digest,
    TIER_DEFAULT,
)
from agent_toolkit import payroll, revenuecat
from agent_toolkit import lanes

# Where the investor update issue is filed (a no-prod-deploy, allow-listed repo).
DIGEST_REPO = "Scheduler-Systems/qa-agent-platform"

# The subordinate reports the chair SYNTHESIZES (slug -> consumed via read_local_digest).
# CEO + the two directors are the oversight chain; daily-digest is the autonomy scoreboard;
# cfo is the money/burn signal.
SUBORDINATE_DIGESTS = (
    "ceo",
    "audit-risk-director",
    "growth-director",
    "daily-digest",
    "cfo",
)


def _report_only() -> bool:
    """Report-only default for the probation board: truthy/unset env => True.

    Only an explicit ``OPS_REPORT_ONLY`` of "0"/"false"/"no" turns delivery into a real
    (gated) GitHub write. Everything else — including the env being unset — keeps the chair
    in honest report-only mode (no GitHub call, no approval interrupt).
    """
    return os.environ.get("OPS_REPORT_ONLY", "").lower() not in ("0", "false", "no")


class State(TypedDict, total=False):
    mode: str            # reserved for future read-only/observe variants
    reports: dict        # slug -> subordinate digest text (fail-safe "(no digest yet)")
    kpis: dict           # the headline KPIs assembled from roster/RC/digests
    decisions: list      # decisions RESOLVED inside the org this cadence (escalate_to "org")
    asks: list           # capital/irreversible/legal items for Shay (escalate_to "shay")
    body: str            # the assembled investor update markdown
    report: dict         # terminal verdict
    report_only: bool    # whether delivery stayed report-only


# =============================================================================
# Nodes
# =============================================================================
def budget_gate(state: State) -> dict:
    """CLOCK-IN gate — STOP before any work if over salary or globally disabled.

    Runs FIRST. Clocked in => proceed to ``gather``; clocked out => terminal report +
    governance (report-only), no reads, no model spend, no writes.
    """
    with span("board_chair.budget_gate"):
        if check_clocked_in("board_chair"):
            return {}
        report = {
            "status": "skipped",
            "detail": "board_chair over token salary or globally disabled",
            "report_only": True,
        }
        governance_capture(
            "board_chair",
            {"clocked_in": False, "report_only": True, "report": report},
        )
        return {"report": report, "report_only": True}


def gather(state: State) -> dict:
    """Read every subordinate digest + the headline KPI facts. Every read FAIL-SAFE.

    The chair CONSUMES reports rather than re-doing work:
      - ``reports`` : each subordinate's latest local digest via ``read_local_digest`` (a
                      missing file degrades to "(no digest yet)" — never an error).
      - ``kpis``    : the headline numbers the board cares about — staffed/active (roster),
                      burn vs budget (payroll), revenue/MRR (RevenueCat, already fail-safe).
                      tests-landed / drafts-produced are surfaced from the CEO/daily-digest
                      narrative (we do NOT re-run QA — see _extract_output).
    """
    with span("board_chair.gather", subordinates=len(SUBORDINATE_DIGESTS)):
        reports = {slug: read_local_digest(slug) for slug in SUBORDINATE_DIGESTS}
        kpis = _assemble_kpis(reports)
        return {"reports": reports, "kpis": kpis}


def synthesize(state: State) -> dict:
    """Assemble the org-level DECISIONS and the Shay-level ASKS. FAIL-SAFE, deterministic.

    DECISIONS (escalate_to "org"): the routine cadence outcomes the board ratifies internally —
    e.g. "CEO report reviewed", "directors' oversight noted". These are resolved inside the org
    and NEVER bubble to Shay.

    ASKS (escalate_to "shay"): ONLY capital / irreversible / legal items reach the investor. We
    surface an ask only when a subordinate digest explicitly flags a Shay-level item (an
    ``escalate_to: shay`` marker or one of the capital/irreversible/legal keywords). With no such
    flag the asks list is EMPTY — the update will say "no asks". Conservative on purpose: the
    board does not invent capital asks.
    """
    reports = state.get("reports") or {}

    with span("board_chair.synthesize", subordinates=len(reports)):
        decisions: list[dict] = []
        for slug in SUBORDINATE_DIGESTS:
            text = reports.get(slug) or "(no digest yet)"
            present = text.strip() not in ("", "(no digest yet)")
            decisions.append(
                {
                    "decision": (
                        f"{slug} report reviewed" if present else f"{slug} report not yet filed"
                    ),
                    "source": slug,
                    "escalate_to": "org",  # ratified inside the org — never bubbles to Shay
                }
            )

        asks = _collect_shay_asks(reports)
        return {"decisions": decisions, "asks": asks}


def compose(state: State) -> dict:
    """Assemble the TIGHT investor update: KPIs, decisions-made, asks-if-any. FAIL-SAFE.

    The body is built DETERMINISTICALLY from the assembled KPIs/decisions/asks so it is ALWAYS
    produced (and the "no asks" line is deterministic). An optional budget-metered model adds a
    one-paragraph chair's note at the top; on ANY model failure (no key, budget, SDK drift) the
    deterministic update stands unchanged — never empty. Phrasing only — no train/eval/distill.
    """
    kpis = state.get("kpis") or {}
    decisions = state.get("decisions") or []
    asks = state.get("asks") or []

    with span("board_chair.compose", asks=len(asks)):
        body = _render_update(kpis, decisions, asks)

        narrative = ""
        try:
            model = budget_guard("board_chair", TIER_DEFAULT)
            prompt = (
                "You are the BOARD CHAIR writing a SHORT investor update for the founder/investor "
                "(Shay) of a software QA-agent company. In 2-3 sentences, give the headline: how "
                "the company is doing on its KPIs (staffing/coverage, burn vs budget, revenue/MRR, "
                "tests landed / drafts produced) and whether there is anything the investor must "
                "act on. FRAMING: this is a STATUS update, not an alarm — if the Shay-level asks "
                "list is empty, say so plainly ('no founder asks this cadence'); do NOT manufacture "
                "urgency or address the founder with 'act now' when there are no bright-line asks. "
                "Be factual and tight; do NOT invent numbers; do NOT create capital asks that the "
                "facts below do not contain. The reconciled ask count below is authoritative — do "
                "not contradict it.\n\n"
                f"KPIs: {json.dumps(kpis, default=str)[:2000]}\n"
                f"Shay-level asks (reconciled, authoritative): {json.dumps(asks, default=str)[:1000]}\n"
            )
            resp = model.invoke(prompt)
            content = getattr(resp, "content", str(resp)) or ""
            narrative = content.strip()
        except Exception as exc:  # model/key unavailable — deterministic update stands
            narrative = f"_(chair's note unavailable: {type(exc).__name__})_"

        if narrative:
            body = f"{narrative}\n\n{body}"
        if not body.strip():  # belt-and-suspenders: never deliver an empty update
            body = _render_update(kpis, decisions, asks)
        return {"body": body}


def deliver(state: State) -> dict:
    """Write the local digest + file the investor-update issue (report-only on probation).

    ``write_local_digest`` always runs (succeeds-or-"" ; never raises) so there is a local
    artifact even with zero credentials. ``file_digest_issue(..., report_only=_report_only())``
    delivers the issue — on probation (the default) it returns an honest report-only plan dict
    with NO GitHub call and NO approval interrupt, so an unattended cadence run can never hang
    or write.
    """
    body = state.get("body") or "(empty investor update)"
    report_only = _report_only()

    with span("board_chair.deliver", report_only=report_only):
        assert_not_model_work(DIGEST_REPO)  # never file into a model-dev repo

        digest_path = write_local_digest("board-chair", "Board → Investor update", body)

        res = file_digest_issue(
            DIGEST_REPO,
            "Board → Investor update",
            body,
            labels=["board:investor-update"],
            report_only=report_only,
            agent="board_chair",
            slack_title="🏛️ Board → Investor update",
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
    """Terminal node — capture governance (report_only=True) and emit the verdict."""
    kpis = state.get("kpis") or {}
    decisions = state.get("decisions") or []
    asks = state.get("asks") or []
    prior = state.get("report") if isinstance(state.get("report"), dict) else {}
    delivery = prior.get("delivery")

    with span("board_chair.finalize", delivery=delivery, asks=len(asks)):
        governance_capture(
            "board_chair",
            {
                "kpis": kpis,
                "decisions": len(decisions),
                "asks": len(asks),
                "delivery": delivery,
                "report_only": True,
            },
        )
        return {
            "report": {
                "kpis": kpis,
                "decisions": len(decisions),
                "asks": len(asks),
                "delivery": delivery,
                "digest": prior.get("digest"),
                "report_only": True,
            }
        }


# =============================================================================
# Routing
# =============================================================================
def _budget_route(state: State) -> str:
    """Clocked in -> start gathering; clocked out -> END (terminal report already set)."""
    return "gather" if check_clocked_in("board_chair") else "clocked_out"


# =============================================================================
# KPI assembly (deterministic, fail-safe — no model)
# =============================================================================
def _is_model_work(name: str) -> bool:
    """Bool predicate over ``assert_not_model_work`` — True if ``name`` is a model-dev role.

    Wraps the toolkit guard so the PURE ``lanes.staffing_view`` can be fed a simple predicate
    (it must never count a model-dev role; Anthropic terms). Any guard error is treated as
    'not model work' (fail-open on the predicate, the guard itself stays authoritative elsewhere)."""
    try:
        assert_not_model_work(name)
        return False
    except Exception:
        return True


def _assemble_kpis(reports: dict) -> dict:
    """Headline KPIs from roster + RevenueCat + the subordinate narratives. FAIL-SAFE.

    - staffed / active : counted off roster.yaml (probation status => not active).
    - burn vs budget   : summed salary vs spent across the roster (payroll math).
    - revenue / MRR    : RevenueCat ``metrics_overview`` (already fail-safe).
    - output           : tests-landed / drafts-produced, surfaced from the CEO / daily-digest
                         narrative WITHOUT re-running QA (the chair consumes, never re-does).

    Any read failing degrades that KPI to a safe default; the KPI dict is always producible.
    """
    salary_total = 0
    spent_total = 0
    try:
        roster = payroll.load_roster()
    except Exception:
        roster = {"agents": {}}
    agents = roster.get("agents", {}) or {}

    # Staffed/active headcount via the SHARED lanes helper (relocated, so the daily-digest survivor
    # computes the SAME view). "active" = operationally ON-SHIFT (clocked-in: not disabled / benched
    # / over-budget) — a probation agent working its report-only shift IS active; this stops the
    # board reporting "0 active" while the whole fleet is in fact working its shift.
    head = lanes.staffing_view(
        roster,
        is_clocked_in=check_clocked_in,
        is_model_work=_is_model_work,
    )
    staffed = head["staffed"]
    active = head["active"]

    # Burn (salary vs spent) is the chair's own KPI — keep it here, per surviving (non-model) agent.
    for name in agents:
        if _is_model_work(name):
            continue
        try:
            salary_total += payroll.salary(name, roster=roster)
            spent_total += payroll.spent(name)
        except Exception:
            pass

    try:
        rc = revenuecat.metrics_overview()
    except Exception:
        rc = {"ok": False, "metrics": {}, "error": "unavailable"}

    return {
        "staffed": staffed,
        "active": active,
        "burn": {
            "salary_tokens": salary_total,
            "spent_tokens": spent_total,
            "remaining_tokens": salary_total - spent_total,
            "over_budget": spent_total > salary_total if salary_total else False,
        },
        "revenue": _kpi_revenue(rc),
        "output": _extract_output(reports),
    }


def _kpi_revenue(rc: dict) -> dict:
    """Pull MRR / revenue / active-subs out of the RC overview. FAIL-SAFE."""
    if not isinstance(rc, dict) or not rc.get("ok"):
        return {"ok": False, "note": (rc or {}).get("error") or "no metrics"}
    metrics = rc.get("metrics") or {}
    return {
        "ok": True,
        "mrr": metrics.get("mrr"),
        "revenue": metrics.get("revenue"),
        "active_subscriptions": metrics.get("active_subscriptions"),
        "active_trials": metrics.get("active_trials"),
    }


def _extract_output(reports: dict) -> dict:
    """Tests-landed / drafts-produced — surfaced from subordinate narratives, NOT re-run.

    We only report whether the relevant subordinate filed a report this cadence; the chair
    does not parse QA results out of prose (that would be re-doing the CEO/daily-digest work).
    A present report counts as "covered"; a missing one as "(no digest yet)".
    """
    def _filed(slug: str) -> str:
        text = (reports or {}).get(slug) or "(no digest yet)"
        return "reported" if text.strip() not in ("", "(no digest yet)") else "(no digest yet)"

    return {
        "tests_landed": _filed("daily-digest"),   # quality scoreboard lives in the daily digest
        "drafts_produced": _filed("growth-director"),  # growth oversight covers drafts/output
    }


# =============================================================================
# Shay-level asks (capital / irreversible / legal ONLY)
# =============================================================================
# The reconciliation algorithm + the Shay-trigger vocabulary are RELOCATED to ``agent_toolkit.lanes``
# (step-3 simplify) as a SHARED helper, so the single-pane survivor (the daily digest) can compute
# the SAME reconciled founder-ask count WITHOUT depending on this agent. The chair re-exports the
# trigger list under its established name for continuity and delegates the reconciliation to lanes —
# there is still exactly ONE reconciliation algorithm (DRY).
_SHAY_TRIGGERS = lanes.SHAY_TRIGGERS


def _collect_shay_asks(reports: dict) -> list[dict]:
    """RECONCILE the founder asks across the subordinate digests into ONE deduped list. FAIL-SAFE.

    Delegates to the SHARED ``lanes.reconcile_founder_asks`` so the board chair and the daily digest
    use the SAME single reconciliation algorithm (the chair no longer owns it privately). The chair
    fixes the iteration order to ``SUBORDINATE_DIGESTS`` so attribution is deterministic. Empty when
    no subordinate flagged a Shay-level item — the update then reads "no asks". Never fabricates.
    """
    return lanes.reconcile_founder_asks(reports or {}, order=SUBORDINATE_DIGESTS)


# =============================================================================
# Render helpers (deterministic, no model)
# =============================================================================
def _fmt_revenue(rev: dict) -> str:
    if not rev.get("ok"):
        return f"revenue/MRR unavailable ({rev.get('note') or 'no metrics'})"
    return (
        f"MRR={rev.get('mrr')} revenue={rev.get('revenue')} "
        f"active_subs={rev.get('active_subscriptions')} trials={rev.get('active_trials')}"
    )


def _render_kpis(kpis: dict) -> list:
    burn = kpis.get("burn") or {}
    rev = kpis.get("revenue") or {}
    out = kpis.get("output") or {}
    return [
        "## KPIs",
        "",
        f"- **Staffing**: {kpis.get('active', 0)} active / {kpis.get('staffed', 0)} staffed",
        f"- **Burn vs budget**: spent {burn.get('spent_tokens', 0)} / "
        f"salary {burn.get('salary_tokens', 0)} tokens "
        f"(remaining {burn.get('remaining_tokens', 0)}"
        + (", OVER BUDGET" if burn.get("over_budget") else "")
        + ")",
        f"- **Revenue**: {_fmt_revenue(rev)}",
        f"- **Output**: tests landed = {out.get('tests_landed', '(no digest yet)')} · "
        f"drafts produced = {out.get('drafts_produced', '(no digest yet)')}",
    ]


def _render_decisions(decisions: list) -> list:
    lines = ["## Decisions made (resolved inside the org)", ""]
    if not decisions:
        lines.append("- _(no decisions this cadence)_")
        return lines
    for d in decisions:
        lines.append(f"- {d.get('decision')} — _escalate_to: {d.get('escalate_to', 'org')}_")
    return lines


def _render_asks(asks: list) -> list:
    # The board chair owns the SINGLE reconciled company view: state the count ONCE, consistently,
    # so "asks: N" can never contradict itself across the report.
    n = lanes.founder_ask_count(asks)
    lines = [
        f"## Asks for Shay (capital / irreversible / legal only) — asks: {n} (reconciled)",
        "",
    ]
    if n == 0:
        lines.append("- **no asks** — everything resolved inside the org this cadence.")
        return lines
    for a in asks:
        lines.append(f"- **{a.get('ask')}** — _escalate_to: shay_")
    return lines


def _render_update(kpis: dict, decisions: list, asks: list) -> str:
    """The tight investor update built ENTIRELY from the assembled facts (no model)."""
    lines = ["# Board → Investor update", ""]
    lines += _render_kpis(kpis)
    lines += [""]
    lines += _render_decisions(decisions)
    lines += [""]
    lines += _render_asks(asks)
    return "\n".join(lines)


# =============================================================================
# Graph wiring
# =============================================================================
builder = StateGraph(State)
builder.add_node("budget_gate", budget_gate)
builder.add_node("gather", gather)
builder.add_node("synthesize", synthesize)
builder.add_node("compose", compose)
builder.add_node("deliver", deliver)
builder.add_node("finalize", finalize)
# CLOCK-IN gate runs first: clocked out -> governance + END; otherwise synthesize the update.
builder.add_edge(START, "budget_gate")
builder.add_conditional_edges(
    "budget_gate",
    _budget_route,
    {"gather": "gather", "clocked_out": END},
)
builder.add_edge("gather", "synthesize")
builder.add_edge("synthesize", "compose")
builder.add_edge("compose", "deliver")
builder.add_edge("deliver", "finalize")
builder.add_edge("finalize", END)

graph = builder.compile()  # NO checkpointer/store — injected by the platform
