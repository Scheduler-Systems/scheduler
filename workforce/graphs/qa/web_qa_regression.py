"""web_qa_regression — the web QA agent's scheduled shift work: watch scheduler-web's
`main` for regressions, triage them, and report.

Deployed-agent friendly: the observe path (read latest COMPLETED CI run + model-triage the
failure + emit a verdict via governance/OTel) is READ-ONLY and runs unattended with no human
gate. Only the issue-opening (write) passes the approval gate — so until the AUTO authority
router lands (epic #18), the write step is supervised; the read+verdict already works
deployed.

Hardening in this revision (all report-only, no gate crossing):
  * latest_completed run selection — an IN-PROGRESS run (conclusion=None) no longer reads as
    "green". We pick the newest *completed* run, optionally scoped to the CI workflow.
  * unconfigured vs error — a missing GitHub token (``GitHubNotConfigured``) now yields the
    verdict "unconfigured" (a config gap), distinct from a genuine recon failure ("error").
  * bounded retry/backoff on the single GitHub read so a transient 5xx/429 doesn't poison a
    shift's verdict.
  * model triage — on a real REGRESSION the agent uses the cost-routed model (budget-guarded,
    fail-safe) to summarise what regressed; this is orchestration, not model work.
  * NEW-vs-still-failing — the head_sha of the failing run is carried so a verdict can say
    whether this is a fresh regression or the same one as last shift.
  * open-issue dedup — before the (gated) write, we check for an existing OPEN
    "QA: regression on main" issue so a persistent failure doesn't file a duplicate each shift.

The CLOCK-IN gate (kill-switch + per-agent bench + over-budget) runs FIRST so a disabled
fleet does zero work.

State in: optional {target, branch, last_reported_sha}.
State out: {conclusion, run_url, head_sha, run_id, verdict, is_new, triage, issue}.
"""
from __future__ import annotations

import os
import time
from typing import Any, Optional

from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END

from agent_toolkit import (
    span,
    governance_capture,
    assert_not_model_work,
    budget_guard,
    check_clocked_in,
    TIER_DEFAULT,
)
from agent_toolkit.github_ops import (
    GitHubOps,
    GitHubNotConfigured,
    assert_allowed_repo,
)

AGENT = "web_qa_regression"
DEFAULT_TARGET = "Scheduler-Systems/scheduler-web"
ISSUE_TITLE = "QA: regression on main"

# Scope recon to the scheduler-web CI gate workflow when present, so an unrelated workflow
# (e.g. a docs-only run) doesn't drive the regression verdict. Overridable via env for reuse.
CI_WORKFLOW_HINT = os.environ.get("WEB_QA_CI_WORKFLOW", "gate.yml")

_READ_RETRIES = 3          # bounded — a deployed shift must finish, not hang
_READ_BACKOFF_SECS = 0.5   # 0.5s, 1.0s between the read attempts


class State(TypedDict, total=False):
    target: str
    branch: str
    last_reported_sha: str   # head_sha we last filed/observed a regression for (NEW vs still)
    conclusion: str
    run_url: str
    head_sha: str
    run_id: int
    verdict: str
    is_new: bool
    triage: str
    issue: dict


def _select_completed_run(runs: Any, workflow_hint: Optional[str]) -> Optional[Any]:
    """Pick the newest COMPLETED run from a newest-first iterable.

    Skips in-progress runs (status != "completed" / conclusion is None) so an unfinished
    run can never be mistaken for a green shift. Prefers a run whose workflow looks like the
    CI gate (``workflow_hint``); if none of the completed runs match the hint, falls back to
    the newest completed run regardless of workflow (better a real verdict than none).
    """
    newest_completed = None
    for run in runs:  # newest first
        if getattr(run, "status", None) != "completed" or getattr(run, "conclusion", None) is None:
            continue
        if newest_completed is None:
            newest_completed = run  # first completed run = fallback
        if workflow_hint:
            name = (getattr(run, "path", None) or getattr(run, "name", "") or "")
            if workflow_hint in name:
                return run  # newest completed run on the CI gate workflow
    return newest_completed


def _latest_completed_run(repo: str, branch: str) -> dict:
    """Read-only recon: newest COMPLETED CI run for ``repo@branch``.

    Lives in the GRAPH (not the shared toolkit) so the in-progress-skipping + CI-scoping
    logic is owned by this agent without changing a cross-agent surface. Still passes the
    toolkit's ``assert_allowed_repo`` guard (allow-list + model-work) and reuses the same
    fail-closed ``GitHubOps._client()`` for auth, so an absent token raises
    ``GitHubNotConfigured`` exactly as a write would. Bounded retry/backoff wraps the single
    network read so a transient 5xx/429 doesn't poison the shift's verdict.
    """
    assert_allowed_repo(repo)  # allow-list + Anthropic-terms model-work guard
    ops = GitHubOps()
    last_exc: Optional[Exception] = None
    for attempt in range(_READ_RETRIES):
        try:
            client = ops._client()  # fail-closed: raises GitHubNotConfigured with no token
            r = client.get_repo(repo)
            # Server-side scope to completed runs on the branch (newest first).
            runs = r.get_workflow_runs(branch=branch, status="completed")
            run = _select_completed_run(runs, CI_WORKFLOW_HINT)
            if run is None:
                return {
                    "status": None,
                    "conclusion": None,
                    "html_url": None,
                    "name": None,
                    "head_sha": None,
                    "run_id": None,
                }
            return {
                "status": run.status,
                "conclusion": run.conclusion,
                "html_url": run.html_url,
                "name": getattr(run, "name", None),
                "head_sha": getattr(run, "head_sha", None),
                "run_id": getattr(run, "id", None),
            }
        except GitHubNotConfigured:
            raise  # config gap, not a transient fault — don't waste retries
        except Exception as exc:  # transient (5xx/429/network) — bounded retry
            last_exc = exc
            if attempt < _READ_RETRIES - 1:
                time.sleep(_READ_BACKOFF_SECS * (attempt + 1))
    raise last_exc if last_exc else RuntimeError("recon failed with no exception")


def plan(state: State) -> dict:
    target = state.get("target", DEFAULT_TARGET)
    assert_not_model_work(target)  # Anthropic-terms guard
    return {"target": target, "branch": state.get("branch", "main")}


def check(state: State) -> dict:
    """Read-only recon — works unattended (no gate).

    Distinguishes three outcomes so the verdict is honest:
      * ``GitHubNotConfigured`` -> conclusion ``"unconfigured"`` (a config gap, not CI status).
      * any other exception     -> conclusion ``"error: <TypeName>"`` (a real recon failure).
      * success                 -> the real CI conclusion of the newest COMPLETED run.
    Only the exception TYPE is recorded — never ``str(e)`` — so no token/URL/secret that might
    be in a message reaches the governance/observability sink.
    """
    with span("web_qa_regression.check", target=state["target"], branch=state["branch"]):
        try:
            info = _latest_completed_run(state["target"], state["branch"])
            return {
                "conclusion": info.get("conclusion") or "",
                "run_url": info.get("html_url") or "",
                "head_sha": info.get("head_sha") or "",
                "run_id": info.get("run_id") or 0,
            }
        except GitHubNotConfigured:
            # Missing credentials must not masquerade as a CI error — it's a config gap.
            return {"conclusion": "unconfigured", "run_url": "", "head_sha": "", "run_id": 0}
        except Exception as e:
            # Resilient: a deployed agent must complete + surface the cause, not crash.
            return {"conclusion": f"error: {type(e).__name__}", "run_url": "", "head_sha": "", "run_id": 0}


def _triage_regression(state: State) -> str:
    """Model-triage a confirmed regression — orchestration, NOT model work.

    Budget-guarded + fail-safe: if no model key / over budget, we degrade to a deterministic
    one-liner rather than crash the shift. Report-only — produces text only, no side effects.
    """
    head_sha = state.get("head_sha") or "?"
    run_url = state.get("run_url") or "?"
    fallback = (
        f"CI gate concluded FAILURE on {state['target']}@{state['branch']} "
        f"(commit {head_sha[:8] if head_sha != '?' else '?'}). Run: {run_url}"
    )
    try:
        model = budget_guard(AGENT, TIER_DEFAULT)
        prompt = (
            "You are the web QA regression agent for the scheduler-web Next.js app. The latest "
            "COMPLETED CI gate run on the watched branch concluded FAILURE — a regression.\n"
            f"repo={state['target']} branch={state['branch']} head_sha={head_sha}\n"
            f"run_url={run_url}\n\n"
            "Write 2-3 sentences for the on-call engineer: what this signals, how urgent it is "
            "for a production web app, and the first thing to check. Do NOT invent specific test "
            "names or stack traces you have not been given; reason only from what is stated."
        )
        resp = model.invoke(prompt)
        text = getattr(resp, "content", str(resp)) or ""
        return text.strip() or fallback
    except Exception as exc:  # model unavailable / over budget — never crash the shift
        return f"{fallback}\n(model triage unavailable: {type(exc).__name__})"


def verdict(state: State) -> dict:
    c = state.get("conclusion") or ""
    if c == "unconfigured":
        v = "unconfigured"   # config gap — a token must be injected; NOT a CI failure
    elif c.startswith("error:"):
        v = "error"          # recon failed — surface it, don't file a false regression
    elif c == "failure":
        v = "REGRESSION"
    elif c == "":
        v = "unknown"        # no completed run found yet (e.g. brand-new branch)
    else:
        v = "green"

    # NEW vs still-failing: compare this failing run's head_sha to the last one we reported on.
    head_sha = state.get("head_sha") or ""
    last = state.get("last_reported_sha") or ""
    is_new = bool(head_sha) and head_sha != last

    triage = ""
    if v == "REGRESSION":
        triage = _triage_regression(state)

    governance_capture(
        AGENT,
        {
            "target": state["target"],
            "branch": state["branch"],
            "conclusion": state.get("conclusion"),
            "verdict": v,
            "is_new": is_new,
            "head_sha": head_sha,
            "run_id": state.get("run_id"),
            "run_url": state.get("run_url"),
            "report_only": True,
        },
    )
    out: dict = {"verdict": v, "is_new": is_new}
    if triage:
        out["triage"] = triage
    return out


def _existing_open_regression_issue(repo: str) -> Optional[int]:
    """Return the number of an already-open ``QA: regression on main`` issue, else None.

    Read-only dedup guard: prevents a persistent main failure from filing a duplicate issue
    every shift. Best-effort — any read failure returns None so dedup never BLOCKS a legit
    file (the gate is the real safety net, not this lookup)."""
    try:
        assert_allowed_repo(repo)
        client = GitHubOps()._client()  # fail-closed (GitHubNotConfigured) with no token
        r = client.get_repo(repo)
        for issue in r.get_issues(state="open", labels=["gate:human-required"]):
            if (issue.title or "").strip() == ISSUE_TITLE and getattr(issue, "pull_request", None) is None:
                return issue.number
        return None
    except Exception:
        return None


def report(state: State) -> dict:
    """Write path — gated (supervised) until the AUTO authority router lands.

    Files a regression issue ONLY when the verdict is REGRESSION *and* no open
    ``QA: regression on main`` issue already exists (dedup). The actual write still flows
    through ``GitHubOps.open_issue``, which is report-only by default and otherwise
    human-gated — this function never crosses that gate, it only avoids spamming duplicates.
    """
    v = state.get("verdict")
    if v != "REGRESSION":
        return {"issue": {"status": f"no-op ({v})"}}

    existing = _existing_open_regression_issue(state["target"])
    if existing is not None:
        return {
            "issue": {
                "status": "deduped",
                "existing_issue": existing,
                "note": "open regression issue already on file; not filing a duplicate",
            }
        }

    new_marker = "NEW regression" if state.get("is_new") else "still-failing regression"
    triage = state.get("triage") or ""
    body = (
        f"{new_marker} detected on `{state['target']}@{state['branch']}`: the latest COMPLETED "
        f"CI run concluded **failure**.\n\n"
        f"Commit: `{(state.get('head_sha') or '')[:12]}`\nRun: {state.get('run_url')}\n\n"
        + (f"Triage:\n{triage}\n\n" if triage else "")
        + "Filed by the web QA agent on its scheduled shift."
    )
    res = GitHubOps().open_issue(
        state["target"],
        ISSUE_TITLE,
        body,
        labels=["gate:human-required"],
        dedup_key=f"web_qa_regression:{state['target']}:regression-on-main",
        agent=AGENT,
    )
    return {"issue": res}


def clock_in(state: State) -> dict:
    """CLOCK-IN gate — runs FIRST. STOP all work if the agent is over salary or the fleet is
    globally disabled (kill switch ``AGENTS_DISABLED`` / ``FLEET_DISABLED`` / per-agent bench).
    No recon, no model spend, no writes on the clocked-out path."""
    with span("web_qa_regression.clock_in"):
        if check_clocked_in(AGENT):
            return {}
        governance_capture(
            AGENT,
            {"clocked_in": False, "verdict": "skipped", "report_only": True},
        )
        return {"verdict": "skipped", "issue": {"status": "skipped (clocked out)"}}


def _route_after_clock_in(state: State) -> str:
    return "clocked_out" if state.get("verdict") == "skipped" else "plan"


builder = StateGraph(State)
builder.add_node("clock_in", clock_in)
builder.add_node("plan", plan)
builder.add_node("check", check)
builder.add_node("verdict", verdict)
builder.add_node("report", report)
builder.add_edge(START, "clock_in")
builder.add_conditional_edges(
    "clock_in", _route_after_clock_in, {"plan": "plan", "clocked_out": END}
)
builder.add_edge("plan", "check")
builder.add_edge("check", "verdict")
builder.add_edge("verdict", "report")
builder.add_edge("report", END)

graph = builder.compile()  # NO checkpointer/store — injected by the platform
