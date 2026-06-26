"""event_routing — the event -> agent ROUTING TABLE as data (the event-driven half).

This is the *single source of truth* for "which inbound event fires which agent", reused by
the webhook receiver (``scripts/event_receiver.py``) and available to anything else that needs
to know the mapping (tests, docs, a future dashboard). Keeping it as plain data — not code
buried in the receiver — is the whole point: the receiver does signature-verify + fire, the
*policy* of what fires lives here.

Why this exists (the audit fix): the fleet was meant to be EVENT-DRIVEN — QA agents fire on
GitHub (PR open / merge / push) and on Sentry issue alerts — but the launchd cron that was
supposed to drive them dies on macOS TCC and a deployment secret is malformed, so nothing
fires. The receiver replaces that broken local path with a signature-verifying HTTP endpoint
that calls ``runs.create`` against the LangSmith deployment; this table tells it what to fire.

Design choices encoded here:
  * GitHub PR open/merge/push -> the QA chain. The lead aggregator
    (``qa_lead_aggregator``) is the merge-gate coordinator; it fans out to the platform QA
    workers itself, so firing the lead is the canonical "run QA on this PR" trigger. We also
    fire ``web_qa_regression`` on a push/merge to the default branch (the regression watcher).
  * Sentry issue alert -> ``web_qa_regression`` (the bug-triage / regression agent).
  * Everything fired here is a REPORT-ONLY graph. The receiver only TRIGGERS runs; it never
    crosses a write/HITL gate — the agents' own graphs keep their gates.

The fired agents (deterministic, no surprises): every agent named below MUST be a real graph
in ``langgraph.json``. ``unknown`` events route to NOTHING (default-deny) — we never fire a
guessed agent off an unrecognized event.
"""
from __future__ import annotations

from typing import Any

# ── canonical event keys ────────────────────────────────────────────────────────
# GitHub pull_request actions we care about. "opened"/"reopened"/"synchronize" = a PR got new
# code to QA; "closed" with merged=true = a merge (regression watch on the target branch).
SOURCE_GITHUB = "github"
SOURCE_SENTRY = "sentry"

# ── the routing table (event -> [agents]) ───────────────────────────────────────
# Keyed by (source, canonical_event). Each value is the ordered list of graph ids to fire.
# qa_lead_aggregator is the QA chain entry point (it dispatches the six platform workers).
_ROUTES: dict[tuple[str, str], list[str]] = {
    # A PR opened / reopened / got new commits -> run the QA chain on it.
    (SOURCE_GITHUB, "pr_opened"):      ["qa_lead_aggregator"],
    (SOURCE_GITHUB, "pr_reopened"):    ["qa_lead_aggregator"],
    (SOURCE_GITHUB, "pr_synchronize"): ["qa_lead_aggregator"],
    # A PR merged -> run the QA chain AND kick the regression watcher on the target branch.
    (SOURCE_GITHUB, "pr_merged"):      ["qa_lead_aggregator", "web_qa_regression"],
    # A raw push to a branch (the `push` event) -> regression watcher (default-branch focus).
    (SOURCE_GITHUB, "push"):           ["web_qa_regression"],
    # A Sentry issue alert (new/regressed/escalating error) -> the bug-triage agent.
    (SOURCE_SENTRY, "issue_alert"):    ["web_qa_regression"],
}

# Graphs that may be fired by an inbound event. Used as an allow-list so a typo in the table
# (or a future edit) can't fire an arbitrary graph; the receiver and tests assert membership.
FIREABLE_AGENTS: frozenset[str] = frozenset(
    a for agents in _ROUTES.values() for a in agents
)


def routes() -> dict[tuple[str, str], list[str]]:
    """Return a copy of the routing table (callers must not mutate the canonical map)."""
    return {k: list(v) for k, v in _ROUTES.items()}


def agents_for(source: str, event: str) -> list[str]:
    """Agents to fire for ``(source, event)``; empty list (fire nothing) if unrouted.

    Default-deny: an unknown source or event returns ``[]`` and the receiver fires nothing.
    """
    return list(_ROUTES.get((source, event), []))


# ── GitHub event normalization ──────────────────────────────────────────────────
# Map a raw GitHub webhook (the X-GitHub-Event header + parsed JSON body) to a canonical
# event key in the table. Returns None when we deliberately ignore the event (e.g. a PR
# "labeled"/"assigned" action that shouldn't trigger QA) — the receiver treats None as
# "accepted, nothing to fire" (200, no fire), distinct from a bad signature (401).
_PR_ACTION_TO_EVENT = {
    "opened": "pr_opened",
    "reopened": "pr_reopened",
    "synchronize": "pr_synchronize",
}


def normalize_github(event_header: str, body: dict[str, Any]) -> str | None:
    """Canonical event key for a GitHub webhook, or None to ignore.

    ``event_header`` is the ``X-GitHub-Event`` value (e.g. "pull_request", "push", "ping").
    A "pull_request" with action "closed" and ``merged: true`` -> "pr_merged"; a non-merge
    close is ignored. A "push" -> "push". "ping" and unhandled events -> None.
    """
    header = (event_header or "").strip().lower()
    if header == "pull_request":
        action = str(body.get("action") or "").lower()
        if action == "closed":
            pr = body.get("pull_request") or {}
            return "pr_merged" if bool(pr.get("merged")) else None
        return _PR_ACTION_TO_EVENT.get(action)
    if header == "push":
        return "push"
    # ping (webhook setup handshake) and everything else: accepted but fires nothing.
    return None


def github_subject_id(event: str, body: dict[str, Any]) -> str | None:
    """A stable subject id for deterministic thread continuity (per-PR / per-branch).

    For PR events: the PR's global node_id (preferred) or "<repo>#<number>". For push: the
    repo full_name + ref so a branch's pushes share a thread. Returns None if not derivable.
    """
    if event.startswith("pr_"):
        pr = body.get("pull_request") or {}
        node_id = pr.get("node_id")
        if node_id:
            return str(node_id)
        repo = (body.get("repository") or {}).get("full_name")
        number = pr.get("number") or body.get("number")
        if repo and number is not None:
            return f"{repo}#{number}"
        return None
    if event == "push":
        repo = (body.get("repository") or {}).get("full_name")
        ref = body.get("ref")
        if repo and ref:
            return f"{repo}@{ref}"
        return None
    return None


def sentry_subject_id(body: dict[str, Any]) -> str | None:
    """A stable subject id for a Sentry issue alert (per-issue thread continuity).

    Sentry's modern webhook nests the issue under ``data.issue``; the legacy/issue-alert
    payload may carry an ``id``/``issue_id`` at the top. Try the common shapes.
    """
    data = body.get("data") or {}
    issue = data.get("issue") or body.get("issue") or {}
    for key in ("id", "issue_id", "shortId", "short_id"):
        val = issue.get(key) if isinstance(issue, dict) else None
        if val:
            return str(val)
    for key in ("id", "issue_id"):
        if body.get(key):
            return str(body[key])
    return None
