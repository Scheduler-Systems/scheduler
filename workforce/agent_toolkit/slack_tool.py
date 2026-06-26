"""Slack posting seam for the ops fleet.

Every agent that produces a digest can call ``post_digest`` after writing its local file.
This module is FAIL-SAFE: a missing token, a network error, or a rate-limit never crashes
a node. The caller gets back a dict (status + details) in all cases.

Authentication (checked in order):
  1. SLACK_BOT_TOKEN (xoxb-...) — full Web API: can create channels, post to any channel,
     set custom username/icon per message.
  2. SLACK_WEBHOOK_URL — incoming webhook: posts to the webhook's pre-configured channel only.
     Used as fallback when no bot token is present.
  3. Neither set: returns {"status": "no_credentials", "detail": "..."}.

Channel routing (agent slug → channel name):
  The table below is the canonical source. Override per-agent via the SLACK_CHANNEL_<AGENT>
  env var (e.g. SLACK_CHANNEL_DAILY_DIGEST=#ops-digest). Unknown agents go to #daily-ops.

Agent personas:
  Each agent posts with a distinct emoji avatar so the Slack thread reads like a real team.
  Set SLACK_AGENT_ICON_<AGENT>=:icon_name: to override (e.g. SLACK_AGENT_ICON_CEO=:crown:).
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

# ── Channel routing ────────────────────────────────────────────────────────────
# Maps agent slug → (channel_name, default_emoji). channel_name must include the #.
_ROUTING: dict[str, tuple[str, str]] = {
    # Executive & board
    "daily_digest":            ("#executive-updates", ":calendar:"),
    "ceo":                     ("#executive-updates", ":necktie:"),
    "cfo":                     ("#executive-updates", ":moneybag:"),
    "board_chair":             ("#executive-updates", ":classical_building:"),
    "audit_risk_director":     ("#executive-updates", ":shield:"),
    "growth_director":         ("#executive-updates", ":chart_with_upwards_trend:"),
    "clo":                     ("#executive-updates", ":scales:"),
    # Ops
    "revenue_reporter":        ("#executive-updates", ":bar_chart:"),
    "store_health_checker":    ("#executive-updates", ":health:"),
    "coo":                     ("#daily-ops",          ":gear:"),
    "git_sync_auditor":        ("#daily-ops",          ":git:"),
    "memory_sync":             ("#daily-ops",          ":brain:"),
    # Engineering
    "cto":                     ("#engineering",        ":computer:"),
    "security_officer":        ("#engineering",        ":shield:"),
    "git_maintainer":          ("#engineering",        ":wrench:"),
    "env_doctor":              ("#engineering",        ":stethoscope:"),
    "hr_ops_manager":          ("#engineering",        ":busts_in_silhouette:"),
    # Marketing
    "cmo":                     ("#marketing",          ":loudspeaker:"),
    "aso_store_listing_agent": ("#marketing",          ":iphone:"),
    "content_campaign_drafter":("#marketing",          ":pencil:"),
    "conversion_growth_analyst":("#marketing",         ":seedling:"),
    "sales_dev":               ("#marketing",          ":handshake:"),
    # QA
    "qa_lead_aggregator":      ("#qa-reports",         ":white_check_mark:"),
    "web_automation_engineer": ("#qa-reports",         ":globe_with_meridians:"),
    "android_automation_engineer":("#qa-reports",      ":android:"),
    "ios_automation_engineer": ("#qa-reports",         ":apple:"),
    "web_manual_tester":       ("#qa-reports",         ":eye:"),
    "android_manual_tester":   ("#qa-reports",         ":mag:"),
    "ios_manual_tester":       ("#qa-reports",         ":iphone:"),
}
_DEFAULT_CHANNEL = "#daily-ops"
_DEFAULT_EMOJI = ":robot_face:"


def _channel_for(agent: str) -> str:
    env_key = f"SLACK_CHANNEL_{agent.upper()}"
    override = os.environ.get(env_key, "").strip()
    if override:
        return override if override.startswith("#") else f"#{override}"
    channel, _ = _ROUTING.get(agent, (_DEFAULT_CHANNEL, _DEFAULT_EMOJI))
    return channel


def _emoji_for(agent: str) -> str:
    env_key = f"SLACK_AGENT_ICON_{agent.upper()}"
    override = os.environ.get(env_key, "").strip()
    if override:
        return override
    _, emoji = _ROUTING.get(agent, (_DEFAULT_CHANNEL, _DEFAULT_EMOJI))
    return emoji


# ── HTTP helpers ────────────────────────────────────────────────────────────────

def _post_json(url: str, payload: dict, headers: Optional[dict] = None, timeout: int = 10) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode()
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                return {"ok": True, "raw": body}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode() if exc.fp else ""
        return {"ok": False, "error": f"http_{exc.code}", "detail": body[:500]}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": "network", "detail": str(exc)[:200]}


# ── Public API ─────────────────────────────────────────────────────────────────

# ── Human-voice formatting (concise, no emoji, conversational) ──────────────────
_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"  # pictographs / emoji / supplemental
    "\U00002600-\U000026FF"  # misc symbols
    "\U00002700-\U000027BF"  # dingbats
    "\U0001F1E6-\U0001F1FF"  # regional indicators (flags)
    "\U0000FE00-\U0000FE0F"  # variation selectors
    "\U00002B00-\U00002BFF"  # arrows / stars
    "\U00002190-\U000021FF"  # arrows
    "]+",
    flags=re.UNICODE,
)

# Injection defense: model-authored text must NOT be able to ping @channel/@here/@everyone
# or fabricate user/channel refs (Slack renders <!channel>, <@U..>, <#C..> specially).
_MENTION_RE = re.compile(r"<!(?:channel|here|everyone)>|<@[A-Z0-9]+>|<#[A-Z0-9]+(?:\|[^>]*)?>", re.I)


def _strip_decoration(text: str) -> str:
    """Remove emoji, Slack mass-mentions, and markdown/Slack decoration, leaving plain text."""
    text = _EMOJI_RE.sub("", text)
    text = _MENTION_RE.sub("", text)
    out = []
    for ln in text.splitlines():
        s = ln.strip().lstrip("#").strip().lstrip("*-•·").strip()
        s = s.replace("**", "").replace("`", "")
        if s:
            out.append(s)
    return "\n".join(out).strip()


def _humanize(agent: str, title: str, body: str, *, max_chars: int = 320) -> str:
    """Turn a verbose, emoji-laden digest into ONE short, human Slack line. FAIL-SAFE.

    Prefers an LLM rewrite in a terse teammate voice; falls back to a stripped, truncated
    version when no model is available or the call fails. Never raises.
    """
    plain = _strip_decoration(f"{title}\n{body}")
    role = agent.replace("_", " ")
    try:
        from .models import get_model  # lazy import — only when actually posting
        m = get_model()
        if m is not None:
            prompt = (
                f"You are the {role} on a small startup team, dropping a quick update in Slack.\n"
                "Rewrite the status below as ONE or TWO short, plain sentences — exactly how a "
                "busy human teammate would actually type it. Lead with what matters. Be specific "
                "with numbers. NO emoji, NO markdown, NO headers or bullets, NO 'memo'/corporate "
                "language, NO preamble like 'Here is'. Max 40 words.\n\n"
                f"STATUS:\n{plain[:1800]}"
            )
            out = m.invoke(prompt)
            msg = _strip_decoration((getattr(out, "content", None) or str(out)).strip())
            if msg:
                return msg[:max_chars]
    except Exception:  # noqa: BLE001 — humanizing must never break a post
        pass
    fallback = plain.replace("\n", " — ")
    return (fallback[: max_chars - 1] + "…") if len(fallback) > max_chars else fallback


def post_digest(
    agent: str,
    title: str,
    body: str,
    *,
    channel: Optional[str] = None,
    thread_ts: Optional[str] = None,
    max_chars: int = 3000,
) -> Dict[str, Any]:
    """Post an agent digest to the appropriate Slack channel. FAIL-SAFE.

    Args:
        agent:     The agent slug (e.g. "daily_digest", "ceo", "qa_lead_aggregator").
        title:     Short headline for the message.
        body:      Markdown body (will be truncated to max_chars with a notice).
        channel:   Override channel (default: routing table + env var).
        thread_ts: Timestamp of an existing message to reply into (for threading).
        max_chars: Maximum body characters to post (Slack limit awareness).

    Returns a dict with at least {"status": "posted|report_only|no_credentials|error", ...}.
    NEVER raises.
    """
    try:
        bot_token = os.environ.get("SLACK_BOT_TOKEN", "").strip()
        webhook_url = os.environ.get("SLACK_WEBHOOK_URL", "").strip()

        if not bot_token and not webhook_url:
            return {"status": "no_credentials", "detail": "Set SLACK_BOT_TOKEN or SLACK_WEBHOOK_URL"}

        target_channel = channel or _channel_for(agent)
        emoji = _emoji_for(agent)
        # Human name from the roster (a label): "Morgan (CFO)" — falls back to the title-cased key.
        try:
            from agent_toolkit import payroll as _payroll
            _nm = (_payroll.load_roster().get("agents", {}).get(agent) or {}).get("name")
        except Exception:
            _nm = None
        _base = agent.replace("_", " ").title()
        display_name = f"{_nm} ({_base})" if _nm else _base

        # Human, concise, emoji-free message (not a raw digest dump).
        text = _humanize(agent, title, body)

        if bot_token:
            return _post_via_bot(bot_token, target_channel, text, display_name, emoji, thread_ts)
        else:
            return _post_via_webhook(webhook_url, text, display_name, emoji)

    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "detail": str(exc)[:300]}


def _post_via_bot(
    token: str, channel: str, text: str, username: str, icon_emoji: str,
    thread_ts: Optional[str],
) -> Dict[str, Any]:
    """Post via Slack Web API (chat.postMessage). Resolves channel name → ID automatically."""
    # Resolve channel name to ID (Slack API requires channel ID for postMessage)
    channel_id = _resolve_channel_id(token, channel)
    if not channel_id:
        # Channel doesn't exist yet; create it
        create_result = _create_channel(token, channel.lstrip("#"))
        if not create_result.get("ok"):
            return {"status": "error", "detail": f"channel_create failed: {create_result.get('error')}"}
        channel_id = create_result.get("channel", {}).get("id", "")

    payload: dict = {
        "channel": channel_id,
        "text": text,
        "username": username,
        "icon_emoji": icon_emoji,
        "unfurl_links": False,
        "unfurl_media": False,
    }
    if thread_ts:
        payload["thread_ts"] = thread_ts

    result = _post_json(
        "https://slack.com/api/chat.postMessage",
        payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    if result.get("ok"):
        return {"status": "posted", "channel": channel, "ts": result.get("ts")}
    return {"status": "error", "detail": result.get("error", "unknown")}


def _post_via_webhook(url: str, text: str, username: str, icon_emoji: str) -> Dict[str, Any]:
    """Post via Slack incoming webhook (single pre-configured channel)."""
    result = _post_json(url, {"text": text, "username": username, "icon_emoji": icon_emoji})
    if result.get("ok") or result.get("raw") == "ok":
        return {"status": "posted", "channel": "(webhook default)", "via": "webhook"}
    return {"status": "error", "detail": str(result)[:300]}


# ── Channel management (bot token only) ───────────────────────────────────────

def ensure_channels(token: Optional[str] = None) -> Dict[str, Any]:
    """Create all required agent channels that don't yet exist. Returns summary dict.

    Required bot scopes: channels:read, channels:write (or groups:read/write for private).
    Call once at setup time; idempotent.
    """
    token = token or os.environ.get("SLACK_BOT_TOKEN", "").strip()
    if not token:
        return {"status": "no_bot_token", "detail": "SLACK_BOT_TOKEN required for channel management"}

    # Collect unique target channels
    required = {channel for channel, _ in _ROUTING.values()} | {_DEFAULT_CHANNEL}
    required = {c.lstrip("#") for c in required}

    existing = _list_channel_names(token)
    results: dict[str, str] = {}
    for name in sorted(required):
        if name in existing:
            results[name] = "exists"
        else:
            r = _create_channel(token, name)
            results[name] = "created" if r.get("ok") else f"error: {r.get('error', '?')}"
    return {"status": "done", "channels": results}


def _list_channel_names(token: str) -> set[str]:
    result = _post_json(
        "https://slack.com/api/conversations.list",
        {"exclude_archived": True, "types": "public_channel", "limit": 200},
        headers={"Authorization": f"Bearer {token}"},
    )
    channels = result.get("channels") or []
    return {c["name"] for c in channels if isinstance(c, dict)}


def _resolve_channel_id(token: str, channel: str) -> str:
    name = channel.lstrip("#")
    result = _post_json(
        "https://slack.com/api/conversations.list",
        {"exclude_archived": True, "types": "public_channel,private_channel", "limit": 200},
        headers={"Authorization": f"Bearer {token}"},
    )
    for c in result.get("channels") or []:
        if isinstance(c, dict) and c.get("name") == name:
            return c.get("id", "")
    return ""


def _create_channel(token: str, name: str) -> dict:
    return _post_json(
        "https://slack.com/api/conversations.create",
        {"name": name, "is_private": False},
        headers={"Authorization": f"Bearer {token}"},
    )
