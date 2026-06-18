"""ios_manual_tester — iOS manual tester: exploratory passes on an iOS simulator (macOS only).

v1 LangGraph worker graph. Maps audit spec: qa-manual-pass-orchestrator (ios).
Runtime: Stratus Mac node. Model tier: TIER_BROWSER (senior pay grade, see roster.yaml).

What it does (orchestration only — orchestrate-local, execute-on-cluster):
  plan      -> use the model to design an exploratory iOS-simulator pass over scheduler-ios.
  dispatch  -> DISPATCH the heavy run (swift test on macos-14) to a Stratus Mac runner via
               GitHub Actions; NEVER build/boot a simulator inside this agent container.
  summarize -> use the model to summarize findings and DRAFT a bug report (verdict + issue body).
  gate      -> REPORT-ONLY: every outward/irreversible write (file a bug issue) passes through
               request_approval. We build the draft and gate the write; we do NOT write to
               GitHub yet — only an explicit human 'approve' would unblock the actual file.
  finalize  -> governance_capture of the terminal decision.

Anthropic-terms guard: assert_not_model_work is called on every repo/target string so the
worker can never point exploratory testing at gal-model / eval-worker etc.
"""
import os

from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END

from agent_toolkit import (
    get_model,
    request_approval,
    span,
    governance_capture,
    dispatch_github_workflow,
    assert_not_model_work,
    check_clocked_in,
    budget_guard,
    TIER_BROWSER,
)
from agent_toolkit.approval import is_approved

try:  # works whether loaded as a package module or by file path (LangGraph platform)
    from .observe import is_observe_mode, read_local_repo_recon, render_recon
except ImportError:  # pragma: no cover - path-based load fallback
    import sys

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from observe import is_observe_mode, read_local_repo_recon, render_recon

# --- Repo recon (verified) -------------------------------------------------
# scheduler-ios is an SPM project; the test gate runs `swift test` on macos-14.
TARGET_REPO = "Scheduler-Systems/scheduler-ios"
# Local checkout path (read-only) used by OBSERVE mode.
LOCAL_REPO_DIR = "scheduler-ios"
TEST_WORKFLOW = "gate.yml"          # .github/workflows/gate.yml — PR + push to main
TEST_REF = "main"
TEST_SCHEME = "SchedulerApp"        # Fastlane scheme (XCODE_SCHEME), iOS 17+ simulator


class State(TypedDict, total=False):
    clocked_in: bool                # budget gate: False -> over token salary / globally disabled
    mode: str                       # "observe" -> read-only learning pass (no dispatch, no writes)
    observations: str               # OBSERVE-mode learning summary (read-only)
    target: str                     # repo under test (default: scheduler-ios)
    focus: str                      # optional exploratory focus area (e.g. "auth flow")
    plan: str                       # model-drafted exploratory pass plan
    dispatched: bool                # did the runner job get triggered?
    dispatch_note: str              # human-readable dispatch outcome
    verdict: str                    # PASS | FAIL | NEEDS-REVIEW
    bug_report: str                 # model-drafted bug issue body (NOT yet filed)
    approved: bool                  # human approval for the GitHub write
    report: str                     # terminal summary (what would happen next)


AGENT = "ios_manual_tester"


def budget_gate(state: State) -> dict:
    """CLOCK-IN gate (runs FIRST): stop if over token salary or globally disabled.

    If the agent is not clocked in, produce a terminal 'clocked_out' report, capture the
    skip to governance, and the conditional edge routes straight to END (no plan, no
    observe, no dispatch, no writes). Otherwise we record clocked_in=True and the normal
    router (observe vs plan) takes over.
    """
    with span("ios_manual_tester.budget_gate", agent=AGENT):
        if check_clocked_in(AGENT):
            return {"clocked_in": True}
        report = (
            "ios_manual_tester is over its token salary or globally disabled — skipping run"
        )
        governance_capture(
            AGENT,
            {
                "clocked_in": False,
                "dispatched": False,
                "report_only": True,
                "verdict": "clocked_out",
                "result": report,
            },
        )
        return {"clocked_in": False, "verdict": "clocked_out", "report": report}


def plan(state: State) -> dict:
    """Use the model to plan an exploratory iOS-simulator pass over the target repo."""
    target = state.get("target") or TARGET_REPO
    assert_not_model_work(target)  # Anthropic-terms guard
    focus = state.get("focus", "core flows: launch, auth, schedule create, navigation")
    with span("ios_manual_tester.plan", target=target, focus=focus):
        model = budget_guard("ios_manual_tester", TIER_BROWSER)
        prompt = (
            "You are an iOS QA manual tester planning an EXPLORATORY pass on an iOS simulator "
            "for the Scheduler app (SwiftUI, ~13/31 screens, SPM project, iOS 17+).\n"
            f"Repo: {target}. Scheme: {TEST_SCHEME}. Focus: {focus}.\n"
            "Note: the iOS app is incomplete — expect missing screens. Produce a concise, "
            "numbered exploratory charter (5-8 steps): what to exercise, what evidence to "
            "capture (screenshots/logs), and the highest-value risk areas to probe. "
            "Do NOT run anything yourself — heavy execution is dispatched to a runner."
        )
        try:
            drafted = model.invoke(prompt).content
        except Exception as exc:  # fail-safe: never wedge the graph on a model hiccup
            drafted = f"(model unavailable: {exc}) default charter: smoke launch -> auth -> schedule create -> tab nav"
        return {"target": target, "focus": focus, "plan": str(drafted)}


def observe(state: State) -> dict:
    """OBSERVE / learning mode — READ-ONLY. No CI dispatch, no proposed bug writes.

    Reads scheduler-ios's local test setup (SPM/XCTest/Fastlane) + recent git history
    (read-only) and asks the browser-tier model to produce an `observations` learning
    summary of how iOS QA works and where an exploratory simulator pass is most likely to
    find fragility. Report-only: no approval gate.
    """
    target = state.get("target") or TARGET_REPO
    focus = state.get("focus", "core flows: launch, auth, schedule create, navigation")
    assert_not_model_work(target)
    with span("ios_manual_tester.observe", target=target, focus=focus, mode="observe"):
        facts = read_local_repo_recon(LOCAL_REPO_DIR)
        recon = render_recon(facts)
        observations = ""
        try:
            model = budget_guard("ios_manual_tester", TIER_BROWSER)
            prompt = (
                "You are an iOS QA manual tester in LEARNING/OBSERVE mode for the Scheduler app "
                "(SwiftUI, ~13/31 screens, SPM project, iOS 17+, no Xcode app target yet). You "
                "are NOT booting a simulator or dispatching `swift test`; you are only studying "
                "the repo to learn how its QA works.\n"
                f"Repo: {target}. Scheme: {TEST_SCHEME}. Focus: {focus}.\n"
                "From the READ-ONLY local recon below (Package.swift / Makefile / Fastfile test "
                "setup and recent git history), write an 'observations' learning summary:\n"
                "1) How iOS QA is structured (`swift test`, test targets, CI gate.yml macos-14).\n"
                "2) The areas that look FRAGILE/incomplete and would be highest value for a "
                "future exploratory simulator pass (missing screens, thin coverage, churny areas "
                "in recent commits).\n"
                "3) What evidence (screenshots/logs) to capture next time.\n"
                "Be concrete and cite filenames. Do not invent test counts.\n\n"
                f"{recon}"
            )
            observations = str(model.invoke(prompt).content)
        except Exception as exc:  # model unavailable — still report deterministic recon
            observations = (
                f"(model observe summary unavailable: {exc})\n\n"
                f"Read-only recon of {target}:\n{recon}"
            )

        report = (
            f"ios_manual_tester OBSERVE (read-only learning) for {target} (focus={focus}): "
            f"test_setup_files={facts.get('test_setup_files') or []}; "
            "no CI dispatched, no bug report proposed."
        )
        governance_capture(
            "ios_manual_tester",
            {
                "mode": "observe",
                "target": target,
                "focus": focus,
                "test_setup_files": facts.get("test_setup_files") or [],
                "dispatched": False,
                "report_only": True,
            },
        )
        return {"observations": observations, "report": report, "verdict": "OBSERVE"}


def dispatch(state: State) -> dict:
    """DISPATCH the heavy swift-test pass to a Stratus Mac runner — never run it here."""
    target = state.get("target") or TARGET_REPO
    assert_not_model_work(target)  # guard the dispatch target too
    with span("ios_manual_tester.dispatch", target=target, workflow=TEST_WORKFLOW):
        try:
            ok = dispatch_github_workflow(
                repo=target,
                workflow=TEST_WORKFLOW,
                ref=TEST_REF,
                inputs={"scheme": TEST_SCHEME, "reason": "ios_manual_tester exploratory pass"},
            )
            note = (
                f"dispatched {TEST_WORKFLOW} on {target}@{TEST_REF} (swift test, macos-14)"
                if ok
                else f"dispatch rejected by GitHub for {target}:{TEST_WORKFLOW}"
            )
        except Exception as exc:
            ok = False
            note = f"dispatch failed: {exc}"
        return {"dispatched": ok, "dispatch_note": note}


def summarize(state: State) -> dict:
    """Use the model to summarize findings and DRAFT (not file) a bug report + verdict."""
    target = state.get("target") or TARGET_REPO
    with span("ios_manual_tester.summarize", target=target, dispatched=state.get("dispatched", False)):
        model = budget_guard("ios_manual_tester", TIER_BROWSER)
        prompt = (
            "You are the iOS QA manual tester writing up an exploratory pass.\n"
            f"Repo: {target}. Dispatch outcome: {state.get('dispatch_note', 'n/a')}.\n"
            f"Exploratory charter:\n{state.get('plan', '(none)')}\n\n"
            "Heavy execution runs on a Stratus Mac runner; treat its result as pending unless "
            "the dispatch failed. Produce TWO sections:\n"
            "1) VERDICT: exactly one of PASS / FAIL / NEEDS-REVIEW with a one-line rationale.\n"
            "2) BUG REPORT (GitHub issue draft): title, steps to reproduce, expected vs actual, "
            "and severity. If no concrete defect is confirmed yet, say so and propose what to "
            "watch for in the runner output. Keep it tight."
        )
        try:
            text = str(model.invoke(prompt).content)
        except Exception as exc:
            text = (
                "VERDICT: NEEDS-REVIEW (model unavailable: %s)\n"
                "BUG REPORT: dispatch=%s — review runner output before filing." % (exc, state.get("dispatch_note"))
            )
        verdict = "NEEDS-REVIEW"
        upper = text.upper()
        if "VERDICT: FAIL" in upper or "VERDICT:FAIL" in upper:
            verdict = "FAIL"
        elif "VERDICT: PASS" in upper or "VERDICT:PASS" in upper:
            verdict = "PASS"
        # Dispatch failure can never be a clean PASS.
        if not state.get("dispatched") and verdict == "PASS":
            verdict = "NEEDS-REVIEW"
        return {"verdict": verdict, "bug_report": text}


def gate(state: State) -> dict:
    """REPORT-ONLY: gate the outward GitHub write (filing a bug issue) on human approval."""
    with span("ios_manual_tester.gate", verdict=state.get("verdict", "")):
        decision = request_approval(
            action="file_ios_bug_issue",
            payload={
                "repo": state.get("target") or TARGET_REPO,
                "verdict": state.get("verdict"),
                "issue_body": state.get("bug_report"),
                "dispatch_note": state.get("dispatch_note"),
            },
            risk="high",
        )
        return {"approved": is_approved(decision)}


def finalize(state: State) -> dict:
    """Terminal node: report what WOULD be written, and capture the decision to governance."""
    with span("ios_manual_tester.finalize", approved=state.get("approved", False)):
        if state.get("approved"):
            report = f"APPROVED — would file bug issue on {state.get('target')} (verdict={state.get('verdict')})"
        else:
            report = f"REPORT-ONLY — verdict={state.get('verdict')}; no GitHub write (not approved)"
        governance_capture(
            "ios_manual_tester",
            {
                "target": state.get("target"),
                "verdict": state.get("verdict"),
                "dispatched": state.get("dispatched", False),
                "approved": state.get("approved", False),
                "result": report,
            },
        )
        return {"report": report}


def _route_after_gate(state: State) -> str:
    """After the clock-in gate: stop if clocked out, else pick OBSERVE vs the normal path."""
    if not state.get("clocked_in"):
        return "__end__"
    return "observe" if is_observe_mode(state) else "plan"


builder = StateGraph(State)
builder.add_node("budget_gate", budget_gate)
builder.add_node("plan", plan)
builder.add_node("observe", observe)
builder.add_node("dispatch", dispatch)
builder.add_node("summarize", summarize)
builder.add_node("gate", gate)
builder.add_node("finalize", finalize)
# CLOCK-IN gate runs first: over-salary / globally-disabled -> terminal clocked_out report.
builder.add_edge(START, "budget_gate")
# Clocked-in runs route through the existing OBSERVE-vs-plan split; clocked-out goes to END.
# OBSERVE mode bypasses dispatch + the approval gate entirely (read-only, report-only).
builder.add_conditional_edges(
    "budget_gate",
    _route_after_gate,
    {"__end__": END, "observe": "observe", "plan": "plan"},
)
builder.add_edge("observe", END)
builder.add_edge("plan", "dispatch")
builder.add_edge("dispatch", "summarize")
builder.add_edge("summarize", "gate")
builder.add_edge("gate", "finalize")
builder.add_edge("finalize", END)

graph = builder.compile()  # NO checkpointer/store — injected by the platform
