"""android_manual_tester — Android manual tester (v1).

Exploratory QA "employee" for scheduler-android. Grade gemini-2.5-pro (TIER_BROWSER),
3x/week shift, report-only on probation (roster.yaml).

Job: plan an exploratory emulator pass, DISPATCH the heavy execution to a Stratus Mac
runner via GitHub Actions (never run an emulator/test suite inside the agent), then use
the model to summarize findings and draft a bug report. Every outward/irreversible action
(filing the bug issue) is gated through request_approval and starts REPORT-ONLY: the draft
is built and the actual write is gated — nothing is written to GitHub here.

Maps audit specs: qa-manual-pass-orchestrator (android).
Runtime: Stratus Mac node. Orchestration only — no model train/eval/distill.
"""
import os

from typing_extensions import TypedDict
from langchain_core.messages import HumanMessage, SystemMessage
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
    TIER_BROWSER,
)

try:  # works whether loaded as a package module or by file path (LangGraph platform)
    from .observe import is_observe_mode, read_local_repo_recon, render_recon
except ImportError:  # pragma: no cover - path-based load fallback
    import sys

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from observe import is_observe_mode, read_local_repo_recon, render_recon

# --- Repo recon (the heavy execution target — runs ON CI, never in this agent) ---------
REPO = "Scheduler-Systems/scheduler-android"
# Local checkout path (read-only) used by OBSERVE mode.
LOCAL_REPO_DIR = "scheduler-android"
# gate.yml runs unit (./gradlew testDebugUnitTest) + instrumentation
# (./gradlew connectedDebugAndroidTest, API 34 x86_64 Google APIs, HiltTestRunner).
TEST_WORKFLOW = "gate.yml"
TEST_REF = "main"
EMULATOR_API = "34"


class State(TypedDict, total=False):
    mode: str            # "observe" -> read-only learning pass (no dispatch, no writes)
    observations: str    # OBSERVE-mode learning summary (read-only)
    target: str          # repo / suite under test
    focus: str           # optional area to explore (e.g. "shift roster builder")
    plan: list           # exploratory checklist the model produced
    dispatched: bool     # did the CI emulator pass get triggered?
    findings: str        # model summary of the pass
    bug_report: str      # drafted issue body (REPORT-ONLY until approved)
    approved: bool       # human approval for the GitHub write
    written: bool        # did we actually file the issue? (always False in v1)
    report: str          # terminal verdict


def plan(state: State) -> dict:
    """Ask the model for a focused exploratory checklist. No execution here."""
    target = state.get("target") or REPO
    assert_not_model_work(target)  # Anthropic-terms guard on the repo/target
    focus = state.get("focus", "core navigation, auth, and the shift roster builder")
    with span("android_manual_tester.plan", target=target, focus=focus):
        model = budget_guard("android_manual_tester", TIER_BROWSER)
        resp = model.invoke([
            SystemMessage(content=(
                "You are an Android exploratory QA tester for the scheduler-android app. "
                "Produce a SHORT exploratory pass checklist (5-8 concrete steps) for a "
                "manual emulator session. Focus on user-visible behavior, edge cases, and "
                "regressions — not unit-test internals. One step per line, no preamble."
            )),
            HumanMessage(content=f"Repo: {target}\nEmulator: API {EMULATOR_API}\nFocus: {focus}"),
        ])
        steps = [ln.strip(" -*\t") for ln in str(resp.content).splitlines() if ln.strip()]
        return {"target": target, "focus": focus, "plan": steps[:8]}


def observe(state: State) -> dict:
    """OBSERVE / learning mode — READ-ONLY. No CI dispatch, no proposed bug writes.

    Reads scheduler-android's local test setup + recent git history (read-only) and asks
    the browser-tier model to produce an `observations` learning summary of how Android QA
    works and where an exploratory emulator pass is most likely to find fragility.
    Report-only: no approval gate.
    """
    target = state.get("target") or REPO
    focus = state.get("focus", "core navigation, auth, and the shift roster builder")
    assert_not_model_work(target)
    with span("android_manual_tester.observe", target=target, focus=focus, mode="observe"):
        facts = read_local_repo_recon(LOCAL_REPO_DIR)
        recon = render_recon(facts)
        observations = ""
        try:
            model = budget_guard("android_manual_tester", TIER_BROWSER)
            resp = model.invoke([
                SystemMessage(content=(
                    "You are an Android exploratory QA tester in LEARNING/OBSERVE mode for the "
                    "scheduler-android app. You are NOT booting an emulator or dispatching any "
                    "tests; you are only studying the repo to learn how its QA works. "
                    "From the READ-ONLY local recon (test setup + recent git history), write an "
                    "'observations' learning summary: (1) how Android QA is structured (Gradle "
                    "unit + Espresso instrumentation, Hilt test runner, CI gate.yml); (2) the "
                    "areas that look FRAGILE or under-tested and would be highest value for a "
                    "future exploratory emulator pass (note churny areas in recent commits); "
                    "(3) what evidence to capture next time. Cite filenames; do not invent results."
                )),
                HumanMessage(content=f"Repo: {target}\nEmulator: API {EMULATOR_API}\nFocus: {focus}\n\n{recon}"),
            ])
            observations = str(resp.content)
        except Exception as exc:  # model unavailable — still report deterministic recon
            observations = (
                f"(model observe summary unavailable: {exc})\n\n"
                f"Read-only recon of {target}:\n{recon}"
            )

        report = (
            f"android_manual_tester OBSERVE (read-only learning) for {target} "
            f"(focus={focus}): test_setup_files={facts.get('test_setup_files') or []}; "
            "no CI dispatched, no bug report proposed."
        )
        governance_capture(
            "android_manual_tester",
            {
                "mode": "observe",
                "target": target,
                "focus": focus,
                "test_setup_files": facts.get("test_setup_files") or [],
                "dispatched": False,
                "written": False,
                "report_only": True,
            },
        )
        return {"observations": observations, "report": report, "written": False}


def dispatch(state: State) -> dict:
    """DISPATCH the emulator/test pass to the Stratus Mac runner via GitHub Actions.

    Heavy execution rule: the agent never boots an emulator or runs gradle locally — it
    triggers CI and orchestrates. A dispatch is not outward-facing/irreversible, so it
    does not need approval; the bug filing later does.
    """
    target = state.get("target") or REPO
    assert_not_model_work(target)  # never dispatch a model-dev workflow
    with span("android_manual_tester.dispatch", target=target, workflow=TEST_WORKFLOW):
        ok = False
        try:
            ok = dispatch_github_workflow(
                repo=target,
                workflow=TEST_WORKFLOW,
                ref=TEST_REF,
                inputs={"emulator_api": EMULATOR_API, "mode": "exploratory"},
            )
        except Exception as exc:  # missing token / network — record, don't crash the run
            return {"dispatched": False, "findings": f"dispatch failed: {exc}"}
        return {"dispatched": ok}


def summarize(state: State) -> dict:
    """Use the model to summarize the pass and draft a bug report. Still REPORT-ONLY."""
    target = state.get("target") or REPO
    with span("android_manual_tester.summarize", target=target,
              dispatched=state.get("dispatched", False)):
        model = budget_guard("android_manual_tester", TIER_BROWSER)
        checklist = "\n".join(f"- {s}" for s in state.get("plan", [])) or "(no plan)"
        dispatched = state.get("dispatched", False)
        status = (
            f"Exploratory emulator pass dispatched to CI ({TEST_WORKFLOW}) on a Stratus "
            f"Mac runner, API {EMULATOR_API}." if dispatched
            else f"Pass NOT dispatched ({state.get('findings', 'unknown reason')})."
        )
        resp = model.invoke([
            SystemMessage(content=(
                "You are an Android QA tester writing up an exploratory session. "
                "Given the planned checklist and the dispatch status, write: (1) a 2-3 "
                "sentence findings summary, then (2) a draft GitHub bug report with "
                "Title / Steps to Reproduce / Expected / Actual / Severity. If no concrete "
                "defect is known yet, frame it as a 'follow-up after CI results' template. "
                "Keep it tight."
            )),
            HumanMessage(content=f"Repo: {target}\nStatus: {status}\nChecklist:\n{checklist}"),
        ])
        draft = str(resp.content).strip()
        return {"findings": status, "bug_report": draft}


def gate(state: State) -> dict:
    """Human-in-the-loop gate for the only outward action: filing the bug issue."""
    with span("android_manual_tester.gate", target=state.get("target", REPO)):
        decision = request_approval(
            action="file_bug_issue",
            payload={
                "repo": state.get("target", REPO),
                "title": "Android exploratory pass — bug report (draft)",
                "body": state.get("bug_report", ""),
                "labels": ["qa", "android", "exploratory"],
            },
            risk="high",
        )
        return {"approved": is_approved(decision)}


def finalize(state: State) -> dict:
    """Terminal node: REPORT-ONLY. Do NOT write to GitHub in v1 (probation).

    Even when approved, v1 only records intent — actual issue creation is left for a later
    phase once the worker earns write authority (roster: report_only_until_2_clean_reviews).
    """
    target = state.get("target") or REPO
    approved = state.get("approved", False)
    with span("android_manual_tester.finalize", target=target, approved=approved):
        verdict = (
            "APPROVED — would file bug issue (REPORT-ONLY in v1; no write performed)"
            if approved else
            "NOT APPROVED — bug report withheld"
        )
        report = (
            f"android_manual_tester pass for {target}\n"
            f"dispatched={state.get('dispatched', False)}\n"
            f"{state.get('findings', '')}\n\n"
            f"DRAFT BUG REPORT:\n{state.get('bug_report', '(none)')}\n\n"
            f"VERDICT: {verdict}"
        )
        governance_capture("android_manual_tester", {
            "target": target,
            "dispatched": state.get("dispatched", False),
            "approved": approved,
            "written": False,
            "verdict": verdict,
        })
        return {"written": False, "report": report}


def budget_gate(state: State) -> dict:
    """CLOCK-IN gate (runs FIRST). If the agent is over its token salary or globally
    disabled, emit a terminal 'clocked_out' report, capture governance, and stop —
    no plan, no dispatch, no observe, no writes. Otherwise it's a no-op pass-through.
    """
    target = state.get("target") or REPO
    with span("android_manual_tester.budget_gate", target=target):
        if check_clocked_in("android_manual_tester"):
            return {}  # clocked in — fall through to the normal/observe path
        report = (
            "android_manual_tester is over its token salary or globally disabled "
            "— skipping run"
        )
        governance_capture("android_manual_tester", {
            "target": target,
            "clocked_in": False,
            "dispatched": False,
            "written": False,
            "report_only": True,
            "verdict": "CLOCKED_OUT",
        })
        return {"report": report, "written": False}


def _clock_route(state: State) -> str:
    """After the CLOCK-IN gate: stop if clocked out, else enter the normal/observe path.

    When clocked in, preserve the existing first-node selection (observe vs plan).
    """
    if not check_clocked_in("android_manual_tester"):
        return "stop"
    return "observe" if is_observe_mode(state) else "plan"


def _entry(state: State) -> str:
    """Route to the read-only OBSERVE path or the normal exploratory-dispatch path."""
    return "observe" if is_observe_mode(state) else "plan"


builder = StateGraph(State)
builder.add_node("budget_gate", budget_gate)
builder.add_node("plan", plan)
builder.add_node("observe", observe)
builder.add_node("dispatch", dispatch)
builder.add_node("summarize", summarize)
builder.add_node("gate", gate)
builder.add_node("finalize", finalize)
# CLOCK-IN gate runs FIRST: if clocked out, emit a terminal report and END (no plan,
# no observe, no dispatch, no writes). If clocked in, fall through to the existing
# first node — OBSERVE mode still bypasses dispatch + the approval gate (read-only).
builder.add_edge(START, "budget_gate")
builder.add_conditional_edges(
    "budget_gate",
    _clock_route,
    {"stop": END, "observe": "observe", "plan": "plan"},
)
builder.add_edge("observe", END)
builder.add_edge("plan", "dispatch")
builder.add_edge("dispatch", "summarize")
builder.add_edge("summarize", "gate")
builder.add_edge("gate", "finalize")
builder.add_edge("finalize", END)

graph = builder.compile()  # NO checkpointer/store — injected by the platform
