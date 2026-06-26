"""Bootstrap GOOGLE_APPLICATION_CREDENTIALS for agents running in LangSmith Cloud.

No agent should ever need interactive `gcloud auth` again.  The priority chain:

  1. GOOGLE_APPLICATION_CREDENTIALS already set in env  →  no-op (already good)
  2. GOOGLE_APPLICATION_CREDENTIALS_JSON env var         →  write to temp file, set creds
     (set this in the LangSmith deployment secrets UI for cloud agents)
  3. Secret Manager                                      →  fetch via REST + ADC, write file
     Secret name: projects/priority-118da/secrets/claude-automation-sa-key

Local dev shortcut:  source ~/.config/gcp-claude/activate.sh   (sets creds path directly)
CI/CD (scheduler-api):  already uses Workload Identity Federation — no changes needed.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

_log = logging.getLogger(__name__)

_SECRET_NAME = (
    "projects/priority-118da/secrets/claude-automation-sa-key/versions/latest"
)
_ACTIVATE_SH = Path.home() / ".config" / "gcp-claude" / "activate.sh"


def ensure_gcp_credentials() -> bool:
    """Ensure GOOGLE_APPLICATION_CREDENTIALS is set.

    Returns True if credentials are now available, False if all paths failed
    (non-fatal — agents that don't call GCP APIs continue normally).
    """
    if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        _log.debug("gcp_auth: GOOGLE_APPLICATION_CREDENTIALS already set — no-op")
        return True

    # ── Path 1: JSON content injected as env var (LangSmith deployment secret) ──
    key_json = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON", "").strip()
    if key_json:
        return _write_key_file(key_json, source="GOOGLE_APPLICATION_CREDENTIALS_JSON env var")

    # ── Path 2: local activate.sh (dev machines / Mac launchd) ──
    if _ACTIVATE_SH.exists():
        _source_activate_sh()
        if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
            _log.info("gcp_auth: credentials sourced from %s", _ACTIVATE_SH)
            return True

    # ── Path 3: Secret Manager REST API (works inside GCP / LangSmith Cloud
    #            if the service-account running the container has secretmanager.versions.access) ──
    try:
        return _fetch_from_secret_manager()
    except Exception as exc:
        _log.debug("gcp_auth: Secret Manager unavailable (%s) — continuing without GCP auth", exc)

    return False


# ─── helpers ────────────────────────────────────────────────────────────────


def _write_key_file(key_json: str, *, source: str) -> bool:
    """Validate JSON, write to a temp file, export GOOGLE_APPLICATION_CREDENTIALS."""
    try:
        json.loads(key_json)  # validate before writing
    except json.JSONDecodeError as exc:
        _log.warning("gcp_auth: %s is not valid JSON (%s) — skipping", source, exc)
        return False

    fd, path = tempfile.mkstemp(suffix=".json", prefix="gcp-sa-key-")
    try:
        os.write(fd, key_json.encode())
    finally:
        os.close(fd)
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = path
    _log.info("gcp_auth: credentials written to %s (source: %s)", path, source)
    return True


def _source_activate_sh() -> None:
    """Parse KEY=VALUE exports from activate.sh and inject them into os.environ.

    We can't actually `source` a shell script from Python, so we parse the simple
    `export KEY=VALUE` lines the activate.sh uses.
    """
    try:
        text = _ACTIVATE_SH.read_text()
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("export "):
                pair = line[len("export "):].strip()
                if "=" in pair:
                    key, _, val = pair.partition("=")
                    # Strip surrounding quotes
                    val = val.strip().strip("'\"")
                    os.environ.setdefault(key.strip(), val)
    except Exception as exc:
        _log.debug("gcp_auth: could not parse activate.sh: %s", exc)


def _fetch_from_secret_manager() -> bool:
    """Fetch the SA key from GCP Secret Manager using google-auth ADC."""
    import google.auth  # type: ignore[import]
    import google.auth.transport.requests  # type: ignore[import]
    import urllib.request

    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    auth_req = google.auth.transport.requests.Request()
    credentials.refresh(auth_req)
    token = credentials.token

    url = f"https://secretmanager.googleapis.com/v1/{_SECRET_NAME}:access"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())

    import base64
    key_json = base64.b64decode(data["payload"]["data"]).decode()
    return _write_key_file(key_json, source=f"Secret Manager ({_SECRET_NAME})")
