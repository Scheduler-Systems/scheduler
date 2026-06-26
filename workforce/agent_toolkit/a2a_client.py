"""A2A client — talk to a deployed agent over LangSmith's native A2A (proven live 2026-06-06).

The runtime primitive for the agent communication fabric: agents (and the human-bridge) message
a deployed agent via `POST {DEPLOYMENT_URL}/a2a/{assistant_uuid}` (JSON-RPC `message/send`), and a
whole conversation maps to ONE LangSmith thread (A2A `contextId` == `thread_id`).

Three footguns the probe surfaced, encoded here:
  * the path needs the assistant **UUID**, not the graph name (resolve via assistants.search);
  * `contextId` goes INSIDE `params.message`, not `params.contextId` (else a fresh thread);
  * auth needs BOTH `x-api-key` AND `X-Tenant-Id` (missing tenant → 403 Forbidden);
  * conversational A2A only works for graphs with a `messages` input field (today: cfo_deepagents).
    Structured graphs use the `/runs` command path instead (see `fire_run`).

Reads LANGGRAPH_DEPLOYMENT_URL / LANGSMITH_API_KEY / LANGSMITH_TENANT_ID from env (source the
fleet `.env` for execution; never log the values). Uses httpx; langgraph_sdk for UUID resolution.
"""
from __future__ import annotations

import os
import uuid as _uuid
from typing import Any

import httpx

_ASSISTANT_CACHE: dict[str, str] = {}  # graph_id -> assistant_id (UUID), per process


def _conf() -> tuple[str, dict[str, str]]:
    url = (os.environ.get("LANGGRAPH_DEPLOYMENT_URL") or os.environ.get("LANGSMITH_DEPLOYMENT_URL") or "").rstrip("/")
    key = os.environ.get("LANGSMITH_API_KEY") or os.environ.get("LANGCHAIN_API_KEY") or ""
    tenant = os.environ.get("LANGSMITH_TENANT_ID") or ""
    if not (url and key and tenant):
        raise RuntimeError("A2A needs LANGGRAPH_DEPLOYMENT_URL, LANGSMITH_API_KEY, LANGSMITH_TENANT_ID in env")
    headers = {"x-api-key": key, "X-Tenant-Id": tenant, "Content-Type": "application/json"}
    return url, headers


async def resolve_assistant_uuid(graph_name: str) -> str:
    """Resolve a graph name (e.g. 'cfo_deepagents') to its deployed assistant UUID.

    UUIDs are deterministic per deployment but re-resolve after each redeploy — never hardcode.
    """
    if graph_name in _ASSISTANT_CACHE:
        return _ASSISTANT_CACHE[graph_name]
    try:
        _uuid.UUID(graph_name)
        return graph_name  # already a UUID
    except ValueError:
        pass
    from langgraph_sdk import get_client

    url, _ = _conf()
    client = get_client(url=url, api_key=os.environ.get("LANGSMITH_API_KEY"),
                        headers={"X-Tenant-Id": os.environ.get("LANGSMITH_TENANT_ID", "")})
    for a in await client.assistants.search(limit=100):
        gid, aid = a.get("graph_id"), a.get("assistant_id")
        if gid and aid:
            _ASSISTANT_CACHE[gid] = aid
    if graph_name not in _ASSISTANT_CACHE:
        raise RuntimeError(f"no deployed assistant for graph '{graph_name}'")
    return _ASSISTANT_CACHE[graph_name]


async def a2a_send(target_graph: str, text: str, *, context_id: str | None = None,
                   timeout: float = 120.0) -> dict[str, Any]:
    """Send an A2A conversational message to a deployed agent; returns the JSON-RPC result (the Task).

    `context_id` ties turns into one conversation/thread — pass the same value across a dialogue
    (e.g. derived from a Slack thread ts). Raises on a non-conversational graph (use `fire_run`).
    """
    url, headers = _conf()
    assistant = await resolve_assistant_uuid(target_graph)
    message: dict[str, Any] = {
        "role": "user",
        "parts": [{"kind": "text", "text": text}],
        "messageId": str(_uuid.uuid4()),  # per the A2A spec
    }
    if context_id:
        message["contextId"] = context_id  # MUST be inside the message, not params.contextId (spec)
    payload = {"jsonrpc": "2.0", "id": str(_uuid.uuid4()), "method": "message/send",
               "params": {"message": message}}
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(f"{url}/a2a/{assistant}", headers=headers, json=payload)
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"A2A error {data['error'].get('code')}: {data['error'].get('message')}")
    return data.get("result", data)


def a2a_text(result: dict[str, Any]) -> str:
    """Extract the agent's reply text from an A2A Task result (best-effort)."""
    arts = result.get("artifacts") or []
    for art in arts:
        for part in art.get("parts") or []:
            if part.get("kind") == "text" or part.get("type") == "text":
                if part.get("text"):
                    return part["text"]
    # fall back to the last assistant message in history
    for msg in reversed(result.get("history") or []):
        for part in msg.get("parts") or []:
            if part.get("kind") == "text" or part.get("type") == "text":
                if part.get("text"):
                    return part["text"]
    return ""


async def fire_run(target_graph: str, agent_input: dict[str, Any] | None = None,
                   *, wait: bool = False, thread_id: str | None = None) -> dict[str, Any]:
    """Command path for STRUCTURED graphs (no `messages` schema): create a run via the SDK.

    This is the proven /runs path the shift dispatch uses; for the 27 non-conversational agents
    until they adopt a `messages` input field.

    Thread continuity (the whole point of the event-driven receiver): in the LangGraph SDK a run
    is threaded ONLY by the FIRST POSITIONAL arg of ``runs.create``/``runs.wait`` (``thread_id``).
    A key named "thread_id" inside ``input`` is just opaque graph state and does NOT thread the
    run. So when a deterministic ``thread_id`` is given we ENSURE that thread exists (idempotently,
    ``if_exists="do_nothing"`` so a PR's repeated pushes reuse the SAME thread instead of erroring)
    and pass it POSITIONALLY — that is what makes a PR's repeated QA runs append to one thread.
    Passing ``None`` (the default, used by threadless callers like shift dispatch) creates a fresh
    stateless run as before.
    """
    from langgraph_sdk import get_client

    url, _ = _conf()
    client = get_client(url=url, api_key=os.environ.get("LANGSMITH_API_KEY"),
                        headers={"X-Tenant-Id": os.environ.get("LANGSMITH_TENANT_ID", "")})
    inp = agent_input or {"event": "shift_start"}
    if thread_id:
        # Idempotently ensure the deterministic thread exists before threading a run onto it.
        # if_exists="do_nothing" makes a later push for the same PR reuse the thread (no 409).
        await client.threads.create(thread_id=thread_id, if_exists="do_nothing")
    if wait:
        return await client.runs.wait(thread_id, target_graph, input=inp)
    return await client.runs.create(thread_id, target_graph, input=inp)
