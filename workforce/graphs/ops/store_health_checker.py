"""store_health_checker — CLOUD agent that watches the money door.

Mission (revenue-critical): catch the things that silently stop a user from paying —
a SKU that is NOT purchasable (the "could not check store status" signal a store/RC
console shows when a product has no store identifier), offering/trial config drift away
from the declared baseline, and a paywall URL that is simply down. A non-purchasable SKU
or a dead paywall = lost sales, so this agent's only job is to NOTICE and REPORT.

House rules it follows (same seams as the rest of the ops fleet):
  - REPORT-ONLY on probation: every outward action goes through ``file_digest_issue(...,
    report_only=_report_only())``. The default reads env ``OPS_REPORT_ONLY`` (truthy/unset
    => True). Report-only NEVER contacts GitHub and NEVER enters the approval interrupt, so
    an unattended scheduled run with no credentials always finishes and never hangs.
  - FAIL-SAFE: every external call (RevenueCat, HTTP probe, GitHub, filesystem, model) is
    wrapped — a missing key / offline backend / SDK drift returns a structured result and
    the run still completes. A telemetry/network problem never crashes a node.
  - SECRETS: env only, never logged. Error strings are type/status only (no bodies/tokens).
  - ANTHROPIC-TERMS / ML boundary: ``assert_not_model_work`` guards every outward id we act
    on (product / offering ids); gal-model / denylisted ids are skipped, never reported on.
  - CLOCK-IN: ``budget_gate`` runs first; over-salary / globally-disabled => terminal report.
  - Compiles WITHOUT a checkpointer/store (the platform injects Postgres).

Honest "could not check": when RevenueCat creds are missing we do NOT pretend the store is
healthy — we emit a single ``unverifiable`` warning ("could not check store status"), which
is exactly the operator-visible signal we want to surface.
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
from agent_toolkit import revenuecat, http_probe
from agent_toolkit.policy import ModelWorkBlocked

# Where the digest is filed (a no-prod-deploy, allow-listed repo).
DIGEST_REPO = "Scheduler-Systems/qa-agent-platform"

# Declared-expected SKUs/offerings live here (the orchestrator writes it). Read FAIL-SAFE.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DEFAULT_BASELINE_PATH = os.path.join(_REPO_ROOT, "docs", "ops", "rc_baseline.json")

# Default paywall URL list (read-only probe) when REVENUE_PAYWALL_URLS is unset.
DEFAULT_PAYWALL_URLS = ("https://scheduler-web-next.web.app/",)

# Hard caps so a huge project can never hang an agent shift.
_MAX_OFFERINGS = 200
_MAX_PACKAGES = 200


def _report_only() -> bool:
    """Report-only default: env ``OPS_REPORT_ONLY`` truthy/unset => True; '0'/'false' => False.

    On probation the fleet must take NO mutating/outward action without a human gate, so the
    safe default is True. Only an explicit falsey value opts out.
    """
    raw = os.environ.get("OPS_REPORT_ONLY")
    if raw is None:
        return True
    return raw.strip().lower() not in ("0", "false", "no", "off")


# --- State -------------------------------------------------------------------------------
class State(TypedDict, total=False):
    mode: str
    products: list
    offerings: list
    sku_findings: list
    paywall: list
    severity: str
    summary: str
    report: dict
    report_only: bool


# --- Baseline ----------------------------------------------------------------------------
def _baseline_path() -> str:
    return os.environ.get("RC_BASELINE_PATH") or DEFAULT_BASELINE_PATH


def _load_baseline() -> dict:
    """Read the declared baseline (expected products/offerings). FAIL-SAFE.

    Returns ``{"products": [...ids...], "offerings": [...ids...], "configured": bool}``.
    Missing file OR empty products+offerings => configured=False ("no baseline configured")
    so we never raise a false drift alarm.
    """
    products: list = []
    offerings: list = []
    try:
        with open(_baseline_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            products = [str(x) for x in (data.get("products") or []) if x not in (None, "")]
            offerings = [str(x) for x in (data.get("offerings") or []) if x not in (None, "")]
    except Exception:  # missing / unreadable / non-JSON — degrade to "no baseline"
        products, offerings = [], []
    configured = bool(products or offerings)
    return {"products": products, "offerings": offerings, "configured": configured}


def _store_identifier(product: dict) -> str:
    """Best-effort extraction of a product's store SKU id across RC v2 field shapes."""
    for key in ("store_identifier", "store_id", "store_sku", "identifier", "sku"):
        val = product.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _is_placeholder(store_id: str) -> bool:
    """A store identifier that is empty or an obvious placeholder => non-purchasable."""
    if not store_id:
        return True
    low = store_id.strip().lower()
    return low in ("", "tbd", "todo", "placeholder", "none", "null", "n/a", "changeme")


def _safe_id(value) -> str:
    return str(value) if value not in (None, "") else ""


def _items(res) -> list:
    """The ``items`` list from a FAIL-SAFE RC result, coerced to an actual list.

    The real ``revenuecat`` helpers always return ``{"items": [...]}``, but SDK/contract
    drift could put a dict/str/None there. We accept ONLY a real list so a later
    ``items[:cap]`` slice or iteration can never raise — anything else degrades to ``[]``.
    """
    if isinstance(res, dict):
        val = res.get("items")
        if isinstance(val, list):
            return val
    return []


# --- Nodes -------------------------------------------------------------------------------
def budget_gate(state: State) -> dict:
    """CLOCK-IN gate — STOP before any work if over salary or globally disabled.

    Runs FIRST. Clocked in => proceed; clocked out => terminal report + governance, no RC
    calls, no probes, no writes.
    """
    with span("store_health_checker.budget_gate"):
        if check_clocked_in("store_health_checker"):
            return {}
        report = {
            "severity": "skipped",
            "detail": "store_health_checker over token salary or globally disabled",
            "report_only": True,
        }
        governance_capture(
            "store_health_checker",
            {"clocked_in": False, "report_only": True, "report": report},
        )
        return {"report": report, "report_only": True}


def check_skus(state: State) -> dict:
    """Pull products + offerings from RevenueCat and detect non-purchasable / drift findings.

    If RC is not configured we emit the honest 'could not check store status' warning rather
    than pretend health. Otherwise every finding is a dict
    ``{"severity", "kind", "detail", ...}``. FAIL-SAFE throughout.
    """
    with span("store_health_checker.check_skus"):
        if not revenuecat.is_configured():
            return {
                "products": [],
                "offerings": [],
                "sku_findings": [
                    {
                        "severity": "warn",
                        "kind": "unverifiable",
                        "detail": "RevenueCat creds missing — could not check store status",
                    }
                ],
            }

        prod_res = revenuecat.list_products()
        off_res = revenuecat.list_offerings()
        products = _items(prod_res)
        offerings = _items(off_res)
        findings: list = []

        # Surface a fetch failure as an honest unverifiable signal (don't silently pass).
        if isinstance(prod_res, dict) and not prod_res.get("ok"):
            findings.append({
                "severity": "warn", "kind": "unverifiable",
                "detail": "could not check store status: products fetch failed "
                          f"({prod_res.get('error')})",
            })
        if isinstance(off_res, dict) and not off_res.get("ok"):
            findings.append({
                "severity": "warn", "kind": "unverifiable",
                "detail": "could not check store status: offerings fetch failed "
                          f"({off_res.get('error')})",
            })

        # Map of known product ids for broken-package / drift detection.
        product_ids: set = set()
        for p in products:
            if not isinstance(p, dict):
                continue
            pid = _safe_id(p.get("id"))
            try:
                if pid:
                    assert_not_model_work(pid)  # defensive: never act on a model-dev id
            except ModelWorkBlocked:
                continue  # skip denylisted ids entirely — never report on them
            if pid:
                product_ids.add(pid)
            # (a) non-purchasable: empty / placeholder store identifier.
            store_id = _store_identifier(p)
            if _is_placeholder(store_id):
                findings.append({
                    "severity": "high", "kind": "non_purchasable",
                    "product": pid or "(unknown)",
                    "detail": "product has empty/placeholder store_identifier — NOT purchasable",
                })

        # (b) broken package: a package's product reference is not among known products.
        for offering in offerings[:_MAX_OFFERINGS]:
            if not isinstance(offering, dict):
                continue
            oid = _safe_id(offering.get("id"))
            try:
                if oid:
                    assert_not_model_work(oid)
            except ModelWorkBlocked:
                continue
            packages = _offering_packages(offering, oid)
            for pkg in packages[:_MAX_PACKAGES]:
                if not isinstance(pkg, dict):
                    continue
                ref = _package_product_ref(pkg)
                if ref and ref not in product_ids:
                    findings.append({
                        "severity": "high", "kind": "broken_package",
                        "offering": oid or "(unknown)",
                        "package": _safe_id(pkg.get("id")) or "(unknown)",
                        "detail": f"package references unknown product '{ref}'",
                    })

        # (c) baseline drift — only when a baseline is actually configured.
        baseline = _load_baseline()
        if baseline["configured"]:
            offering_ids = {
                _safe_id(o.get("id")) for o in offerings if isinstance(o, dict)
            }
            offering_ids.discard("")
            findings.extend(_drift_findings("product", baseline["products"], product_ids))
            findings.extend(_drift_findings("offering", baseline["offerings"], offering_ids))

        return {"products": products, "offerings": offerings, "sku_findings": findings}


def check_paywall(state: State) -> dict:
    """Probe each paywall URL (read-only). Unreachable / non-2xx => a high finding. FAIL-SAFE."""
    with span("store_health_checker.check_paywall"):
        urls = _paywall_urls()
        results: list = []
        for url in urls:
            try:
                res = http_probe(url)
            except Exception as exc:  # http_probe never raises, but stay belt-and-suspenders
                res = {"url": url, "reachable": False, "ok": False,
                       "status": None, "error": f"probe failed: {type(exc).__name__}"}
            if not isinstance(res, dict):
                res = {"url": url, "reachable": False, "ok": False, "status": None,
                       "error": "probe returned non-dict"}
            res = dict(res)
            if not res.get("ok"):
                res["severity"] = "high"
                res["kind"] = "paywall_down"
            results.append(res)
        return {"paywall": results}


def triage(state: State) -> dict:
    """Roll findings up into a single severity + a short summary. FAIL-SAFE.

    severity = 'high' if any high finding (non_purchasable / broken_package / paywall down),
    else 'medium' if any medium finding (drift), else 'ok'. Uses the budget-metered model to
    word the summary; on ANY model failure falls back to a deterministic summary.
    """
    sku_findings = state.get("sku_findings") or []
    paywall = state.get("paywall") or []
    with span("store_health_checker.triage", findings=len(sku_findings), urls=len(paywall)):
        highs = [f for f in sku_findings if f.get("severity") == "high"]
        mediums = [f for f in sku_findings if f.get("severity") == "medium"]
        paywall_down = [p for p in paywall if not p.get("ok")]

        if highs or paywall_down:
            severity = "high"
        elif mediums:
            severity = "medium"
        else:
            severity = "ok"

        deterministic = (
            f"Store/RC health = {severity}. "
            f"sku_findings: {len(highs)} high, {len(mediums)} medium, "
            f"{len(sku_findings) - len(highs) - len(mediums)} other; "
            f"paywall: {len(paywall_down)}/{len(paywall)} URL(s) down."
        )
        summary = deterministic
        try:
            model = budget_guard("store_health_checker", TIER_DEFAULT)
            prompt = (
                "You are a revenue store-health checker. A non-purchasable SKU or a dead "
                "paywall = lost sales. Write a SHORT (2-4 sentence) operator summary of the "
                "store/RevenueCat health below. Be factual; do not invent findings.\n\n"
                f"Severity: {severity}\n"
                f"SKU findings: {json.dumps(sku_findings, default=str)[:4000]}\n"
                f"Paywall probes: {json.dumps(paywall, default=str)[:2000]}\n"
            )
            resp = model.invoke(prompt)
            content = getattr(resp, "content", str(resp)) or ""
            if content.strip():
                summary = content.strip()
        except Exception as exc:  # model/key unavailable — keep the deterministic summary
            summary = f"{deterministic} (model summary unavailable: {type(exc).__name__})"

        return {"severity": severity, "summary": summary}


def deliver(state: State) -> dict:
    """Write the local digest + file the GitHub issue (report-only on probation). FAIL-SAFE."""
    severity = state.get("severity") or "ok"
    summary = state.get("summary") or f"Store/RC health = {severity}."
    sku_findings = state.get("sku_findings") or []
    paywall = state.get("paywall") or []
    report_only = _report_only()

    with span("store_health_checker.deliver", severity=severity, report_only=report_only):
        body = _render_body(severity, summary, sku_findings, paywall)
        # Always leave a local artifact even with zero credentials.
        write_local_digest("store-health-checker", "Store/RC health", body)

        labels = ["alert:store-health"]
        if severity == "high":
            labels.append("gate:human-required")

        res = file_digest_issue(
            DIGEST_REPO,
            "Store/RC health: " + severity,
            body,
            labels=labels,
            report_only=report_only,
            agent="store_health_checker",
            # STABLE dedup key — severity rides in the title/body but must NOT drift the
            # find-or-update key, or every ok->high->ok flip re-files a duplicate issue
            # (#33/#35/#43 spam). One standing "store-health" record, updated each shift.
            record_kind="store-health",
            slack_title="🏥 Store/RC health: " + severity,
        )
        delivery = res.get("status") if isinstance(res, dict) else None
        return {
            "report": {"severity": severity, "delivery": delivery},
            "report_only": report_only,
        }


def finalize(state: State) -> dict:
    """Terminal node — capture governance (report_only=True) and emit the final report."""
    severity = state.get("severity") or "ok"
    sku_findings = state.get("sku_findings") or []
    paywall = state.get("paywall") or []
    prior = state.get("report") if isinstance(state.get("report"), dict) else {}
    paywall_down = sum(1 for p in paywall if not p.get("ok"))

    with span("store_health_checker.finalize", severity=severity):
        governance_capture(
            "store_health_checker",
            {
                "severity": severity,
                "n_findings": len(sku_findings),
                "paywall_down": paywall_down,
                "report_only": True,
            },
        )
        report = {
            "severity": severity,
            "n_findings": len(sku_findings),
            "paywall_down": paywall_down,
            "delivery": prior.get("delivery"),
            "report_only": True,
        }
        return {"report": report}


# --- Helpers -----------------------------------------------------------------------------
def _paywall_urls() -> list:
    raw = os.environ.get("REVENUE_PAYWALL_URLS")
    if raw:
        urls = [u.strip() for u in raw.split(",") if u.strip()]
        if urls:
            return urls
    return list(DEFAULT_PAYWALL_URLS)


def _offering_packages(offering: dict, offering_id: str) -> list:
    """Packages for an offering — inline if RC embedded them, else a FAIL-SAFE list call."""
    inline = offering.get("packages")
    if isinstance(inline, dict):
        inline = inline.get("items")
    if isinstance(inline, list):
        return inline
    if not offering_id:
        return []
    try:
        res = revenuecat.list_packages(offering_id)
    except Exception:
        return []
    return res.get("items") or [] if isinstance(res, dict) else []


def _package_product_ref(pkg: dict) -> str:
    """The product id a package points at, across RC v2 field shapes. '' if none."""
    for key in ("product_id", "product"):
        val = pkg.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
        if isinstance(val, dict):
            pid = val.get("id")
            if isinstance(pid, str) and pid.strip():
                return pid.strip()
    return ""


def _drift_findings(kind: str, expected: list, actual: set) -> list:
    """Compare expected vs actual ids: missing => 'drift' medium, unexpected extra => 'drift' low."""
    findings: list = []
    expected_set = {str(e) for e in expected}
    for missing in sorted(expected_set - actual):
        findings.append({
            "severity": "medium", "kind": "drift",
            "detail": f"expected {kind} '{missing}' is missing from RevenueCat",
        })
    for extra in sorted(actual - expected_set):
        findings.append({
            "severity": "low", "kind": "drift",
            "detail": f"unexpected {kind} '{extra}' not in baseline",
        })
    return findings


def _render_body(severity: str, summary: str, sku_findings: list, paywall: list) -> str:
    lines = [
        f"**Severity:** {severity}",
        "",
        summary,
        "",
        f"## SKU / offering findings ({len(sku_findings)})",
    ]
    if sku_findings:
        for f in sku_findings:
            sev = f.get("severity", "?")
            kind = f.get("kind", "?")
            detail = f.get("detail", "")
            lines.append(f"- **[{sev}] {kind}** — {detail}")
    else:
        lines.append("_none_")
    lines += ["", f"## Paywall probes ({len(paywall)})"]
    if paywall:
        for p in paywall:
            mark = "ok" if p.get("ok") else "DOWN"
            lines.append(
                f"- `{p.get('url')}` — {mark} "
                f"(reachable={p.get('reachable')}, status={p.get('status')}, "
                f"error={p.get('error')})"
            )
    else:
        lines.append("_none_")
    return "\n".join(lines)


# --- Routing -----------------------------------------------------------------------------
def _budget_route(state: State) -> str:
    """Clocked in -> start the checks; clocked out -> END (terminal report already set)."""
    return "check_skus" if check_clocked_in("store_health_checker") else "clocked_out"


# --- Graph wiring ------------------------------------------------------------------------
builder = StateGraph(State)
builder.add_node("budget_gate", budget_gate)
builder.add_node("check_skus", check_skus)
builder.add_node("check_paywall", check_paywall)
builder.add_node("triage", triage)
builder.add_node("deliver", deliver)
builder.add_node("finalize", finalize)

builder.add_edge(START, "budget_gate")
builder.add_conditional_edges(
    "budget_gate",
    _budget_route,
    {"check_skus": "check_skus", "clocked_out": END},
)
builder.add_edge("check_skus", "check_paywall")
builder.add_edge("check_paywall", "triage")
builder.add_edge("triage", "deliver")
builder.add_edge("deliver", "finalize")
builder.add_edge("finalize", END)

graph = builder.compile()  # NO checkpointer/store — injected by the platform
