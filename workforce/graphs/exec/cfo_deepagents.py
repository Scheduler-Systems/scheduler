"""CFO role on the LangChain **Deep Agents** runtime — bake-off twin of ``graphs/exec/cfo.py``.

Same DATA (payroll / revenuecat / qa-shift reads via the existing ``cfo`` pure functions) and
the same OUTBOUND SEAM (``file_digest_issue`` — GitHub write gated by ``OPS_REPORT_ONLY``, Slack
delivered), but a different HARNESS: a deepagents planning loop instead of a hand-wired
StateGraph. This isolates the "agent harness" variable while holding hosting (same LangSmith
deployment), models (same router), report-only posture, and delivery constant.

Safety parity with the LangGraph CFO:
  * KILL-SWITCH — every tool short-circuits when ``check_clocked_in('cfo')`` is False
    (AGENTS_DISABLED / FLEET_DISABLED / over-budget): no reads, no model-loop side effects, no post.
  * REPORT-ONLY — delivery routes through ``file_digest_issue(report_only=_report_only())``,
    identical to the LangGraph twin, so probation never writes to GitHub.
  * INJECTION — the model-authored line is sanitized centrally in ``slack_tool`` (mass-mentions
    stripped) before it reaches Slack.
Tagged ``runtime=deepagents`` for the scorecard.
"""
from __future__ import annotations

import json

from langchain_core.tools import tool

from agent_toolkit import get_model, TIER_DEFAULT, check_clocked_in, file_digest_issue
from agent_toolkit.learning_loop import get_prompt
from graphs.exec.cfo import gather as _gather, analyze as _analyze, propose as _propose, DIGEST_REPO, _report_only

_RUNTIME = "deepagents"
_AGENT = "cfo"
# Prompt Hub identifier for this agent's system prompt (pushed by
# scripts/langsmith_setup.push_agent_prompts). Pulled at build time via get_prompt;
# the embedded _SYSTEM below stays the fail-safe fallback so the graph NEVER breaks.
_PROMPT_NAME = "scheduler-qa-cfo"
_CLOCKED_OUT = "clocked out (AGENTS_DISABLED / FLEET_DISABLED / over budget) — no action taken"


@tool
def get_financial_picture() -> str:
    """Read the fleet's current spend, revenue and financial analysis (read-only). Returns JSON."""
    if not check_clocked_in(_AGENT):
        return _CLOCKED_OUT
    g = _gather({})
    a = _analyze(g)
    return json.dumps({"revenue": g.get("revenue"), "analysis": a.get("analysis")}, default=str)[:4000]


@tool
def get_budget_proposal() -> str:
    """Read the deterministic, propose-only budget allocation across the roster (no money moved)."""
    if not check_clocked_in(_AGENT):
        return _CLOCKED_OUT
    g = _gather({})
    a = _analyze(g)
    p = _propose({**g, **a})
    return json.dumps(p.get("proposals") or [], default=str)[:4000]


@tool
def post_cfo_update(message: str) -> str:
    """Deliver the CFO's ONE short human update through the SAME seam as the LangGraph CFO.

    GitHub issue is gated by OPS_REPORT_ONLY (probation = a plan, no write); Slack is delivered
    (and sanitized) by slack_tool. Honors the kill-switch. Returns the delivery status.
    """
    if not check_clocked_in(_AGENT):
        return _CLOCKED_OUT
    res = file_digest_issue(
        DIGEST_REPO,
        "CFO: spend + budget allocation (proposal)",
        message,
        labels=["exec:cfo"],
        report_only=_report_only(),
        agent=_AGENT,
        slack_title="CFO update (Deep Agents runtime)",
    )
    return str(res.get("status", "unknown")) if isinstance(res, dict) else "unknown"


_SYSTEM = (
    "You are the CFO of Scheduler Systems, a company run by deployed software agents (each an "
    "'employee' with a token-budget salary). You are on PROBATION and strictly REPORT-ONLY: you "
    "propose, you never move money.\n\n"
    "You work in two modes — decide which from the message you receive:\n\n"
    "(1) ANSWER A QUESTION — if someone (Shay, or another agent) asks you something, ANSWER IT "
    "DIRECTLY and accurately. First call get_financial_picture and/or get_budget_proposal to get "
    "the real numbers, then reply in plain language with the SPECIFIC figures that answer their "
    "question (e.g. actual spend vs salary, burn, the anomaly). Be concise (1–3 sentences), no "
    "emoji, no markdown, no preamble. Do NOT call post_cfo_update when answering — just reply with "
    "the answer. If a tool reports 'clocked out', say that briefly and stop.\n\n"
    "(2) SHIFT UPDATE — if there is no question (a scheduled shift trigger / 'shift_start'), call "
    "get_financial_picture and get_budget_proposal, then post EXACTLY ONE short plain update via "
    "post_cfo_update — what spend looks like, any anomaly, and the one thing (if any) that needs "
    "Shay's decision. Two sentences max. Then stop.\n\n"
    "Never move money. If a tool reports 'clocked out', stop immediately."
)


def _build():
    """Compile the Deep Agent as a graph (the same CompiledStateGraph type the fleet deploys)."""
    from deepagents import create_deep_agent

    # Pull the centrally-governed prompt from the Prompt Hub; fall back to the embedded
    # _SYSTEM on ANY failure (no creds / not found / offline), so the build never breaks.
    system_prompt = get_prompt(_PROMPT_NAME, fallback=_SYSTEM)
    return create_deep_agent(
        model=get_model(TIER_DEFAULT),
        tools=[get_financial_picture, get_budget_proposal, post_cfo_update],
        system_prompt=system_prompt,
    )


graph = _build()
