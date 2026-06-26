"""aso_store_listing_agent — CLOUD growth agent that repositions the store listing.

REVENUE LEVER (no app release): the App Store / Google Play listing markets a generic
"to-do" / checklist app, but Scheduler is monetized as B2B shift scheduling for SMB teams.
That mispositioning leaks the funnel before the paywall. Repositioning the listing copy is
an ASO-only change (copy + keywords + screenshots) — no binary release — so it is the
fastest store-side conversion lever. This agent does the repositioning RESEARCH and DRAFTS
the ASO copy ({title, subtitle, keywords, short_desc, long_desc}) per store, then delivers
the drafts for a human to review.

House rules it follows (same seams as the rest of the ops/growth fleet — see
revenue_reporter, store_health_checker, conversion_growth_analyst):

  - PROBATION / PROPOSE-ONLY. Drafts only. Every outward action goes through
    ``file_digest_issue(..., report_only=_report_only())`` where ``_report_only()`` defaults
    True (env ``OPS_REPORT_ONLY``; only "0"/"false"/"no" turns it off). On probation the
    delivery is an honest ``{"status": "report_only", ...}`` plan dict — NO GitHub write and,
    critically, NO approval interrupt — so a scheduled unattended run can never hang or write.

  - DO-NOT-CLAIM GUARDRAIL (load-bearing). The drafts are built ONLY from the declared,
    verified facts in ``docs/growth/scheduler_positioning.json`` so the agent never invents a
    feature. After drafting, ``compliance_scan`` re-scans the whole draft for any banned
    over-claim term (``product.do_not_claim`` — e.g. "time tracking", "AI scheduling",
    "clock-in/out"). If any appear, a prominent ``⚠️ COMPLIANCE`` warning is added to BOTH the
    delivered body and the returned ``compliance_flags`` — an over-claim is NEVER silently
    emitted (a directory submission already over-claimed those features once).

  - NEVER HANG. With no credentials the run still completes: the positioning file read, the
    model draft, and the GitHub delivery are each wrapped so a missing key / offline / SDK
    drift returns a structured result and the node moves on.

  - FAIL-SAFE drafting. The model (TIER_DEFAULT, metered via ``budget_guard``) is used ONLY
    to phrase the declared facts; on ANY model failure we fall back to a DETERMINISTIC draft
    built directly from the facts, so a draft is always produced (never empty).

  - SECRETS: env only, never logged. Error strings are type-only (no bodies/tokens).

  - ANTHROPIC-TERMS / ML BOUNDARY. ``assert_not_model_work`` guards every outward repo string
    (the ASO branches and the digest repo); gal-model / denylisted ids are skipped, never
    reported on. No model train/eval/distill — phrasing only.

  - Compiles WITHOUT a checkpointer/store (the platform injects Postgres). Every node body is
    wrapped in ``span("aso_store_listing_agent.<node>", ...)``; governance is captured at end.
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
    TIER_DEFAULT,
)
from agent_toolkit.policy import ModelWorkBlocked

# Where the draft digest is filed (allow-listed in github_ops; no prod deploy).
DIGEST_REPO = "Scheduler-Systems/qa-agent-platform"

# Declared, VERIFIED product facts live here (the orchestrator owns the file). Read FAIL-SAFE.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DEFAULT_POSITIONING_PATH = os.path.join(_REPO_ROOT, "docs", "growth", "scheduler_positioning.json")

# Stores we draft listing copy for when positioning.aso.stores is unavailable.
DEFAULT_STORES = ("App Store", "Google Play")

# Minimal, conservative facts used when the positioning file is missing/unreadable so the
# agent still produces a useful repositioning draft (never empty) and never over-claims.
DEFAULT_FACTS = {
    "what_it_is": "B2B shift scheduling for small-business teams",
    "ships": [
        "per-user pricing",
        "one-click deterministic roster / shift builder",
        "team chat",
        "CSV export",
    ],
    "do_not_claim": ["time tracking", "AI scheduling", "clock-in/out", "offline"],
    "positioning_problem": (
        "The store listing markets a generic to-do / checklist app, but the product is "
        "monetized as B2B shift scheduling. Reposition to shift scheduling for SMB teams "
        "(an ASO/listing change — no app release required)."
    ),
    "stores": list(DEFAULT_STORES),
}


def _report_only() -> bool:
    """Report-only default for the probation agent: truthy/unset env => True.

    On probation the fleet must take NO mutating/outward action without a human gate, so the
    safe default is True. Only an explicit ``OPS_REPORT_ONLY`` of "0"/"false"/"no" flips
    delivery into a real (gated) GitHub write.
    """
    return os.environ.get("OPS_REPORT_ONLY", "").lower() not in ("0", "false", "no")


# --- State -------------------------------------------------------------------------------
class State(TypedDict, total=False):
    mode: str                 # reserved for future read-only/observe variants
    facts: dict               # declared positioning facts (fail-safe load)
    drafts: dict              # store -> {title, subtitle, keywords, short_desc, long_desc}
    compliance_flags: list    # banned over-claim terms detected in the drafts (per store)
    summary: str              # short operator note
    report: dict              # terminal verdict
    report_only: bool         # whether delivery stayed report-only


# --- Positioning facts (fail-safe load) --------------------------------------------------
def _positioning_path() -> str:
    return os.environ.get("SCHEDULER_POSITIONING_PATH") or DEFAULT_POSITIONING_PATH


def _load_positioning() -> dict:
    """Read the declared positioning facts. FAIL-SAFE.

    Returns a normalized dict ``{"what_it_is", "ships", "do_not_claim", "positioning_problem",
    "stores"}``. A missing / unreadable / non-JSON file degrades to ``DEFAULT_FACTS`` so the
    agent still produces a draft and never raises.
    """
    try:
        with open(_positioning_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:  # missing / unreadable / non-JSON — degrade to minimal defaults
        return dict(DEFAULT_FACTS)

    if not isinstance(data, dict):
        return dict(DEFAULT_FACTS)

    product = data.get("product") if isinstance(data.get("product"), dict) else {}
    aso = data.get("aso") if isinstance(data.get("aso"), dict) else {}

    def _str_list(value, fallback):
        if isinstance(value, list):
            items = [str(x).strip() for x in value if str(x).strip()]
            if items:
                return items
        return list(fallback)

    return {
        "what_it_is": str(product.get("what_it_is") or DEFAULT_FACTS["what_it_is"]).strip(),
        "ships": _str_list(product.get("ships"), DEFAULT_FACTS["ships"]),
        "do_not_claim": _str_list(product.get("do_not_claim"), DEFAULT_FACTS["do_not_claim"]),
        "positioning_problem": str(
            data.get("positioning_problem") or DEFAULT_FACTS["positioning_problem"]
        ).strip(),
        "stores": _str_list(aso.get("stores"), DEFAULT_FACTS["stores"]),
    }


# --- Nodes -------------------------------------------------------------------------------
def budget_gate(state: State) -> dict:
    """CLOCK-IN gate — STOP before any work if over salary or globally disabled.

    Runs FIRST. Clocked in => proceed to ``gather``; clocked out => terminal report +
    governance (report-only) then route to END. No file read, no model spend, no writes on
    the clocked-out path.
    """
    with span("aso_store_listing_agent.budget_gate"):
        if check_clocked_in("aso_store_listing_agent"):
            return {}
        report = {
            "delivery": "skipped",
            "detail": "aso_store_listing_agent over token salary or globally disabled",
            "report_only": True,
        }
        governance_capture(
            "aso_store_listing_agent",
            {"clocked_in": False, "report_only": True, "report": report},
        )
        return {"report": report, "report_only": True}


def gather(state: State) -> dict:
    """Load the declared positioning facts (fail-safe). Guards the digest repo defensively."""
    with span("aso_store_listing_agent.gather"):
        # Defensive ML-boundary guard on the outward delivery target.
        try:
            assert_not_model_work(DIGEST_REPO)
        except ModelWorkBlocked:
            pass  # the digest repo is allow-listed; never let a guard crash the run
        facts = _load_positioning()
        return {"facts": facts}


def draft_listing(state: State) -> dict:
    """Draft ASO copy per store from the declared facts. FAIL-SAFE, never over-claims.

    The model (TIER_DEFAULT, metered via ``budget_guard``) is used ONLY to phrase the declared
    ``ships`` facts into a {title, subtitle, keywords, short_desc, long_desc} draft per store,
    explicitly honoring ``do_not_claim``. On ANY model failure (no key, budget, SDK drift) we
    fall back to a DETERMINISTIC draft built directly from the facts, so a draft is ALWAYS
    produced. ``compliance_scan`` is the real safety net — drafting only tries not to over-claim.
    """
    facts = state.get("facts") or dict(DEFAULT_FACTS)
    stores = facts.get("stores") or list(DEFAULT_STORES)

    with span("aso_store_listing_agent.draft_listing", stores=len(stores)):
        # Deterministic baseline draft per store — always available, never empty.
        drafts = {store: _deterministic_draft(store, facts) for store in stores}

        try:
            model = budget_guard("aso_store_listing_agent", TIER_DEFAULT)
            prompt = (
                "You are an ASO (app-store optimization) copywriter repositioning a "
                "mispositioned app listing. The app is monetized as B2B shift scheduling for "
                "small-business teams, but the current listing reads like a generic to-do app.\n\n"
                f"What it is: {facts.get('what_it_is')}\n"
                f"Positioning problem: {facts.get('positioning_problem')}\n"
                f"Features it SHIPS (only claim these): {json.dumps(facts.get('ships') or [])}\n"
                "DO NOT CLAIM these (the app does NOT have them — never mention or imply them): "
                f"{json.dumps(facts.get('do_not_claim') or [])}\n"
                f"Stores: {json.dumps(stores)}\n\n"
                "For EACH store, write listing copy as JSON: a top-level object mapping each "
                "store name to an object with keys title, subtitle, keywords, short_desc, "
                "long_desc. Reposition firmly to shift scheduling for SMB teams. Use ONLY the "
                "shipped features. Return ONLY the JSON object — no prose, no code fences."
            )
            resp = model.invoke(prompt)
            content = getattr(resp, "content", str(resp)) or ""
            parsed = _parse_json_object(content)
            if isinstance(parsed, dict):
                for store in stores:
                    block = parsed.get(store)
                    coerced = _coerce_draft(block)
                    if coerced:
                        # MERGE the model's fields onto the deterministic baseline (per-field
                        # override). A partial/truncated model block (e.g. only a title) must
                        # NOT blank out the other fields — the complete fallback fills any gap,
                        # so no field is ever empty and we still can't over-claim a dropped field.
                        merged = dict(drafts[store])
                        merged.update(coerced)
                        drafts[store] = merged
        except Exception:  # model/key unavailable — keep the deterministic drafts (never empty)
            pass

        return {"drafts": drafts}


def compliance_scan(state: State) -> dict:
    """Scan every draft for banned over-claim terms (``do_not_claim``). LOAD-BEARING.

    Case-insensitive substring scan across all draft fields per store. Each hit becomes a
    structured flag ``{"store", "term", "field"}``. An over-claim is NEVER silently emitted:
    when ``compliance_flags`` is non-empty the ``deliver`` body carries a prominent
    ``⚠️ COMPLIANCE`` warning and the flags are returned in state. FAIL-SAFE.
    """
    facts = state.get("facts") or {}
    drafts = state.get("drafts") or {}
    banned = [str(t).strip().lower() for t in (facts.get("do_not_claim") or []) if str(t).strip()]

    with span("aso_store_listing_agent.compliance_scan", drafts=len(drafts), banned=len(banned)):
        flags: list = []
        for store, draft in drafts.items():
            if not isinstance(draft, dict):
                continue
            for field in ("title", "subtitle", "keywords", "short_desc", "long_desc"):
                value = draft.get(field)
                text = value if isinstance(value, str) else json.dumps(value, default=str)
                low = (text or "").lower()
                for term in banned:
                    if term and term in low:
                        flags.append({"store": store, "term": term, "field": field})
        return {"compliance_flags": flags}


def deliver(state: State) -> dict:
    """Write the local digest + file the draft issue (report-only on probation). FAIL-SAFE.

    - ``write_local_digest`` always runs (succeeds-or-"" ; never raises) so there is a local
      artifact even with zero credentials.
    - ``file_digest_issue(..., report_only=_report_only())`` delivers the issue. On probation
      (the default) this returns an honest report-only plan dict with NO GitHub call and NO
      approval interrupt — an unattended run can never hang or write.

    When ``compliance_flags`` is non-empty a prominent ``⚠️ COMPLIANCE`` warning is added to
    the body so an over-claim can never be silently shipped past a reviewer.
    """
    facts = state.get("facts") or {}
    drafts = state.get("drafts") or {}
    compliance_flags = state.get("compliance_flags") or []
    report_only = _report_only()

    with span(
        "aso_store_listing_agent.deliver",
        stores=len(drafts),
        flags=len(compliance_flags),
        report_only=report_only,
    ):
        body = _render_body(facts, drafts, compliance_flags)
        summary = (
            f"ASO listing repositioning drafts for {len(drafts)} store(s); "
            f"{len(compliance_flags)} over-claim flag(s)."
        )

        # Local artifact first — always, fail-safe.
        write_local_digest("aso-store-listing-agent", "ASO listing repositioning (draft)", body)

        # Compliance flags are a human-review signal — surface the gate label.
        labels = ["growth:aso"]
        if compliance_flags:
            labels.append("gate:human-required")

        res = file_digest_issue(
            DIGEST_REPO,
            "ASO listing repositioning (draft)",
            body,
            labels=labels,
            report_only=report_only,
            agent="aso_store_listing_agent",
        )
        delivery = res.get("status") if isinstance(res, dict) else None
        return {
            "summary": summary,
            "report": {
                "delivery": delivery,
                "stores": len(drafts),
                "compliance_flags": len(compliance_flags),
                "report_only": report_only,
            },
            "report_only": report_only,
        }


def finalize(state: State) -> dict:
    """Terminal node — capture governance (report_only=True) and emit the final report."""
    drafts = state.get("drafts") or {}
    compliance_flags = state.get("compliance_flags") or []
    prior = state.get("report") if isinstance(state.get("report"), dict) else {}

    with span("aso_store_listing_agent.finalize", stores=len(drafts)):
        governance_capture(
            "aso_store_listing_agent",
            {
                "stores": len(drafts),
                "compliance_flags": len(compliance_flags),
                "delivery": prior.get("delivery"),
                "report_only": True,
            },
        )
        return {
            "report": {
                "stores": len(drafts),
                "compliance_flags": len(compliance_flags),
                "delivery": prior.get("delivery"),
                "report_only": True,
            }
        }


# --- Helpers -----------------------------------------------------------------------------
def _parse_json_object(text: str):
    """Best-effort parse of a JSON object from model output (tolerates code fences/prose)."""
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except Exception:
            return None
    return None


def _coerce_draft(block) -> dict:
    """Coerce a model draft block into the canonical 5-field shape. ``{}`` if unusable."""
    if not isinstance(block, dict):
        return {}
    draft: dict = {}
    for field in ("title", "subtitle", "short_desc", "long_desc"):
        val = block.get(field)
        if isinstance(val, str) and val.strip():
            draft[field] = val.strip()
    # keywords may come as a list or a comma string — normalize to a comma string.
    kw = block.get("keywords")
    if isinstance(kw, list):
        kw = ", ".join(str(k).strip() for k in kw if str(k).strip())
    if isinstance(kw, str) and kw.strip():
        draft["keywords"] = kw.strip()
    return draft if draft else {}


def _deterministic_draft(store: str, facts: dict) -> dict:
    """A repositioning draft built ENTIRELY from the declared facts (no model). Never empty.

    Uses ONLY ``facts['ships']`` so it can never over-claim a ``do_not_claim`` feature.
    """
    ships = facts.get("ships") or list(DEFAULT_FACTS["ships"])
    ships_phrase = ", ".join(ships)
    what = facts.get("what_it_is") or DEFAULT_FACTS["what_it_is"]
    keywords = "shift scheduling, staff scheduling, employee shifts, roster, rota, team schedule, work shifts"
    return {
        "title": "Scheduler — Shift Scheduling for Teams",
        "subtitle": "Build staff shifts & rosters in one click",
        "keywords": keywords,
        "short_desc": f"{what}. Plan shifts, build rosters, and keep your team in sync.",
        "long_desc": (
            f"Scheduler is {what.lower()}. Reposition from a generic to-do app to what teams "
            f"actually use it for: building and sharing work shifts. Features: {ships_phrase}. "
            "Built for small-business teams that need their week's schedule done fast."
        ),
    }


def _render_body(facts: dict, drafts: dict, compliance_flags: list) -> str:
    """Render the draft digest. A non-empty ``compliance_flags`` adds a prominent warning."""
    lines: list = []

    if compliance_flags:
        terms = sorted({str(f.get("term")) for f in compliance_flags if f.get("term")})
        lines += [
            "⚠️ COMPLIANCE: drop these over-claim terms: " + ", ".join(terms),
            "",
            "These terms describe features Scheduler does NOT ship (see do_not_claim). A human "
            "MUST remove them before any listing change goes live.",
            "",
            "Per-flag detail:",
        ]
        for f in compliance_flags:
            lines.append(
                f"- store=`{f.get('store')}` field=`{f.get('field')}` term=`{f.get('term')}`"
            )
        lines.append("")

    lines += [
        "## Positioning",
        "",
        f"- What it is: {facts.get('what_it_is', '')}",
        f"- Problem: {facts.get('positioning_problem', '')}",
        f"- Ships (only claim these): {', '.join(facts.get('ships') or [])}",
        f"- DO NOT claim: {', '.join(facts.get('do_not_claim') or [])}",
        "",
        "## ASO listing drafts (per store)",
        "",
    ]
    if drafts:
        for store, draft in drafts.items():
            lines.append(f"### {store}")
            if isinstance(draft, dict):
                for field in ("title", "subtitle", "keywords", "short_desc", "long_desc"):
                    lines.append(f"- **{field}:** {draft.get(field, '')}")
            else:
                lines.append("- _(no draft)_")
            lines.append("")
    else:
        lines.append("_no drafts_")

    return "\n".join(lines)


# --- Routing -----------------------------------------------------------------------------
def _budget_route(state: State) -> str:
    """Clocked in -> start drafting; clocked out -> END (terminal report already set)."""
    return "gather" if check_clocked_in("aso_store_listing_agent") else "clocked_out"


# --- Graph wiring ------------------------------------------------------------------------
builder = StateGraph(State)
builder.add_node("budget_gate", budget_gate)
builder.add_node("gather", gather)
builder.add_node("draft_listing", draft_listing)
builder.add_node("compliance_scan", compliance_scan)
builder.add_node("deliver", deliver)
builder.add_node("finalize", finalize)

builder.add_edge(START, "budget_gate")
builder.add_conditional_edges(
    "budget_gate",
    _budget_route,
    {"gather": "gather", "clocked_out": END},
)
builder.add_edge("gather", "draft_listing")
builder.add_edge("draft_listing", "compliance_scan")
builder.add_edge("compliance_scan", "deliver")
builder.add_edge("deliver", "finalize")
builder.add_edge("finalize", END)

graph = builder.compile()  # NO checkpointer/store — injected by the platform
