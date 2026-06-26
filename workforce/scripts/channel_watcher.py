"""Ambient channel watcher — the real "talk to your agents" bridge.

No @mention required: each channel has an owning agent that WATCHES it and answers ANY human
message in its lane (like a teammate who reads the channel), then replies in-thread as itself.

How it's the REAL agent, not a puppet: the answer is produced by the agent's OWN graph/tools —
the conversational CFO is the actual `cfo_deepagents` graph; the other roles answer grounded in
their real `gather()`/`analyze()` data (the exact functions the deployed fleet reports from) via
the real model router. Nothing is hand-written.

Mechanism: poll each channel with the OpenClaw bot token (conversations.history) — NO Socket-Mode
connection, so it never contends with OpenClaw's gateway. New human message → route to the owning
agent → run it → post the reply (chat.postMessage as OpenClaw, threaded). Tracks last-seen ts per
channel in a small state file so it only answers new messages. Stops on AGENTS_DISABLED.

Run from the worktree with the fleet .env + the OpenClaw bot token sourced. report-only.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request

# channel_id -> (channel_name, role-key). Role-key picks the responder.
CHANNELS = {
    "C0B8DHHEUSX": ("executive-updates", "ceo"),
    "C0B9E7L9DNU": ("engineering", "cto"),
    "C0B84EUCYNB": ("qa-reports", "qa"),
    "C0B84ERN2MD": ("marketing", "cmo"),
    "C0B8N4K5QRX": ("daily-ops", "coo"),
    "C09UQB90MHU": ("daily-operations", "coo"),
    "C0APBJGSLKA": ("infra-alerts", "cto"),
}
# Stamp each reply with the agent's identity (one OpenClaw bot posts for all; chat:write.customize
# for true per-agent names/avatars is a separate scope — this label works with zero extra scope).
# The six C-suite labels are fixed; every WORKER agent gets a label too (built from the roster at
# import time) so a worker's own reply is recognizable as an agent turn — without that, a worker's
# escalation reply would be mistaken for an unlabeled bot post and the escalation chain would die.
ROLE_LABEL = {
    "ceo": "Casey (CEO) 🧑‍💼", "cto": "Tobin (CTO) 🛠️", "qa": "Quinn (QA Lead) ✅",
    "cmo": "Marlowe (CMO) 📣", "coo": "Ollie (COO) ⚙️", "cfo": "Morgan (CFO) 💰",
}

_NAMES: dict = {}  # agent_key -> human display name (a label), loaded from roster.yaml below


def _worker_label(role: str) -> str:
    """A stable, unique Slack label for a worker agent: 'Wes (Web Automation Engineer) 👷'."""
    rt = role.replace('_', ' ').title()
    nm = _NAMES.get(role)
    return f"{nm} ({rt}) 👷" if nm else f"{rt} 👷"
POLL_SECONDS = int(os.environ.get("WATCHER_POLL_SECONDS", "12"))
STATE_FILE = os.environ.get("WATCHER_STATE", "/tmp/channel_watcher_state.json")
BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
BOT_USER = os.environ.get("SLACK_BOT_USER_ID", "U0AJQ0LARCP")  # OpenClaw

# --- collaboration: peers chime in on each other's lanes (governed + loop-capped) -------------
# route_collaboration is pure keyword logic (no model call); only the chosen agent's respond()
# costs a model call. Every agent→agent turn is gated through a2a_gate.gate_a2a (report-only).
#
# Load collaboration/a2a_gate BY PATH (not `from agent_toolkit import ...`). The package __init__
# pulls heavy ML deps (langchain_core) that are absent in the deps-free CI venv; importing via the
# package would raise there, the bare `except` would null these out, and the entire loop cap would be
# SILENTLY disabled (and untestable). Both modules are pure-python and have no heavy deps of their
# own, so a path load always succeeds — the loop-prevention is then live AND exercised by tests.
import importlib.util as _ilu


def _load_sibling(_mod_name: str):
    """Import a pure agent_toolkit module by file path, bypassing the heavy package __init__."""
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _path = os.path.join(_root, "agent_toolkit", f"{_mod_name}.py")
    _spec = _ilu.spec_from_file_location(_mod_name, _path)
    _m = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_m)
    return _m


try:
    _collab = _load_sibling("collaboration")
    _a2a = _load_sibling("a2a_gate")
    import yaml as _yaml
    _CAPS = _yaml.safe_load(open(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "docs", "governance", "capabilities.yaml")).read())
    # Load the org chart from roster.yaml and register a Slack label for every WORKER agent so the
    # watcher can recognize a worker's own reply as an agent turn (drives escalation up the chain).
    _ORG = _collab.load_org_chart()
    # Roster human names (a label) so worker posts read "Wes (Web Automation Engineer)" etc.
    try:
        _roster = _yaml.safe_load(open(os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "roster.yaml")).read())
        _NAMES.update({_k: _v.get("name") for _k, _v in (_roster.get("agents") or {}).items()
                       if isinstance(_v, dict) and _v.get("name")})
    except Exception:
        pass
    for _w in _ORG.all_workers():
        ROLE_LABEL.setdefault(_w, _worker_label(_w))
except Exception:  # pragma: no cover - degraded mode: human answers still work
    _collab = None
    _a2a = None
    _CAPS = {}
    _ORG = None

# Recover the posting role from an agent reply's "*ROLE LABEL*" prefix (these are OUR own posts, so
# an agent can tell its own past turns from a peer's and never trigger itself).
_LABEL_TO_ROLE = {label: role for role, label in ROLE_LABEL.items()}


def _role_from_agent_text(text: str) -> str | None:
    """If `text` is one of our labeled agent replies, return its role-key; else None (human/other)."""
    first = (text or "").lstrip().split("\n", 1)[0].strip()
    if first.startswith("*") and first.endswith("*"):
        return _LABEL_TO_ROLE.get(first.strip("*").strip())
    return None


def _slack(method: str, payload: dict) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"https://slack.com/api/{method}", data=data,
        headers={"Authorization": f"Bearer {BOT_TOKEN}", "Content-Type": "application/json; charset=utf-8"},
    )
    return json.load(urllib.request.urlopen(req, timeout=30))


def _slack_get(method: str, params: dict) -> dict:
    qs = "&".join(f"{k}={urllib.request.quote(str(v))}" for k, v in params.items())
    req = urllib.request.Request(
        f"https://slack.com/api/{method}?{qs}", headers={"Authorization": f"Bearer {BOT_TOKEN}"})
    return json.load(urllib.request.urlopen(req, timeout=30))


def _load_state() -> dict:
    try:
        return json.load(open(STATE_FILE))
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    try:
        json.dump(state, open(STATE_FILE, "w"))
    except Exception:
        pass


# --- thread-map maintenance: keep the loop-cap counter from being silently dropped --------------
# The per-thread agent-turn counter lives in `threads` (thread_ts -> count). It IS the loop cap: if a
# still-active thread's counter is evicted, route_collaboration is fed depth 0 and the thread can
# re-bounce a full MAX_DEPTH round and RE-page Shay. Two rules keep that from happening:
#   (1) _touch() re-inserts a key on every update so the map is genuinely LRU-ordered (plain
#       `threads[k] = v` does NOT move an existing key to the end in CPython — the hot thread would
#       otherwise keep its stale early position and be evicted FIRST).
#   (2) _trim_threads() evicts oldest-first but NEVER drops a key that still enforces the cap: any
#       LIVE counter (depth >= 1 — including a mid-chain thread paused below MAX_DEPTH) or any
#       `:escalated` guard. Those are pinned until a human message RESETS the thread to depth 0
#       (which un-pins it explicitly); a depth-0 entry is the only evictable thread state.
_THREADS_MAX = 4000      # start trimming past this many tracked keys
_THREADS_KEEP = 2500     # target size to trim down toward (evict the oldest evictable beyond this)


def _touch(threads: dict, key: str, value) -> None:
    """Set threads[key]=value AND move it to the most-recently-used end (real LRU ordering)."""
    threads.pop(key, None)
    threads[key] = value


def _is_pinned(threads: dict, key: str) -> bool:
    """A key that must not be evicted while its thread is still LIVE.

    Pin the `:escalated` guard, AND any depth counter >= 1. A live thread spends most of its life at
    an INTERMEDIATE depth (1..MAX_DEPTH-1), not at the cap: the deeper org chain (exec delegates
    down, worker escalates up) is up to MAX_DEPTH turns long, and a transient `a2a_gate` denial (a
    not-yet-granted manager↔report edge, a fail-closed HITL, a rate-limit) makes `_drive_collaboration`
    return early, leaving the thread live and unresolved BELOW the cap. If such a mid-chain counter is
    evicted, route_collaboration is fed depth 0 and the SAME live thread re-bounces a full round and
    RE-pages Shay — exceeding both invariants (<= MAX_DEPTH agent turns per thread; <= one page to the
    founder per thread). So pin EVERY non-zero counter; only depth 0 (a fresh human reset — see main())
    is evictable, which is the one safe moment to reclaim a thread."""
    if key.endswith(":escalated"):
        return True
    try:
        return int(threads.get(key, 0)) >= 1
    except (TypeError, ValueError):
        return False


def _trim_threads(threads: dict) -> None:
    """Bound the thread-map LRU-style, but NEVER evict a key that still enforces the loop cap.

    Evicts oldest-first (insertion order, kept LRU by _touch) down toward _THREADS_KEEP, skipping any
    pinned key (any LIVE counter at depth >= 1 — settled OR mid-chain — or an `:escalated` guard).
    This is the fix for the runaway: a still-live thread (whether capped or paused below the cap) can
    no longer have its counter/guard dropped while it is still inside the channel cursor window, so it
    cannot re-bounce from depth 0 or re-escalate to Shay.
    """
    if len(threads) <= _THREADS_MAX:
        return
    to_remove = len(threads) - _THREADS_KEEP
    for k in list(threads):           # oldest (least-recently-touched) first
        if to_remove <= 0:
            break
        if _is_pinned(threads, k):
            continue
        threads.pop(k, None)
        to_remove -= 1


# --- the agents answer, grounded in their real data --------------------------
def respond(role: str, text: str) -> str:
    """Produce the owning agent's real answer to `text`, grounded in its real data + persona."""
    try:
        return _grounded_answer(role, text)
    except Exception as exc:  # never let one bad turn wedge the watcher
        return f"(the {role} agent hit an error answering: {str(exc)[:120]})"


# C-suite personas (kept verbatim). Worker personas are derived from the roster role text at call
# time (see _persona_for), so every rostered agent — not just the six execs — answers in-character.
_PERSONA = {
    "ceo": "the CEO of Scheduler Systems — company-wide state, priorities, what needs the founder",
    "cto": "the CTO of Scheduler Systems — deploys, CI, security posture, incidents",
    "qa": "the QA Lead — shippability verdicts, coverage, test failures",
    "cmo": "the CMO — growth, ASO, RevenueCat conversion (currently dark: RC keys missing)",
    "coo": "the COO — fleet/ops health, blockers, what needs the founder",
}

# role-key -> the dotted module path of its graph (for gather()/analyze() grounding). The six execs
# plus the qa lead are explicit; worker entries are filled from langgraph.json at import (so a worker
# answers grounded in its OWN graph's data when that graph exposes gather/analyze).
_ROLE_MODULE = {
    "ceo": "graphs.exec.ceo", "cto": "graphs.exec.cto", "qa": "graphs.qa.qa_lead_aggregator",
    "cmo": "graphs.exec.cmo", "coo": "graphs.exec.coo",
}
try:  # map every deployed worker graph to its module, e.g. "web_automation_engineer".
    _LG = _yaml.safe_load(open(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "langgraph.json")).read())
    for _name, _spec in (_LG.get("graphs") or {}).items():
        # spec like "./graphs/qa/web_automation_engineer.py:graph" -> "graphs.qa.web_automation_engineer"
        _dotted = _spec.split(":", 1)[0].lstrip("./").rsplit(".py", 1)[0].replace("/", ".")
        _ROLE_MODULE.setdefault(_name, _dotted)
except Exception:  # pragma: no cover - grounding falls back to roster persona without it
    pass


# Roster role descriptions, read ONCE (agent role-key -> the roster "role:" text). A worker's
# persona is derived from this so every rostered agent answers in-character without re-reading the
# file on each turn. Empty if the roster is unreadable (persona then falls back to the bare role).
try:
    with open(_collab._roster_path()) as _rf:
        _ROSTER_ROLE_DESC = {
            _k: (_v or {}).get("role")
            for _k, _v in ((_yaml.safe_load(_rf.read()) or {}).get("agents") or {}).items()
        }
except Exception:  # pragma: no cover - persona falls back to the bare role-key without it
    _ROSTER_ROLE_DESC = {}


def _persona_for(role: str) -> str:
    """A persona string for ANY rostered agent: the C-suite verbatim, else the roster role text."""
    if role in _PERSONA:
        return _PERSONA[role]
    desc = _ROSTER_ROLE_DESC.get(role)
    if desc:
        return f"the {role.replace('_', ' ')} agent — {desc}"
    return f"the {role.replace('_', ' ')} agent (report-only)"


def _fleet_status() -> str:
    """Compact roster summary so any agent can answer who's-on-shift / staffing questions honestly."""
    if not _NAMES:
        return ""
    return (f"{len(_NAMES)} agent employees on the roster (all report-only / probation): "
            + ", ".join(_NAMES[a] for a in sorted(_NAMES)))


def _grounded_answer(role: str, text: str) -> str:
    """A real grounded answer for ANY rostered agent: pull the agent's OWN live context (its graph's
    gather()/analyze() when present), answer with the real model router, persona from _persona_for."""
    from agent_toolkit import get_model, TIER_DEFAULT
    context = ""
    try:
        mod = _ROLE_MODULE.get(role) or (_collab.ROLE_TO_GRAPH.get(role) if _collab else None)
        if mod and "." in mod:
            m = __import__(mod, fromlist=["gather", "analyze"])
            if hasattr(m, "gather"):
                g = m.gather({})
                context = json.dumps(m.analyze(g) if hasattr(m, "analyze") else g, default=str)[:3000]
    except Exception:
        context = ""
    # Roster/staffing questions ("who's working?") need the fleet roster — wire it in on demand.
    if any(w in text.lower() for w in ("who", "shift", "working", "staff", "team", "active", "roster", "on duty", "headcount")):
        _fs = _fleet_status()
        if _fs:
            context = (context + "\n\n" + _fs) if context else _fs
    sys = (f"You are {_persona_for(role)}, chatting with your team in Slack. RESPOND TO WHAT THEY "
           f"ACTUALLY SAID, naturally, like a colleague: if they greet you, greet back and offer "
           f"help; if they ask a question (e.g. 'who's working?'), ANSWER IT directly from your "
           f"context; do NOT dump an unsolicited status report. Concise (1-3 sentences), plain "
           f"language, no preamble. If you lack the data, say so honestly. You are report-only — you "
           f"propose, you never act.\n\nYour real data (use only if it's relevant to their message): "
           f"{context or '(none available right now)'}")
    model = get_model(TIER_DEFAULT)
    resp = model.invoke([{"role": "system", "content": sys}, {"role": "user", "content": text}])
    return getattr(resp, "content", str(resp)) or "(no answer)"


def _post_labeled(cid: str, thread_ts: str, role: str, body: str) -> None:
    labeled = f"*{ROLE_LABEL.get(role, role.upper())}*\n{body}"
    _slack("chat.postMessage", {"channel": cid, "thread_ts": thread_ts,
                                "reply_broadcast": True, "text": labeled})


def _collaborate(cid: str, name: str, thread_ts: str, text: str, from_role: str,
                 thread_state: dict) -> None:
    """One peer-collaboration step on a thread: route → gate (report-only) → reply, loop-capped.

    `thread_state` maps thread_ts -> count of AGENT turns already taken on that thread. A human
    message resets it to 0 (done by the caller); each agent auto-reply increments it; at MAX_DEPTH
    we stop and post ONE escalation line instead of continuing. Pure routing is free; only the
    chosen peer's respond() costs a model call.
    """
    if _collab is None:
        return
    depth = int(thread_state.get(thread_ts, 0))
    target, reason = _collab.route_collaboration(text, from_role=from_role, channel=name,
                                                 thread_depth=depth)
    if target is None:
        # A capped-but-unresolved thread gets exactly ONE escalation line, never an endless loop.
        if reason == "settled" and not thread_state.get(f"{thread_ts}:escalated"):
            _touch(thread_state, f"{thread_ts}:escalated", True)
            _post_labeled(cid, thread_ts, from_role or "coo",
                          "Thread unresolved after the team went back and forth — escalating to Shay.")
            print(f"[{name}] thread {thread_ts} settled → escalated to Shay")
        return

    # Gate the agent→agent turn through the A2A governance gate (report-only). Drop if not allowed.
    src_graph = _collab.ROLE_TO_GRAPH.get(from_role, from_role)
    tgt_graph = _collab.ROLE_TO_GRAPH.get(target, target)
    if _a2a is not None:
        try:
            verdict = _a2a.gate_a2a(src_graph, tgt_graph, text, capabilities=_CAPS, report_only=True)
            if not verdict.get("allowed"):
                print(f"[{name}] collab {from_role}->{target} DENIED by gate: {verdict.get('reason')}")
                return
        except Exception as exc:
            print(f"[{name}] collab gate error {from_role}->{target}: {str(exc)[:80]}")
            return

    # Count this agent turn BEFORE posting so a crash can't let the thread exceed the cap. _touch
    # keeps this active thread at the most-recently-used end so the trim can't evict its live counter.
    _touch(thread_state, thread_ts, depth + 1)
    print(f"[{name}] collab {reason} (depth {depth}->{depth + 1})")
    answer = respond(target, text)
    _post_labeled(cid, thread_ts, target, answer)


def _drive_collaboration(cid: str, name: str, thread_ts: str, seed_text: str, seed_role: str,
                         threads: dict) -> None:
    """Drive a bounded A→B→A peer chain on one thread, synchronously, until it settles.

    Each iteration routes the latest turn to a DIFFERENT peer, gates it (report-only), posts the
    peer's reply, and increments the thread's agent-turn count. The loop is shut three ways: the
    depth cap inside route_collaboration (>=MAX_DEPTH → settled), the same cap re-checked here, and
    a hard iteration ceiling as a backstop. An agent never routes to its own lane (router rule).
    """
    if _collab is None:
        return
    cur_role, cur_text = seed_role, seed_text
    # Hard backstop: even if routing logic regressed, this can never exceed MAX_DEPTH+1 iterations.
    for _ in range(_collab.MAX_DEPTH + 1):
        depth = int(threads.get(thread_ts, 0))
        target, _reason = _collab.route_collaboration(cur_text, from_role=cur_role,
                                                      channel=name, thread_depth=depth)
        before = depth
        # _collaborate routes again, gates, posts the peer's reply (or, at the cap, one escalation).
        _collaborate(cid, name, thread_ts, cur_text, cur_role, threads)
        if target is None:
            return  # settled / off-lane / self — chain ends (escalation, if any, already emitted)
        if int(threads.get(thread_ts, 0)) <= before:
            return  # gate dropped the turn — nothing posted, so the chain ends here
        # The peer just spoke; its reply seeds the next turn (A→B→A…), still capped by depth.
        cur_role = target  # the topic persists down the thread; depth is what terminates it


def main():
    if not BOT_TOKEN:
        print("missing SLACK_BOT_TOKEN"); return
    state = _load_state()
    # On first run, mark "now" as the baseline so we only answer messages from here on.
    now_ts = str(time.time())
    for cid in CHANNELS:
        state.setdefault(cid, now_ts)
    threads = state.setdefault("_threads", {})   # thread_ts -> agent-turn count (loop cap)
    answered = state.setdefault("_answered", {})  # ts -> 1 (dedup: never answer a message twice)
    active = state.setdefault("_active_threads", {})  # "cid|thread_ts" -> ts: poll its REPLIES too,
    #   because a follow-up posted INSIDE a thread never appears in conversations.history (top-level),
    #   so a conversation would die after one turn unless we also watch the thread's replies.
    _save_state(state)
    print(f"WATCHER UP — {len(CHANNELS)} channels, every {POLL_SECONDS}s, ambient (no @mention), "
          f"collaboration ON (cap {_collab.MAX_DEPTH if _collab else 'n/a'}), report-only.")
    while True:
        if os.environ.get("AGENTS_DISABLED"):
            print("AGENTS_DISABLED — watcher stopping."); break
        for cid, (name, role) in CHANNELS.items():
            try:
                res = _slack_get("conversations.history", {"channel": cid, "oldest": state.get(cid, now_ts), "limit": 20})
                msgs = sorted(res.get("messages", []), key=lambda m: float(m.get("ts", 0)))
                for m in msgs:
                    ts = m.get("ts", "0")
                    if float(ts) <= float(state.get(cid, now_ts)):
                        continue
                    state[cid] = ts
                    if answered.get(ts):           # dedup: never answer the same message twice
                        continue
                    if m.get("subtype"):           # skip channel-join/system messages
                        continue
                    text = (m.get("text") or "").strip()
                    if not text:
                        continue
                    thread_ts = m.get("thread_ts") or ts

                    # Is this one of OUR own labeled agent posts? If so it's a peer turn for
                    # collaboration — never a human message to answer, and an agent never triggers
                    # itself (route_collaboration rule 4).
                    agent_role = _role_from_agent_text(text) if (
                        m.get("bot_id") or m.get("user") == BOT_USER) else None

                    if agent_role is not None:
                        # An agent spoke. Let a DIFFERENT peer chime in (loop-capped + gated).
                        answered[ts] = 1
                        _drive_collaboration(cid, name, thread_ts, text, agent_role, threads)
                    elif m.get("bot_id") or m.get("user") == BOT_USER:
                        # Some other bot / unlabeled bot post — ignore (not a human, not our agent).
                        continue
                    else:
                        # A real human message: the owning agent answers (existing behavior), and a
                        # human message RESETS/starts this thread at depth 0. The reset (depth 0, no
                        # `:escalated` guard) deliberately UN-pins the thread — a fresh human turn is
                        # the one moment it's safe to let the trim reclaim it later. _touch keeps the
                        # reset thread at the most-recently-used end.
                        answered[ts] = 1
                        threads.pop(f"{thread_ts}:escalated", None)
                        _touch(threads, thread_ts, 0)
                        active[f"{cid}|{thread_ts}"] = ts   # watch this thread's replies for follow-ups
                        print(f"[{name}] {role} answering: {text[:60]}")
                        answer = respond(role, text)
                        _post_labeled(cid, thread_ts, role, answer)
                        # …then peers collaborate on what the human raised (bounded A→B→A chain).
                        _drive_collaboration(cid, name, thread_ts, text, role, threads)

                # Poll the REPLIES of this channel's active threads: a follow-up posted inside a thread
                # never shows in conversations.history, so without this a conversation dies after turn 1.
                for _akey in [k for k in active if k.startswith(f"{cid}|")]:
                    _tts = _akey.split("|", 1)[1]
                    try:
                        _rr = _slack_get("conversations.replies", {"channel": cid, "ts": _tts, "limit": 30})
                    except Exception:
                        continue
                    for _rm in sorted(_rr.get("messages", []), key=lambda x: float(x.get("ts", 0))):
                        _rts = _rm.get("ts", "0")
                        if _rts == _tts or answered.get(_rts) or _rm.get("subtype"):
                            continue
                        _rtext = (_rm.get("text") or "").strip()
                        if not _rtext:
                            continue
                        _is_bot = bool(_rm.get("bot_id") or _rm.get("user") == BOT_USER)
                        _ar = _role_from_agent_text(_rtext) if _is_bot else None
                        if _ar is not None:                       # a peer agent replied → collaborate
                            answered[_rts] = 1
                            _drive_collaboration(cid, name, _tts, _rtext, _ar, threads)
                        elif _is_bot:
                            continue
                        else:                                     # a HUMAN follow-up in the thread → answer it
                            answered[_rts] = 1
                            active[_akey] = _rts
                            print(f"[{name}] {role} answering (thread reply): {_rtext[:60]}")
                            _post_labeled(cid, _tts, role, respond(role, _rtext))
                            _drive_collaboration(cid, name, _tts, _rtext, role, threads)
                _save_state(state)
            except Exception as exc:
                print(f"[{name}] poll error: {str(exc)[:100]}")
        # Bound the dedup/thread maps so a long-lived watcher doesn't grow without limit. The
        # `answered` trim is harmless (the per-channel cursor blocks re-fetch); the `threads` trim
        # MUST preserve any key still enforcing the loop cap — _trim_threads does (see its docstring).
        if len(answered) > 5000:
            for k in list(answered)[:-2000]:
                answered.pop(k, None)
        if len(active) > 400:                 # stop polling long-dead threads (keep the most recent)
            for k in list(active)[:-150]:
                active.pop(k, None)
        _trim_threads(threads)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
