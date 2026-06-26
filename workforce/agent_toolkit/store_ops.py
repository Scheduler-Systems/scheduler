"""Store operations seam — App Store Connect + Google Play Developer APIs.

Gives the growth/revenue agents real, KEY-BASED (no UI, no 2FA) tools to OWN store +
pricing ops: read the live subscription/offer state and (gated) create a free trial. This
is the agent doing the store work — not a human clicking consoles.

Credentials (read from env; provisioned into the deployment from GCP Secret Manager):
  App Store Connect (ES256 JWT):
    APP_STORE_CONNECT_API_KEY     — the .p8 private key (PEM)
    APP_STORE_CONNECT_API_KEY_ID  — the key id (kid)
    APP_STORE_CONNECT_ISSUER_ID   — the issuer id
  Google Play:
    GOOGLE_PLAY_SERVICE_ACCOUNT_JSON — the service-account JSON (androidpublisher scope)

Design (matches revenuecat.py): FAIL-SAFE — a missing cred, network error, or non-2xx never
raises; callers always get ``{"ok": bool, ...}``. Secrets are NEVER logged. WRITES are
gated: ``create_*`` returns a *plan* unless ``approve=True`` AND not OPS_REPORT_ONLY — a
real price/trial change is irreversible-ish and escalates to a human, per the fleet's
propose→execute-in-bounds→escalate posture.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional

import httpx

_ASC_BASE = "https://api.appstoreconnect.apple.com"
_PLAY_BASE = "https://androidpublisher.googleapis.com/androidpublisher/v3"


# ── shared ───────────────────────────────────────────────────────────────────

def _report_only() -> bool:
    """Default-on: writes are withheld unless OPS_REPORT_ONLY is explicitly falsey."""
    return os.environ.get("OPS_REPORT_ONLY", "").lower() not in ("0", "false", "no")


def _planned(action: str, payload: dict, reason: str) -> Dict[str, Any]:
    return {"ok": True, "status": "plan", "action": action, "would": payload, "reason": reason}


# ── App Store Connect ─────────────────────────────────────────────────────────

def _asc_key() -> str:
    """The .p8 private key — raw PEM (APP_STORE_CONNECT_API_KEY) or base64 (..._B64).

    The base64 form lets the multi-line PEM travel safely as a single-line deployment secret.
    """
    k = os.environ.get("APP_STORE_CONNECT_API_KEY", "")
    if not k and os.environ.get("APP_STORE_CONNECT_API_KEY_B64"):
        try:
            import base64
            k = base64.b64decode(os.environ["APP_STORE_CONNECT_API_KEY_B64"]).decode()
        except Exception:  # noqa: BLE001
            k = ""
    return k


def asc_configured() -> bool:
    return bool(
        _asc_key()
        and os.environ.get("APP_STORE_CONNECT_API_KEY_ID")
        and os.environ.get("APP_STORE_CONNECT_ISSUER_ID")
    )


def _asc_token() -> Optional[str]:
    """Build a short-lived ASC bearer JWT (ES256). Returns None if unconfigured/failed."""
    if not asc_configured():
        return None
    try:
        import jwt  # PyJWT
        now = int(time.time())
        return jwt.encode(
            {"iss": os.environ["APP_STORE_CONNECT_ISSUER_ID"], "iat": now, "exp": now + 1200,
             "aud": "appstoreconnect-v1"},
            _asc_key(),
            algorithm="ES256",
            headers={"kid": os.environ["APP_STORE_CONNECT_API_KEY_ID"], "typ": "JWT"},
        )
    except Exception as exc:  # noqa: BLE001 — bad key / lib drift, degrade
        return None


def _asc_request(method: str, path: str, *, json_body: Optional[dict] = None,
                 params: Optional[dict] = None) -> Dict[str, Any]:
    """Fail-safe ASC request. NEVER raises, NEVER logs the token/key."""
    tok = _asc_token()
    if not tok:
        return {"ok": False, "error": "App Store Connect not configured", "status": None}
    try:
        resp = httpx.request(
            method, f"{_ASC_BASE}/{path.lstrip('/')}",
            headers={"Authorization": f"Bearer {tok}", "Accept": "application/json"},
            params=params, json=json_body, timeout=30.0,
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"request failed: {type(exc).__name__}", "status": None}
    if resp.status_code // 100 != 2:
        return {"ok": False, "error": f"HTTP {resp.status_code}", "status": resp.status_code}
    try:
        return {"ok": True, "data": resp.json(), "status": resp.status_code}
    except Exception:  # noqa: BLE001
        return {"ok": True, "data": {}, "status": resp.status_code}


def asc_subscription_state(limit: int = 50) -> Dict[str, Any]:
    """Read the apps' subscriptions + whether each already has an introductory (trial) offer.

    Returns a compact summary the growth agent can reason over: per subscription, its name,
    productId, state, and ``has_intro_offer`` (so it knows if a free trial is already live).
    """
    apps = _asc_request("GET", "/v1/apps", params={"limit": limit})
    if not apps.get("ok"):
        return apps
    out: List[dict] = []
    for app in (apps.get("data", {}).get("data") or []):
        app_id = app.get("id")
        name = (app.get("attributes") or {}).get("name")
        groups = _asc_request("GET", f"/v1/apps/{app_id}/subscriptionGroups", params={"limit": 50})
        for grp in (groups.get("data", {}).get("data") or []):
            gid = grp.get("id")
            subs = _asc_request("GET", f"/v1/subscriptionGroups/{gid}/subscriptions",
                                params={"limit": 200, "include": "introductoryOffers"})
            for s in (subs.get("data", {}).get("data") or []):
                a = s.get("attributes") or {}
                intro = ((s.get("relationships") or {}).get("introductoryOffers") or {}).get("data") or []
                out.append({
                    "app": name, "subscription_id": s.get("id"),
                    "product_id": a.get("productId"), "name": a.get("name"),
                    "state": a.get("state"), "has_intro_offer": bool(intro),
                })
    return {"ok": True, "subscriptions": out}


def asc_create_free_trial(subscription_id: str, *, duration: str = "ONE_WEEK",
                          approve: bool = False) -> Dict[str, Any]:
    """Create a free-trial introductory offer on an iOS subscription. GATED.

    Returns a PLAN (no API call) unless ``approve=True`` and not OPS_REPORT_ONLY — creating a
    trial is a live-billing change that must be a deliberate, approved action.
    ``duration`` is an ASC enum (ONE_WEEK / TWO_WEEKS / ONE_MONTH ...).
    """
    body = {
        "data": {
            "type": "subscriptionIntroductoryOffers",
            "attributes": {"duration": duration, "offerMode": "FREE_TRIAL", "numberOfPeriods": 1},
            "relationships": {"subscription": {"data": {"type": "subscriptions", "id": subscription_id}}},
        }
    }
    if _report_only() or not approve:
        return _planned("asc.create_free_trial", body,
                        "live-billing write withheld — needs approve=True and OPS_REPORT_ONLY off")
    return _asc_request("POST", "/v1/subscriptionIntroductoryOffers", json_body=body)


# ── Google Play ────────────────────────────────────────────────────────────────

def play_configured() -> bool:
    return bool(os.environ.get("GOOGLE_PLAY_SERVICE_ACCOUNT_JSON"))


def _play_token() -> Optional[str]:
    if not play_configured():
        return None
    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request
        info = json.loads(os.environ["GOOGLE_PLAY_SERVICE_ACCOUNT_JSON"])
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/androidpublisher"])
        creds.refresh(Request())
        return creds.token
    except Exception:  # noqa: BLE001
        return None


def play_subscription_state(package_name: str) -> Dict[str, Any]:
    """Read a Play app's subscriptions + base plans/offers (so the agent sees trial/annual state)."""
    tok = _play_token()
    if not tok:
        return {"ok": False, "error": "Google Play not configured", "status": None}
    try:
        resp = httpx.get(
            f"{_PLAY_BASE}/applications/{package_name}/subscriptions",
            headers={"Authorization": f"Bearer {tok}"}, params={"pageSize": 100}, timeout=30.0,
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"request failed: {type(exc).__name__}", "status": None}
    if resp.status_code // 100 != 2:
        return {"ok": False, "error": f"HTTP {resp.status_code}", "status": resp.status_code}
    return {"ok": True, "data": resp.json(), "status": resp.status_code}


def play_create_free_trial(package_name: str, product_id: str, base_plan_id: str, *,
                           approve: bool = False) -> Dict[str, Any]:
    """Create a 7-day free-trial offer on a Play base plan. GATED (plan unless approved + writable)."""
    plan = {"package": package_name, "product_id": product_id, "base_plan_id": base_plan_id,
            "offer": "7-day free trial (P1W)"}
    if _report_only() or not approve:
        return _planned("play.create_free_trial", plan,
                        "live-billing write withheld — needs approve=True and OPS_REPORT_ONLY off")
    # Play subscription offers are created via subscriptions.basePlans.offers.create — kept gated
    # here; the deterministic plan is what the agent proposes for human approval before first write.
    return {"ok": False, "error": "play offer write not yet enabled — approve the plan to wire it",
            "plan": plan, "status": None}


def store_state() -> Dict[str, Any]:
    """One read across both stores for a growth agent: subscriptions + whether trials exist."""
    return {
        "app_store": asc_subscription_state() if asc_configured() else {"ok": False, "error": "unconfigured"},
        "google_play_configured": play_configured(),
    }
