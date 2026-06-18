"""qa_lead_aggregator — QA-lead coordinator: one merge-gate "is Scheduler shippable?" verdict.

This is the team lead (roster.yaml: team_lead, grade gemini-2.5-flash -> TIER_DEFAULT,
schedule "on every PR + nightly", status probation -> report-only). Its job is
COORDINATION only:

  1. plan      — resolve the six platform targets, guard each against the model-dev
                 denylist, and DISPATCH the heavy suites to CI/runners. Test suites,
                 emulators and simulators NEVER run inside this agent
                 (orchestrate-local, execute-on-cluster).
  2. collect   — gather the latest result/verdict from each of the six platform worker
                 graphs (invoke them; fall back to anything already in shared state).
  3. aggregate — call the model (TIER_DEFAULT) to synthesize ONE structured shippability
                 verdict: overall pass/block + a per-platform reason.
  4. gate      — REPORT-ONLY. Build the PR-comment write, then route it through the
                 human-in-the-loop approval gate. The actual GitHub write is NOT
                 performed in v1 (probation): we only record whether it was approved.
  5. finalize  — terminal node: emit the GAL governance capture.

Runtime: cloud/CI
Maps audit specs: qa-test-aggregator, qa-test-orchestrator (P0)
"""
import json
import os
from typing import Any

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
    budget_guard,
    check_clocked_in,
    TIER_DEFAULT,
)

try:  # works whether loaded as a package module or by file path (LangGraph platform)
    from .observe import is_observe_mode, read_local_repo_recon, render_recon
except ImportError:  # pragma: no cover - path-based load fallback
    import sys

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from observe import is_observe_mode, read_local_repo_recon, render_recon

# --- Platform recon -----------------------------------------------------------
# repo            : GitHub repo to dispatch the gate workflow into (heavy execution).
# workflow        : the workflow_dispatch file that runs the suite on CI/runners.
# worker          : the worker graph whose verdict we collect for this platform.
# commands        : exact suite commands (recon) — for the report, NOT run here.
PLATFORMS: dict[str, dict[str, Any]] = {
    "web": {
        "repo": "Scheduler-Systems/scheduler-web",
        "workflow": "gate.yml",
        "worker": "web_automation_engineer",
        "manual_worker": "web_manual_tester",
        "commands": ["npm test", "npm run test:e2e", "npm run build"],
    },
    "android": {
        "repo": "Scheduler-Systems/scheduler-android",
        "workflow": "gate.yml",
        "worker": "android_automation_engineer",
        "manual_worker": "android_manual_tester",
        "commands": ["./gradlew testDebugUnitTest", "./gradlew connectedDebugAndroidTest"],
    },
    "ios": {
        "repo": "Scheduler-Systems/scheduler-ios",
        "workflow": "gate.yml",
        "worker": "ios_automation_engineer",
        "manual_worker": "ios_manual_tester",
        "commands": ["swift test"],
    },
}


class State(TypedDict, total=False):
    # Inputs
    mode: str                         # "observe" -> read-only learning pass (no dispatch, no writes)
    observations: str                 # OBSERVE-mode learning summary (read-only)
    target: str                       # PR/ref slug being gated (informational)
    ref: str                          # git ref to dispatch suites against
    pr_repo: str                      # repo whose PR we would comment on
    pr_number: int                    # PR number we would comment on
    worker_reports: dict              # optional: results already in shared state
    # Intermediate
    dispatched: dict                  # platform -> bool (workflow_dispatch accepted)
    collected: dict                   # platform -> {verdict, reason, source}
    # Outputs
    verdict: dict                     # the structured shippability verdict
    report: str                       # human-readable report
    approved: bool                    # whether the PR-comment write was approved
    wrote_comment: bool               # always False in v1 (report-only)


def plan(state: State) -> dict:
    """Guard every target and DISPATCH the heavy suites to CI/runners."""
    ref = state.get("ref", "main")
    with span("qa_lead_aggregator.plan", target=state.get("target", ""), ref=ref):
        dispatched: dict[str, bool] = {}
        for platform, cfg in PLATFORMS.items():
            repo = cfg["repo"]
            assert_not_model_work(repo)          # Anthropic-terms guard (repo string)
            assert_not_model_work(cfg["workflow"])
            for cmd in cfg["commands"]:
                assert_not_model_work(cmd)       # guard each suite command too
            # Heavy execution lives on CI/runners, never in this container.
            try:
                ok = dispatch_github_workflow(repo, cfg["workflow"], ref=ref)
            except Exception:
                ok = False                       # no token / network — degrade, don't crash
            dispatched[platform] = ok
        return {"dispatched": dispatched, "ref": ref}


def observe(state: State) -> dict:
    """OBSERVE / learning mode — READ-ONLY across all platforms. No dispatch, no writes.

    The QA lead studies how QA works across web/android/ios by reading each platform's
    local test setup + recent git history (read-only) and asking the model for a
    cross-platform `observations` learning summary of how the suites fit together and
    where the product's QA looks fragile. Report-only: no approval gate.
    """
    ref = state.get("ref", "main")
    with span("qa_lead_aggregator.observe", ref=ref, mode="observe"):
        per_platform_recon: dict[str, str] = {}
        files_seen: dict[str, list] = {}
        for platform, cfg in PLATFORMS.items():
            repo = cfg["repo"]
            assert_not_model_work(repo)            # guard every target even read-only
            assert_not_model_work(cfg["workflow"])
            for cmd in cfg["commands"]:
                assert_not_model_work(cmd)
            local_dir = repo.split("/")[-1]        # Scheduler-Systems/scheduler-web -> scheduler-web
            facts = read_local_repo_recon(local_dir)
            per_platform_recon[platform] = render_recon(facts, max_files=4)
            files_seen[platform] = facts.get("test_setup_files") or []

        recon_block = "\n\n".join(
            f"=== PLATFORM: {p} ({PLATFORMS[p]['repo']}) ===\n{recon}"
            for p, recon in per_platform_recon.items()
        )

        observations = ""
        try:
            model = budget_guard("qa_lead_aggregator", TIER_DEFAULT)
            prompt = (
                "You are the QA lead for the Scheduler product (web, android, ios) in "
                "LEARNING/OBSERVE mode. You are NOT dispatching any suites or running tests; "
                "you are only studying the repos to understand how the product's QA works as a "
                "whole.\n"
                "From the READ-ONLY per-platform recon below (test setup + recent git history "
                "for each platform), write a cross-platform 'observations' learning summary:\n"
                "1) How each platform's QA is structured and how they fit together as one "
                "shippability gate (web Vitest/Playwright, android Gradle/Espresso, ios "
                "swift test).\n"
                "2) Where the product's QA looks FRAGILE or uneven across platforms (coverage "
                "gaps, the incomplete iOS app, flaky-prone areas, churny areas in recent "
                "commits).\n"
                "3) What you would coordinate / watch most closely on the next real gate.\n"
                "Be concrete and cite platforms + filenames. Do not invent results.\n\n"
                f"{recon_block}"
            )
            resp = model.invoke(prompt)
            observations = getattr(resp, "content", str(resp)) or ""
        except Exception as exc:  # model unavailable — still report deterministic recon
            observations = (
                f"(model observe summary unavailable: {exc})\n\n"
                f"Read-only per-platform recon:\n{recon_block}"
            )

        report = (
            "qa_lead_aggregator OBSERVE (read-only cross-platform learning): "
            f"test_setup_files={files_seen}; no CI dispatched, no PR comment proposed.\n\n"
            f"{observations}"
        )
        governance_capture(
            "qa_lead_aggregator",
            {
                "mode": "observe",
                "ref": ref,
                "platforms": list(PLATFORMS),
                "test_setup_files": files_seen,
                "dispatched": False,
                "wrote_comment": False,
                "report_only": True,
            },
        )
        return {"observations": observations, "report": report}


def _invoke_worker(name: str, target: str) -> dict | None:
    """Best-effort: invoke a sibling worker graph and return its result state."""
    try:
        module = __import__(f"graphs.qa.{name}", fromlist=["graph"])
        return module.graph.invoke({"target": target})
    except Exception:
        return None


def _platform_verdict(platform: str, cfg: dict, state: State) -> dict:
    """Collect this platform's latest verdict: shared-state first, else invoke worker."""
    preloaded = (state.get("worker_reports") or {})
    target = cfg["repo"]

    # 1) Prefer a verdict already present in shared state (e.g. workers ran earlier).
    if platform in preloaded:
        entry = preloaded[platform]
        return {
            "verdict": entry.get("verdict", "unknown"),
            "reason": entry.get("reason") or entry.get("report", ""),
            "source": "shared_state",
        }

    # 2) Otherwise invoke the automation worker graph for this platform.
    result = _invoke_worker(cfg["worker"], target)
    if result is None:
        return {
            "verdict": "unknown",
            "reason": f"{cfg['worker']} unavailable; suite dispatched to CI, results pending",
            "source": "unavailable",
        }
    report = result.get("report", "")
    # Phase-1 workers are stubs: treat an explicit STUB report as "pending", not pass.
    verdict = "pending" if "STUB" in report else result.get("verdict", "unknown")
    return {"verdict": verdict, "reason": report, "source": cfg["worker"]}


def collect(state: State) -> dict:
    """Gather the latest result/verdict from each platform's worker graph."""
    with span("qa_lead_aggregator.collect", platforms=",".join(PLATFORMS)):
        collected = {p: _platform_verdict(p, cfg, state) for p, cfg in PLATFORMS.items()}
        return {"collected": collected}


def _block_reasons(collected: dict) -> list[str]:
    """Anything not an explicit pass blocks shipping (conservative default-deny)."""
    return [p for p, v in collected.items() if v.get("verdict") != "pass"]


def aggregate(state: State) -> dict:
    """Synthesize ONE structured shippability verdict with the model (TIER_DEFAULT)."""
    collected = state.get("collected", {})
    dispatched = state.get("dispatched", {})
    blockers = _block_reasons(collected)
    overall = "pass" if not blockers else "block"

    with span("qa_lead_aggregator.aggregate", overall=overall, blockers=len(blockers)):
        per_platform = {
            p: {"verdict": v.get("verdict"), "reason": v.get("reason"), "source": v.get("source")}
            for p, v in collected.items()
        }

        # The model SUMMARIZES the deterministic facts into a crisp lead's note.
        # It does not decide pass/block — the deterministic rule above does.
        summary = ""
        try:
            model = budget_guard("qa_lead_aggregator", TIER_DEFAULT)
            prompt = (
                "You are the QA lead for the Scheduler product (web, android, ios). "
                "Given each platform's verdict below, write a 2-4 sentence shippability "
                "summary for the PR. Be concrete about what blocks shipping. Do NOT change "
                "the overall decision; the decision is already computed.\n\n"
                f"OVERALL: {overall}\n"
                f"BLOCKERS: {blockers or 'none'}\n"
                f"PER-PLATFORM: {json.dumps(per_platform, indent=2)}\n"
                f"SUITES DISPATCHED TO CI: {json.dumps(dispatched)}\n"
            )
            resp = model.invoke(prompt)
            summary = getattr(resp, "content", str(resp))
        except Exception as exc:  # model/key unavailable — fall back to a deterministic note
            summary = (
                f"Scheduler is {'shippable' if overall == 'pass' else 'NOT shippable'}. "
                f"Blocking platforms: {blockers or 'none'}. (model summary unavailable: {exc})"
            )

        verdict = {
            "product": "scheduler",
            "overall": overall,                # "pass" | "block"
            "shippable": overall == "pass",
            "blockers": blockers,
            "per_platform": per_platform,
            "dispatched": dispatched,
            "summary": summary,
        }
        report = (
            f"Scheduler shippability: {overall.upper()}\n"
            f"Blockers: {', '.join(blockers) if blockers else 'none'}\n\n"
            f"{summary}\n\n"
            + "\n".join(
                f"- {p}: {d['verdict']} ({d['source']}) — {d['reason']}"
                for p, d in per_platform.items()
            )
        )
        return {"verdict": verdict, "report": report}


def gate(state: State) -> dict:
    """REPORT-ONLY: gate the outward PR-comment write. Do NOT write to GitHub in v1."""
    verdict = state.get("verdict", {})
    pr_repo = state.get("pr_repo", "")
    if pr_repo:
        assert_not_model_work(pr_repo)  # guard the write target too

    with span("qa_lead_aggregator.gate", overall=verdict.get("overall", "unknown")):
        decision = request_approval(
            action="post_shippability_comment",
            payload={
                "repo": pr_repo,
                "pr": state.get("pr_number"),
                "overall": verdict.get("overall"),
                "comment": state.get("report", ""),
            },
            # Blocking a release / commenting on a PR is consequential.
            risk="high" if verdict.get("overall") == "block" else "medium",
        )
        approved = is_approved(decision)
        # v1 / probation: build + gate the write, but DO NOT perform it yet.
        return {"approved": approved, "wrote_comment": False}


def finalize(state: State) -> dict:
    """Terminal node: emit the governance capture for this run."""
    verdict = state.get("verdict", {})
    with span("qa_lead_aggregator.finalize", overall=verdict.get("overall", "unknown")):
        decision = {
            "overall": verdict.get("overall"),
            "shippable": verdict.get("shippable"),
            "blockers": verdict.get("blockers", []),
            "approved_to_comment": state.get("approved", False),
            "wrote_comment": state.get("wrote_comment", False),  # always False in v1
            "report_only": True,
        }
        governance_capture("qa_lead_aggregator", decision)
        return {}


def budget_gate(state: State) -> dict:
    """CLOCK-IN gate: skip the whole run if this agent is over salary or globally disabled.

    If ``check_clocked_in`` says STOP, emit a terminal "clocked_out" report + governance
    capture and end the run WITHOUT dispatching, collecting, or proposing any write. When
    clocked in, this is a no-op pass-through to the normal OBSERVE / dispatch routing.
    """
    with span("qa_lead_aggregator.budget_gate"):
        if check_clocked_in("qa_lead_aggregator"):
            return {}
        report = (
            "qa_lead_aggregator is over its token salary or globally disabled — skipping run"
        )
        verdict = {"product": "scheduler", "overall": "clocked_out", "report_only": True}
        governance_capture(
            "qa_lead_aggregator",
            {
                "clocked_in": False,
                "overall": "clocked_out",
                "dispatched": False,
                "wrote_comment": False,
                "report_only": True,
            },
        )
        return {"verdict": verdict, "report": report}


def _budget_route(state: State) -> str:
    """After the CLOCK-IN gate: END if clocked out, else enter OBSERVE / dispatch routing.

    Re-checks ``check_clocked_in`` (cheap, fail-safe) so the routing decision matches the
    terminal report ``budget_gate`` just produced. When clocked in, defer to the normal
    OBSERVE-vs-dispatch entry routing.
    """
    if not check_clocked_in("qa_lead_aggregator"):
        return "stop"
    return "observe" if is_observe_mode(state) else "plan"


builder = StateGraph(State)
builder.add_node("budget_gate", budget_gate)
builder.add_node("plan", plan)
builder.add_node("observe", observe)
builder.add_node("collect", collect)
builder.add_node("aggregate", aggregate)
builder.add_node("gate", gate)
builder.add_node("finalize", finalize)
# CLOCK-IN gate first: if over salary / globally disabled, end before any dispatch or write.
builder.add_edge(START, "budget_gate")
# When clocked in, fall through to the existing OBSERVE-vs-dispatch routing; else END.
builder.add_conditional_edges(
    "budget_gate",
    _budget_route,
    {"observe": "observe", "plan": "plan", "stop": END},
)
# OBSERVE mode bypasses dispatch + collect + the approval gate entirely (read-only).
builder.add_edge("observe", END)
builder.add_edge("plan", "collect")
builder.add_edge("collect", "aggregate")
builder.add_edge("aggregate", "gate")
builder.add_edge("gate", "finalize")
builder.add_edge("finalize", END)

graph = builder.compile()  # NO checkpointer/store — injected by the platform
