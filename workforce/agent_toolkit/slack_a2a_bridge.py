"""Slack <-> A2A bridge — a HUMAN @mentions an agent in Slack, the agent answers in the thread,
and the human watches agents talk to each other.

It RIDES OpenClaw's existing gateway (`openclaw gateway --port 18789`, the one process that holds
the single allowed Socket-Mode connection for the app's `appToken`). This module NEVER opens a
second Socket-Mode connection: OpenClaw terminates the Slack event and forwards a normalized
mention `{channel, thread_ts, user, text}` to this handler; replies go OUT through the bot-token
Web API via `slack_tool.post_digest`. One Socket connection in (OpenClaw), bot-token posts out.

Seam (verified against the installed OpenClaw dist):
  * OpenClaw config `channels.slack.webhookPath = "/slack/events"` — OpenClaw is the Slack ingress.
  * `channels.slack.allowFrom = ["U08L384N6VD"]` — the allow-list of human Slack user IDs that may
    pilot the fleet (mirrors `commands.ownerAllowFrom`). We re-check it here (defense in depth).
  * OpenClaw forwards each inbound mention as a normalized event; `handle_mention` is the entry.

Trust model (the line the task draws):
  * A HUMAN asking an agent is gated by `allowFrom` ONLY (sender-auth). It is NOT an `a2a_gate`
    decision — `a2a_gate` governs AGENT senders. An authorized human piloting the fleet is allowed.
  * The agent's TEXT answer to a direct question is a RESPONSE, not an unsolicited outward action,
    so it is posted back to the same thread without a fresh HITL gate.
  * Any AGENT->peer turn the agent initiates IS governed: it goes through `a2a_gate.gate_a2a`
    (capability `message:<target>` default-deny + HITL on outward) before delivery, and is mirrored
    into the Slack thread as one line so the human can watch agents talk.
  * Any ACTION an agent takes (spend, publish, external write, ...) stays gated by hitl/a2a_gate in
    the agent's own graph — this bridge only carries conversation.

Fail-safe: every public function returns a dict and never raises (a bad mention must not wedge the
gateway). Secrets (LANGSMITH_*, SLACK_BOT_TOKEN, OpenClaw tokens) are read from env for execution
and never logged.
"""
from __future__ import annotations

import asyncio
import os
import re
import uuid
from typing import Any

from . import a2a_client, a2a_gate, slack_tool

# ── Channel -> default agent (reverse of slack_tool._ROUTING anchors) ───────────
# A mention with no explicit "@ROLE" falls back to the channel's owning agent.
_CHANNEL_DEFAULT: dict[str, str] = {
    "executive-updates": "ceo",
    "qa-reports":        "qa_lead_aggregator",
    "marketing":         "cmo",
    "daily-ops":         "daily_digest",
    "engineering":       "cto",
}
_DEFAULT_AGENT = "daily_digest"

# Only this graph is A2A-conversational today; the other 27 take a structured /runs fire.
_CONVERSATIONAL = {"cfo_deepagents"}

# "@ROLE" leading token -> agent slug. Built from the routing table + a few human aliases.
_ROLE_ALIASES: dict[str, str] = {
    "cfo": "cfo_deepagents", "ceo": "ceo", "cto": "cto", "cmo": "cmo", "coo": "coo",
    "qa": "qa_lead_aggregator", "qalead": "qa_lead_aggregator",
    "audit": "audit_risk_director", "growth": "growth_director",
    "hr": "hr_ops_manager", "board": "board_chair",
}


def _agent_slugs() -> set[str]:
    """All valid agent slugs (the routing table is canonical) plus the conversational graph."""
    return set(slack_tool._ROUTING.keys()) | _CONVERSATIONAL | set(_ROLE_ALIASES.values())


# ── (1) sender-auth via allowFrom ───────────────────────────────────────────────

def _allow_from() -> set[str]:
    """Authorized human Slack user IDs. From OPENCLAW_ALLOW_FROM (csv) — sourced from
    openclaw.json `channels.slack.allowFrom` at launch; never read the file's secret values."""
    raw = os.environ.get("OPENCLAW_ALLOW_FROM", "").strip()
    return {u.strip() for u in raw.split(",") if u.strip()}


def sender_authorized(user: str) -> bool:
    """True iff `user` is on the allow-list (or "*" wildcard present). Default-deny on empty list."""
    allow = _allow_from()
    if "*" in allow:
        return True
    return user in allow


# ── (2) resolve target agent: parse "@ROLE ..." else channel default ────────────

_MENTION_HEAD = re.compile(r"^\s*@?([A-Za-z_][A-Za-z0-9_]*)\b[\s,:-]*(.*)$", re.S)


def resolve_target(channel: str, text: str) -> tuple[str, str]:
    """Return (agent_slug, clean_text). A leading '@ROLE' that matches a known agent/alias wins;
    otherwise fall back to the channel default. `clean_text` strips the consumed @ROLE token."""
    chan = (channel or "").lstrip("#").strip().lower()
    slugs = _agent_slugs()
    m = _MENTION_HEAD.match(text or "")
    if m:
        head = m.group(1).lower()
        canon = _ROLE_ALIASES.get(head, head)
        if canon in slugs:
            return canon, m.group(2).strip() or (text or "").strip()
    return _CHANNEL_DEFAULT.get(chan, _DEFAULT_AGENT), (text or "").strip()


# ── (3) stable contextId: one Slack thread == one LangSmith thread ──────────────

def context_id(channel: str, thread_ts: str) -> str:
    """A STABLE UUID derived from the Slack thread — the A2A contextId IS the LangSmith thread_id
    and MUST be a valid UUID (a plain "slack-..." string → -32602 "Invalid thread ID"). uuid5 is
    deterministic, so one Slack thread == one LangSmith conversation across turns."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"slack:{channel}:{thread_ts}"))


# ── (4)+(5) fire the target agent and (5) reply into the thread ─────────────────

async def _fire(agent: str, text: str, ctx: str, meta: dict[str, Any]) -> str:
    """Dispatch to the agent and return its reply text (best-effort, empty on structured fire)."""
    if agent in _CONVERSATIONAL:
        result = await a2a_client.a2a_send(agent, text, context_id=ctx)
        return a2a_client.a2a_text(result)
    # Structured graphs: fire a /runs job carrying the slack envelope; they reply async via their
    # own slack_tool.post_digest into the same thread (the thread_ts travels in the event).
    await a2a_client.fire_run(agent, {
        "event": "slack_mention",
        "text": text,
        "context_id": ctx,
        "thread_ts": meta.get("thread_ts"),
        "channel": meta.get("channel"),
        "from_user": meta.get("user"),
    })
    return ""  # ack-only; the agent posts its own threaded reply when the run completes


def handle_mention(event: dict[str, Any], *, report_only: bool = True) -> dict[str, Any]:
    """OpenClaw's seam entry point. `event` = {channel, thread_ts, user, text}.

    Pipeline: (1) allowFrom auth -> (2) resolve target -> (3) stable contextId ->
    (4) fire (conversational a2a_send | structured fire_run) -> (5) reply via post_digest
    into the thread root (NEVER raw chat.postMessage; keeps _strip_decoration injection defense).

    Returns a status dict; NEVER raises.
    """
    try:
        channel = str(event.get("channel", "")).strip()
        user = str(event.get("user", "")).strip()
        text = str(event.get("text", ""))
        # thread root: reply into the thread the human started (thread_ts, else the message ts).
        thread_root = str(event.get("thread_ts") or event.get("ts") or "").strip()

        # (1) sender-auth — only authorized humans pilot the fleet. This is the human gate; it is
        # NOT a2a_gate (that governs agent senders). Unauthorized -> silent deny (no thread spam).
        if not sender_authorized(user):
            return {"status": "denied", "reason": "sender not in allowFrom", "user": user}

        # (2) resolve target agent
        agent, clean = resolve_target(channel, text)

        # (3) stable contextId == LangSmith thread
        ctx = context_id(channel, thread_root)

        # (4) fire
        meta = {"channel": channel, "thread_ts": thread_root, "user": user}
        reply = asyncio.run(_fire(agent, clean, ctx, meta))

        # (5) reply — only for the conversational path (structured agents self-post). The agent's
        # text answer to a direct question is a RESPONSE, so no fresh HITL here. post_digest keeps
        # the _strip_decoration injection defense (no @channel/@here, no fabricated refs).
        posted = None
        if reply:
            posted = slack_tool.post_digest(agent, "reply", reply, thread_ts=thread_root)

        return {"status": "ok", "agent": agent, "context_id": ctx,
                "replied": bool(reply), "post": posted}
    except Exception as exc:  # noqa: BLE001 — a bad mention must never wedge the gateway
        return {"status": "error", "detail": str(exc)[:300]}


# ── (6) agent-to-agent: a peer turn the human can watch ─────────────────────────

def relay_agent_turn(from_agent: str, target: str, text: str, *, channel: str, thread_ts: str,
                     capabilities: dict[str, Any], mandate: dict[str, Any] | None = None,
                     report_only: bool = True, seq: int = 0, prev_hash: str = "") -> dict[str, Any]:
    """When an agent addresses a PEER, govern it through a2a_gate.gate_a2a (capability + HITL +
    hash-chained audit), then — if allowed — deliver via a2a_send AND mirror the turn into the
    Slack thread as one line so the human watches agents talk. Returns {gate, delivered, mirror}.

    NEVER raises. If the gate denies (or HITL blocks in live mode), nothing is sent.
    """
    try:
        gate = a2a_gate.gate_a2a(from_agent, target, text, capabilities=capabilities,
                                 mandate=mandate, report_only=report_only,
                                 seq=seq, prev_hash=prev_hash)
        if not gate.get("allowed"):
            return {"gate": gate, "delivered": False, "mirror": None}

        ctx = context_id(channel, thread_ts)
        result = asyncio.run(a2a_client.a2a_send(target, text, context_id=ctx)) \
            if target in _CONVERSATIONAL else None
        # Mirror the line into the human-watchable thread (attributed to the speaking agent).
        line = f"-> @{target}: {text}"
        mirror = slack_tool.post_digest(from_agent, "to-peer", line, thread_ts=thread_ts)
        return {"gate": gate, "delivered": True, "result": result, "mirror": mirror}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "detail": str(exc)[:300]}


# ── OpenClaw seam adapters ──────────────────────────────────────────────────────
# Two ways OpenClaw hands a mention to this bridge, BOTH riding its single Socket connection:
#
#  A) SPAWN-COMMAND seam (always available, no extra config) — register this as the channel's
#     `agent command`. OpenClaw's `agentCommandFromIngress` spawns it per mention with the prompt
#     body on stdin and injects OPENCLAW_MCP_MESSAGE_CHANNEL / OPENCLAW_MCP_ACCOUNT_ID. The thread
#     ts arrives via OPENCLAW_MCP_THREAD_TS (templated) or the structured-context header. Call
#     `from_openclaw_command()`; its return string is what OpenClaw posts back into the thread.
#
#  B) HTTP-FORWARD seam — if the operator forwards the gateway's normalized event to a local URL,
#     `scripts/run_slack_a2a_bridge.py` receives the JSON and calls `handle_mention` directly.

def from_openclaw_command() -> str:
    """Entry for the SPAWN-COMMAND seam. Reads the mention from stdin + OPENCLAW_* env, runs the
    handler, and returns a short string for OpenClaw to post (empty string = stay silent/ack-only).

    Env contract (set by OpenClaw on the spawned agent run):
      stdin                          -> the message text (clean prompt body)
      OPENCLAW_MCP_MESSAGE_CHANNEL   -> channel id/name
      OPENCLAW_MCP_THREAD_TS         -> thread root ts (template var, optional)
      OPENCLAW_MCP_SENDER_ID         -> Slack user id of the human (optional; falls back to env)
    """
    import sys
    text = sys.stdin.read() if not sys.stdin.isatty() else ""
    event = {
        "channel": os.environ.get("OPENCLAW_MCP_MESSAGE_CHANNEL", ""),
        "thread_ts": os.environ.get("OPENCLAW_MCP_THREAD_TS", ""),
        "user": os.environ.get("OPENCLAW_MCP_SENDER_ID", ""),
        "text": text,
    }
    result = handle_mention(event, report_only=os.environ.get("BRIDGE_REPORT_ONLY", "1") != "0")
    if result.get("status") == "denied":
        return ""  # unauthorized -> silent (no thread spam)
    # Conversational replies were already posted by handle_mention; return a terse ack for the log.
    return "" if result.get("replied") else f"[{result.get('agent','?')}] on it."
