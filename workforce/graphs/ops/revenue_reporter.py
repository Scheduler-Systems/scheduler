"""revenue_reporter — the weekly revenue + pipeline digest agent.

Runtime: cloud/CI (LangGraph Platform managed Cloud SaaS); register-able in
``langgraph.json`` (the orchestrator owns that file — not this module).

MISSION: once a week, gather three signals and deliver a single human-readable digest:
  1. RevenueCat headline metrics (MRR, active subs/trials, revenue) — the money number,
  2. Deploy state of the Scheduler product repos (latest GitHub Actions run per repo),
  3. A best-effort pipeline summary (open PR/issue counts across the workspace),
then compose a concise weekly report (model where available, deterministic fallback when
not) and deliver it as a GitHub issue digest.

LOAD-BEARING DECISIONS (match the ops-fleet house style — see hr_ops_manager,
web_automation_engineer, git_local_maintainer):

  * PROBATION / REPORT-ONLY by default. The digest is delivered via
    ``file_digest_issue(..., report_only=_report_only())`` where ``_report_only()`` defaults
    True (env ``OPS_REPORT_ONLY``; only "0"/"false"/"no" turns it off). On probation the
    delivery is an honest ``{"status": "report_only", ...}`` plan dict — NO GitHub write and,
    critically, NO approval interrupt — so a scheduled unattended run can never hang or write.

  * NEVER HANG. With no credentials the run still completes: RevenueCat / GitHub / work-board
    calls are each wrapped so a missing key / offline / SDK drift returns a structured result
    and the node moves on. A telemetry/network problem never crashes a node.

  * FAIL-SAFE compose. The model is used ONLY to phrase the gathered facts; on ANY model
    failure (no key, budget, SDK drift) we fall back to a DETERMINISTIC text report built
    directly from the gathered dicts, so a digest is always produced.

  * ANTHROPIC-TERMS / ML BOUNDARY. ``assert_not_model_work`` guards every outward repo string
    (the Scheduler repos and the digest repo). No model train/eval/distill; gal-model and the
    policy denylist are never read or reported.

  * Compiles WITHOUT a checkpointer/store (the platform injects Postgres). Every node body is
    wrapped in ``span("revenue_reporter.<node>", ...)``; governance is captured at the end.
"""
from __future__ import annotations

import os

import threading

from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END

from agent_toolkit import (
    budget_guard,
    check_clocked_in,
    span,
    governance_capture,
    assert_not_model_work,
    TIER_DEFAULT,
)
from agent_toolkit import revenuecat
from agent_toolkit import work_board
from agent_toolkit.github_ops import GitHubOps
from agent_toolkit.ops_report import write_local_digest, file_digest_issue

# The repo the weekly digest issue is filed into (allow-listed in github_ops).
DIGEST_REPO = "Scheduler-Systems/qa-agent-platform"
# The product repos whose deploy/CI state we report on.
SCHEDULER_REPOS = [
    "Scheduler-Systems/scheduler-web",
    "Scheduler-Systems/scheduler-api",
    "Scheduler-Systems/scheduler-ios",
    "Scheduler-Systems/scheduler-android",
]


# Hard wall-clock bound for the pipeline recon. ``work_board.fetch_open_issues`` shells out
# to ``gh`` via ``subprocess.run(..., check=True)`` with NO ``timeout=``; in the cloud a
# stalled network or a credential helper prompting on stdin would block that subprocess
# forever, and a bare ``try/except`` cannot bound wall-clock time. We run the call in a
# worker thread and abandon it on timeout so an unattended scheduled run can NEVER hang.
# (Env ``OPS_PIPELINE_TIMEOUT`` overrides; default 15s.)
def _pipeline_timeout() -> float:
    try:
        return max(1.0, float(os.environ.get("OPS_PIPELINE_TIMEOUT", "15")))
    except (TypeError, ValueError):
        return 15.0


def _fetch_pipeline() -> dict:
    """Bounded, fail-safe open-issue recon. Returns ``{"note": "unavailable"}`` on any
    error OR if the underlying ``gh`` subprocess does not finish within the wall-clock
    bound — so ``gather`` can never block on a stalled subprocess.

    The work runs in a DAEMON thread: on timeout we abandon it and return promptly. A
    daemon thread can never hold the interpreter open at exit, so even a permanently
    wedged ``gh`` child cannot keep an unattended run alive past process teardown.
    """
    box: dict = {}

    def _run() -> None:
        try:
            box["items"] = work_board.fetch_open_issues()
        except Exception as exc:  # any error inside the worker — record + degrade
            box["error"] = type(exc).__name__

    worker = threading.Thread(target=_run, name="revenue_reporter.pipeline", daemon=True)
    worker.start()
    worker.join(timeout=_pipeline_timeout())
    if worker.is_alive() or "items" not in box:
        # Still running (gh wedged) or the worker errored — degrade, never block.
        return {"note": "unavailable"}

    try:
        items = box["items"]
        per_repo: dict = {}
        for it in items:
            per_repo[it.repo] = per_repo.get(it.repo, 0) + 1
        return {"open_items": len(items), "by_repo": per_repo}
    except Exception:
        return {"note": "unavailable"}


def _report_only() -> bool:
    """Report-only default for the probation agent: truthy/unset env => True.

    Only an explicit ``OPS_REPORT_ONLY`` of "0"/"false"/"no" turns delivery into a real
    (gated) GitHub write. Everything else — including the env being unset — keeps the agent
    in honest report-only mode (no GitHub call, no approval interrupt).
    """
    return os.environ.get("OPS_REPORT_ONLY", "").lower() not in ("0", "false", "no")


class State(TypedDict, total=False):
    mode: str            # reserved for future read-only/observe variants
    rc: dict             # RevenueCat metrics_overview() result (fail-safe)
    deploy: dict         # repo -> latest CI run dict (or {"error": <type>})
    pipeline: dict       # open PR/issue counts (or {"note": "unavailable"})
    summary: str         # composed weekly report text
    report: dict         # terminal verdict
    report_only: bool    # whether delivery stayed report-only


def budget_gate(state: State) -> dict:
    """CLOCK-IN gate — STOP before any work if over salary or globally disabled.

    Runs FIRST. If clocked in, control passes to ``gather``; if not, we capture governance
    (report-only) and route to END. No RC/GitHub calls, no model spend, no writes on the
    clocked-out path.
    """
    with span("revenue_reporter.budget_gate"):
        if check_clocked_in("revenue_reporter"):
            return {}
        governance_capture(
            "revenue_reporter",
            {
                "clocked_in": False,
                "delivery": "skipped",
                "report_only": True,
            },
        )
        return {"report": {"clocked_in": False}}


def gather(state: State) -> dict:
    """Collect the three signals — RevenueCat, deploy state, pipeline. Every call FAIL-SAFE.

    - ``rc``       : ``revenuecat.metrics_overview()`` already returns a structured
                     ``{"ok": bool, "metrics": ..., "error": ...}`` dict; it never raises.
    - ``deploy``   : per Scheduler repo, guard the repo string (Anthropic terms) and read the
                     latest CI run via ``GitHubOps().latest_run`` wrapped so ANY error becomes
                     ``{"error": <type>}`` (no token / offline / SDK drift never crashes).
    - ``pipeline`` : best-effort open PR/issue counts via ``work_board.fetch_open_issues``
                     (the cloud container may lack ``gh``); on any failure we degrade to
                     ``{"note": "unavailable"}``.
    """
    with span("revenue_reporter.gather", repos=len(SCHEDULER_REPOS)):
        # 1) RevenueCat — already fail-safe.
        rc = revenuecat.metrics_overview()

        # 2) Deploy state per product repo — guard + wrap every read.
        deploy: dict = {}
        for repo in SCHEDULER_REPOS:
            assert_not_model_work(repo)  # never read/report an ML-model repo
            try:
                deploy[repo] = GitHubOps().latest_run(repo, "main")
            except Exception as exc:  # no creds / offline / SDK drift — degrade per repo
                deploy[repo] = {"error": type(exc).__name__}

        # 3) Pipeline summary — best-effort AND wall-clock-bounded (the cloud env may lack
        #    gh, or gh may stall on a network/auth prompt); see _fetch_pipeline. Never hangs.
        pipeline = _fetch_pipeline()

        return {"rc": rc, "deploy": deploy, "pipeline": pipeline}


def compose(state: State) -> dict:
    """Phrase the gathered facts as a concise weekly report. FAIL-SAFE.

    The model (TIER_DEFAULT, metered via ``budget_guard``) is used ONLY to summarize the
    already-gathered dicts. On ANY failure (no key, budget, SDK drift) we fall back to a
    DETERMINISTIC text report built directly from rc/deploy/pipeline, so a digest is always
    produced. No model train/eval/distill — phrasing only.
    """
    rc = state.get("rc") or {}
    deploy = state.get("deploy") or {}
    pipeline = state.get("pipeline") or {}

    with span("revenue_reporter.compose", rc_ok=bool(rc.get("ok"))):
        facts = _deterministic_report(rc, deploy, pipeline)
        summary = ""
        try:
            model = budget_guard("revenue_reporter", TIER_DEFAULT)
            prompt = (
                "You are the revenue/ops reporter for the Scheduler product fleet. Write a "
                "CONCISE weekly report for the team from the gathered facts below. Cover, in "
                "order: (1) the RevenueCat money signal (MRR / active subs / trials / revenue — "
                "or clearly note when metrics were unavailable), (2) the deploy/CI state of each "
                "Scheduler repo, (3) the open pipeline (PR/issue counts). Do NOT invent numbers; "
                "only report what the facts show. Be direct and skimmable.\n\n"
                f"{facts}"
            )
            resp = model.invoke(prompt)
            summary = getattr(resp, "content", str(resp)) or ""
        except Exception as exc:  # model unavailable — deterministic fallback (never empty)
            summary = (
                f"(model summary unavailable: {type(exc).__name__}) — deterministic report:\n\n"
                f"{facts}"
            )

        if not summary.strip():  # belt-and-suspenders: never deliver an empty summary
            summary = facts
        return {"summary": summary}


def deliver(state: State) -> dict:
    """Write a local digest artifact and file the weekly digest issue (report-only on probation).

    - ``write_local_digest`` always runs (succeeds-or-"" ; never raises) so there is a local
      artifact even with zero credentials.
    - ``file_digest_issue(..., report_only=_report_only())`` delivers the issue. On probation
      (the default) this returns an honest report-only plan dict with NO GitHub call and NO
      approval interrupt — an unattended run can never hang or write.
    """
    summary = state.get("summary") or ""
    rc = state.get("rc") or {}
    deploy = state.get("deploy") or {}
    pipeline = state.get("pipeline") or {}
    report_only = _report_only()

    with span("revenue_reporter.deliver", report_only=report_only):
        body = summary + "\n\n---\n\n## Raw facts\n\n" + _facts_appendix(rc, deploy, pipeline)

        # Local artifact first — always, fail-safe.
        digest_path = write_local_digest(
            "revenue-reporter", "Weekly revenue + pipeline", body
        )

        # GitHub issue delivery — report-only by default (no write, no interrupt).
        res = file_digest_issue(
            DIGEST_REPO,
            "Weekly revenue + pipeline report",
            body,
            labels=["report:weekly"],
            report_only=report_only,
            agent="revenue_reporter",
            slack_title="📊 Weekly Revenue Report",
        )

        return {
            "report": {
                "delivery": res.get("status"),
                "digest": digest_path,
                "report_only": report_only,
                "slack": res.get("slack"),
            },
            "report_only": report_only,
        }


def finalize(state: State) -> dict:
    """Terminal node — capture governance (report-only) and emit the verdict."""
    rc = state.get("rc") or {}
    deploy = state.get("deploy") or {}
    prior = state.get("report") or {}
    delivery = prior.get("delivery")

    with span("revenue_reporter.finalize", delivery=delivery):
        governance_capture(
            "revenue_reporter",
            {
                "rc_ok": rc.get("ok"),
                "repos": len(deploy),
                "delivery": delivery,
                "report_only": True,
            },
        )
        return {
            "report": {
                "rc_ok": rc.get("ok"),
                "repos": len(deploy),
                "delivery": delivery,
                "digest": prior.get("digest"),
                "report_only": True,
            }
        }


def _budget_route(state: State) -> str:
    """Route past the clock-in gate: clocked in -> gather; clocked out -> END."""
    return "gather" if check_clocked_in("revenue_reporter") else "clocked_out"


# --- Deterministic report helpers (used by compose fallback + the issue appendix) --------
def _fmt_rc(rc: dict) -> list[str]:
    if not rc.get("ok"):
        return [f"- RevenueCat: unavailable ({rc.get('error') or 'no metrics'})"]
    metrics = rc.get("metrics") or {}
    if not metrics:
        return ["- RevenueCat: ok, but no metrics returned"]
    return ["- RevenueCat metrics:"] + [
        f"    - {key}: {value}" for key, value in sorted(metrics.items())
    ]


def _fmt_deploy(deploy: dict) -> list[str]:
    lines: list[str] = ["- Deploy / CI state:"]
    if not deploy:
        return ["- Deploy / CI state: (no repos checked)"]
    for repo in SCHEDULER_REPOS:
        info = deploy.get(repo) or {}
        if info.get("error"):
            lines.append(f"    - {repo}: error ({info['error']})")
        else:
            lines.append(
                f"    - {repo}: status={info.get('status')} "
                f"conclusion={info.get('conclusion')}"
            )
    return lines


def _fmt_pipeline(pipeline: dict) -> list[str]:
    if pipeline.get("note") == "unavailable":
        return ["- Pipeline: unavailable (gh not reachable)"]
    return [f"- Pipeline: {pipeline.get('open_items', 0)} open PR/issue items"]


def _deterministic_report(rc: dict, deploy: dict, pipeline: dict) -> str:
    """A skimmable plain-text report built ENTIRELY from the gathered dicts (no model)."""
    lines = ["Weekly revenue + pipeline report", ""]
    lines += _fmt_rc(rc)
    lines += _fmt_deploy(deploy)
    lines += _fmt_pipeline(pipeline)
    return "\n".join(lines)


def _facts_appendix(rc: dict, deploy: dict, pipeline: dict) -> str:
    """The raw gathered facts, appended verbatim to the digest body for auditability."""
    return _deterministic_report(rc, deploy, pipeline)


# --- Graph wiring ------------------------------------------------------------------------
builder = StateGraph(State)
builder.add_node("budget_gate", budget_gate)
builder.add_node("gather", gather)
builder.add_node("compose", compose)
builder.add_node("deliver", deliver)
builder.add_node("finalize", finalize)
# CLOCK-IN gate runs first: clocked out -> governance + END; otherwise enter the pipeline.
builder.add_edge(START, "budget_gate")
builder.add_conditional_edges(
    "budget_gate",
    _budget_route,
    {"gather": "gather", "clocked_out": END},
)
builder.add_edge("gather", "compose")
builder.add_edge("compose", "deliver")
builder.add_edge("deliver", "finalize")
builder.add_edge("finalize", END)

graph = builder.compile()  # NO checkpointer/store — injected by the platform
