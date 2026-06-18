"""web_automation_engineer — Vitest unit + Playwright e2e gatekeeper for scheduler-web.

Maps audit specs: vitest-gatekeeper, e2e-playwright-orchestrator.
Runtime: cloud/CI (LangGraph Platform managed Cloud SaaS).

THE LOAD-BEARING DECISION (orchestrate-local, execute-on-cluster):
This agent NEVER runs Vitest, Playwright, browsers, emulators, or a build inside the
LangGraph container. It is the conductor: it DISPATCHES the heavy suites to CI via
``dispatch_github_workflow`` (the scheduler-web ``gate.yml`` runs the Vitest ``gate`` job
and the Playwright ``e2e`` job), then uses the model ONLY to summarize pass/fail and
classify each failure as flaky-vs-regression. No model training/eval/distillation
(Anthropic-terms guardrail via ``assert_not_model_work``).

REPORT-ONLY by default: every outward/irreversible action (PR comment, bug issue, merge)
is built as a draft, then held at the human-in-the-loop ``request_approval`` gate. The
graph builds the verdict + drafted writes but does NOT touch GitHub in v1 until approved.

Repo recon (scheduler-web):
  - Vitest unit:  ``npm test`` (vitest run); coverage ``npm run test:coverage`` (v8).
  - Playwright e2e: ``npm run test:e2e`` (playwright test) vs https://scheduler-web-next.web.app;
    projects: chromium (default, excludes a11y) + accessibility; CI = 1 worker, 2 retries.
  - Workflows: ``gate.yml`` (PR/push: typecheck, lint, unit tests, build + e2e job),
    ``release.yml`` (tag push). Artifacts: test-results/ (e2e), coverage/ (unit).
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
    TIER_DEFAULT,
)
try:  # works whether loaded as a package module or by file path (LangGraph platform)
    from .observe import is_observe_mode, read_local_repo_recon, render_recon
except ImportError:  # pragma: no cover - path-based load fallback
    import sys

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from observe import is_observe_mode, read_local_repo_recon, render_recon

# Recon constants — the live scheduler-web CI surface.
REPO = "Scheduler-Systems/scheduler-web"
GATE_WORKFLOW = "gate.yml"  # Vitest unit `gate` job + Playwright `e2e` job
DEFAULT_REF = "main"
# Local checkout path (read-only) used by OBSERVE mode.
LOCAL_REPO_DIR = "scheduler-web"


class State(TypedDict, total=False):
    mode: str              # "observe" -> read-only learning pass (no dispatch, no writes)
    target: str            # repo to test (default REPO)
    ref: str               # git ref / branch to dispatch against
    pr_number: int         # PR to comment on (if any)
    observations: str      # OBSERVE-mode learning summary (read-only)
    # dispatch outcome
    unit_dispatched: bool
    e2e_dispatched: bool
    dispatch_errors: list  # human-readable dispatch failures
    # model output
    summary: str           # pass/fail summary
    classification: str    # flaky | regression | mixed | indeterminate
    # drafted (NOT yet sent) outward actions, gated below
    proposed_actions: list
    approved: bool
    report: str            # terminal verdict


def plan(state: State) -> dict:
    """Resolve target + guard against any model-development work."""
    target = state.get("target") or REPO
    ref = state.get("ref") or DEFAULT_REF
    # Guard EVERY outward target string per Anthropic terms (skips gal-model / eval-worker).
    assert_not_model_work(target)
    assert_not_model_work(GATE_WORKFLOW)
    with span("web_automation_engineer.plan", target=target, ref=ref):
        return {"target": target, "ref": ref}


def observe(state: State) -> dict:
    """OBSERVE / learning mode — READ-ONLY. No CI dispatch, no proposed writes.

    Reads scheduler-web's local test setup + recent git history (read-only) and asks the
    model to produce an `observations` learning summary of how web QA works and where it
    looks fragile. Report-only: no approval gate. Governance is captured at the end.
    """
    target = state.get("target") or REPO
    ref = state.get("ref") or DEFAULT_REF
    assert_not_model_work(target)  # guard the target even on the read-only path
    with span("web_automation_engineer.observe", target=target, ref=ref, mode="observe"):
        facts = read_local_repo_recon(LOCAL_REPO_DIR)
        recon = render_recon(facts)
        observations = ""
        try:
            model = budget_guard("web_automation_engineer", TIER_DEFAULT)
            prompt = (
                "You are a web QA automation engineer in LEARNING/OBSERVE mode for the "
                "scheduler-web Next.js app. You are NOT running or dispatching any tests; you "
                "are only studying the repo to understand how its QA works.\n"
                "From the READ-ONLY local recon below (Vitest unit + Playwright e2e setup and "
                "recent git history), write an 'observations' learning summary:\n"
                "1) How this platform's QA is structured (unit vs e2e, configs, CI gate.yml).\n"
                "2) Where it looks FRAGILE or flaky-prone (retries, external base URL, "
                "missing coverage, churny areas in recent commits).\n"
                "3) What you would watch when you later run the real gate.\n"
                "Be concrete and cite filenames. Do not invent results.\n\n"
                f"{recon}"
            )
            resp = model.invoke(prompt)
            observations = getattr(resp, "content", str(resp)) or ""
        except Exception as exc:  # model unavailable — still report deterministic recon
            observations = (
                f"(model observe summary unavailable: {exc})\n\n"
                f"Read-only recon of {target}:\n{recon}"
            )

        report = (
            f"web_automation_engineer OBSERVE (read-only learning) for {target}@{ref}: "
            f"test_setup_files={facts.get('test_setup_files') or []}; "
            "no CI dispatched, no writes proposed."
        )
        governance_capture(
            "web_automation_engineer",
            {
                "mode": "observe",
                "target": target,
                "ref": ref,
                "test_setup_files": facts.get("test_setup_files") or [],
                "dispatched": False,
                "report_only": True,
            },
        )
        return {"observations": observations, "report": report}


def dispatch(state: State) -> dict:
    """DISPATCH Vitest unit + Playwright e2e to CI — never run them in the agent.

    scheduler-web's gate.yml runs the Vitest `gate` job and the Playwright `e2e` job
    together, so one workflow_dispatch covers both suites. Inputs flag both for the
    triage step and any future per-suite split.
    """
    target = state.get("target") or REPO
    ref = state.get("ref") or DEFAULT_REF
    errors: list = []
    with span("web_automation_engineer.dispatch", target=target, ref=ref):
        ok = False
        try:
            ok = dispatch_github_workflow(
                repo=target,
                workflow=GATE_WORKFLOW,
                ref=ref,
                inputs={"suite": "unit+e2e", "engineer": "web_automation_engineer"},
            )
        except Exception as exc:  # never crash the agent on a dispatch failure
            errors.append(f"dispatch {target}/{GATE_WORKFLOW}@{ref} failed: {exc}")
        if not errors and not ok:
            errors.append(
                f"dispatch {target}/{GATE_WORKFLOW}@{ref} returned non-204 "
                "(workflow may lack a workflow_dispatch trigger)"
            )
        # gate.yml runs both jobs from a single dispatch.
        return {
            "unit_dispatched": ok,
            "e2e_dispatched": ok,
            "dispatch_errors": errors,
        }


def triage(state: State) -> dict:
    """Use the model (TIER_DEFAULT) ONLY to summarize + classify flaky-vs-regression.

    Builds the REPORT and the DRAFT outward actions. Writes nothing to GitHub here.
    """
    target = state.get("target") or REPO
    ref = state.get("ref") or DEFAULT_REF
    unit_ok = state.get("unit_dispatched", False)
    e2e_ok = state.get("e2e_dispatched", False)
    errors = state.get("dispatch_errors") or []

    with span(
        "web_automation_engineer.triage",
        target=target,
        unit_dispatched=unit_ok,
        e2e_dispatched=e2e_ok,
    ):
        model = budget_guard("web_automation_engineer", TIER_DEFAULT)
        prompt = (
            "You are a web QA automation engineer for the scheduler-web Next.js app.\n"
            "Vitest unit + Playwright e2e suites were DISPATCHED to GitHub Actions "
            f"(repo={target}, workflow={GATE_WORKFLOW}, ref={ref}).\n"
            "Playwright runs in CI with 2 retries (so a test that fails then passes on "
            "retry is FLAKY, not a regression).\n\n"
            f"Dispatch result: unit_dispatched={unit_ok}, e2e_dispatched={e2e_ok}.\n"
            f"Dispatch errors: {errors or 'none'}.\n\n"
            "Write a concise pass/fail summary, then on a final line output exactly:\n"
            "CLASSIFICATION: <flaky|regression|mixed|indeterminate>\n"
            "Use 'indeterminate' if the suites could not be dispatched."
        )
        summary = ""
        classification = "indeterminate"
        try:
            resp = model.invoke(prompt)
            summary = getattr(resp, "content", str(resp)) or ""
            for line in reversed(summary.splitlines()):
                if line.strip().upper().startswith("CLASSIFICATION:"):
                    classification = line.split(":", 1)[1].strip().lower() or classification
                    break
        except Exception as exc:  # model failure must not crash the agent
            summary = f"(model triage unavailable: {exc})"
            classification = "indeterminate"

        # Draft outward actions — REPORT-ONLY; each is gated before execution.
        proposed_actions: list = []
        if classification in ("regression", "mixed"):
            proposed_actions.append(
                {
                    "kind": "open_issue",
                    "repo": target,
                    "title": f"[web-qa] Regression suspected on {ref}",
                    "body": summary,
                }
            )
        pr_number = state.get("pr_number")
        if pr_number:
            proposed_actions.append(
                {
                    "kind": "pr_comment",
                    "repo": target,
                    "pr_number": pr_number,
                    "body": summary,
                }
            )

        return {
            "summary": summary,
            "classification": classification,
            "proposed_actions": proposed_actions,
        }


def gate(state: State) -> dict:
    """Human-in-the-loop gate for ALL outward/irreversible writes (comment/issue/merge)."""
    actions = state.get("proposed_actions") or []
    if not actions:
        # Nothing to write — report-only, no approval needed.
        return {"approved": False}
    with span("web_automation_engineer.gate", num_actions=len(actions)):
        decision = request_approval(
            action="web_qa_publish",
            payload={
                "target": state.get("target"),
                "classification": state.get("classification"),
                "actions": actions,
            },
            risk="high",
        )
        return {"approved": is_approved(decision)}


def finalize(state: State) -> dict:
    """Execute approved writes (still gated), emit the verdict, and capture governance."""
    target = state.get("target") or REPO
    approved = state.get("approved", False)
    actions = state.get("proposed_actions") or []
    classification = state.get("classification", "indeterminate")

    with span("web_automation_engineer.finalize", approved=approved):
        executed: list = []
        if approved:
            # v1: writes are GATED and intentionally NOT performed yet — the GitHub
            # write tools are wired in a later phase. Record what WOULD be sent.
            for a in actions:
                executed.append({"kind": a.get("kind"), "status": "would-write (approved)"})
        else:
            for a in actions:
                executed.append({"kind": a.get("kind"), "status": "skipped (not approved)"})

        report = (
            f"web_automation_engineer verdict for {target}: "
            f"classification={classification}; "
            f"dispatched(unit={state.get('unit_dispatched', False)}, "
            f"e2e={state.get('e2e_dispatched', False)}); "
            f"actions={executed or 'report-only'}"
        )
        governance_capture(
            "web_automation_engineer",
            {
                "target": target,
                "classification": classification,
                "approved": approved,
                "executed": executed,
                "dispatch_errors": state.get("dispatch_errors") or [],
            },
        )
        return {"report": report}


def budget_gate(state: State) -> dict:
    """CLOCK-IN gate — STOP before any work if the agent is over salary or globally disabled.

    Runs FIRST (START -> budget_gate). If clocked in, control passes to the normal entry
    routing (observe vs plan); if not, we emit a terminal report, capture governance, and end.
    No CI dispatch, no model spend, no writes on the clocked-out path.
    """
    with span("web_automation_engineer.budget_gate"):
        if check_clocked_in("web_automation_engineer"):
            return {}
        report = (
            "web_automation_engineer is over its token salary or globally disabled "
            "— skipping run"
        )
        governance_capture(
            "web_automation_engineer",
            {
                "clocked_in": False,
                "report": report,
                "dispatched": False,
                "report_only": True,
            },
        )
        return {"report": report}


def _budget_route(state: State) -> str:
    """Route past the clock-in gate: clocked in -> entry routing; clocked out -> END."""
    if not check_clocked_in("web_automation_engineer"):
        return "clocked_out"
    return _entry(state)


def _entry(state: State) -> str:
    """Route to the read-only OBSERVE path or the normal dispatch path."""
    return "observe" if is_observe_mode(state) else "plan"


builder = StateGraph(State)
builder.add_node("budget_gate", budget_gate)
builder.add_node("plan", plan)
builder.add_node("observe", observe)
builder.add_node("dispatch", dispatch)
builder.add_node("triage", triage)
builder.add_node("gate", gate)
builder.add_node("finalize", finalize)
# CLOCK-IN gate runs first: clocked out -> terminal report -> END; otherwise enter the graph.
builder.add_edge(START, "budget_gate")
# When clocked in, OBSERVE mode bypasses dispatch + the approval gate (read-only, report-only).
builder.add_conditional_edges(
    "budget_gate",
    _budget_route,
    {"observe": "observe", "plan": "plan", "clocked_out": END},
)
builder.add_edge("observe", END)
builder.add_edge("plan", "dispatch")
builder.add_edge("dispatch", "triage")
builder.add_edge("triage", "gate")
builder.add_edge("gate", "finalize")
builder.add_edge("finalize", END)

graph = builder.compile()  # NO checkpointer/store — injected by the platform
