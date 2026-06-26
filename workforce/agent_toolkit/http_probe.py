"""Fail-safe HTTP reachability probe — read-only GET, never raises.

Used by the store-health checker to confirm a paywall / hosted-checkout URL is actually
reachable (the "is the thing a user would tap still up?" check). Deliberately tiny and
FAIL-SAFE: any DNS/TLS/timeout/HTTP problem is reported as a structured result, never an
exception, so a flaky network can't crash an agent run. GET only — it never mutates.
"""
from __future__ import annotations

from typing import Optional

import httpx

_TIMEOUT_SECONDS = 15.0
# Only read a small head of the body to look for a marker — never slurp a whole page.
_MAX_BODY_BYTES = 65536


def probe(url: str, *, marker: Optional[str] = None, timeout: float = _TIMEOUT_SECONDS) -> dict:
    """GET ``url`` and report reachability. NEVER raises.

    Returns::

        {
          "url": str,
          "reachable": bool,      # got an HTTP response at all (any status)
          "ok": bool,             # reachable AND 2xx/3xx AND (marker found if given)
          "status": int | None,
          "marker_found": bool | None,   # None when no marker was requested
          "error": str | None,    # type-only on failure (no response bodies / secrets)
        }
    """
    result: dict = {
        "url": url,
        "reachable": False,
        "ok": False,
        "status": None,
        "marker_found": None,
        "error": None,
    }
    try:
        resp = httpx.get(url, timeout=timeout, follow_redirects=True)
    except Exception as exc:  # DNS/TLS/timeout/connection — degrade, don't crash
        result["error"] = f"unreachable: {type(exc).__name__}"
        return result

    result["reachable"] = True
    result["status"] = resp.status_code
    healthy_status = resp.status_code // 100 in (2, 3)
    marker_ok = True
    if marker:
        try:
            body = resp.text[:_MAX_BODY_BYTES] if resp.text else ""
        except Exception:
            body = ""
        marker_ok = marker in body
        result["marker_found"] = marker_ok
    result["ok"] = bool(healthy_status and marker_ok)
    if not healthy_status:
        result["error"] = f"HTTP {resp.status_code}"
    elif marker and not marker_ok:
        result["error"] = "marker not found"
    return result
