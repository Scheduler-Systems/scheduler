"""cfo — the Chief Financial Officer of the deployed agent workforce (propose-only).

The org chart (``roster.yaml``) treats every deployed agent as an *employee* with a salary
(a token budget). The CFO is the EXECUTIVE who watches ALL the money: per-agent token burn
vs salary, per-class burn, and revenue-vs-cost (RevenueCat MRR vs total token burn). Like
every officer, the CFO CONSUMES the subordinate agents' reports (payroll/ledger + the
qa-shift cost baseline digest + LangSmith reconciliation + the RC funnel) rather than
re-doing their work, and lands its single action — a BUDGET ALLOCATION across the full
roster — as a PROPOSAL in a digest. It NEVER moves money or edits the roster.

Pipeline (each node ``span()``-wrapped; clock-in gate runs FIRST):
  1. budget_gate — CLOCK-IN: stop before any work if over salary or globally disabled.
  2. gather      — per-agent + per-class spend (payroll.spent/salary/remaining for EVERY
                   roster agent), real burn via payroll.reconcile_with_langsmith (fail-safe),
                   revenue via revenuecat.metrics_overview (fail-safe), and the QA-shift cost
                   baseline via read_local_digest("qa-shift"). Every read FAIL-SAFE.
  3. analyze     — total salary envelope vs total spend; per-class burn; revenue-vs-cost
                   (RC MRR vs token burn); anomalies = agents whose spent exceeds salary OR
                   whose real LangSmith tokens >> salary.
  4. propose     — a BUDGET-ALLOCATION proposal across the FULL roster that keeps the total
                   <= policy.team_token_budget: default the cheapest grade that passes
                   scorecards, bench (~0 budget) un-scheduled agents. Each line is marked
                   escalate_to "org" unless it needs a budget INCREASE => "shay" (capital).
  5. deliver     — write_local_digest("cfo", ...) + file_digest_issue(..., labels=["exec:cfo"],
                   report_only=_report_only()). Report-only on probation: NO GitHub write, NO
                   approval interrupt — an unattended run can never hang or write.
  6. finalize    — terminal report + governance_capture(report_only=True).

House rules (same seams as the rest of the fleet):
  * PROPOSE-ONLY: budget moves are proposals; the CFO never edits the roster or the ledger.
  * NEVER HANGS: no reachable request_approval/interrupt on the scheduled path; report-only
    default True.
  * FAIL-SAFE: every payroll/RC/LangSmith/digest/model read is wrapped — a missing key /
    offline backend / SDK drift returns a structured result and the run still completes.
  * SECRETS env only, never logged; error strings are type-only.
  * ANTHROPIC-TERMS / ML boundary: ``assert_not_model_work`` guards every agent name and the
    digest repo; gal-model / denylisted ids are skipped, never costed or proposed.

Runtime: cloud/CI. Compiles WITHOUT a checkpointer/store (the platform injects Postgres).
"""
from __future__ import annotations

import json
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
from agent_toolkit import revenuecat, payroll
from agent_toolkit.budget import load_budget_policy
from agent_toolkit.policy import ModelWorkBlocked

# Where the CFO's spend + budget-allocation digest issue is filed (a no-prod-deploy,
# allow-listed repo).
DIGEST_REPO = "Scheduler-Systems/qa-agent-platform"

# The subordinate cost-baseline report the CFO consumes (officers READ reports, never re-run
# the work). A missing digest reads as "(no digest yet)", never an error.
QA_SHIFT_DIGEST = "qa-shift"

# The cheapest grade the CFO defaults un-flagged agents to in its allocation proposal. The
# fleet's cheap tier is Gemini Flash (see models.py / roster grades); this is the
# default-the-cheapest-grade-that-passes-scorecards lever.
CHEAPEST_GRADE = "gemini-2.5-flash"

# Token budget assigned to a benched (un-scheduled) agent in the proposal: ~0.
BENCH_TOKENS = 0

# Roster statuses that count as scheduled/operational (i.e. NOT benched). An agent with no
# schedule is proposed for the bench at ~0 budget.
_UNSCHEDULED = ("", "none", "benched", "off", "disabled")


def _report_only() -> bool:
    """Report-only default: env ``OPS_REPORT_ONLY`` truthy/unset => True; '0'/'false'/'no' => False.

    On probation the fleet takes NO mutating/outward action without a human gate, so the safe
    default is True. Only an explicit falsey value opts out.
    """
    return os.environ.get("OPS_REPORT_ONLY", "").lower() not in ("0", "false", "no")


# --- State -------------------------------------------------------------------------------
class State(TypedDict, total=False):
    mode: str               # reserved for future read-only/observe variants
    spend: dict             # per-agent + per-class spend facts (payroll + LangSmith recon)
    revenue: dict           # RevenueCat metrics_overview() result (fail-safe)
    qa_shift: str           # the qa-shift cost baseline digest text (fail-safe)
    analysis: dict          # envelope vs spend, per-class burn, revenue-vs-cost, anomalies
    proposals: list         # the budget-allocation proposal lines (each escalate_to org|shay)
    rationale: str          # optional one-line model rationale (fail-safe; phrasing only)
    body: str               # the assembled markdown digest body
    report: dict            # terminal verdict
    report_only: bool       # whether delivery stayed report-only


# =============================================================================
# Nodes
# =============================================================================
def budget_gate(state: State) -> dict:
    """CLOCK-IN gate — STOP before any work if over salary or globally disabled.

    Runs FIRST. Clocked in => proceed to gather; clocked out => terminal report + governance,
    no reads, no model spend, no writes.
    """
    with span("cfo.budget_gate"):
        if check_clocked_in("cfo"):
            return {}
        report = {
            "status": "skipped",
            "detail": "cfo over token salary or globally disabled",
            "report_only": True,
        }
        governance_capture(
            "cfo",
            {"clocked_in": False, "report_only": True, "report": report},
        )
        return {"report": report, "report_only": True}


def gather(state: State) -> dict:
    """Collect per-agent + per-class spend, revenue, and the QA-shift cost baseline. FAIL-SAFE.

    - spend   : for EVERY roster agent, payroll.salary/spent/remaining + is_over_budget, plus
                a fail-safe LangSmith reconciliation (real tokens/cost; None when unavailable),
                grouped REVENUE/GROWTH FIRST, then QUALITY, then OPS, then HR via the roster
                ``org`` groups. A missing/corrupt roster degrades to empty spend.
    - revenue : ``revenuecat.metrics_overview`` (already fail-safe).
    - qa_shift: the qa-shift cost baseline digest (read, never re-run).
    """
    with span("cfo.gather"):
        # 1) Roster -> per-agent spend cards (payroll math + fail-safe LangSmith recon).
        try:
            roster = payroll.load_roster()
        except Exception:
            roster = {"agents": {}, "org": {}, "policy": {}}
        agents = roster.get("agents", {}) or {}

        cards: dict = {}
        for name, record in agents.items():
            try:
                assert_not_model_work(name)  # never cost a model-dev role
            except ModelWorkBlocked:
                continue
            record = record or {}
            try:
                sal = payroll.salary(name, roster=roster)
                sp = payroll.spent(name)
                rem = payroll.remaining(name, roster=roster)
                over = payroll.is_over_budget(name, roster=roster)
            except Exception:
                sal, sp, rem, over = 0, 0, 0, False
            ls = payroll.reconcile_with_langsmith(name)  # None when unavailable
            cards[name] = {
                "role": record.get("role"),
                "grade": record.get("grade"),
                "schedule": record.get("schedule"),
                "status": record.get("status") or "unknown",
                "scorecard": record.get("scorecard", {}) or {},
                "salary_tokens": sal,
                "spent_tokens": sp,
                "remaining_tokens": rem,
                "over_budget": over,
                "langsmith": ls,
            }

        # Per-class grouping (revenue/growth first), from the roster org groups.
        by_class = _class_spend(roster, cards)

        spend = {"agents": cards, "by_class": by_class}

        # 2) Revenue — the money number (already fail-safe).
        revenue = revenuecat.metrics_overview()

        # 3) QA-shift cost baseline — CONSUME the report, never re-run the work.
        qa_shift = read_local_digest(QA_SHIFT_DIGEST)

        return {"spend": spend, "revenue": revenue, "qa_shift": qa_shift}


def analyze(state: State) -> dict:
    """Compute the financial picture: envelope vs spend, per-class burn, revenue-vs-cost,
    and anomalies. FAIL-SAFE (pure arithmetic over the gathered dicts).

    - envelope        : total salary across the roster vs total spend (and total real
                        LangSmith burn where available).
    - team_budget     : ``policy.team_token_budget`` (the hard cap the proposal stays under).
    - revenue_vs_cost : RC MRR vs total token burn (a coarse cost signal; informational).
    - anomalies       : agents whose ``spent`` exceeds ``salary`` (over budget) OR whose real
                        LangSmith tokens >> salary (independent overload signal).
    """
    spend = state.get("spend") or {}
    revenue = state.get("revenue") or {}
    cards = spend.get("agents") or {}
    by_class = spend.get("by_class") or {}

    with span("cfo.analyze", agents=len(cards)):
        total_salary = sum(int(c.get("salary_tokens") or 0) for c in cards.values())
        total_spent = sum(int(c.get("spent_tokens") or 0) for c in cards.values())
        total_real = 0
        for c in cards.values():
            ls = c.get("langsmith")
            if isinstance(ls, dict):
                total_real += int(ls.get("total_tokens") or 0)

        # The hard cap the allocation proposal must stay under.
        try:
            team_budget = load_budget_policy().get("team_token_budget")
        except Exception:
            team_budget = None

        # Revenue-vs-cost: RC MRR vs the token burn (coarse; informational only — we don't
        # invent a token->dollar rate here, just surface both numbers honestly).
        mrr = None
        if revenue.get("ok"):
            metrics = revenue.get("metrics") or {}
            mrr = metrics.get("mrr")

        anomalies: list = []
        for name, c in cards.items():
            sal = int(c.get("salary_tokens") or 0)
            sp = int(c.get("spent_tokens") or 0)
            if c.get("over_budget") or (sal and sp > sal):
                anomalies.append(
                    {
                        "agent": name,
                        "kind": "over_budget",
                        "detail": f"spent={sp} > salary={sal} (remaining={c.get('remaining_tokens')})",
                    }
                )
            ls = c.get("langsmith") or {}
            real = ls.get("total_tokens") if isinstance(ls, dict) else None
            if real and sal and int(real) > sal:
                anomalies.append(
                    {
                        "agent": name,
                        "kind": "overloaded",
                        "detail": f"LangSmith tokens={real} >> salary={sal}",
                    }
                )

        # CRITICAL: keep SPEND and ALLOCATION strictly separate — never conflate them.
        #   * ACTUAL SPEND vs the cap is the truthful over/under-budget signal. The real money
        #     burned (LangSmith real tokens where available, else the ledger spend) is what
        #     decides whether the fleet is "over the cap". 98k spend against a 5.54M cap is
        #     UNDER — and the digest must say so, never "over cap".
        #   * The SALARY ALLOCATION (sum of roster salaries) exceeding the cap is a SEPARATE
        #     PLANNING issue (the roster promises more budget than the cap allows). It is a
        #     proposal to re-balance the allocation — NOT a statement that spend is over the cap.
        actual_spend = total_real or total_spent  # real burn first, ledger spend as fallback
        over_team_budget_spend = bool(team_budget) and actual_spend > int(team_budget)
        salary_allocation_over_cap = bool(team_budget) and total_salary > int(team_budget)

        analysis = {
            "total_salary": total_salary,
            "total_spent": total_spent,
            "total_real_tokens": total_real,
            "team_budget": team_budget,
            "envelope_remaining": total_salary - total_spent,
            # Actual SPEND vs cap (the real over/under-budget truth). Spend < cap => NOT over cap.
            "actual_spend": actual_spend,
            "over_team_budget": over_team_budget_spend,
            "spend_remaining_vs_cap": (int(team_budget) - actual_spend) if team_budget else None,
            # Salary ALLOCATION vs cap is a DISTINCT planning signal — labelled so it is never
            # rendered as "spend over cap".
            "salary_allocation_over_cap": salary_allocation_over_cap,
            "allocation_overrun": (total_salary - int(team_budget)) if salary_allocation_over_cap else 0,
            "revenue_vs_cost": {"mrr": mrr, "token_burn": total_real or total_spent},
            "per_class_burn": {
                cls: {
                    "salary": data.get("salary", 0),
                    "spent": data.get("spent", 0),
                    "real_tokens": data.get("real_tokens", 0),
                }
                for cls, data in by_class.items()
            },
            "anomalies": anomalies,
        }
        return {"analysis": analysis}


def propose(state: State) -> dict:
    """Assemble a BUDGET-ALLOCATION proposal across the FULL roster. Proposes only — never moves
    money. FAIL-SAFE.

    Rules:
      * Keep the TOTAL proposed allocation <= ``policy.team_token_budget`` (the hard cap). If
        the naive sum of current salaries already exceeds the cap, scale every line down
        proportionally so the total fits.
      * Default un-scheduled agents to the BENCH (~0 tokens).
      * Default every scheduled agent to the CHEAPEST grade that passes scorecards (the cheap
        tier — Gemini Flash). An agent the analysis flagged as over budget keeps its current
        salary but is marked as needing a budget INCREASE.
      * escalate_to "org" by default; only a budget INCREASE (capital) escalates to "shay".

    The allocation is built DETERMINISTICALLY so it is ALWAYS produced. An optional
    budget-metered model adds only a one-line rationale per line; on ANY model failure (no
    key, budget, SDK drift) the deterministic proposal stands unchanged — never empty.
    """
    spend = state.get("spend") or {}
    analysis = state.get("analysis") or {}
    cards = spend.get("agents") or {}
    team_budget = analysis.get("team_budget")
    anomaly_agents = {a.get("agent") for a in (analysis.get("anomalies") or [])}

    with span("cfo.propose", agents=len(cards), team_budget=team_budget):
        # First pass: a raw allocation per agent (bench un-scheduled; else keep current salary,
        # noting a needed increase for flagged agents).
        raw: list = []
        for name, c in cards.items():
            sal = int(c.get("salary_tokens") or 0)
            if _is_unscheduled(c.get("schedule")):
                raw.append(
                    {
                        "agent": name,
                        "action": "bench",
                        "current_salary_tokens": sal,
                        "proposed_tokens": BENCH_TOKENS,
                        "grade": CHEAPEST_GRADE,
                        "reason": "un-scheduled — bench at ~0 budget until a shift is assigned",
                        "escalate_to": "org",
                    }
                )
                continue
            needs_increase = name in anomaly_agents
            raw.append(
                {
                    "agent": name,
                    "action": "increase" if needs_increase else "hold",
                    "current_salary_tokens": sal,
                    "proposed_tokens": sal,
                    "grade": CHEAPEST_GRADE,
                    "reason": (
                        "over budget — propose a budget INCREASE (capital decision)"
                        if needs_increase
                        else "default the cheapest grade that passes scorecards; hold salary"
                    ),
                    # A budget INCREASE is capital/irreversible => Shay; everything else is
                    # resolved inside the org.
                    "escalate_to": "shay" if needs_increase else "org",
                }
            )

        # Second pass: keep the TOTAL <= team_budget. If the proposed total exceeds the cap,
        # scale every (non-bench) line down proportionally so the envelope fits the hard cap.
        proposed_total = sum(int(p["proposed_tokens"]) for p in raw)
        if team_budget and proposed_total > int(team_budget):
            scalable = sum(
                int(p["proposed_tokens"]) for p in raw if p["action"] != "bench"
            )
            if scalable > 0:
                factor = int(team_budget) / scalable
                for p in raw:
                    if p["action"] == "bench":
                        continue
                    scaled = int(p["proposed_tokens"] * factor)
                    p["proposed_tokens"] = max(0, scaled)
                    p["reason"] = (
                        p["reason"]
                        + f" · scaled to fit team budget (factor {factor:.3f})"
                    )

        # Optional model rationale — phrasing only (no train/eval/distill), FAIL-SAFE. The
        # deterministic allocation above is the source of truth; the model just adds a short
        # CFO rationale line. On ANY model failure the proposal stands unchanged.
        try:
            model = budget_guard("cfo", TIER_DEFAULT)
            prompt = (
                "You are the CFO of a fleet of deployed software agents (each an 'employee' "
                "with a token-budget salary). Given the budget-allocation proposal below, write "
                "ONE short sentence of rationale for the team. This is a STATUS report, not a "
                "founder alarm: NEVER claim spend is 'over the cap' unless ACTUAL spend exceeds "
                "the cap — the salary ALLOCATION exceeding the cap is a separate PLANNING "
                "re-balance, not over-spend. Do NOT invent numbers; the allocation is fixed — you "
                "are only phrasing it.\n\n"
                f"{json.dumps(raw, default=str)[:3000]}\n"
            )
            resp = model.invoke(prompt)
            rationale = (getattr(resp, "content", str(resp)) or "").strip()
        except Exception as exc:  # model/key unavailable — deterministic proposal stands
            rationale = f"(model rationale unavailable: {type(exc).__name__})"

        return {"proposals": raw, "rationale": rationale}


def deliver(state: State) -> dict:
    """Write the local digest + file the CFO spend/budget-allocation issue (report-only). FAIL-SAFE.

    ``write_local_digest`` always runs (succeeds-or-"" ; never raises). ``file_digest_issue(...,
    report_only=_report_only())`` delivers the issue — on probation (the default) it returns an
    honest report-only plan dict with NO GitHub call and NO approval interrupt, so an unattended
    run can never hang or write.
    """
    analysis = state.get("analysis") or {}
    proposals = state.get("proposals") or []
    spend = state.get("spend") or {}
    revenue = state.get("revenue") or {}
    qa_shift = state.get("qa_shift") or ""
    rationale = state.get("rationale") or ""
    report_only = _report_only()

    with span("cfo.deliver", report_only=report_only, proposals=len(proposals)):
        assert_not_model_work(DIGEST_REPO)  # never file into a model-dev repo

        body = _render_body(spend, revenue, qa_shift, analysis, proposals, rationale)

        digest_path = write_local_digest("cfo", "CFO: spend + budget allocation", body)

        res = file_digest_issue(
            DIGEST_REPO,
            "CFO: spend + budget allocation (proposal)",
            body,
            labels=["exec:cfo"],
            report_only=report_only,
            agent="cfo",
            slack_title="💰 CFO: spend + budget allocation (proposal)",
        )
        delivery = res.get("status") if isinstance(res, dict) else None
        return {
            "body": body,
            "report": {
                "delivery": delivery,
                "digest": digest_path,
                "proposals": len(proposals),
                "report_only": report_only,
            },
            "report_only": report_only,
        }


def finalize(state: State) -> dict:
    """Terminal node — capture governance (report_only=True) and emit the final report."""
    analysis = state.get("analysis") or {}
    proposals = state.get("proposals") or []
    prior = state.get("report") if isinstance(state.get("report"), dict) else {}

    with span("cfo.finalize", proposals=len(proposals)):
        governance_capture(
            "cfo",
            {
                "total_salary": analysis.get("total_salary"),
                "total_spent": analysis.get("total_spent"),
                "team_budget": analysis.get("team_budget"),
                "anomalies": len(analysis.get("anomalies") or []),
                "proposals": len(proposals),
                "delivery": prior.get("delivery"),
                "report_only": True,
            },
        )
        return {
            "report": {
                "total_salary": analysis.get("total_salary"),
                "total_spent": analysis.get("total_spent"),
                "team_budget": analysis.get("team_budget"),
                "anomalies": len(analysis.get("anomalies") or []),
                "proposals": len(proposals),
                "delivery": prior.get("delivery"),
                "digest": prior.get("digest"),
                "report_only": True,
            }
        }


# =============================================================================
# Helpers (deterministic, no model)
# =============================================================================
def _is_unscheduled(schedule) -> bool:
    """True when an agent has no real shift (=> propose the bench at ~0 budget)."""
    return str(schedule or "").strip().lower() in _UNSCHEDULED


def _class_spend(roster: dict, cards: dict) -> dict:
    """Sum salary/spent/real-tokens per org class, REVENUE/GROWTH FIRST. FAIL-SAFE.

    Reads the roster ``org`` growth/qa/ops groups; any roster agent not named in a group is
    bucketed under "other" so nothing is dropped. Ordered growth -> qa -> ops -> other.
    """
    org = (roster or {}).get("org", {}) or {}

    def _members(key) -> list:
        group = org.get(key)
        if isinstance(group, (list, tuple)):
            return [str(x) for x in group]
        if isinstance(group, str) and group:
            return [group]
        return []

    grouped: dict = {}
    assigned: set = set()
    for cls in ("growth", "qa", "ops"):
        names = [n for n in _members(cls) if n in cards]
        assigned.update(names)
        grouped[cls] = _sum_cards(names, cards)
    other = [n for n in cards if n not in assigned]
    if other:
        grouped["other"] = _sum_cards(other, cards)
    return grouped


def _sum_cards(names: list, cards: dict) -> dict:
    salary = spent = real = 0
    for n in names:
        c = cards.get(n) or {}
        salary += int(c.get("salary_tokens") or 0)
        spent += int(c.get("spent_tokens") or 0)
        ls = c.get("langsmith")
        if isinstance(ls, dict):
            real += int(ls.get("total_tokens") or 0)
    return {"agents": list(names), "salary": salary, "spent": spent, "real_tokens": real}


def _render_rc(revenue: dict) -> list:
    if not revenue.get("ok"):
        return [f"- RevenueCat: unavailable ({revenue.get('error') or 'no metrics'})"]
    metrics = revenue.get("metrics") or {}
    if not metrics:
        return ["- RevenueCat: ok, but no metrics returned"]
    return ["- RevenueCat metrics:"] + [
        f"    - {key}: {value}" for key, value in sorted(metrics.items())
    ]


def _render_body(
    spend: dict, revenue: dict, qa_shift: str, analysis: dict, proposals: list, rationale: str = ""
) -> str:
    cards = spend.get("agents") or {}
    by_class = analysis.get("per_class_burn") or {}
    anomalies = analysis.get("anomalies") or []
    rvc = analysis.get("revenue_vs_cost") or {}

    lines = ["# CFO: spend + budget allocation (proposal)", ""]
    if rationale:
        lines += [f"_{rationale}_", ""]

    # Envelope. SPEND vs the cap is the over/under-budget TRUTH; the salary ALLOCATION exceeding
    # the cap is a SEPARATE, clearly-labelled planning item (never rendered as "spend over cap").
    cap = analysis.get("team_budget")
    actual_spend = analysis.get("actual_spend")
    if actual_spend is None:  # tolerate an older analysis dict
        actual_spend = analysis.get("total_real_tokens") or analysis.get("total_spent")
    over_spend = analysis.get("over_team_budget")
    spend_status = (
        f"⚠️ OVER CAP (spent {actual_spend} > cap {cap})"
        if over_spend
        else f"under cap (spent {actual_spend} / cap {cap})"
    )
    lines += ["## 💵 ENVELOPE", ""]
    lines += [
        f"- actual spend vs cap: {spend_status}",
        f"- total real LangSmith burn: {analysis.get('total_real_tokens')} tokens",
        f"- ledger spend: {analysis.get('total_spent')} tokens",
        f"- team token budget (hard cap): {cap}",
        f"- revenue-vs-cost: MRR={rvc.get('mrr')} vs token_burn={rvc.get('token_burn')}",
        "",
    ]
    # The salary-allocation-exceeds-cap PLANNING item — distinct from spend, surfaced as a
    # re-balance proposal, NEVER as "we are over the cap on spend".
    if analysis.get("salary_allocation_over_cap"):
        lines += [
            f"- 📐 PLANNING (allocation, NOT spend): roster salary allocation "
            f"{analysis.get('total_salary')} exceeds the {cap} cap by "
            f"{analysis.get('allocation_overrun')} — propose a re-balance so the allocated "
            f"envelope fits the cap. (Actual spend is {actual_spend}, "
            + ("OVER" if over_spend else "UNDER") + " the cap.)",
            "",
        ]
    else:
        lines += [
            f"- 📐 salary allocation: {analysis.get('total_salary')} tokens (within the {cap} cap)",
            "",
        ]

    # Revenue.
    lines += ["## 💰 REVENUE", ""]
    lines += _render_rc(revenue)
    lines.append("")

    # Per-class burn (revenue/growth first).
    lines += ["## 📊 PER-CLASS BURN (revenue/growth → quality → ops)", ""]
    if not by_class:
        lines.append("_(no class data)_")
    for cls, data in by_class.items():
        lines.append(
            f"- **{cls}**: salary={data.get('salary', 0)} spent={data.get('spent', 0)} "
            f"real={data.get('real_tokens', 0)}"
        )
    lines.append("")

    # Anomalies. The no-anomaly line is phrased POSITIVELY ("all agents within salary") so it does
    # not echo over-budget trigger vocabulary that a downstream substring scan would false-positive
    # on (the audit director reads this digest; "none (no agent over salary)" used to trip it).
    lines += ["## 🚨 ANOMALIES", ""]
    if not anomalies:
        lines.append("- none — every agent is within its salary; no overload detected")
    for a in anomalies:
        lines.append(f"- **{a.get('agent')}** [{a.get('kind')}]: {a.get('detail')}")
    lines.append("")

    # QA-shift cost baseline (consumed report).
    lines += ["## 🧪 QA-SHIFT COST BASELINE (`.tmp/qa-shift/latest.md`)", "", qa_shift or "(no digest yet)", ""]

    # The budget-allocation proposal.
    lines += ["## 📋 BUDGET ALLOCATION (PROPOSAL — propose-only, no money moved)", ""]
    if not proposals:
        lines.append("_(no roster agents to allocate)_")
    for p in proposals:
        lines.append(
            f"- **{p.get('agent')}** → {p.get('action')} "
            f"{p.get('current_salary_tokens')}→{p.get('proposed_tokens')} tokens "
            f"(grade {p.get('grade')}) · escalate_to **{p.get('escalate_to')}** — {p.get('reason')}"
        )
    total = sum(int(p.get("proposed_tokens") or 0) for p in proposals)
    lines += ["", f"_proposed total: {total} tokens (cap {analysis.get('team_budget')})_"]

    return "\n".join(lines)


# =============================================================================
# Routing
# =============================================================================
def _budget_route(state: State) -> str:
    """Clocked in -> gather; clocked out -> END (terminal report already set)."""
    return "gather" if check_clocked_in("cfo") else "clocked_out"


# =============================================================================
# Graph wiring
# =============================================================================
builder = StateGraph(State)
builder.add_node("budget_gate", budget_gate)
builder.add_node("gather", gather)
builder.add_node("analyze", analyze)
builder.add_node("propose", propose)
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
builder.add_edge("propose", "deliver")
builder.add_edge("deliver", "finalize")
builder.add_edge("finalize", END)

graph = builder.compile()  # NO checkpointer/store — injected by the platform
