"""web_automation_engineer — Vitest unit + Playwright e2e gatekeeper for scheduler-web.

Maps audit specs: vitest-gatekeeper, e2e-playwright-orchestrator.
Runtime: cloud/CI (LangGraph Platform managed Cloud SaaS).

THE LOAD-BEARING DECISION (orchestrate-local, execute-on-cluster):
This agent NEVER runs Vitest, Playwright, browsers, emulators, or a build inside the
LangGraph container. It is the conductor: it DISPATCHES the heavy suites to CI via
``dispatch_github_workflow`` (the scheduler-web ``gate.yml`` runs the Vitest ``gate`` job
and the Playwright ``e2e`` job), READS the dispatched run's real conclusion back via the
read-only ``github_ops.GitHubOps.latest_run`` recon (same helper the sibling
``web_qa_regression`` uses), then uses the model ONLY to summarize pass/fail and classify
each failure as flaky-vs-regression FROM THE ACTUAL CI OUTCOME — never from the bare
"did the dispatch POST succeed" booleans. No model training/eval/distillation
(Anthropic-terms guardrail via ``assert_not_model_work``).

REPORT-ONLY by default: every outward/irreversible action (PR comment, bug issue, merge)
is built as a draft, then held at the human-in-the-loop ``request_approval`` gate. Once
approved, the write is executed THROUGH ``github_ops.GitHubOps`` — which itself enforces,
in order, the Anthropic-terms guard, a default-DENY repo allow-list, the report-only
probation switch (``GITHUB_OPS_REPORT_ONLY``), and a second human gate. So in probation
(the deployed default) ``finalize`` records the structured draft GitHub returns and writes
nothing; it can only ever mutate GitHub once a least-privilege token is injected AND the
probation switch is lifted AND a human approves — three independent locks.

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
from agent_toolkit.github_ops import (
    GitHubOps,
    GitHubWriteBlocked,
    GitHubNotConfigured,
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

# The only classification verdicts this agent may emit. Anything the model returns that is
# not in this set collapses to the safe default (default-DENY → indeterminate).
VALID_CLASSIFICATIONS = ("flaky", "regression", "mixed", "indeterminate")
_DEFAULT_CLASSIFICATION = "indeterminate"


def _parse_classification(text: str) -> str:
    """Extract the model's CLASSIFICATION verdict robustly; default-DENY to indeterminate.

    Hardened against models that wrap the sentinel in markdown/backticks, change case,
    emit it mid-line, or omit it entirely. We scan ALL lines (last match wins, matching the
    'final line' convention), strip markdown noise, and ONLY accept a value that is in
    ``VALID_CLASSIFICATIONS`` — an unknown/garbage verdict is treated as indeterminate so a
    confused model can never escalate to a false 'regression' write.
    """
    verdict = _DEFAULT_CLASSIFICATION
    if not text:
        return verdict
    for line in text.splitlines():
        # Strip markdown emphasis/backticks/bullets that wrap the sentinel.
        cleaned = line.strip().strip("*`_> -").strip()
        upper = cleaned.upper()
        if "CLASSIFICATION:" not in upper:
            continue
        # Take everything after the FIRST 'CLASSIFICATION:' token on the line.
        idx = upper.index("CLASSIFICATION:") + len("CLASSIFICATION:")
        raw = cleaned[idx:].strip().strip("*`_.").strip()
        # Keep only the first whitespace-delimited token, lower-cased.
        candidate = raw.split()[0].lower() if raw.split() else ""
        if candidate in VALID_CLASSIFICATIONS:
            verdict = candidate  # last valid match wins (final-line convention)
    return verdict


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
    # the ACTUAL CI run we read back after dispatch (correlation handle + result)
    run_status: str        # queued | in_progress | completed | "" (unknown)
    run_conclusion: str    # success | failure | cancelled | "" | error:<Type>
    run_url: str           # html_url of the correlated run (audit handle)
    run_sha: str           # head_sha of the correlated run (correlation handle)
    run_name: str          # workflow run name
    run_recon_error: str   # why we could not read the run back (type only)
    # model output
    summary: str           # pass/fail summary
    classification: str    # flaky | regression | mixed | indeterminate
    model_available: bool  # False ONLY when no model API key is configured (distinct alert)
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


def read_run(state: State) -> dict:
    """READ the dispatched run's REAL outcome back — the fix that ends blind triage.

    Until now triage classified flaky-vs-regression from only the
    ``unit_dispatched``/``e2e_dispatched`` POST booleans (did the dispatch *fire*), never
    from the workflow's actual conclusion. Here we read the dispatched run back via the
    read-only, allow-list-scoped ``GitHubOps.latest_run`` recon (the same helper the sibling
    ``web_qa_regression`` uses) so triage classifies from the ACTUAL CI result. We capture
    ``html_url`` + ``head_sha`` as the correlation handle so observe/triage/finalize all cite
    the same concrete run rather than guessing.

    Read-only: NO approval gate, no writes. Resilient like ``web_qa_regression.check`` — on
    any failure we record only the exception TYPE (never ``str(e)``, which could carry a
    token/URL) and let triage degrade to indeterminate rather than file a false regression.
    """
    target = state.get("target") or REPO
    ref = state.get("ref") or DEFAULT_REF
    if not state.get("unit_dispatched") and not state.get("e2e_dispatched"):
        # Dispatch never landed — there is no run to correlate; let triage report that.
        return {"run_recon_error": "not-dispatched"}
    with span("web_automation_engineer.read_run", target=target, ref=ref):
        try:
            info = GitHubOps().latest_run(target, ref)
            return {
                "run_status": info.get("status") or "",
                "run_conclusion": info.get("conclusion") or "",
                "run_url": info.get("html_url") or "",
                "run_sha": info.get("head_sha") or "",
                "run_name": info.get("name") or "",
            }
        except Exception as exc:  # recon failed — surface the TYPE only, never str(exc)
            return {"run_recon_error": type(exc).__name__}


def triage(state: State) -> dict:
    """Use the model (TIER_DEFAULT) ONLY to summarize + classify flaky-vs-regression.

    Now classifies from the ACTUAL CI run read back in ``read_run`` (conclusion / status /
    correlated run url+sha) — not from the bare dispatch booleans. Builds the REPORT and the
    DRAFT outward actions. Writes nothing to GitHub here.
    """
    target = state.get("target") or REPO
    ref = state.get("ref") or DEFAULT_REF
    unit_ok = state.get("unit_dispatched", False)
    e2e_ok = state.get("e2e_dispatched", False)
    errors = state.get("dispatch_errors") or []
    run_status = state.get("run_status") or ""
    run_conclusion = state.get("run_conclusion") or ""
    run_url = state.get("run_url") or ""
    run_sha = state.get("run_sha") or ""
    run_recon_error = state.get("run_recon_error") or ""

    with span(
        "web_automation_engineer.triage",
        target=target,
        unit_dispatched=unit_ok,
        e2e_dispatched=e2e_ok,
        run_conclusion=run_conclusion or run_recon_error or "unknown",
    ):
        # Distinguish "no model key configured" (a config alert) from a transient model
        # error. budget_guard re-raises get_model's RuntimeError when no provider key is set;
        # we catch THAT specifically so a missing key never masquerades as a real verdict.
        model = None
        model_available = True
        key_missing_msg = ""
        try:
            model = budget_guard("web_automation_engineer", TIER_DEFAULT)
        except RuntimeError as exc:
            if "No model API key configured" in str(exc):
                model_available = False
                key_missing_msg = (
                    "ALERT: no model API key configured in this deployment — triage cannot "
                    "classify flaky-vs-regression. Set DEEPSEEK_API_KEY / GEMINI_API_KEY "
                    "(default tier) in the deployment env. Verdict forced to indeterminate."
                )
            else:
                raise  # a different config error is a real failure — don't swallow it

        # The REAL CI picture handed to the model (or used for the deterministic fallback).
        if run_recon_error:
            run_block = (
                f"CI RUN RECON FAILED ({run_recon_error}) — the dispatched run's conclusion "
                "could NOT be read back. Treat the result as UNKNOWN."
            )
        else:
            run_block = (
                f"CI RUN (read back from GitHub Actions):\n"
                f"  status={run_status or 'unknown'}\n"
                f"  conclusion={run_conclusion or 'unknown'}\n"
                f"  run_url={run_url or 'n/a'}\n"
                f"  head_sha={run_sha or 'n/a'}"
            )

        summary = ""
        classification = _DEFAULT_CLASSIFICATION
        if not model_available:
            summary = key_missing_msg
            classification = _DEFAULT_CLASSIFICATION
        else:
            prompt = (
                "You are a web QA automation engineer for the scheduler-web Next.js app.\n"
                "Vitest unit + Playwright e2e suites were DISPATCHED to GitHub Actions "
                f"(repo={target}, workflow={GATE_WORKFLOW}, ref={ref}), and the resulting CI "
                "run was then READ BACK. Classify from the ACTUAL run conclusion below, NOT "
                "from whether the dispatch fired.\n"
                "Playwright runs in CI with 2 retries (so a test that fails then passes on "
                "retry is FLAKY, not a regression). Map the conclusion:\n"
                "  - conclusion=success  -> flaky if any retried-then-passed, else not a "
                "regression (use 'flaky' only with evidence of retries; otherwise the run is "
                "green and there is nothing to file).\n"
                "  - conclusion=failure  -> regression (a genuine red gate), or mixed if only "
                "one suite failed.\n"
                "  - conclusion=cancelled/unknown or recon failed -> indeterminate.\n\n"
                f"Dispatch result: unit_dispatched={unit_ok}, e2e_dispatched={e2e_ok}.\n"
                f"Dispatch errors: {errors or 'none'}.\n\n"
                f"{run_block}\n\n"
                "Write a concise pass/fail summary citing the conclusion + run_url, then on a "
                "final line output exactly:\n"
                "CLASSIFICATION: <flaky|regression|mixed|indeterminate>\n"
                "Use 'indeterminate' if the suites could not be dispatched or the run could "
                "not be read back."
            )
            try:
                resp = model.invoke(prompt)
                summary = getattr(resp, "content", str(resp)) or ""
                classification = _parse_classification(summary)
            except Exception as exc:  # model failure must not crash the agent
                # Record TYPE only — the message could echo a key/URL.
                summary = f"(model triage unavailable: {type(exc).__name__})"
                classification = _DEFAULT_CLASSIFICATION

        # Draft outward actions — REPORT-ONLY; each is gated before execution.
        # Guard: only draft a regression issue when the model classified regression/mixed AND
        # the CI run was ACTUALLY read as a failure. A green/unknown run never files a bug —
        # this prevents the old blind-theater behaviour where booleans alone drove a verdict.
        proposed_actions: list = []
        ci_failed = run_conclusion == "failure"
        if classification in ("regression", "mixed") and ci_failed:
            proposed_actions.append(
                {
                    "kind": "open_issue",
                    "repo": target,
                    "title": f"[web-qa] Regression suspected on {ref}",
                    "body": (
                        f"{summary}\n\n"
                        f"CI conclusion: {run_conclusion}\nRun: {run_url or 'n/a'}\n"
                        f"Commit: {run_sha or 'n/a'}"
                    ),
                    "labels": ["gate:human-required"],
                }
            )
        pr_number = state.get("pr_number")
        if pr_number:
            proposed_actions.append(
                {
                    "kind": "pr_comment",
                    "repo": target,
                    "pr_number": pr_number,
                    "body": (
                        f"{summary}\n\nCI conclusion: {run_conclusion or 'unknown'}\n"
                        f"Run: {run_url or 'n/a'}"
                    ),
                }
            )

        return {
            "summary": summary,
            "classification": classification,
            "model_available": model_available,
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


def _execute_action(ops: GitHubOps, action: dict) -> dict:
    """Route ONE approved draft to the matching real GitHubOps write. The actual side-effect
    safety lives in github_ops (allow-list + report-only switch + second human gate); here we
    only translate the draft shape and report the outcome honestly.

    In probation (``GITHUB_OPS_REPORT_ONLY`` truthy — the deployed default) GitHubOps returns
    a ``{"status": "report_only", ...}`` plan and writes NOTHING. With no token it raises
    ``GitHubNotConfigured`` (fail-closed, never a fake success). Either way we record the
    truth rather than the old hardcoded ``"would-write (approved)"`` string.
    """
    kind = action.get("kind")
    repo = action.get("repo") or REPO
    try:
        if kind == "open_issue":
            res = ops.open_issue(
                repo,
                action.get("title") or "[web-qa] regression",
                action.get("body") or "",
                labels=action.get("labels") or [],
            )
        elif kind == "pr_comment":
            res = ops.comment_issue(repo, int(action["pr_number"]), action.get("body") or "")
        else:
            return {"kind": kind, "status": f"unsupported-action ({kind})"}
        return {"kind": kind, "result": res}
    except GitHubNotConfigured as exc:
        # No token wired yet — the surface is honestly inert, not faking a write.
        return {"kind": kind, "status": f"not-configured ({type(exc).__name__})"}
    except GitHubWriteBlocked as exc:
        # A guard (allow-list / second human gate) refused — report TYPE only.
        return {"kind": kind, "status": f"blocked ({type(exc).__name__})"}
    except Exception as exc:  # never crash finalize on a write error
        return {"kind": kind, "status": f"error ({type(exc).__name__})"}


def finalize(state: State) -> dict:
    """Execute approved writes THROUGH github_ops (still triple-guarded), emit the verdict,
    and capture governance.

    Closing the report-only-to-action loop: when the human gate approved the drafts, we now
    actually dispatch them to ``GitHubOps`` instead of recording a ``"would-write"`` string.
    GitHubOps keeps the real safety — in probation it returns a report-only plan and writes
    nothing, and with no token it fails closed — so this stays safe in the deployed
    report-only/probation posture while finally being able to act once those locks are lifted.
    """
    target = state.get("target") or REPO
    approved = state.get("approved", False)
    actions = state.get("proposed_actions") or []
    classification = state.get("classification", "indeterminate")

    with span("web_automation_engineer.finalize", approved=approved):
        executed: list = []
        if approved and actions:
            ops = GitHubOps()  # report_only resolved from env (probation default) inside ops
            for a in actions:
                executed.append(_execute_action(ops, a))
        else:
            for a in actions:
                executed.append({"kind": a.get("kind"), "status": "skipped (not approved)"})

        report = (
            f"web_automation_engineer verdict for {target}: "
            f"classification={classification}; "
            f"model_available={state.get('model_available', True)}; "
            f"ci_conclusion={state.get('run_conclusion') or state.get('run_recon_error') or 'unknown'}; "
            f"run_url={state.get('run_url') or 'n/a'}; "
            f"dispatched(unit={state.get('unit_dispatched', False)}, "
            f"e2e={state.get('e2e_dispatched', False)}); "
            f"actions={executed or 'report-only'}"
        )
        governance_capture(
            "web_automation_engineer",
            {
                "target": target,
                "classification": classification,
                "model_available": state.get("model_available", True),
                "run_conclusion": state.get("run_conclusion"),
                "run_url": state.get("run_url"),
                "run_sha": state.get("run_sha"),
                "run_recon_error": state.get("run_recon_error"),
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
builder.add_node("read_run", read_run)
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
# Read the dispatched run's REAL conclusion back before triage classifies it.
builder.add_edge("dispatch", "read_run")
builder.add_edge("read_run", "triage")
builder.add_edge("triage", "gate")
builder.add_edge("gate", "finalize")
builder.add_edge("finalize", END)

graph = builder.compile()  # NO checkpointer/store — injected by the platform
