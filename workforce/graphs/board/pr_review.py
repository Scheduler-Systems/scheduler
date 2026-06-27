"""board_pr_review — the BOARD's PR-evaluation officer (decide on PRs, report-only).

This is the "agents delegate work to other agents" rung of the North Star applied to code
review: instead of every PR waiting on a human, the board EVALUATES it. The deciding is the
deterministic ``agent_toolkit.pr_eval.evaluate_pr`` (review verdict + blast radius + HARD-GATE
classification + a safe-to-automerge flag); THIS graph is the report-only wrapper that turns
that verdict into a durable PR review — and, only off probation, merges the provably-safe
class. It never merges to a production repo (``github_ops.merge_pr`` hard-blocks that anyway).

It is fired by the event receiver on ``pr_opened`` / ``pr_synchronize`` alongside the QA chain
(see ``agent_toolkit.event_routing``). The PR identity (``repo`` + ``number``) arrives in the
run input; a malformed/missing identity degrades to a terminal report (never a crash).

House style (the same seams as audit_risk_director / board_chair — the board template):
  * REPORT-ONLY on probation (the default): ``_report_only()`` is True unless ``OPS_REPORT_ONLY``
    is an explicit "0"/"false"/"no". Under report-only the verdict is DRAFTED (returned, and a
    record-comment would be posted to the PR via ``github_ops`` — a RECORD action that is allowed
    even on probation) and NOTHING is merged.
  * OFF report-only AND only for the ``safe_to_automerge`` class: the graph would squash-merge the
    PR via ``GitHubOps().merge_pr`` — which still hard-blocks production repos and routes through
    the allow-list + approval gates. A HARD-GATE PR is always HELD for a human, never merged here.
  * NEVER HANGS unattended: there is no reachable ``request_approval``/interrupt on the report-only
    path; ``comment_on_pr`` is a RECORD write (no merge gate) and merge only runs off probation.
  * FAIL-SAFE: ``evaluate_pr`` tolerates ``gh`` failures (→ UNKNOWN, never safe); the deliver node
    wraps the GitHub write so a token/network problem degrades to a report, never crashes.
  * SECRETS env-only; error strings are type-only. ML BOUNDARY: ``assert_not_model_work`` guards
    the target repo before any write.
  * CLOCK-IN first (``budget_gate``); ``governance_capture(..., {"report_only": True})`` terminal.
  * Compiles WITHOUT a checkpointer/store (the platform injects Postgres).
"""
from __future__ import annotations

import os

from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END

from agent_toolkit import (
    span,
    governance_capture,
    assert_not_model_work,
    check_clocked_in,
)
from agent_toolkit import pr_eval
from agent_toolkit.policy import ModelWorkBlocked

AGENT = "board_pr_review"


def _report_only() -> bool:
    """Report-only default: env ``OPS_REPORT_ONLY`` truthy/unset => True; '0'/'false'/'no' => False.

    On probation the board takes NO mutating action without a human gate, so the safe default is
    True. Only an explicit falsey value lets the safe-class auto-merge path run.
    """
    return os.environ.get("OPS_REPORT_ONLY", "").lower() not in ("0", "false", "no")


# --- State -------------------------------------------------------------------------------
class State(TypedDict, total=False):
    repo: str             # "Owner/repo" — the PR's repository (from the run input)
    number: int           # the PR number (from the run input)
    verdict: dict         # the full evaluate_pr() result
    decision: dict        # the action taken: drafted review and/or merge outcome
    report: dict          # terminal verdict
    report_only: bool


# =============================================================================
# Nodes
# =============================================================================
def budget_gate(state: State) -> dict:
    """CLOCK-IN gate — STOP before any work if over salary or globally disabled."""
    with span("board_pr_review.budget_gate"):
        if check_clocked_in(AGENT):
            return {}
        report = {
            "status": "skipped",
            "detail": f"{AGENT} over token salary or globally disabled",
            "report_only": True,
        }
        governance_capture(AGENT, {"clocked_in": False, "report_only": True, "report": report})
        return {"report": report, "report_only": True}


def evaluate(state: State) -> dict:
    """Evaluate the PR deterministically (no LLM, no merge). FAIL-SAFE.

    Reads ``repo`` + ``number`` from the run input and calls ``pr_eval.evaluate_pr``. A missing
    identity or any evaluation error degrades to an UNKNOWN/not-safe verdict so the run always
    completes with a structured report and never merges.
    """
    repo = (state.get("repo") or "").strip()
    number = state.get("number")

    with span("board_pr_review.evaluate", repo=repo, number=number):
        if not repo or number is None:
            verdict = _unknown_verdict(repo, number, "missing repo/number in run input")
            return {"verdict": verdict}
        try:
            verdict = pr_eval.evaluate_pr(repo, int(number))
        except Exception as exc:  # gh/parse/etc. — never crash the run
            verdict = _unknown_verdict(repo, number, f"evaluate_pr error: {type(exc).__name__}")
        return {"verdict": verdict}


def deliver(state: State) -> dict:
    """DRAFT the review (report-only) and — only off probation — merge the safe class. FAIL-SAFE.

    * Report-only (default): post a RECORD review comment on the PR via ``github_ops`` (allowed
      on probation — a comment is a durable record, not an irreversible code action) and merge
      NOTHING. The drafted verdict is returned regardless of whether the comment write succeeds.
    * Off report-only AND ``safe_to_automerge``: squash-merge via ``GitHubOps().merge_pr`` (which
      still hard-blocks production repos + routes the allow-list/approval gates). Any non-safe /
      HARD-GATE PR is HELD for a human — never merged here.
    """
    verdict = state.get("verdict") or {}
    repo = verdict.get("repo") or (state.get("repo") or "")
    number = verdict.get("pr")
    report_only = _report_only()

    with span("board_pr_review.deliver", report_only=report_only, safe=verdict.get("safe_to_automerge")):
        # ML boundary: never write into a model-dev repo.
        try:
            if repo:
                assert_not_model_work(repo)
        except ModelWorkBlocked:
            return {"decision": {"action": "blocked", "reason": "model-dev repo"},
                    "report_only": report_only}

        body = _review_comment_body(verdict, report_only)

        # Lazy import: github_ops is langgraph-free, but keep the import local so this node's
        # intent (a single guarded write) is self-contained and mockable.
        from agent_toolkit.github_ops import (
            GitHubOps,
            GitHubNotConfigured,
            GitHubWriteBlocked,
        )

        decision: dict = {"action": "drafted", "review_posted": None, "merged": None}

        # 1) DRAFT the review as a PR record-comment (report-only-safe). Fail-soft.
        if repo and number is not None:
            try:
                ops = GitHubOps()  # report_only resolved from env inside ops
                res = ops.comment_on_pr(repo, int(number), body)
                decision["review_posted"] = res.get("status") if isinstance(res, dict) else "done"
            except (GitHubNotConfigured, GitHubWriteBlocked, Exception) as exc:
                decision["review_posted"] = f"skipped:{type(exc).__name__}"

        # 2) Merge ONLY the safe class, and ONLY off report-only.
        if not report_only and verdict.get("safe_to_automerge") and repo and number is not None:
            try:
                ops = GitHubOps(report_only=False)
                res = ops.merge_pr(repo, int(number), method="squash")
                decision["action"] = "merged"
                decision["merged"] = res.get("merged") if isinstance(res, dict) else None
            except (GitHubNotConfigured, GitHubWriteBlocked, Exception) as exc:
                # A hard-block (prod repo) or rejection is the SAFE outcome — record and hold.
                decision["action"] = "held"
                decision["merged"] = f"blocked:{type(exc).__name__}"
        elif verdict.get("safe_to_automerge"):
            decision["action"] = "would-merge (report-only)"

        return {"decision": decision, "report_only": report_only}


def finalize(state: State) -> dict:
    """Terminal node — capture governance (report_only=True) and emit the final verdict."""
    verdict = state.get("verdict") or {}
    decision = state.get("decision") or {}
    prior = state.get("report") if isinstance(state.get("report"), dict) else {}

    with span("board_pr_review.finalize", action=decision.get("action")):
        report = prior or {
            "pr": verdict.get("pr"),
            "repo": verdict.get("repo"),
            "verdict": verdict.get("verdict"),
            "safe_to_automerge": verdict.get("safe_to_automerge"),
            "gate_reason": verdict.get("gate_reason"),
            "blast_radius": verdict.get("blast_radius"),
            "action": decision.get("action"),
            "review_posted": decision.get("review_posted"),
            "merged": decision.get("merged"),
            "report_only": True,
        }
        governance_capture(AGENT, {**report, "report_only": True})
        return {"report": report}


# =============================================================================
# Helpers (deterministic, no model)
# =============================================================================
def _unknown_verdict(repo, number, why: str) -> dict:
    """A not-safe UNKNOWN verdict shaped exactly like ``evaluate_pr`` output."""
    return {
        "pr": number,
        "repo": repo,
        "verdict": pr_eval.VERDICT_UNKNOWN,
        "safe_to_automerge": False,
        "gate_reason": f"not evaluated: {why}",
        "blast_radius": pr_eval.BLAST_MEDIUM,
        "summary": f"PR {repo}#{number}: not evaluated ({why})",
        "evidence": why,
    }


def _review_comment_body(verdict: dict, report_only: bool) -> str:
    """Render the board's PR review as a markdown comment body (deterministic)."""
    safe = verdict.get("safe_to_automerge")
    mode = "report-only (no merge)" if report_only else "active"
    head = "✅ SAFE to auto-merge" if safe else f"⛔ HELD — {verdict.get('gate_reason')}"
    return (
        "## 🤝 Board PR review (automated, report-only by construction)\n\n"
        f"**Decision:** {head}\n\n"
        f"- verdict: `{verdict.get('verdict')}`\n"
        f"- blast radius: `{verdict.get('blast_radius')}`\n"
        f"- mode: `{mode}`\n\n"
        f"```\n{verdict.get('summary', '')}\n\n{verdict.get('evidence', '')}\n```\n\n"
        "_This is a board agent's draft review. It does not merge HARD-GATE changes "
        "(prod deploy / customer / billing / security baseline / irreversible) — those are "
        "always held for a human._"
    )


# =============================================================================
# Routing
# =============================================================================
def _budget_route(state: State) -> str:
    return "evaluate" if check_clocked_in(AGENT) else "clocked_out"


# =============================================================================
# Graph wiring
# =============================================================================
builder = StateGraph(State)
builder.add_node("budget_gate", budget_gate)
builder.add_node("evaluate", evaluate)
builder.add_node("deliver", deliver)
builder.add_node("finalize", finalize)

builder.add_edge(START, "budget_gate")
builder.add_conditional_edges(
    "budget_gate",
    _budget_route,
    {"evaluate": "evaluate", "clocked_out": END},
)
builder.add_edge("evaluate", "deliver")
builder.add_edge("deliver", "finalize")
builder.add_edge("finalize", END)

graph = builder.compile()  # NO checkpointer/store — injected by the platform
