"""conversion_growth_analyst — CLOUD agent that watches the money funnel and PROPOSES
concrete conversion experiments as drafts (propose-only).

This is the sharpest revenue lever the fleet owns. The declared baseline is brutal:
252 customers / 1 paid subscription / $5 MRR (~0.4% paid conversion). The job is NOT to
ship anything — it is to NOTICE the conversion gap and PROPOSE concrete, reviewable
experiments (reposition the mispositioned listing, add the missing annual plan, configure
the free trial, revisit pricing) so a human can pick and run them.

House rules it follows (same seams as the rest of the ops/growth fleet — see
revenue_reporter, store_health_checker, hr_ops_manager):

  * PROPOSE-ONLY / PROBATION. Experiments are DRAFTS. The digest is delivered via
    ``file_digest_issue(..., report_only=_report_only())`` where ``_report_only()`` defaults
    True (env ``OPS_REPORT_ONLY``; only "0"/"false"/"no" turns it off). On probation the
    delivery is an honest ``{"status": "report_only", ...}`` plan dict — NO GitHub write and,
    critically, NO approval interrupt — so a scheduled unattended run can never hang or write.

  * NEVER HANG. With no credentials the run still completes: RevenueCat falls back to the
    declared ``funnel_baseline``; each paywall probe and the positioning read are wrapped so a
    missing key / offline / SDK drift returns a structured result and the node moves on. A
    telemetry/network problem never crashes a node.

  * FAIL-SAFE / DETERMINISTIC FALLBACK. The model (TIER_DEFAULT, metered via ``budget_guard``)
    is used ONLY to phrase experiments from the gathered facts; on ANY failure (no key,
    budget, SDK drift) we fall back to a DETERMINISTIC experiment list built directly from the
    declared ``revenue_levers``, so a non-empty set of proposals is ALWAYS produced.

  * NO OVER-CLAIM. The model phrases the experiments, so ``compliance_scan`` re-scans every
    draft for any ``product.do_not_claim`` term (features Scheduler does NOT ship — e.g. "AI
    scheduling", "time tracking"). A hit becomes a structured ``compliance_flag`` and the
    delivered body leads with a prominent ``⚠️ COMPLIANCE`` warning — an over-claim is NEVER
    silently emitted (a directory submission already over-claimed those once).

  * ANTHROPIC-TERMS / ML BOUNDARY. ``assert_not_model_work`` guards every outward target
    (the digest repo + any ASO/listing repo we name in an experiment). No model
    train/eval/distill; gal-model / the policy denylist are never acted on or reported.

  * SECRETS: env only, never logged. Error strings are type/status only.

  * CLOCK-IN: ``budget_gate`` runs first; over-salary / globally-disabled => terminal report
    + governance, no RC calls, no probes, no model spend, no writes.

  * Compiles WITHOUT a checkpointer/store (the platform injects Postgres). Every node body is
    wrapped in ``span("conversion_growth_analyst.<node>", ...)``; governance is captured at the
    end with ``report_only: True``.
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
    http_probe,
    TIER_DEFAULT,
)
from agent_toolkit import revenuecat, store_ops
from agent_toolkit.policy import ModelWorkBlocked

# Where the experiments digest is filed (a no-prod-deploy, allow-listed repo).
DIGEST_REPO = "Scheduler-Systems/qa-agent-platform"

# Declared, VERIFIED product facts (funnel baseline, levers, pricing, paywall URLs). The
# orchestrator owns this file; we read it FAIL-SAFE so a missing/corrupt file never crashes.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DEFAULT_POSITIONING_PATH = os.path.join(
    _REPO_ROOT, "docs", "growth", "scheduler_positioning.json"
)

# Hard caps so a huge positioning file / URL list can never hang an agent shift.
_MAX_PAYWALL_URLS = 25
_MAX_LEVERS = 25
# Keep the proposed experiment set tight and reviewable (3-5 concrete experiments).
_MIN_EXPERIMENTS = 3
_MAX_EXPERIMENTS = 5


def _report_only() -> bool:
    """Report-only default for the probation agent: truthy/unset env => True.

    Only an explicit ``OPS_REPORT_ONLY`` of "0"/"false"/"no" turns delivery into a real
    (gated) GitHub write. Everything else — including the env being unset — keeps the agent
    in honest report-only mode (no GitHub call, no approval interrupt), so an unattended
    scheduled run can never hang or write.
    """
    return os.environ.get("OPS_REPORT_ONLY", "").lower() not in ("0", "false", "no")


# --- State -------------------------------------------------------------------------------
class State(TypedDict, total=False):
    mode: str             # reserved for future read-only/observe variants
    positioning: dict     # declared facts read from scheduler_positioning.json (fail-safe)
    rc: dict              # RevenueCat metrics_overview() result (fail-safe; baseline fallback)
    paywall: list         # http_probe results for each declared paywall URL
    findings: dict        # computed conversion metrics + identified gaps
    experiments: list     # the proposed conversion experiments (drafts)
    compliance_flags: list  # banned over-claim terms (product.do_not_claim) found in the drafts
    summary: str          # human-readable experiments digest text
    report: dict          # terminal verdict
    report_only: bool     # whether delivery stayed report-only


# --- Positioning (declared facts) --------------------------------------------------------
def _positioning_path() -> str:
    return os.environ.get("GROWTH_POSITIONING_PATH") or DEFAULT_POSITIONING_PATH


def _load_positioning() -> dict:
    """Read the declared growth facts. FAIL-SAFE — missing/unreadable/non-JSON => {}."""
    try:
        with open(_positioning_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:  # missing / unreadable / non-JSON — degrade to "no declared facts"
        return {}


def _paywall_urls(positioning: dict) -> list:
    """The declared paywall URLs to probe (env override wins). Capped, FAIL-SAFE."""
    raw = os.environ.get("REVENUE_PAYWALL_URLS")
    if raw:
        urls = [u.strip() for u in raw.split(",") if u.strip()]
        if urls:
            return urls[:_MAX_PAYWALL_URLS]
    urls = positioning.get("paywall_urls")
    if isinstance(urls, list):
        return [str(u).strip() for u in urls if str(u).strip()][:_MAX_PAYWALL_URLS]
    return []


# --- Nodes -------------------------------------------------------------------------------
def budget_gate(state: State) -> dict:
    """CLOCK-IN gate — STOP before any work if over salary or globally disabled.

    Runs FIRST. Clocked in => proceed to gather; clocked out => terminal report + governance
    (report-only), no RC calls, no probes, no model spend, no writes.
    """
    with span("conversion_growth_analyst.budget_gate"):
        if check_clocked_in("conversion_growth_analyst"):
            return {}
        report = {
            "clocked_in": False,
            "delivery": "skipped",
            "report_only": True,
        }
        governance_capture(
            "conversion_growth_analyst",
            {"clocked_in": False, "report_only": True, "report": report},
        )
        return {"report": report, "report_only": True}


def gather(state: State) -> dict:
    """Collect the funnel signals — declared facts, RevenueCat metrics, paywall reachability.

    - ``positioning`` : the declared, VERIFIED facts (funnel baseline, levers, pricing,
                        paywall URLs) read FAIL-SAFE from scheduler_positioning.json.
    - ``rc``          : ``revenuecat.metrics_overview()`` (already fail-safe). When RC is not
                        configured / the call degrades, we DON'T pretend — the analyze node
                        falls back to the declared ``funnel_baseline`` for the conversion math.
    - ``paywall``     : a read-only ``http_probe`` per declared paywall URL (is the thing a
                        user would tap still up?), each wrapped so a probe can never crash.
    """
    with span("conversion_growth_analyst.gather"):
        positioning = _load_positioning()

        # RevenueCat headline metrics — already FAIL-SAFE (never raises).
        rc = revenuecat.metrics_overview()

        # Paywall reachability — read-only, each probe wrapped (http_probe never raises, but
        # stay belt-and-suspenders so a probe problem can't crash the node).
        paywall: list = []
        for url in _paywall_urls(positioning):
            try:
                res = http_probe(url)
            except Exception as exc:
                res = {"url": url, "reachable": False, "ok": False, "status": None,
                       "error": f"probe failed: {type(exc).__name__}"}
            if not isinstance(res, dict):
                res = {"url": url, "reachable": False, "ok": False, "status": None,
                       "error": "probe returned non-dict"}
            paywall.append(res)

        # Real App Store product/trial state via the store_ops agent tool (FAIL-SAFE). This
        # replaces guessing from declared facts: we see EXACTLY which live products lack a trial.
        store = store_ops.asc_subscription_state() if store_ops.asc_configured() else {"ok": False}
        no_trial = [
            s for s in (store.get("subscriptions") or [])
            if s.get("state") == "APPROVED" and not s.get("has_intro_offer")
        ]

        return {"positioning": positioning, "rc": rc, "paywall": paywall,
                "store": store, "no_trial_products": no_trial}


def analyze(state: State) -> dict:
    """Compute paid conversion + trial uptake and identify gaps from the declared levers.

    Conversion = paid_subscriptions / customers. We prefer LIVE RevenueCat numbers when the
    metrics fetch succeeded and exposes them; otherwise we fall back to the declared
    ``funnel_baseline`` (252 customers / 1 paid sub => ~0.4%). Gaps are derived from the
    declared facts: a mispositioned listing, no annual plan, an unconfigured trial, pricing.
    FAIL-SAFE throughout — never raises.
    """
    positioning = state.get("positioning") or {}
    rc = state.get("rc") or {}
    paywall = state.get("paywall") or []

    with span("conversion_growth_analyst.analyze"):
        baseline = positioning.get("funnel_baseline") or {}
        metrics = rc.get("metrics") if isinstance(rc.get("metrics"), dict) else {}

        # Customers / paid subs: prefer live RC metrics, fall back to the declared baseline.
        customers = _first_number(
            metrics.get("customers"),
            metrics.get("active_customers"),
            baseline.get("customers"),
        )
        paid_subs = _first_number(
            metrics.get("active_subscriptions"),
            metrics.get("paid_subscriptions"),
            baseline.get("paid_subscriptions"),
        )
        active_trials = _first_number(
            metrics.get("active_trials"),
            baseline.get("active_trials"),
        )
        source = "revenuecat" if rc.get("ok") and metrics else "declared_baseline"

        # Paid conversion = paid_subs / customers (guard divide-by-zero).
        paid_conversion = None
        if isinstance(customers, (int, float)) and customers > 0 and isinstance(paid_subs, (int, float)):
            paid_conversion = paid_subs / customers
        # Trial uptake = active_trials / customers (only when known).
        trial_uptake = None
        if isinstance(customers, (int, float)) and customers > 0 and isinstance(active_trials, (int, float)):
            trial_uptake = active_trials / customers

        # Gaps from the declared facts (each is a concrete, reviewable lever).
        pricing = positioning.get("pricing") or {}
        gaps: list = []
        if positioning.get("positioning_problem"):
            gaps.append("listing_mispositioned")
        if pricing.get("annual_plan_exists") is False:
            gaps.append("no_annual_plan")
        if pricing.get("trial_configured") is False:
            gaps.append("trial_not_configured")
        if active_trials in (None, 0):
            gaps.append("trial_uptake_unknown_or_zero")
        # Low paid conversion is THE problem — flag it whenever we can compute it.
        if isinstance(paid_conversion, (int, float)) and paid_conversion < 0.01:
            gaps.append("low_paid_conversion")

        paywall_down = [p for p in paywall if isinstance(p, dict) and not p.get("ok")]
        if paywall_down:
            gaps.append("paywall_unreachable")

        # REAL trial gap from the live App Store read (store_ops) — supersedes the declared guess.
        no_trial = state.get("no_trial_products") or []
        if no_trial and "trial_not_configured" not in gaps:
            gaps.append("trial_not_configured")

        findings = {
            "source": source,
            "customers": customers,
            "paid_subscriptions": paid_subs,
            "active_trials": active_trials,
            "paid_conversion": paid_conversion,
            "paid_conversion_pct": _as_pct(paid_conversion),
            "trial_uptake": trial_uptake,
            "trial_uptake_pct": _as_pct(trial_uptake),
            "gaps": gaps,
            "paywall_down": len(paywall_down),
            # The concrete, live list the agent can act on (gated create_free_trial per product).
            "no_trial_products": [s.get("product_id") for s in no_trial][:20],
            "no_trial_count": len(no_trial),
        }
        return {"findings": findings}


def propose(state: State) -> dict:
    """Draft 3-5 CONCRETE conversion experiments. PROPOSE-ONLY — never executes.

    Each experiment is a dict ``{hypothesis, change, metric_to_move, effort, expected_lift}``.
    The model (TIER_DEFAULT, metered via ``budget_guard``) is used ONLY to phrase experiments
    from the gathered facts; on ANY model failure we fall back to a DETERMINISTIC list built
    directly from the declared ``revenue_levers`` (and the identified gaps), so the proposal
    set is NEVER empty. ``assert_not_model_work`` guards every outward target we name.
    """
    positioning = state.get("positioning") or {}
    findings = state.get("findings") or {}

    with span("conversion_growth_analyst.propose"):
        # Guard every outward target we might name in an experiment (Anthropic terms). The
        # digest repo + any ASO/listing repo from the declared facts. Skip denylisted ids.
        for target in _outward_targets(positioning):
            try:
                assert_not_model_work(target)
            except ModelWorkBlocked:
                continue  # never propose work against a model-dev target

        # DETERMINISTIC fallback FIRST — always a non-empty, useful set built from the levers.
        deterministic = _deterministic_experiments(positioning, findings)
        experiments = deterministic
        try:
            model = budget_guard("conversion_growth_analyst", TIER_DEFAULT)
            prompt = (
                "You are a conversion / growth analyst for the Scheduler product. The core "
                "revenue problem: many installs/customers, almost no paid conversion (declared "
                "baseline ~0.4%). PROPOSE 3-5 CONCRETE conversion experiments as drafts (a human "
                "reviews before anything ships). Do NOT invent product features — only use the "
                "declared facts. Do NOT claim features Scheduler does not ship.\n\n"
                f"FINDINGS: {json.dumps(findings, default=str)[:3000]}\n"
                f"DECLARED LEVERS: {json.dumps(positioning.get('revenue_levers') or [], default=str)[:2000]}\n"
                f"PRICING: {json.dumps(positioning.get('pricing') or {}, default=str)[:1000]}\n"
                f"POSITIONING PROBLEM: {str(positioning.get('positioning_problem') or '')[:600]}\n\n"
                "Return ONLY a JSON array of 3-5 objects, each with keys: "
                '"hypothesis", "change", "metric_to_move", "effort", "expected_lift". '
                "No prose, no code fences."
            )
            resp = model.invoke(prompt)
            content = getattr(resp, "content", str(resp)) or ""
            parsed = _parse_experiments(content)
            if parsed:
                experiments = parsed
        except Exception:  # model/key/budget unavailable — keep the deterministic experiments
            experiments = deterministic

        # Belt-and-suspenders: never deliver an empty proposal set.
        if not experiments:
            experiments = deterministic or _baseline_experiment(findings)
        # Keep the set tight and reviewable.
        experiments = experiments[:_MAX_EXPERIMENTS]
        return {"experiments": experiments}


def compliance_scan(state: State) -> dict:
    """Scan every drafted experiment for banned over-claim terms. LOAD-BEARING.

    The model phrases experiments and could echo a feature Scheduler does NOT ship (the
    ``product.do_not_claim`` list — e.g. "AI scheduling", "time tracking"). A directory
    submission already over-claimed those once. Case-insensitive substring scan across every
    experiment field; each hit becomes a structured ``{"index", "term", "field"}`` flag. An
    over-claim is NEVER silently emitted: when ``compliance_flags`` is non-empty the ``deliver``
    body carries a prominent ``⚠️ COMPLIANCE`` warning and the flags ride in state. FAIL-SAFE.
    """
    positioning = state.get("positioning") or {}
    experiments = state.get("experiments") or []
    product = positioning.get("product") if isinstance(positioning.get("product"), dict) else {}
    banned = [str(t).strip().lower() for t in (product.get("do_not_claim") or []) if str(t).strip()]

    with span("conversion_growth_analyst.compliance_scan", n=len(experiments), banned=len(banned)):
        flags: list = []
        if banned:
            for i, exp in enumerate(experiments, 1):
                if not isinstance(exp, dict):
                    continue
                for field in ("hypothesis", "change", "metric_to_move", "effort", "expected_lift"):
                    value = exp.get(field)
                    text = value if isinstance(value, str) else json.dumps(value, default=str)
                    low = (text or "").lower()
                    for term in banned:
                        if term and term in low:
                            flags.append({"index": i, "term": term, "field": field})
        return {"compliance_flags": flags}


def deliver(state: State) -> dict:
    """Write the local digest + file the experiments issue (report-only on probation). FAIL-SAFE.

    - ``write_local_digest`` always runs (succeeds-or-"" ; never raises) so there is a local
      artifact even with zero credentials.
    - ``file_digest_issue(..., report_only=_report_only())`` delivers the issue. On probation
      (the default) this returns an honest report-only plan dict with NO GitHub call and NO
      approval interrupt — an unattended run can never hang or write.
    """
    findings = state.get("findings") or {}
    experiments = state.get("experiments") or []
    compliance_flags = state.get("compliance_flags") or []
    report_only = _report_only()

    with span(
        "conversion_growth_analyst.deliver",
        n=len(experiments),
        flags=len(compliance_flags),
        report_only=report_only,
    ):
        body = _render_body(findings, experiments, compliance_flags)

        # Local artifact first — always, fail-safe.
        digest_path = write_local_digest(
            "conversion-growth-analyst", "Conversion experiments", body
        )

        # GitHub issue delivery — report-only by default (no write, no interrupt).
        res = file_digest_issue(
            DIGEST_REPO,
            "Conversion experiments (draft)",
            body,
            labels=["growth:experiment"],
            report_only=report_only,
            agent="conversion_growth_analyst",
        )
        delivery = res.get("status") if isinstance(res, dict) else None
        return {
            "report": {
                "delivery": delivery,
                "digest": digest_path,
                "experiments": len(experiments),
                "compliance_flags": len(compliance_flags),
                "report_only": report_only,
            },
            "report_only": report_only,
        }


def finalize(state: State) -> dict:
    """Terminal node — capture governance (report_only=True) and emit the final report."""
    findings = state.get("findings") or {}
    experiments = state.get("experiments") or []
    compliance_flags = state.get("compliance_flags") or []
    prior = state.get("report") if isinstance(state.get("report"), dict) else {}

    with span("conversion_growth_analyst.finalize", n=len(experiments), flags=len(compliance_flags)):
        governance_capture(
            "conversion_growth_analyst",
            {
                "paid_conversion_pct": findings.get("paid_conversion_pct"),
                "gaps": findings.get("gaps", []),
                "n_experiments": len(experiments),
                "compliance_flags": len(compliance_flags),
                "delivery": prior.get("delivery"),
                "report_only": True,
            },
        )
        return {
            "report": {
                "paid_conversion_pct": findings.get("paid_conversion_pct"),
                "n_experiments": len(experiments),
                "compliance_flags": len(compliance_flags),
                "delivery": prior.get("delivery"),
                "digest": prior.get("digest"),
                "report_only": True,
            }
        }


# --- Routing -----------------------------------------------------------------------------
def _budget_route(state: State) -> str:
    """Clocked in -> start gathering; clocked out -> END (terminal report already set)."""
    return "gather" if check_clocked_in("conversion_growth_analyst") else "clocked_out"


# --- Helpers -----------------------------------------------------------------------------
def _first_number(*values):
    """Return the first value that is a real (non-bool) number, else None."""
    for v in values:
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            return v
    return None


def _as_pct(fraction) -> str:
    """Format a 0..1 fraction as a short percent string, or 'unknown'."""
    if not isinstance(fraction, (int, float)):
        return "unknown"
    return f"~{fraction * 100:.2f}%"


def _outward_targets(positioning: dict) -> list:
    """Every outward target string we might name in an experiment (for the ML-boundary guard).

    The digest repo plus any ASO/listing repo refs declared in the positioning facts
    (``aso.in_flight_branches`` entries are ``owner/repo:branch`` — we guard the repo part).
    """
    targets = [DIGEST_REPO]
    aso = positioning.get("aso") or {}
    for ref in aso.get("in_flight_branches") or []:
        if isinstance(ref, str) and ref:
            repo = ref.split(":", 1)[0].strip()
            if repo:
                targets.append(repo)
    return targets


def _deterministic_experiments(positioning: dict, findings: dict) -> list:
    """Build a concrete experiment per declared lever (model-free, never empty when levers exist).

    Maps each declared ``revenue_levers`` entry to a structured experiment with a plausible
    metric_to_move / effort / expected_lift. Conservative, factual — no invented features.
    """
    levers = positioning.get("revenue_levers") or []
    pct = findings.get("paid_conversion_pct", "unknown")

    # Concrete templates keyed by the lever's intent (matched on keywords in the lever text).
    templates = [
        (
            ("reposition", "listing", "aso"),
            {
                "hypothesis": (
                    "The store listing markets a generic to-do app while the product is "
                    "monetized as B2B shift scheduling — repositioning to shift scheduling "
                    "attracts higher-intent installs that convert to paid."
                ),
                "change": "Rewrite store listing copy + screenshots to B2B shift scheduling for SMB teams (ASO; no app release).",
                "metric_to_move": "paid_conversion",
                "effort": "M",
                "expected_lift": "qualified installs + paid conversion off the ~0.4% floor",
            },
        ),
        (
            ("annual",),
            {
                "hypothesis": "No annual plan exists today; an annual option captures commitment-ready teams and lifts ARPU/retention.",
                "change": "Add an annual plan in RevenueCat (per-user) alongside the monthly price points.",
                "metric_to_move": "ARPU / annual mix",
                "effort": "S",
                "expected_lift": "annual mix + reduced churn for committed teams",
            },
        ),
        (
            ("trial",),
            {
                "hypothesis": "The free trial is not configured in RevenueCat; an activated trial increases first-purchase conversion.",
                "change": "Configure and enable the free trial entitlement in RevenueCat; wire the paywall to start it.",
                "metric_to_move": "trial_uptake -> paid_conversion",
                "effort": "S",
                "expected_lift": "trial starts + trial->paid conversion",
            },
        ),
        (
            ("pricing", "price", "competitor"),
            {
                "hypothesis": "Pricing is currently underpriced vs competitors; revisiting price points lifts revenue without hurting conversion.",
                "change": "A/B the per-user price points ($2.99 / $4.99) vs a tested higher tier; keep per-user model.",
                "metric_to_move": "ARPU / MRR",
                "effort": "M",
                "expected_lift": "ARPU/MRR uplift at comparable conversion",
            },
        ),
    ]

    experiments: list = []
    used_default = set()
    for lever in levers[:_MAX_LEVERS]:
        text = str(lever).lower()
        matched = None
        for keywords, tmpl in templates:
            if any(k in text for k in keywords):
                matched = tmpl
                break
        if matched is not None:
            exp = dict(matched)
        else:
            # Unknown lever — still emit a concrete, reviewable experiment from its text.
            exp = {
                "hypothesis": f"Declared revenue lever: {lever}.",
                "change": str(lever),
                "metric_to_move": "paid_conversion",
                "effort": "M",
                "expected_lift": "incremental paid conversion",
            }
        exp = dict(exp)
        exp["source_lever"] = str(lever)
        # Avoid emitting the exact same templated experiment twice.
        key = (exp["hypothesis"], exp["change"])
        if key in used_default:
            continue
        used_default.add(key)
        experiments.append(exp)

    if not experiments:
        experiments = _baseline_experiment(findings)

    # Pad up to the minimum with the always-true conversion-floor experiment if needed.
    if len(experiments) < _MIN_EXPERIMENTS:
        for extra in _baseline_experiment(findings):
            key = (extra["hypothesis"], extra["change"])
            if key not in used_default:
                used_default.add(key)
                experiments.append(extra)
            if len(experiments) >= _MIN_EXPERIMENTS:
                break

    annotate = f" (current paid conversion {pct})"
    for exp in experiments:
        if "current paid conversion" not in exp.get("hypothesis", ""):
            exp["hypothesis"] = exp.get("hypothesis", "") + annotate
    return experiments[:_MAX_EXPERIMENTS]


def _baseline_experiment(findings: dict) -> list:
    """A single always-available conversion-floor experiment (used when nothing else exists)."""
    pct = findings.get("paid_conversion_pct", "unknown")
    return [
        {
            "hypothesis": (
                f"Paid conversion sits at {pct} — instrument the paywall funnel to find where "
                "high-intent users drop before purchase."
            ),
            "change": "Add paywall funnel instrumentation (view -> start -> purchase) and review drop-off.",
            "metric_to_move": "paid_conversion",
            "effort": "S",
            "expected_lift": "diagnoses the conversion floor; unblocks targeted experiments",
            "source_lever": "(baseline)",
        }
    ]


def _parse_experiments(text: str) -> list:
    """Best-effort parse of a JSON array of experiment objects from model output. FAIL-SAFE.

    Tolerates code fences / surrounding prose. Returns only well-formed experiment dicts; an
    unparseable response yields [] so the caller keeps the deterministic fallback.
    """
    if not text:
        return []
    candidates = [text]
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        candidates.append(text[start : end + 1])
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except Exception:
            continue
        if isinstance(data, list):
            out = [_normalize_experiment(e) for e in data if isinstance(e, dict)]
            out = [e for e in out if e]
            if out:
                return out[:_MAX_EXPERIMENTS]
    return []


def _normalize_experiment(exp: dict) -> dict:
    """Coerce a model experiment dict to the canonical shape; '' for missing fields."""
    keys = ("hypothesis", "change", "metric_to_move", "effort", "expected_lift")
    norm = {k: str(exp.get(k, "")).strip() for k in keys}
    # Require at least a hypothesis or a change to be a usable experiment.
    if not (norm["hypothesis"] or norm["change"]):
        return {}
    return norm


def _render_body(findings: dict, experiments: list, compliance_flags: list = None) -> str:
    """Render the experiments digest body (markdown).

    When ``compliance_flags`` is non-empty a prominent ``⚠️ COMPLIANCE`` warning leads the body
    so an over-claim (a drafted experiment that names a ``do_not_claim`` feature Scheduler does
    not ship) can never be silently shipped past a human reviewer.
    """
    compliance_flags = compliance_flags or []
    lines = [
        "## Conversion experiments (draft — propose-only, human review before anything ships)",
        "",
    ]
    if compliance_flags:
        terms = sorted({str(f.get("term")) for f in compliance_flags if f.get("term")})
        lines += [
            "> ⚠️ COMPLIANCE: drafts mention features Scheduler does NOT ship — drop these "
            "over-claim terms before anything goes live: " + ", ".join(terms) + ".",
            "> (See product.do_not_claim — a directory submission already over-claimed these once.)",
            "",
        ]
    lines += [
        "### Funnel snapshot",
        f"- source: {findings.get('source')}",
        f"- customers: {findings.get('customers')}",
        f"- paid subscriptions: {findings.get('paid_subscriptions')}",
        f"- paid conversion: {findings.get('paid_conversion_pct')}",
        f"- active trials: {findings.get('active_trials')}",
        f"- trial uptake: {findings.get('trial_uptake_pct')}",
        f"- paywall URLs down: {findings.get('paywall_down')}",
        f"- gaps: {', '.join(findings.get('gaps', [])) or 'none'}",
        "",
        f"### Proposed experiments ({len(experiments)})",
    ]
    if experiments:
        for i, exp in enumerate(experiments, 1):
            lines.append(f"{i}. **{exp.get('hypothesis', '')}**")
            lines.append(f"   - change: {exp.get('change', '')}")
            lines.append(f"   - metric to move: {exp.get('metric_to_move', '')}")
            lines.append(f"   - effort: {exp.get('effort', '')}")
            lines.append(f"   - expected lift: {exp.get('expected_lift', '')}")
    else:
        lines.append("_none_")
    return "\n".join(lines)


# --- Graph wiring ------------------------------------------------------------------------
builder = StateGraph(State)
builder.add_node("budget_gate", budget_gate)
builder.add_node("gather", gather)
builder.add_node("analyze", analyze)
builder.add_node("propose", propose)
builder.add_node("compliance_scan", compliance_scan)
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
builder.add_edge("propose", "compliance_scan")
builder.add_edge("compliance_scan", "deliver")
builder.add_edge("deliver", "finalize")
builder.add_edge("finalize", END)

graph = builder.compile()  # NO checkpointer/store — injected by the platform
