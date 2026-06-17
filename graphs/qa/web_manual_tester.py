"""web_manual_tester — Web manual tester: exploratory passes via headless browser on scheduler-web.

v1 worker graph. Maps audit spec: qa-manual-pass-orchestrator (web). Runtime: cloud/CI.

What it does (orchestration only — see AGENTS.md, no model train/eval/distill):
  1. plan      — ask the browser-tier model to draft an exploratory test plan.
  2. dispatch  — fire the headless Playwright session to a CI runner (NEVER run it here;
                 orchestrate-local, execute-on-cluster).
  3. summarize — have the model turn the plan into findings + a draft bug report.
  4. gate      — REPORT-ONLY: build the bug-issue payload, then pause on request_approval.
                 The actual GitHub write is gated and NOT performed by this graph.
  5. finalize  — terminal node: governance_capture the run decision.

Every outward/irreversible action (the bug issue) passes through request_approval and
starts report-only — the verdict/report is built, the write is gated, nothing is written
to GitHub here.
"""
import os

from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END

from agent_toolkit import (
    get_model,
    budget_guard,
    check_clocked_in,
    request_approval,
    is_approved,
    span,
    governance_capture,
    dispatch_github_workflow,
    assert_not_model_work,
    TIER_BROWSER,
)

try:  # works whether loaded as a package module or by file path (LangGraph platform)
    from .observe import is_observe_mode, read_local_repo_recon, render_recon
except ImportError:  # pragma: no cover - path-based load fallback
    import sys

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from observe import is_observe_mode, read_local_repo_recon, render_recon

# --- Repo recon (scheduler-web) -------------------------------------------------
REPO = "Scheduler-Systems/scheduler-web"
# Local checkout path (read-only) used by OBSERVE mode.
LOCAL_REPO_DIR = "scheduler-web"
# gate.yml runs type check, lint, unit (vitest), build and the Playwright e2e suite.
E2E_WORKFLOW = "gate.yml"
DEFAULT_REF = "main"
# Smoke target the Playwright config points at by default.
BASE_URL = "https://scheduler-web-next.web.app"
# Playwright projects: `chromium` (default suite) and `accessibility` (a11y).
PLAYWRIGHT_PROJECTS = ("chromium", "accessibility")
# Artifacts a failing e2e run uploads (gate.yml) — where findings come from.
RESULT_ARTIFACTS = ("test-results/", "coverage/")


class State(TypedDict, total=False):
    mode: str              # "observe" -> read-only learning pass (no dispatch, no writes)
    observations: str      # OBSERVE-mode learning summary (read-only)
    target: str            # repo/app under test (recon target)
    ref: str               # git ref to dispatch against
    plan: str              # model-drafted exploratory test plan
    dispatched: bool       # whether the headless Playwright run was dispatched to CI
    findings: str          # model-summarized findings from the pass
    bug_report: str        # drafted bug report (markdown)
    bug_payload: dict      # the GitHub issue write we WOULD make (gated)
    approved: bool         # human approval for the GitHub write
    report: str            # terminal human-readable result


def plan(state: State) -> dict:
    """Draft an exploratory browser pass on scheduler-web (model orchestration)."""
    target = state.get("target") or REPO
    assert_not_model_work(target)  # Anthropic-terms guard
    with span("web_manual_tester.plan", target=target):
        model = budget_guard("web_manual_tester", TIER_BROWSER)
        prompt = (
            "You are a senior QA engineer planning an EXPLORATORY (manual-style) browser "
            f"pass on the scheduler-web app at {BASE_URL}.\n"
            "Produce a concise, prioritized checklist of user flows and edge cases to probe "
            "in a headless Chromium session: auth/landing, core scheduling flows, the premium "
            "paywall gate, navigation, empty/error states, and accessibility.\n"
            "Output a short bulleted plan only — no code, no commands."
        )
        try:
            plan_text = model.invoke(prompt).content
        except Exception as e:  # fail-safe: planning must not crash the worker
            plan_text = f"(model unavailable: {e}) Fallback plan: auth, core scheduling, paywall, nav, a11y."
        return {"target": target, "ref": state.get("ref") or DEFAULT_REF, "plan": plan_text}


def observe(state: State) -> dict:
    """OBSERVE / learning mode — READ-ONLY. No CI dispatch, no proposed bug writes.

    Reads scheduler-web's local test setup + recent git history (read-only) and asks the
    browser-tier model to produce an `observations` learning summary of how the web app's
    QA works and where exploratory testing is most likely to find fragility. Report-only.
    """
    target = state.get("target") or REPO
    ref = state.get("ref") or DEFAULT_REF
    assert_not_model_work(target)
    with span("web_manual_tester.observe", target=target, ref=ref, mode="observe"):
        facts = read_local_repo_recon(LOCAL_REPO_DIR)
        recon = render_recon(facts)
        observations = ""
        try:
            model = budget_guard("web_manual_tester", TIER_BROWSER)
            prompt = (
                "You are a senior web exploratory QA tester in LEARNING/OBSERVE mode for the "
                "scheduler-web Next.js app. You are NOT running a browser session or dispatching "
                "any tests; you are only studying the repo to learn how its QA works.\n"
                "From the READ-ONLY local recon below (test setup + recent git history), write "
                "an 'observations' learning summary:\n"
                "1) How web QA is structured (Vitest unit, Playwright e2e/a11y, CI gate.yml).\n"
                "2) The user flows and areas that look FRAGILE or under-tested and would be the "
                "highest-value targets for a future exploratory pass (auth, scheduling, the "
                "premium paywall gate, empty/error states, a11y, churny areas in recent commits).\n"
                "3) What evidence you would want to capture next time.\n"
                "Be concrete and cite filenames. Do not invent findings.\n\n"
                f"{recon}"
            )
            observations = model.invoke(prompt).content or ""
        except Exception as exc:  # model unavailable — still report deterministic recon
            observations = (
                f"(model observe summary unavailable: {exc})\n\n"
                f"Read-only recon of {target}:\n{recon}"
            )

        report = (
            f"web_manual_tester OBSERVE (read-only learning) for {target}@{ref}: "
            f"test_setup_files={facts.get('test_setup_files') or []}; "
            "no CI dispatched, no bug report proposed."
        )
        governance_capture(
            "web_manual_tester",
            {
                "mode": "observe",
                "target": target,
                "ref": ref,
                "test_setup_files": facts.get("test_setup_files") or [],
                "dispatched": False,
                "report_only": True,
            },
        )
        return {"observations": str(observations), "report": report}


def dispatch(state: State) -> dict:
    """Dispatch the headless Playwright session to a CI runner — never run it here."""
    target = state.get("target") or REPO
    ref = state.get("ref") or DEFAULT_REF
    assert_not_model_work(target)  # guard the dispatch target too
    assert_not_model_work(E2E_WORKFLOW)
    with span("web_manual_tester.dispatch", target=target, ref=ref, workflow=E2E_WORKFLOW):
        try:
            ok = dispatch_github_workflow(
                repo=target,
                workflow=E2E_WORKFLOW,
                ref=ref,
                inputs={
                    "projects": ",".join(PLAYWRIGHT_PROJECTS),
                    "base_url": BASE_URL,
                    "reason": "web_manual_tester exploratory pass",
                },
            )
        except Exception:
            ok = False  # fail-safe: a dispatch failure is reported, not raised
        return {"dispatched": bool(ok)}


def summarize(state: State) -> dict:
    """Summarize findings and draft a bug report (model orchestration only)."""
    target = state.get("target") or REPO
    with span("web_manual_tester.summarize", target=target, dispatched=state.get("dispatched", False)):
        model = budget_guard("web_manual_tester", TIER_BROWSER)
        prompt = (
            "Based on this exploratory test plan for scheduler-web, summarize the most likely "
            "high-value findings and draft ONE GitHub bug report (markdown: Title, Summary, "
            "Steps to Reproduce, Expected, Actual, Severity). Be specific and conservative — "
            "do not fabricate failures you cannot justify from the plan.\n\n"
            f"Headless Playwright run dispatched to CI: {state.get('dispatched', False)} "
            f"(artifacts land in {', '.join(RESULT_ARTIFACTS)}).\n\n"
            f"PLAN:\n{state.get('plan', '(no plan)')}"
        )
        try:
            out = model.invoke(prompt).content
        except Exception as e:
            out = f"(model unavailable: {e}) No findings summarized."
        # The drafted report doubles as findings; keep both for the state record.
        return {"findings": out, "bug_report": out}


def gate(state: State) -> dict:
    """REPORT-ONLY: build the bug-issue payload, then gate the GitHub write on approval."""
    target = state.get("target") or REPO
    with span("web_manual_tester.gate", target=target):
        bug_payload = {
            "repo": target,
            "kind": "github_issue",
            "labels": ["qa", "exploratory", "web"],
            "title": "[web_manual_tester] exploratory pass findings",
            "body": state.get("bug_report", "(no report)"),
        }
        decision = request_approval(
            action="open_bug_issue",
            payload=bug_payload,
            risk="high",
        )
        return {"bug_payload": bug_payload, "approved": is_approved(decision)}


def finalize(state: State) -> dict:
    """Terminal node: report the verdict and capture the decision to governance.

    Even when approved, this v1 does NOT perform the GitHub write itself — it records the
    gated decision. The actual issue creation is handed off to the approval/dispatch layer.
    """
    approved = state.get("approved", False)
    with span("web_manual_tester.finalize", approved=approved):
        if approved:
            report = "APPROVED bug report (write handed off to dispatch layer; not written here)."
        else:
            report = "REPORT-ONLY: bug report drafted; GitHub write skipped (not approved)."
        decision = {
            "target": state.get("target") or REPO,
            "dispatched": state.get("dispatched", False),
            "approved": approved,
            "bug_payload": state.get("bug_payload"),
            "result": report,
        }
        governance_capture("web_manual_tester", decision)
        return {"report": report}


def budget_gate(state: State) -> dict:
    """CLOCK-IN gate: STOP if this agent is over its token salary or globally disabled.

    Terminal when clocked out — produces a 'clocked_out' report, captures the decision to
    governance, and the graph routes straight to END (no plan/observe, no dispatch, no
    approval gate). Fail-safe lives in check_clocked_in (degrades to clocked-in on error).
    """
    with span("web_manual_tester.budget_gate"):
        if check_clocked_in("web_manual_tester"):
            return {}
        report = (
            "web_manual_tester is over its token salary or globally disabled — skipping run"
        )
        decision = {
            "target": state.get("target") or REPO,
            "clocked_in": False,
            "dispatched": False,
            "report_only": True,
            "result": report,
        }
        governance_capture("web_manual_tester", decision)
        return {"report": report}


def _gate_route(state: State) -> str:
    """After the clock-in gate: continue to the run if clocked in, else terminate."""
    return _entry(state) if check_clocked_in("web_manual_tester") else "__end__"


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
# CLOCK-IN gate runs first: over-salary / globally-disabled -> terminal clocked_out, no run.
builder.add_edge(START, "budget_gate")
# Clocked in -> normal entry (OBSERVE read-only path or exploratory-dispatch path);
# clocked out -> END (terminal report already built by budget_gate).
builder.add_conditional_edges(
    "budget_gate", _gate_route, {"observe": "observe", "plan": "plan", "__end__": END}
)
# OBSERVE mode bypasses dispatch + the approval gate entirely (read-only, report-only).
builder.add_edge("observe", END)
builder.add_edge("plan", "dispatch")
builder.add_edge("dispatch", "summarize")
builder.add_edge("summarize", "gate")
builder.add_edge("gate", "finalize")
builder.add_edge("finalize", END)

graph = builder.compile()  # NO checkpointer/store — injected by the platform
