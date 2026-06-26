"""RevenueCat REST client — FAIL-SAFE, read-only, orchestration only.

The ops fleet's revenue/store agents read RevenueCat to (a) report revenue metrics and
(b) detect non-purchasable SKUs / offering drift. This module is the ONLY place RC is
called, and it follows the toolkit's house rules:

- **Secrets from the ENVIRONMENT only** — never hardcode, never log a key/value:
    REVENUECAT_API_KEY   — a RevenueCat **v2 secret** API key (Bearer)
    REVENUECAT_PROJECT_ID — the RC project id the SKUs live under
    REVENUECAT_API_BASE  — override (default https://api.revenuecat.com/v2)
- **FAIL-SAFE**: a missing key, offline backend, non-2xx, or SDK/JSON hiccup returns a
  structured ``{"ok": False, "error": ...}`` (or an empty list helper) — it NEVER raises,
  so a telemetry/network problem can't crash an agent run.
- **READ-ONLY**: only GETs. This client never mutates RevenueCat.
- **Orchestration, not model work**: no train/eval/distill. (Defense-in-depth: callers
  still pass outward targets through ``policy.assert_not_model_work``.)

RC v2 endpoints used (all GET, project-scoped):
  /projects/{project}/metrics/overview   — headline metrics (MRR, active subs/trials, ...)
  /projects/{project}/products           — products (store SKUs) — paginated
  /projects/{project}/offerings          — offerings — paginated
  /projects/{project}/offerings/{id}/packages — packages within an offering — paginated
"""
from __future__ import annotations

import os
from typing import Any, Optional

import httpx

DEFAULT_API_BASE = "https://api.revenuecat.com/v2"
_TIMEOUT_SECONDS = 20.0
# Hard cap on pagination so a runaway/looping cursor can never hang an agent shift.
_MAX_PAGES = 25


def _api_base() -> str:
    return (os.environ.get("REVENUECAT_API_BASE") or DEFAULT_API_BASE).rstrip("/")


def is_configured() -> bool:
    """True when both the API key and project id are present in the environment."""
    return bool(os.environ.get("REVENUECAT_API_KEY") and os.environ.get("REVENUECAT_PROJECT_ID"))


def _missing() -> Optional[str]:
    """Return a human message naming the missing env var(s), or None if configured."""
    missing = [
        name
        for name in ("REVENUECAT_API_KEY", "REVENUECAT_PROJECT_ID")
        if not os.environ.get(name)
    ]
    return f"{' + '.join(missing)} not set" if missing else None


def _project_id() -> str:
    return os.environ.get("REVENUECAT_PROJECT_ID", "")


def _get(path: str, *, params: Optional[dict] = None) -> dict:
    """GET ``path`` (relative to the v2 base) and return a structured result.

    Returns ``{"ok": True, "data": <json>}`` on a 2xx, else ``{"ok": False, "error": ...,
    "status": <int|None>}``. NEVER raises and NEVER logs the API key. The error string is
    deliberately status/type only — RC error bodies can echo identifiers, so we keep them
    short and credential-free.
    """
    miss = _missing()
    if miss:
        return {"ok": False, "error": miss, "status": None}
    key = os.environ.get("REVENUECAT_API_KEY", "")
    url = f"{_api_base()}/{path.lstrip('/')}"
    try:
        resp = httpx.get(
            url,
            headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
            params=params or {},
            timeout=_TIMEOUT_SECONDS,
        )
    except Exception as exc:  # network/DNS/timeout — degrade, don't crash
        return {"ok": False, "error": f"request failed: {type(exc).__name__}", "status": None}
    if resp.status_code // 100 != 2:
        return {"ok": False, "error": f"HTTP {resp.status_code}", "status": resp.status_code}
    try:
        return {"ok": True, "data": resp.json(), "status": resp.status_code}
    except Exception:
        return {"ok": False, "error": "non-JSON response", "status": resp.status_code}


def _get_all(path: str) -> dict:
    """Follow RC v2 cursor pagination for a list endpoint. FAIL-SAFE.

    RC v2 list responses are ``{"items": [...], "next_page": "<path|url|null>"}``. Returns
    ``{"ok": bool, "items": [...], "error": <str|None>, "pages": <int>}``. On the first page
    error returns ok=False with whatever items were gathered (none).
    """
    items: list[dict] = []
    next_path: Optional[str] = path
    pages = 0
    error: Optional[str] = None
    while next_path and pages < _MAX_PAGES:
        res = _get(next_path)
        pages += 1
        if not res.get("ok"):
            error = res.get("error")
            break
        data = res.get("data") or {}
        page_items = data.get("items")
        if isinstance(page_items, list):
            items.extend(i for i in page_items if isinstance(i, dict))
        nxt = data.get("next_page")
        # next_page may be a full URL or a relative path; normalize to a path the _get
        # helper can re-issue (strip the base if present).
        if isinstance(nxt, str) and nxt:
            base = _api_base()
            next_path = nxt[len(base):] if nxt.startswith(base) else nxt
        else:
            next_path = None
    return {"ok": error is None, "items": items, "error": error, "pages": pages}


# --- Typed read helpers -------------------------------------------------------------
def metrics_overview() -> dict:
    """Headline revenue metrics for the project (MRR, active subs/trials, revenue, ...).

    Returns ``{"ok": bool, "metrics": {<id>: <value>}, "raw": <list>, "error": <str|None>}``.
    The flattened ``metrics`` map keys each metric by its ``id`` (e.g. ``mrr``,
    ``active_subscriptions``, ``active_trials``) for easy reporting; ``raw`` keeps the full
    objects (name/unit/period) for the digest.
    """
    res = _get(f"projects/{_project_id()}/metrics/overview")
    if not res.get("ok"):
        return {"ok": False, "metrics": {}, "raw": [], "error": res.get("error")}
    data = res.get("data") or {}
    raw = data.get("metrics")
    raw = raw if isinstance(raw, list) else []
    flat: dict[str, Any] = {}
    for m in raw:
        if isinstance(m, dict) and m.get("id") is not None:
            flat[str(m["id"])] = m.get("value")
    return {"ok": True, "metrics": flat, "raw": raw, "error": None}


def list_products() -> dict:
    """All products (store SKUs) in the project. Returns ``{"ok", "items": [...], "error"}``."""
    return _get_all(f"projects/{_project_id()}/products")


def list_offerings() -> dict:
    """All offerings in the project. Returns ``{"ok", "items": [...], "error"}``."""
    return _get_all(f"projects/{_project_id()}/offerings")


def list_packages(offering_id: str) -> dict:
    """Packages within an offering. Returns ``{"ok", "items": [...], "error"}``."""
    return _get_all(f"projects/{_project_id()}/offerings/{offering_id}/packages")
