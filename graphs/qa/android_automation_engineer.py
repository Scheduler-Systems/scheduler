"""android_automation_engineer — Android automation engineer (v1).

Job: run scheduler-android's Gradle JUnit unit suite + Espresso instrumentation, then
summarize and classify each failure as flaky-vs-regression. TIER_DEFAULT model.

ORCHESTRATE-LOCAL, EXECUTE-ON-CLUSTER: this agent NEVER runs Gradle/emulators in its own
container. It DISPATCHES the heavy suites to CI (the scheduler-android `gate.yml` workflow:
`./gradlew test` unit + `./gradlew connectedDebugAndroidTest` Espresso on an API-34 AVD) via
`dispatch_github_workflow`, then orchestrates + summarizes the results with the model.

REPORT-ONLY: every outward/irreversible write (PR comment, bug issue, merge) is built first,
then gated through `request_approval`. v1 does NOT actually write to GitHub yet — it produces
the verdict + the gated payloads and stops at the gate. The actual GitHub write lands once a
write client is wired behind the approval.

Maps audit specs: android-junit-gate-triage, android-espresso-triage.
Runtime: cloud/CI -> ARC runner (dispatch target = GitHub Actions).
"""
import os

from typing import Any
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END

from agent_toolkit import (
    budget_guard,
    check_clocked_in,
    request_approval,
    is_approved,
    span,
    governance_capture,
    dispatch_github_workflow,
    assert_not_model_work,
    TIER_DEFAULT,
)

try:  # works whether loaded as a package module or by file path (LangGraph platform)
    from .observe import is_observe_mode, read_local_repo_recon, render_recon
except ImportError:  # pragma: no cover - path-based load fallback
    import sys

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from observe import is_observe_mode, read_local_repo_recon, render_recon

# scheduler-android test surface (from repo recon).
DEFAULT_REPO = "Scheduler-Systems/scheduler-android"
DEFAULT_WORKFLOW = "gate.yml"  # unit (./gradlew test) + Espresso (connectedDebugAndroidTest)
SUITES = ("gradle-unit", "espresso-instrumentation")
# Local checkout path (read-only) used by OBSERVE mode.
LOCAL_REPO_DIR = "scheduler-android"

_VERDICTS = {"pass", "regression", "flaky", "blocked"}


class State(TypedDict, total=False):
    # inputs
    mode: str               # "observe" -> read-only learning pass (no dispatch, no writes)
    observations: str       # OBSERVE-mode learning summary (read-only)
    repo: str               # GitHub owner/repo (default scheduler-android)
    ref: str                # branch/sha under test (default "main")
    workflow: str           # workflow file to dispatch (default gate.yml)
    pr_number: int          # PR to comment on, if any
    test_results: dict      # optional pre-fetched CI results to summarize (skips dispatch)
    # outputs
    dispatched: bool
    verdict: str
    report: str
    approved: bool
    pending_writes: list


def budget_gate(state: State) -> dict:
    """CLOCK-IN gate: STOP the run if the agent is over its token salary or globally disabled.

    Fail-safe per `check_clocked_in`: when clocked out, produce a terminal 'clocked_out'
    report, capture governance, and end without dispatching, summarizing, or proposing
    any writes. When clocked in, this node is a no-op and the graph proceeds normally.
    """
    if check_clocked_in("android_automation_engineer"):
        return {}
    report = (
        "android_automation_engineer is over its token salary or globally disabled — "
        "skipping run"
    )
    with span("android_automation_engineer.budget_gate", clocked_in=False):
        governance_capture(
            "android_automation_engineer",
            {
                "mode": state.get("mode", ""),
                "repo": state.get("repo", DEFAULT_REPO),
                "ref": state.get("ref", "main"),
                "suites": list(SUITES),
                "clocked_in": False,
                "dispatched": False,
                "verdict": "clocked_out",
                "report_only": True,
            },
        )
        return {"verdict": "clocked_out", "report": report}


def plan(state: State) -> dict:
    repo = state.get("repo", DEFAULT_REPO)
    ref = state.get("ref", "main")
    workflow = state.get("workflow", DEFAULT_WORKFLOW)
    # Anthropic-terms guard on every target string we act on.
    assert_not_model_work(repo)
    assert_not_model_work(workflow)
    for suite in SUITES:
        assert_not_model_work(suite)
    with span("android_automation_engineer.plan", repo=repo, ref=ref, workflow=workflow):
        return {"repo": repo, "ref": ref, "workflow": workflow}


def observe(state: State) -> dict:
    """OBSERVE / learning mode — READ-ONLY. No CI dispatch, no proposed writes.

    Reads scheduler-android's local test setup (Gradle/JUnit/Espresso) + recent git
    history (read-only) and asks the model to produce an `observations` learning summary
    of how Android QA works and where it looks fragile. Report-only: no approval gate.
    """
    repo = state.get("repo", DEFAULT_REPO)
    ref = state.get("ref", "main")
    assert_not_model_work(repo)
    for suite in SUITES:
        assert_not_model_work(suite)
    with span("android_automation_engineer.observe", repo=repo, ref=ref, mode="observe"):
        facts = read_local_repo_recon(LOCAL_REPO_DIR)
        recon = render_recon(facts)
        observations = ""
        try:
            model = budget_guard("android_automation_engineer", TIER_DEFAULT)
            prompt = (
                "You are an Android QA automation engineer in LEARNING/OBSERVE mode for "
                "scheduler-android. You are NOT running or dispatching Gradle/Espresso; you are "
                "only studying the repo to understand how its QA works.\n"
                "From the READ-ONLY local recon below (Gradle JUnit unit + Espresso "
                "instrumentation setup and recent git history), write an 'observations' "
                "learning summary:\n"
                "1) How Android QA is structured (unit `./gradlew test` vs Espresso "
                "`connectedDebugAndroidTest`, build.gradle config, CI gate.yml).\n"
                "2) Where it looks FRAGILE/flaky-prone (emulator/AVD, ANR/timeout/race risk, "
                "Hilt test runner, churny areas in recent commits).\n"
                "3) What you would watch when you later run the real gate.\n"
                "Be concrete and cite filenames. Do not invent results.\n\n"
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
            f"android_automation_engineer OBSERVE (read-only learning) for {repo}@{ref}: "
            f"test_setup_files={facts.get('test_setup_files') or []}; "
            "no CI dispatched, no writes proposed."
        )
        governance_capture(
            "android_automation_engineer",
            {
                "mode": "observe",
                "repo": repo,
                "ref": ref,
                "suites": list(SUITES),
                "test_setup_files": facts.get("test_setup_files") or [],
                "dispatched": False,
                "report_only": True,
            },
        )
        return {"observations": observations, "report": report, "verdict": "observe"}


def dispatch(state: State) -> dict:
    """Dispatch the heavy suites to CI. Skipped if results were pre-supplied."""
    if state.get("test_results"):
        return {"dispatched": False}
    repo = state["repo"]
    workflow = state["workflow"]
    ref = state["ref"]
    with span("android_automation_engineer.dispatch", repo=repo, workflow=workflow, ref=ref):
        ok = False
        try:
            ok = dispatch_github_workflow(
                repo=repo,
                workflow=workflow,
                ref=ref,
                inputs={"suites": ",".join(SUITES)},
            )
        except Exception:
            ok = False  # fail-safe: never crash the agent on a dispatch error
        return {"dispatched": ok}


def summarize(state: State) -> dict:
    """Use the model to summarize CI results and classify flaky-vs-regression."""
    repo = state["repo"]
    results = state.get("test_results") or {}
    with span("android_automation_engineer.summarize", repo=repo, has_results=bool(results)):
        if not results:
            # No results yet (e.g. just dispatched, or none supplied) — defer the verdict.
            return {
                "verdict": "blocked",
                "report": (
                    f"Dispatched {', '.join(SUITES)} to {repo}::{state['workflow']}@{state['ref']}. "
                    "No CI results available to summarize yet; re-invoke with `test_results` once "
                    "the run completes."
                ),
            }

        model = budget_guard("android_automation_engineer", TIER_DEFAULT)
        prompt = (
            "You are an Android QA automation engineer for scheduler-android. Summarize the CI "
            "results below for two suites: Gradle JUnit unit tests (`./gradlew test`) and Espresso "
            "instrumentation (`./gradlew connectedDebugAndroidTest`, API-34 AVD).\n"
            "For EACH failing test, classify it as 'flaky' (timeout/emulator/race/network/"
            "ANR/flaky-by-history) or 'regression' (deterministic assertion/compile/logic failure).\n"
            "Then give ONE overall verdict, exactly one of: pass | regression | flaky | blocked.\n"
            "Be concise. Format:\n"
            "VERDICT: <pass|regression|flaky|blocked>\n"
            "SUMMARY: <2-4 lines>\n"
            "FAILURES:\n- <test> :: <flaky|regression> :: <why>\n\n"
            f"CI RESULTS (JSON):\n{results}"
        )
        try:
            resp = model.invoke(prompt)
            report = getattr(resp, "content", str(resp))
        except Exception as exc:
            return {
                "verdict": "blocked",
                "report": f"Model summarization failed: {exc!r}. Raw results: {results}",
            }

        verdict = _parse_verdict(report)
        return {"verdict": verdict, "report": report}


def gate(state: State) -> dict:
    """REPORT-ONLY: build the proposed GitHub writes and gate them. Do NOT write yet."""
    verdict = state.get("verdict", "blocked")
    repo = state["repo"]
    report = state.get("report", "")
    pr_number = state.get("pr_number")

    # Build the proposed outward actions (none are executed in v1).
    pending: list[dict[str, Any]] = []
    if pr_number is not None:
        pending.append(
            {"action": "pr_comment", "repo": repo, "pr": pr_number, "body": report}
        )
    if verdict == "regression":
        pending.append(
            {
                "action": "open_bug_issue",
                "repo": repo,
                "title": f"[android-automation] regression on {state['ref']}",
                "body": report,
                "labels": ["bug", "android", "regression", "qa-agent"],
            }
        )

    with span("android_automation_engineer.gate", verdict=verdict, pending=len(pending)):
        if not pending:
            # Nothing outward to do (e.g. clean pass, no PR) — no approval needed.
            return {"approved": False, "pending_writes": []}

        decision = request_approval(
            action="android_qa_github_writes",
            payload={"repo": repo, "verdict": verdict, "writes": pending},
            risk="high",
        )
        approved = is_approved(decision)
        # v1 is report-only: even when approved we record intent but do NOT write to GitHub.
        return {"approved": approved, "pending_writes": pending}


def finalize(state: State) -> dict:
    """Terminal node: governance capture of the run's decision."""
    verdict = state.get("verdict", "blocked")
    approved = state.get("approved", False)
    pending = state.get("pending_writes", [])
    with span(
        "android_automation_engineer.finalize",
        verdict=verdict,
        approved=approved,
        pending=len(pending),
    ):
        decision = {
            "repo": state.get("repo", DEFAULT_REPO),
            "ref": state.get("ref", "main"),
            "suites": list(SUITES),
            "dispatched": state.get("dispatched", False),
            "verdict": verdict,
            "approved_writes": approved,
            "pending_writes": [w.get("action") for w in pending],
            "report_only": True,  # v1 never executes the GitHub writes
        }
        governance_capture("android_automation_engineer", decision)
        return {"report": state.get("report", ""), "verdict": verdict}


def _parse_verdict(report: str) -> str:
    """Extract the model's overall verdict; default to 'blocked' if unparseable."""
    for line in (report or "").splitlines():
        stripped = line.strip().lower()
        if stripped.startswith("verdict:"):
            value = stripped.split(":", 1)[1].strip()
            for v in _VERDICTS:
                if value.startswith(v):
                    return v
    # Fallback heuristic.
    low = (report or "").lower()
    if "regression" in low:
        return "regression"
    if "flaky" in low:
        return "flaky"
    if "pass" in low:
        return "pass"
    return "blocked"


def _entry(state: State) -> str:
    """Route to the read-only OBSERVE path or the normal dispatch path."""
    return "observe" if is_observe_mode(state) else "plan"


def _after_budget_gate(state: State) -> str:
    """After the CLOCK-IN gate: END if clocked out, else the normal observe/plan entry."""
    if state.get("verdict") == "clocked_out":
        return "__end__"
    return _entry(state)


builder = StateGraph(State)
builder.add_node("budget_gate", budget_gate)
builder.add_node("plan", plan)
builder.add_node("observe", observe)
builder.add_node("dispatch", dispatch)
builder.add_node("summarize", summarize)
builder.add_node("gate", gate)
builder.add_node("finalize", finalize)
# CLOCK-IN gate first: if over salary / globally disabled, stop before any work.
builder.add_edge(START, "budget_gate")
# OBSERVE mode bypasses dispatch + the approval gate entirely (read-only, report-only).
builder.add_conditional_edges(
    "budget_gate",
    _after_budget_gate,
    {"observe": "observe", "plan": "plan", "__end__": END},
)
builder.add_edge("observe", END)
builder.add_edge("plan", "dispatch")
builder.add_edge("dispatch", "summarize")
builder.add_edge("summarize", "gate")
builder.add_edge("gate", "finalize")
builder.add_edge("finalize", END)

graph = builder.compile()  # NO checkpointer/store — injected by the platform
