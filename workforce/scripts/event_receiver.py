#!/usr/bin/env python3
"""event_receiver — the signature-verifying webhook RECEIVER that makes the fleet event-driven.

THE AUDIT FIX (event half): QA agents were meant to fire on GitHub (PR open/merge/push) and on
Sentry issue alerts, but the local launchd cron that drove them dies on macOS TCC and a
deployment secret is malformed, so nothing fires. This service replaces that dead path: it
receives a GitHub/Sentry webhook over HTTP, VERIFIES the signature, and (only then) fires the
right QA agent against the LangSmith deployment via ``runs.create`` with a deterministic
``thread_id`` (per-PR / per-issue continuity). This is the pattern LangChain's open-swe uses.

Hard security properties (verified by tests, all BEFORE any fire):
  * GitHub: HMAC-SHA256 of the RAW body under ``GITHUB_WEBHOOK_SECRET``, compared with
    ``X-Hub-Signature-256`` in CONSTANT TIME (``hmac.compare_digest``). No header, no secret,
    or a mismatch -> 401 and FIRE NOTHING.
  * Sentry: HMAC-SHA256 of the RAW body under ``SENTRY_CLIENT_SECRET`` (Sentry's
    ``Sentry-Hook-Signature`` scheme), constant-time compared. Same 401-before-fire rule.
  * Replay defense: the replay key is derived from SIGNED material — the SHA-256 of the raw
    request BODY (the exact bytes the HMAC covers) — NOT from the unsigned ``X-GitHub-Delivery``
    / ``Sentry-Hook-Resource`` headers (those are outside GitHub's/Sentry's body-only HMAC, so an
    attacker can mutate them on a captured request). A body we have already processed is rejected
    (401) before firing, so a captured-and-replayed request cannot re-fire an agent even by
    mutating the unsigned delivery/resource header (a genuine redelivery carries the same body and
    so still dedups). (In-process LRU; a deployed instance should back this with a shared store,
    noted as deploy debt — and because the key is signed material, a shared store fixes the
    multi-instance case completely.)
  * NEVER log the secret or the raw body. We log only the source, event kind, and decision.

The fire path (proven live 2026-06-06): ``runs.create`` against the deployment needs BOTH
``x-api-key: $LANGSMITH_API_KEY`` AND ``X-Tenant-Id: $LANGSMITH_TENANT_ID`` — encoded in
``agent_toolkit.a2a_client.fire_run``, which we reuse. The fired graphs are REPORT-ONLY; this
receiver only TRIGGERS runs, it never crosses a write/HITL gate.

Fail-safe: a fire error never crashes the receiver — it is caught and returned as a per-agent
``{"agent": ..., "status": "error"}`` entry; the HTTP response is still 202 (accepted) because
the *event was valid*. Only an UNSIGNED / BADLY-SIGNED / REPLAYED request is rejected (401).

Run (deploy-gated; this builds the code only):
    LANGGRAPH_DEPLOYMENT_URL=... LANGSMITH_API_KEY=... LANGSMITH_TENANT_ID=... \
    GITHUB_WEBHOOK_SECRET=... SENTRY_CLIENT_SECRET=... \
    python -m scripts.event_receiver --port 8787
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import json
import logging
import os
import sys
import uuid
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

# Make ``agent_toolkit`` importable whether run as ``python -m scripts.event_receiver`` or
# ``python scripts/event_receiver.py`` from the repo root.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from agent_toolkit import event_routing  # noqa: E402
from agent_toolkit.github_ops import ALLOWED_REPOS  # noqa: E402 — canonical write/act allow-list

logger = logging.getLogger("event_receiver")

# A branch/ref from a webhook body is attacker-influenced (a low-priv actor or a fork can open a
# PR / push a branch named anything). GitHub ref names already forbid most shell metacharacters,
# but we are the trust boundary, so we hard-constrain ref text to a conservative safe charset
# before it enters agent state — no spaces, no shell metachars, no command-substitution syntax.
import re  # noqa: E402

_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9._/\-]+$")
_MAX_REF_LEN = 255  # GitHub ref names are bounded; cap defensively.


def _safe_ref(ref: Any) -> str | None:
    """Return ``ref`` only if it is a safe git-ref token; else None.

    Defends against shell-metachar / command-substitution branch names (e.g. ``$(curl evil)``)
    being shipped into the run input. Non-string, over-long, or out-of-charset -> None (dropped)."""
    if not isinstance(ref, str):
        return None
    ref = ref.strip()
    if not ref or len(ref) > _MAX_REF_LEN or not _SAFE_REF_RE.match(ref):
        return None
    return ref

# Stable namespace so a given PR/issue subject always maps to the SAME thread_id across
# deliveries (per-PR continuity). Fixed UUID -> deterministic uuid5.
_THREAD_NS = uuid.UUID("6f7c0e2a-0c3a-5b9d-9e21-2f1a4b6c8d10")

# Header names (lower-cased by http.server; we normalize on read).
_GH_SIG_HEADER = "x-hub-signature-256"
_GH_EVENT_HEADER = "x-github-event"
_GH_DELIVERY_HEADER = "x-github-delivery"
_SENTRY_SIG_HEADERS = ("sentry-hook-signature",)  # Sentry sends the HMAC here
_SENTRY_RESOURCE_HEADER = "sentry-hook-resource"


# ── signature verification (constant-time, secret never logged) ──────────────────

def _hmac_sha256_hex(secret: str, raw: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()


def verify_github_signature(secret: str, raw_body: bytes, signature_header: str | None) -> bool:
    """True iff ``X-Hub-Signature-256`` ("sha256=<hex>") matches HMAC-SHA256(raw_body).

    Default-deny: empty secret, missing/malformed header, or any mismatch -> False. The compare
    is constant time. We never raise (a malformed header must yield False, not an exception).
    """
    if not secret or not signature_header:
        return False
    header = signature_header.strip()
    prefix = "sha256="
    if not header.startswith(prefix):
        return False
    sent = header[len(prefix):]
    expected = _hmac_sha256_hex(secret, raw_body)
    # compare_digest over equal-length hex strings; tolerate case via lower().
    return hmac.compare_digest(sent.lower(), expected.lower())


def verify_sentry_signature(secret: str, raw_body: bytes, signature_header: str | None) -> bool:
    """True iff Sentry's ``Sentry-Hook-Signature`` matches HMAC-SHA256(raw_body) under secret.

    Sentry signs the raw request body with the integration's client secret using SHA256 and
    sends the bare hex digest (no "sha256=" prefix). Default-deny + constant-time, never raises.
    """
    if not secret or not signature_header:
        return False
    expected = _hmac_sha256_hex(secret, raw_body)
    return hmac.compare_digest(signature_header.strip().lower(), expected.lower())


# ── deterministic thread id (per-PR / per-issue continuity) ──────────────────────

def thread_id_for(source: str, subject_id: str) -> str:
    """Deterministic thread_id = uuid5(NS, "<source>:<subject_id>").

    Same PR/issue subject -> same thread across deliveries, so a PR's QA runs append to one
    LangSmith thread (the continuity the audit fix wants). Different subjects -> different ids.
    """
    return str(uuid.uuid5(_THREAD_NS, f"{source}:{subject_id}"))


# ── replay defense (bounded in-process seen-set) ─────────────────────────────────

class ReplayGuard:
    """Bounded LRU of delivery ids we've already accepted. ``seen(id)`` records and reports.

    Deployed, this should be a shared/TTL store so two instances or a restart don't re-accept a
    replay — flagged as deploy debt. In-process is enough to make the property TESTABLE and to
    stop a same-process replay.
    """

    def __init__(self, capacity: int = 4096) -> None:
        self._cap = max(1, capacity)
        self._seen: "OrderedDict[str, None]" = OrderedDict()

    def seen(self, delivery_id: str | None) -> bool:
        """Return True if this id was already processed (a replay); else record it and return
        False. A missing id (None/empty) is treated as a replay-failure -> rejected by caller."""
        if not delivery_id:
            return True  # no id to dedup on -> refuse (defense in depth)
        if delivery_id in self._seen:
            self._seen.move_to_end(delivery_id)
            return True
        self._seen[delivery_id] = None
        if len(self._seen) > self._cap:
            self._seen.popitem(last=False)
        return False


# ── the run firer (injectable for tests; defaults to the proven a2a_client path) ─

def _default_fire(agent: str, thread_id: str, agent_input: dict[str, Any]) -> Any:
    """Fire one report-only graph via the proven runs.create path (a2a_client.fire_run).

    a2a_client.fire_run creates a run with the x-api-key + X-Tenant-Id headers it already
    encodes. The deterministic thread is passed as ``fire_run``'s ``thread_id`` (NOT smuggled
    into the input dict) so the run is actually THREADED on the LangGraph side — a PR's repeated
    pushes append to ONE thread for per-PR / per-issue continuity. fire_run is async, so drive it
    on a fresh loop here.
    """
    from agent_toolkit import a2a_client

    return asyncio.run(a2a_client.fire_run(agent, dict(agent_input), thread_id=thread_id))


class EventReceiver:
    """Pure core: verify -> route -> fire. The HTTP handler is a thin shell over this.

    Separated from the socket layer so the security-critical decisions (reject-before-fire,
    deterministic thread, fail-safe firing) are unit-testable with no network. ``fire`` is
    injectable: tests pass a recording stub; production uses ``_default_fire``.
    """

    def __init__(self, *, github_secret: str | None = None, sentry_secret: str | None = None,
                 fire=None, replay_guard: ReplayGuard | None = None,
                 warn_on_unset: bool = True) -> None:
        # Secrets default to env at construction; never logged (value is never read into a log).
        self._gh_secret = github_secret if github_secret is not None else os.environ.get("GITHUB_WEBHOOK_SECRET", "")
        self._sentry_secret = sentry_secret if sentry_secret is not None else os.environ.get("SENTRY_CLIENT_SECRET", "")
        self._fire = fire or _default_fire
        self._replay = replay_guard or ReplayGuard()
        # STARTUP WARNING (FINDING 2): a missing webhook secret is a SILENT fail — the receiver would
        # 401 EVERY webhook for that source and only log a coarse "rejected" line per request, so
        # "nothing fires" looks like "no traffic". Make the misconfiguration LOUD at construction (the
        # one place every entry path — CLI, build_receiver_from_env, an imported deployment — passes
        # through), naming ONLY the unset var(s), never any value. ``warn_on_unset=False`` silences
        # it for tests that deliberately construct an unconfigured receiver.
        if warn_on_unset:
            self.warn_unset_secrets()

    def warn_unset_secrets(self) -> list[str]:
        """Log a clear STARTUP warning for any unset webhook secret; return the unset NAMES.

        Names only — never a value. Returns the list of unset secret var names (for tests). If a
        source's secret is unset, EVERY request to that source is rejected (401) before firing — so
        this is the difference between an invisible silent-fail and an operator-visible warning.
        """
        unset: list[str] = []
        if not (self._gh_secret or "").strip():
            unset.append("GITHUB_WEBHOOK_SECRET")
        if not (self._sentry_secret or "").strip():
            unset.append("SENTRY_CLIENT_SECRET")
        if len(unset) == 2:
            logger.error(
                "STARTUP: neither GITHUB_WEBHOOK_SECRET nor SENTRY_CLIENT_SECRET is set — EVERY "
                "webhook will be rejected (401) and NO agent will ever fire. Set at least one before "
                "activating (run scripts/check_deploy_env.py to preflight)."
            )
        elif unset:
            src = "GitHub" if unset[0] == "GITHUB_WEBHOOK_SECRET" else "Sentry"
            logger.warning(
                "STARTUP: %s is unset — every %s webhook will be rejected (401) and fire nothing. "
                "Set it (or scripts/check_deploy_env.py) before relying on %s events.",
                unset[0], src, src,
            )
        return unset

    # -- per-source handlers; each returns (http_status, result_dict) -------------

    def handle(self, source: str, headers: dict[str, str], raw_body: bytes) -> tuple[int, dict[str, Any]]:
        """Verify + (maybe) fire for a request. ``headers`` keys are lower-cased.

        Returns (status, body). 401 = rejected (bad/absent/replayed signature) and FIRES
        NOTHING. 202 = accepted (signature valid); body lists what fired. 200 = accepted but
        nothing routed (e.g. a GitHub ping or an ignored action). 400 = malformed JSON on an
        otherwise-verifiable request is treated as a reject (we can't trust it) -> 401.
        """
        h = {k.lower(): v for k, v in headers.items()}
        if source == event_routing.SOURCE_GITHUB:
            return self._handle_github(h, raw_body)
        if source == event_routing.SOURCE_SENTRY:
            return self._handle_sentry(h, raw_body)
        return 404, {"error": "unknown source"}

    def _reject(self, reason: str) -> tuple[int, dict[str, Any]]:
        # Single rejection shape; reason is a coarse label (never includes body/secret).
        logger.warning("rejected webhook: %s", reason)
        return 401, {"ok": False, "rejected": reason, "fired": []}

    def _handle_github(self, h: dict[str, str], raw_body: bytes) -> tuple[int, dict[str, Any]]:
        # 1) signature FIRST — before parsing/trusting the body.
        if not verify_github_signature(self._gh_secret, raw_body, h.get(_GH_SIG_HEADER)):
            return self._reject("github-signature")
        # 2) replay — reject a re-delivered request before doing anything. The replay key MUST be
        # derived from SIGNED material: GitHub's HMAC (X-Hub-Signature-256) covers only the BODY,
        # so X-GitHub-Delivery is attacker-mutable on a captured request. Keying on the body hash
        # means an unchanged signed body can never be re-keyed by mutating the unsigned delivery
        # header (a genuine GitHub redelivery carries the same body, so it still dedups). We bind
        # in the delivery id too ONLY as an extra discriminator — it can make two DISTINCT signed
        # bodies that happen to collide independent, but it can never make ONE signed body fire
        # twice, because the body hash component is fixed for a fixed body.
        body_digest = hashlib.sha256(raw_body).hexdigest()
        if self._replay.seen(f"github:body:{body_digest}"):
            return self._reject("github-replay")
        # 3) now the body is trusted enough to parse.
        try:
            body = json.loads(raw_body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return self._reject("github-malformed-json")
        event = event_routing.normalize_github(h.get(_GH_EVENT_HEADER, ""), body)
        if event is None:
            return 200, {"ok": True, "ignored": h.get(_GH_EVENT_HEADER, ""), "fired": []}
        subject = event_routing.github_subject_id(event, body) or h.get(_GH_DELIVERY_HEADER) or "unknown"
        return self._fire_event(event_routing.SOURCE_GITHUB, event, subject, body)

    def _handle_sentry(self, h: dict[str, str], raw_body: bytes) -> tuple[int, dict[str, Any]]:
        sig = next((h.get(name) for name in _SENTRY_SIG_HEADERS if h.get(name)), None)
        if not verify_sentry_signature(self._sentry_secret, raw_body, sig):
            return self._reject("sentry-signature")
        # Replay key from SIGNED material only. Sentry's HMAC (Sentry-Hook-Signature) covers only
        # the BODY, so the Sentry-Hook-Resource header is attacker-mutable on a captured request —
        # we MUST NOT key on it (the old resource-header fast-path let a replay mint a fresh key).
        # Key on the body hash: an unchanged signed body can never be re-fired by mutating the
        # unsigned resource header. The resource header is still read below purely to CLASSIFY the
        # hook kind (issue alert vs other), never to dedup.
        delivery = h.get(_SENTRY_RESOURCE_HEADER)
        if self._replay.seen(f"sentry:body:{hashlib.sha256(raw_body).hexdigest()}"):
            return self._reject("sentry-replay")
        try:
            body = json.loads(raw_body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return self._reject("sentry-malformed-json")
        # Only fire on issue alerts (the bug-triage trigger); ignore other Sentry hooks.
        action = str(body.get("action") or "").lower()
        resource = (delivery or "").lower()
        is_issue_alert = resource in ("issue", "event_alert", "metric_alert") or "issue" in action or body.get("data", {}).get("issue")
        if not is_issue_alert:
            return 200, {"ok": True, "ignored": "sentry-non-issue", "fired": []}
        subject = event_routing.sentry_subject_id(body) or delivery or "unknown"
        return self._fire_event(event_routing.SOURCE_SENTRY, "issue_alert", subject, body)

    # -- routing + fail-safe firing ----------------------------------------------

    def _fire_event(self, source: str, event: str, subject_id: str,
                    body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        # SSRF/injection gate (the receiver is the trust boundary, not just each downstream
        # agent). A GitHub org has ONE webhook secret, so EVERY repo in the org — and every PR a
        # low-priv actor / fork opens — yields a VALIDLY-SIGNED webhook with attacker-influenced
        # ``repository.full_name``. Signature-verify proves the bytes came from GitHub; it does
        # NOT prove the named repo is one the fleet may act on. So when the body names a repo, it
        # MUST be on the canonical ALLOWED_REPOS allow-list before we route the run input
        # (``target``/``repo``) anywhere — else refuse to route (200-ignored, fire NOTHING). This
        # is default-deny at the gate, not "trust the agent to re-check assert_allowed_repo".
        repo = (body.get("repository") or {}).get("full_name")
        if repo is not None and repo not in ALLOWED_REPOS:
            logger.warning("ignored %s/%s for non-allow-listed repo", source, event)
            return 200, {"ok": True, "ignored": "repo-not-allow-listed", "fired": []}
        agents = event_routing.agents_for(source, event)
        thread_id = thread_id_for(source, subject_id)
        results: list[dict[str, Any]] = []
        for agent in agents:
            # defense in depth: never fire a graph that isn't on the fireable allow-list.
            if agent not in event_routing.FIREABLE_AGENTS:
                results.append({"agent": agent, "status": "blocked"})
                continue
            agent_input = self._build_input(source, event, agent, subject_id, body)
            try:
                self._fire(agent, thread_id, agent_input)
                results.append({"agent": agent, "status": "fired", "thread_id": thread_id})
            except Exception as exc:  # fail-safe: one bad fire must not crash the receiver
                logger.error("fire failed for %s (%s/%s): %s", agent, source, event, type(exc).__name__)
                results.append({"agent": agent, "status": "error", "thread_id": thread_id})
        logger.info("event %s/%s -> %d agent(s)", source, event, len(results))
        return 202, {"ok": True, "source": source, "event": event,
                     "thread_id": thread_id, "fired": results}

    @staticmethod
    def _build_input(source: str, event: str, agent: str, subject_id: str,
                     body: dict[str, Any]) -> dict[str, Any]:
        """Construct the structured input the report-only graph reads. Minimal + deterministic;
        no secrets. The agents accept extra keys, so we pass useful context (repo/branch/PR)."""
        repo = (body.get("repository") or {}).get("full_name")
        inp: dict[str, Any] = {"event": f"{source}:{event}", "trigger": "webhook",
                               "subject_id": subject_id}
        if repo:
            inp["target"] = repo
            inp["repo"] = repo
        if event.startswith("pr_"):
            pr = body.get("pull_request") or {}
            inp["pr_number"] = pr.get("number") or body.get("number")
            head = (pr.get("head") or {})
            # branch/ref is attacker-influenced — sanitize to a safe git-ref charset (drops
            # shell-metachar / command-substitution names like ``$(curl evil)``) before it
            # enters agent state. A non-conforming ref becomes None rather than poisoned text.
            inp["branch"] = _safe_ref(head.get("ref"))
            inp["head_sha"] = _safe_ref(head.get("sha"))
        elif event == "push":
            inp["branch"] = _safe_ref((body.get("ref") or "").rsplit("/", 1)[-1] or None)
            inp["head_sha"] = _safe_ref(body.get("after"))
            inp["head_sha"] = body.get("after")
        elif source == event_routing.SOURCE_SENTRY:
            inp["sentry_issue"] = subject_id
        return inp


# ── HTTP shell ───────────────────────────────────────────────────────────────────

# Map URL path -> source. Both a generic and a per-source path are accepted.
_PATH_SOURCE = {
    "/webhooks/github": event_routing.SOURCE_GITHUB,
    "/github": event_routing.SOURCE_GITHUB,
    "/webhooks/sentry": event_routing.SOURCE_SENTRY,
    "/sentry": event_routing.SOURCE_SENTRY,
}


def make_handler(receiver: EventReceiver):
    """Build a BaseHTTPRequestHandler class bound to ``receiver`` (so the server is testable)."""

    class _Handler(BaseHTTPRequestHandler):
        server_version = "qa-event-receiver/1.0"

        def log_message(self, fmt, *args):  # noqa: D401 - silence default access log (no body/secret)
            return

        def _send(self, status: int, payload: dict[str, Any]) -> None:
            data = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):  # noqa: N802 - liveness probe only
            if self.path.rstrip("/") in ("/healthz", "/health", ""):
                self._send(200, {"ok": True, "service": "event_receiver"})
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self):  # noqa: N802
            source = _PATH_SOURCE.get(self.path.split("?", 1)[0].rstrip("/"))
            if source is None:
                self._send(404, {"error": "unknown path"})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except (TypeError, ValueError):
                length = 0
            # Cap body size to avoid an unbounded read (a hostile large body); 5 MiB is ample.
            if length < 0 or length > 5 * 1024 * 1024:
                self._send(413, {"error": "body too large"})
                return
            raw = self.rfile.read(length) if length else b""
            headers = {k: v for k, v in self.headers.items()}
            try:
                status, payload = receiver.handle(source, headers, raw)
            except Exception:  # absolute fail-safe: never 500 due to handler logic
                logger.exception("unexpected receiver error")
                status, payload = 500, {"ok": False, "error": "internal"}
            self._send(status, payload)

    return _Handler


def build_receiver_from_env() -> EventReceiver:
    return EventReceiver()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="QA fleet webhook receiver (event-driven trigger).")
    parser.add_argument("--host", default=os.environ.get("RECEIVER_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("RECEIVER_PORT", "8787")))
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    # Fail fast if the deployment fire path isn't configured — but DON'T print the values.
    missing = [k for k in ("LANGGRAPH_DEPLOYMENT_URL", "LANGSMITH_API_KEY", "LANGSMITH_TENANT_ID")
               if not (os.environ.get(k) or (k == "LANGGRAPH_DEPLOYMENT_URL" and os.environ.get("LANGSMITH_DEPLOYMENT_URL")))]
    if missing:
        logger.warning("fire path not fully configured (missing: %s) — runs will error until set", ",".join(missing))

    # The webhook-secret startup warning (both-unset AND single-unset) is emitted by the receiver
    # at construction (EventReceiver.warn_unset_secrets), so every entry path — not just this CLI —
    # surfaces the silent-fail. build_receiver_from_env() triggers it below.
    receiver = build_receiver_from_env()
    httpd = ThreadingHTTPServer((args.host, args.port), make_handler(receiver))
    logger.info("event_receiver listening on %s:%d", args.host, args.port)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("shutting down")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
