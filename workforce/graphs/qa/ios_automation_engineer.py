"""ios_automation_engineer — XCTest automation for scheduler-ios (macOS runner).

What this worker does (orchestration ONLY — no heavy execution in the agent):
  1. DISPATCH the iOS test suite to a macOS GitHub Actions runner via
     dispatch_github_workflow (gate.yml runs `swift test` on macos-14). The agent
     NEVER builds, runs `swift test`, or boots a simulator in its own container.
  2. SUMMARIZE the outcome with the model (TIER_DEFAULT), degrading gracefully against
     the incomplete scheduler-ios app (SPM project, ~13/31 screens, no Xcode app target
     yet — a non-dispatch or failure is expected and must NOT crash the worker).
  3. Build a shippability VERDICT + report.
  4. REPORT-ONLY: gate the PR comment behind request_approval. Do NOT write to GitHub
     here — the actual comment is only issued after an explicit human 'approve'.

Maps audit spec: ios-xctest-qa-orchestrator. Runtime: Stratus Mac node.

Recon (scheduler-ios):
  - repo: Scheduler-Systems/scheduler-ios  (SPM, iOS 17+/macOS 14+)
  - test command: `swift test`  (Makefile `make test`)
  - CI: .github/workflows/gate.yml on macos-14 (Xcode 16.2), `swift test` at the test step
  - tests: Tests/SchedulerAppTests/ (~2.3k LOC across 6 files)
"""
import os

from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END

from agent_toolkit import (
    get_model,
    request_approval,
    is_approved,
    span,
    governance_capture,
    dispatch_github_workflow,
    assert_not_model_work,
    check_clocked_in,
    budget_guard,
    TIER_DEFAULT,
)

try:  # works whether loaded as a package module or by file path (LangGraph platform)
    from .observe import is_observe_mode, read_local_repo_recon, render_recon
except ImportError:  # pragma: no cover - path-based load fallback
    import sys

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from observe import is_observe_mode, read_local_repo_recon, render_recon

AGENT = "ios_automation_engineer"
REPO = "Scheduler-Systems/scheduler-ios"
WORKFLOW = "gate.yml"
# Local checkout path (read-only) used by OBSERVE mode.
LOCAL_REPO_DIR = "scheduler-ios"


class State(TypedDict, total=False):
    mode: str            # "observe" -> read-only learning pass (no dispatch, no writes)
    observations: str    # OBSERVE-mode learning summary (read-only)
    repo: str            # target repo (default: scheduler-ios)
    ref: str             # git ref / PR head branch to test (default: main)
    pr: int              # PR number to comment on (optional; gates the comment)
    dispatched: bool     # did the CI dispatch succeed
    dispatch_error: str  # why dispatch failed (graceful degradation)
    summary: str         # model-written summary of the run
    verdict: str         # PASS | FAIL | DEGRADED
    report: str          # full report body (the candidate PR comment)
    approved: bool       # human decision on the PR comment
    result: str          # terminal outcome string


def observe(state: State) -> dict:
    """OBSERVE / learning mode — READ-ONLY. No CI dispatch, no proposed writes.

    Reads scheduler-ios's local test setup (SPM/XCTest) + recent git history (read-only)
    and asks the model to produce an `observations` learning summary of how iOS QA works
    and where it looks fragile. Report-only: no approval gate.
    """
    repo = state.get("repo") or REPO
    ref = state.get("ref") or "main"
    assert_not_model_work(repo)
    with span(f"{AGENT}.observe", repo=repo, ref=ref, mode="observe"):
        facts = read_local_repo_recon(LOCAL_REPO_DIR)
        recon = render_recon(facts)
        observations = ""
        try:
            model = budget_guard(AGENT, TIER_DEFAULT)
            prompt = (
                "You are an iOS QA automation engineer in LEARNING/OBSERVE mode for "
                "scheduler-ios (SwiftUI, SPM project, ~13/31 screens, no Xcode app target yet). "
                "You are NOT running or dispatching `swift test`; you are only studying the repo "
                "to understand how its QA works.\n"
                "From the READ-ONLY local recon below (Package.swift / Makefile / Fastfile test "
                "setup and recent git history), write an 'observations' learning summary:\n"
                "1) How iOS QA is structured (`swift test`, test targets, CI gate.yml on "
                "macos-14).\n"
                "2) Where it looks FRAGILE/incomplete (missing Xcode app target, missing "
                "screens, thin coverage, simulator/runner risk, churny areas in recent commits).\n"
                "3) What you would watch when you later run the real gate.\n"
                "Be concrete and cite filenames. Do not invent test counts.\n\n"
                f"{recon}"
            )
            resp = model.invoke(prompt)
            observations = getattr(resp, "content", str(resp)) or ""
        except Exception as exc:  # model unavailable — still report deterministic recon
            observations = (
                f"(model observe summary unavailable: {exc})\n\n"
                f"Read-only recon of {repo}:\n{recon}"
            )

        report = (
            f"## iOS automation ({AGENT}) — OBSERVE (read-only learning)\n\n"
            f"- **Target:** `{repo}@{ref}`\n"
            f"- **Test-setup files:** {facts.get('test_setup_files') or []}\n"
            "- No CI dispatched, no writes proposed.\n\n"
            f"{observations}\n"
        )
        governance_capture(
            AGENT,
            {
                "mode": "observe",
                "repo": repo,
                "ref": ref,
                "test_setup_files": facts.get("test_setup_files") or [],
                "dispatched": False,
                "report_only": True,
            },
        )
        return {"observations": observations, "report": report, "verdict": "OBSERVE", "result": report}


def dispatch(state: State) -> dict:
    """Gate the target, then dispatch XCTest to the macOS runner. Never run tests here."""
    repo = state.get("repo") or REPO
    ref = state.get("ref") or "main"
    # Anthropic-terms guard: must skip gal-model / eval-worker targets.
    assert_not_model_work(repo)
    assert_not_model_work(WORKFLOW)
    with span(f"{AGENT}.dispatch", repo=repo, ref=ref, workflow=WORKFLOW):
        try:
            ok = dispatch_github_workflow(
                repo=repo,
                workflow=WORKFLOW,
                ref=ref,
                inputs={"suite": "swift-test", "requested_by": AGENT},
            )
            if ok:
                return {"repo": repo, "ref": ref, "dispatched": True}
            return {
                "repo": repo,
                "ref": ref,
                "dispatched": False,
                "dispatch_error": "workflow_dispatch did not return HTTP 204",
            }
        except Exception as exc:  # degrade gracefully — incomplete app / missing token
            return {
                "repo": repo,
                "ref": ref,
                "dispatched": False,
                "dispatch_error": str(exc),
            }


def summarize(state: State) -> dict:
    """Summarize the dispatch outcome with the model and assign a verdict.

    scheduler-ios is incomplete (SPM, ~13/31 screens, no Xcode app target). A failed or
    skipped dispatch is DEGRADED, not a crash — keep the worker resilient.
    """
    repo = state.get("repo") or REPO
    ref = state.get("ref") or "main"
    dispatched = state.get("dispatched", False)
    dispatch_error = state.get("dispatch_error", "")

    if dispatched:
        verdict = "DISPATCHED"
        facts = (
            f"Dispatched `swift test` (gate.yml) on a macOS runner for {repo}@{ref}. "
            "Results land in GitHub Actions; this worker orchestrates and does not run "
            "the suite itself."
        )
    else:
        verdict = "DEGRADED"
        facts = (
            f"Could NOT dispatch the iOS test suite for {repo}@{ref}: "
            f"{dispatch_error or 'unknown reason'}. scheduler-ios is an incomplete SPM "
            "project (no Xcode app target yet), so degraded runs are expected — reported, "
            "not failed."
        )

    with span(f"{AGENT}.summarize", repo=repo, verdict=verdict, dispatched=dispatched):
        summary = facts
        try:
            model = budget_guard(AGENT, TIER_DEFAULT)
            prompt = (
                "You are an iOS QA automation engineer. In 2-3 sentences, write a neutral, "
                "factual status update for a PR comment from these facts. Do not invent test "
                "counts or pass/fail numbers you were not given.\n\n"
                f"Repo: {repo}\nRef: {ref}\nVerdict: {verdict}\nFacts: {facts}"
            )
            resp = model.invoke(prompt)
            text = getattr(resp, "content", None)
            if isinstance(text, str) and text.strip():
                summary = text.strip()
        except Exception as exc:  # model unavailable — fall back to deterministic facts
            summary = f"{facts}\n\n(model summary unavailable: {exc})"

        report = (
            f"## iOS automation ({AGENT})\n\n"
            f"- **Target:** `{repo}@{ref}`\n"
            f"- **Suite:** `swift test` via `{WORKFLOW}` (macOS runner)\n"
            f"- **Verdict:** {verdict}\n\n"
            f"{summary}\n"
        )
        return {"summary": summary, "verdict": verdict, "report": report}


def gate(state: State) -> dict:
    """REPORT-ONLY: request approval before any PR comment. Do NOT write to GitHub here."""
    pr = state.get("pr")
    with span(f"{AGENT}.gate", pr=pr or 0, verdict=state.get("verdict", "")):
        if not pr:
            # No PR to comment on — nothing outward-facing to approve.
            return {"approved": False}
        decision = request_approval(
            action="ios_pr_comment",
            payload={
                "repo": state.get("repo") or REPO,
                "pr": pr,
                "verdict": state.get("verdict"),
                "body": state.get("report"),
            },
            risk="medium",
        )
        return {"approved": is_approved(decision)}


def finalize(state: State) -> dict:
    """Terminal node: record what would happen and capture the decision to governance.

    The PR comment is the ONLY outward action and it is gated above. v1 stays report-only:
    even on approval we record intent rather than writing to GitHub from the agent.
    """
    approved = state.get("approved", False)
    pr = state.get("pr")
    verdict = state.get("verdict", "DEGRADED")
    with span(f"{AGENT}.finalize", approved=approved, verdict=verdict):
        if pr and approved:
            result = f"approved: PR comment ready for #{pr} (report-only — not written by agent)"
        elif pr:
            result = f"skipped: PR comment for #{pr} not approved"
        else:
            result = "report-only: no PR target; summary produced, no outward action"

        decision = {
            "repo": state.get("repo") or REPO,
            "ref": state.get("ref") or "main",
            "pr": pr,
            "verdict": verdict,
            "dispatched": state.get("dispatched", False),
            "approved": approved,
            "result": result,
        }
        governance_capture(AGENT, decision)
        return {"result": result}


def budget_gate(state: State) -> dict:
    """CLOCK-IN gate: if the agent is over its token salary or globally disabled, STOP.

    Produces a terminal 'clocked_out' report, captures the decision to governance, and
    ends the run before any dispatch or model spend. When clocked in, this node is a
    no-op pass-through and the conditional edge routes to the normal entry.
    """
    repo = state.get("repo") or REPO
    ref = state.get("ref") or "main"
    with span(f"{AGENT}.budget_gate", repo=repo, ref=ref):
        if check_clocked_in(AGENT):
            return {}
        result = (
            f"{AGENT} is over its token salary or globally disabled — skipping run"
        )
        report = (
            f"## iOS automation ({AGENT}) — CLOCKED OUT\n\n"
            f"- **Target:** `{repo}@{ref}`\n"
            f"- {result}\n"
        )
        governance_capture(
            AGENT,
            {
                "repo": repo,
                "ref": ref,
                "verdict": "CLOCKED_OUT",
                "clocked_in": False,
                "result": result,
            },
        )
        return {"verdict": "CLOCKED_OUT", "report": report, "result": result}


def _clock_route(state: State) -> str:
    """After the clock-in gate: END if clocked out, else the normal entry routing."""
    if state.get("verdict") == "CLOCKED_OUT":
        return "__end__"
    return "observe" if is_observe_mode(state) else "dispatch"


def _entry(state: State) -> str:
    """Route to the read-only OBSERVE path or the normal dispatch path."""
    return "observe" if is_observe_mode(state) else "dispatch"


builder = StateGraph(State)
builder.add_node("budget_gate", budget_gate)
builder.add_node("observe", observe)
builder.add_node("dispatch", dispatch)
builder.add_node("summarize", summarize)
builder.add_node("gate", gate)
builder.add_node("finalize", finalize)
# CLOCK-IN gate first: if clocked out (over salary / globally disabled), end immediately.
builder.add_edge(START, "budget_gate")
# OBSERVE mode bypasses dispatch + the approval gate entirely (read-only, report-only).
builder.add_conditional_edges(
    "budget_gate",
    _clock_route,
    {"observe": "observe", "dispatch": "dispatch", "__end__": END},
)
builder.add_edge("observe", END)
builder.add_edge("dispatch", "summarize")
builder.add_edge("summarize", "gate")
builder.add_edge("gate", "finalize")
builder.add_edge("finalize", END)

graph = builder.compile()  # NO checkpointer/store — injected by the platform
