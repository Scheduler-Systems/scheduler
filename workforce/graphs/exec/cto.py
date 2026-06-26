"""cto — the Chief Technology Officer officer (repo/deploy/security posture, PROPOSE-ONLY).

Runtime: cloud/CI (LangGraph Platform managed Cloud SaaS); register-able in
``langgraph.json`` (the orchestrator owns that file — not this module).

The CTO is an EXECUTIVE: it CONSUMES the fleet's reports rather than re-doing work. It reads
its own prior digest (``read_local_digest("cto")``) for continuity, observes the deploy/CI
state of every Scheduler product repo + the qa-agent-platform via the read-only
``GitHubOps().latest_run`` recon (each call wrapped FAIL-SAFE), carries the HELD IDOR
entitlement rollout as a standing open security item, and lands every tech/security action as
a PROPOSAL in a digest issue. It NEVER merges, deploys, or mutates anything itself — merges
and deploys are escalated to Shay; everything else is resolved inside the org.

LOAD-BEARING DECISIONS (match the ops-fleet house style — see revenue_reporter, daily_digest,
hr_ops_manager):

  * PROBATION / REPORT-ONLY by default. The digest is delivered via
    ``file_digest_issue(..., report_only=_report_only())`` where ``_report_only()`` defaults
    True (env ``OPS_REPORT_ONLY``; only "0"/"false"/"no" turns it off). On probation the
    delivery is an honest ``{"status": "report_only", ...}`` plan dict — NO GitHub write and,
    critically, NO approval interrupt — so a scheduled unattended run can never hang or write.

  * NEVER HANG. There is no reachable ``request_approval``/interrupt on the scheduled path.
    With no credentials the run still completes: every GitHub read is wrapped so a missing key
    / offline / SDK drift returns a structured ``{"error": <type>}`` per repo and the node
    moves on. The model is OPTIONAL phrasing only; on any model failure we keep the
    deterministic body. A telemetry/network problem never crashes a node.

  * FAIL-SAFE everywhere. Prior-digest read, per-repo CI recon, and the model summary are each
    wrapped; missing data => deterministic fallback; the digest is ALWAYS produced.

  * ANTHROPIC-TERMS / ML BOUNDARY. ``assert_not_model_work`` guards every outward repo string
    (the product/platform repos and the digest repo) before any read/report. No model
    train/eval/distill; gal-model / denylisted ids are skipped per repo, never reported.

  * INVESTOR ESCALATION. Only capital/irreversible/legal items are "asks for Shay". Merges and
    production deploys are irreversible-to-paying-users, so they escalate to ``"shay"``;
    everything else (raise a tracking issue, add a CI gate, prep a security fix branch) is
    resolved inside the org and escalates to ``"org"``.

  * Compiles WITHOUT a checkpointer/store (the platform injects Postgres). Every node body is
    wrapped in ``span("cto.<node>", ...)``; governance is captured (report_only=True) terminally.
"""
from __future__ import annotations

import os

from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END

from agent_toolkit import (
    budget_guard,
    check_clocked_in,
    span,
    governance_capture,
    assert_not_model_work,
    read_local_digest,
    write_local_digest,
    file_digest_issue,
    TIER_DEFAULT,
)
from agent_toolkit.github_ops import GitHubOps
from agent_toolkit.policy import ModelWorkBlocked
from agent_toolkit import lanes

# This officer's slug (prior-digest read + local artifact path).
AGENT = "cto"
# The repo the CTO posture digest issue is filed into (allow-listed in github_ops).
DIGEST_REPO = "Scheduler-Systems/qa-agent-platform"
# The repos whose deploy/CI/security posture the CTO reports on: the Scheduler product repos
# plus the platform repo the fleet itself ships from.
TECH_REPOS = [
    "Scheduler-Systems/scheduler-web",
    "Scheduler-Systems/scheduler-api",
    "Scheduler-Systems/scheduler-ios",
    "Scheduler-Systems/scheduler-android",
    "Scheduler-Systems/qa-agent-platform",
]
# The repos a red CI / pending rollout on is escalated to SHAY (a merge/deploy there is
# irreversible to paying users). Other tech actions are resolved inside the org.
PROD_REPOS = frozenset(
    {
        "Scheduler-Systems/scheduler-web",
        "Scheduler-Systems/scheduler-api",
        "Scheduler-Systems/scheduler-ios",
        "Scheduler-Systems/scheduler-android",
    }
)

# THE STANDING OPEN SECURITY ITEM: the Firestore IDOR entitlement-rollout is fixed but HELD —
# validated server-maintained schedule_acl rules (20/20) are NOT deployed to production, so the
# live IDOR remains open until a human ships the gated multi-step rollout. The CTO surfaces this
# every run until it is resolved; deploying it is irreversible to prod, so it escalates to Shay.
#
# RELOCATED (step-3 simplify): the dossier CONTENT now lives in ``agent_toolkit.lanes`` as the
# single source of truth (``lanes.IDOR_SECURITY_ITEM`` / ``lanes.idor_security_item()``), owned by
# the lane registry rather than this agent — so the IDOR posture survives the CTO's eventual
# offboard (the Board audit_risk_director reads the SAME lanes source). The CTO simply re-exports
# the lanes constant under its established name (``cto.IDOR_SECURITY_ITEM``) for continuity.
IDOR_SECURITY_ITEM = lanes.IDOR_SECURITY_ITEM


def _report_only() -> bool:
    """Report-only default for the probation officer: truthy/unset env => True.

    Only an explicit ``OPS_REPORT_ONLY`` of "0"/"false"/"no" turns delivery into a real
    (gated) GitHub write. Everything else — including the env being unset — keeps the officer
    in honest report-only mode (no GitHub call, no approval interrupt).
    """
    return os.environ.get("OPS_REPORT_ONLY", "").lower() not in ("0", "false", "no")


class State(TypedDict, total=False):
    mode: str            # reserved for future read-only/observe variants
    prior: str           # the CTO's prior local digest (continuity), or "(no digest yet)"
    deploy: dict         # repo -> latest CI run dict (or {"error": <type>}/{"skipped": ...})
    security: list       # standing/open security items (IDOR rollout, + derived)
    findings: list       # analyzed red-CI / pending-rollout flags
    proposals: list      # tech/security proposals (each tagged escalate_to org|shay)
    summary: str         # composed posture report text
    report: dict         # terminal verdict
    report_only: bool    # whether delivery stayed report-only


def budget_gate(state: State) -> dict:
    """CLOCK-IN gate — STOP before any work if over salary or globally disabled.

    Runs FIRST. If clocked in, control passes to ``gather``; if not, we capture governance
    (report-only) and route to END. No GitHub recon, no model spend, no writes on the
    clocked-out path.
    """
    with span("cto.budget_gate"):
        if check_clocked_in(AGENT):
            return {}
        governance_capture(
            AGENT,
            {
                "clocked_in": False,
                "delivery": "skipped",
                "report_only": True,
            },
        )
        return {"report": {"clocked_in": False}}


def gather(state: State) -> dict:
    """Observe posture: read the prior CTO digest + per-repo CI state; seed the security list.

    Every read FAIL-SAFE:
    - ``prior``    : ``read_local_digest("cto")`` for continuity (never raises; "(no digest yet)").
    - ``deploy``   : per repo, guard the repo string (Anthropic terms — a denylisted repo is
                     SKIPPED, never read/reported) and read the latest CI run via the read-only
                     ``GitHubOps().latest_run`` wrapped so ANY error becomes ``{"error": <type>}``
                     (no token / offline / SDK drift never crashes).
    - ``security`` : seed with the standing HELD IDOR item (always surfaced until resolved).
    """
    with span("cto.gather", repos=len(TECH_REPOS)):
        prior = read_local_digest(AGENT)

        deploy: dict = {}
        for repo in TECH_REPOS:
            try:
                assert_not_model_work(repo)  # never read/report an ML-model repo
            except ModelWorkBlocked:
                deploy[repo] = {"skipped": "model_work_denylist"}
                continue
            try:
                deploy[repo] = GitHubOps().latest_run(repo, "main")
            except Exception as exc:  # no creds / offline / SDK drift — degrade per repo
                deploy[repo] = {"error": type(exc).__name__}

        # The HELD IDOR entitlement rollout is a STANDING open security item — surface it every
        # run until it is shipped. Read the dossier from the AUTHORITATIVE lanes source (a copy so
        # downstream mutation can't corrupt the constant); lanes owns the facts now.
        security = [lanes.idor_security_item()]

        return {"prior": prior, "deploy": deploy, "security": security}


def analyze(state: State) -> dict:
    """Flag red CI and pending security rollouts. Deterministic — no model, no network.

    A repo is RED when its latest run concluded anything other than success (failure/cancelled/
    timed_out), or the recon itself errored (we cannot confirm green). Each red prod repo is a
    SHAY escalation (a fix-merge/deploy there is irreversible to paying users); a red non-prod
    repo is resolved inside the org. The HELD IDOR rollout is carried straight through as a
    pending security finding.
    """
    deploy = state.get("deploy") or {}
    security = state.get("security") or []

    with span("cto.analyze", repos=len(deploy)):
        findings: list = []
        for repo in TECH_REPOS:
            info = deploy.get(repo) or {}
            if info.get("skipped"):
                continue  # denylisted repo — never analyzed/reported
            prod = repo in PROD_REPOS
            if info.get("error"):
                findings.append(
                    {
                        "kind": "ci_unknown",
                        "repo": repo,
                        "detail": f"CI state unavailable ({info['error']}) — cannot confirm green",
                        "escalate_to": "org",  # a recon gap is an org task, not a capital ask
                    }
                )
                continue
            conclusion = info.get("conclusion")
            if conclusion is not None and conclusion != "success":
                findings.append(
                    {
                        "kind": "ci_red",
                        "repo": repo,
                        "detail": f"latest CI conclusion={conclusion} (status={info.get('status')})",
                        # A red PROD repo's fix-merge/deploy is irreversible → Shay; else org.
                        "escalate_to": "shay" if prod else "org",
                    }
                )

        # Pending security rollouts carried from gather (e.g. the HELD IDOR item).
        for item in security:
            if item.get("status") in ("held", "pending", "open"):
                findings.append(
                    {
                        "kind": "security_pending",
                        "repo": None,
                        "detail": f"{item.get('title')} — {item.get('detail')}",
                        "escalate_to": item.get("escalate_to", "shay"),
                    }
                )

        return {"findings": findings}


def propose(state: State) -> dict:
    """Assemble tech/security PROPOSALS from the findings. Proposes only — never executes.

    Each finding becomes a concrete proposed action tagged with its escalation lane:
      - red PROD CI / pending-deploy / HELD-IDOR-deploy  -> escalate_to "shay" (irreversible).
      - red non-prod CI / unknown CI / tracking work     -> escalate_to "org" (resolved inside).
    Merges and deploys are NEVER taken here; the CTO only proposes and the digest carries them.
    """
    findings = state.get("findings") or []

    with span("cto.propose", findings=len(findings)):
        proposals: list = []
        for f in findings:
            kind = f.get("kind")
            escalate = f.get("escalate_to", "org")
            if kind == "ci_red":
                action = (
                    f"Investigate and propose a fix for RED CI on {f.get('repo')}; "
                    + (
                        "fix-PR merge/deploy is human-gated."
                        if escalate == "shay"
                        else "resolve inside the org (fix-PR, re-run)."
                    )
                )
            elif kind == "ci_unknown":
                action = (
                    f"Restore CI visibility for {f.get('repo')} (inject least-privilege GitHub "
                    "App token / fix recon) so green can be confirmed."
                )
            elif kind == "security_pending":
                action = (
                    "Ship the HELD IDOR entitlement rollout (schedule_acl) via the gated "
                    "multi-step deploy — production deploy is human-gated (Shay)."
                )
            else:
                action = f"Review tech posture item: {f.get('detail')}"
            proposals.append(
                {
                    "action": action,
                    "kind": kind,
                    "repo": f.get("repo"),
                    "detail": f.get("detail"),
                    "escalate_to": escalate,
                }
            )

        # Always-on continuity proposal: keep observing posture (org-resolved, never a capital ask).
        if not proposals:
            proposals.append(
                {
                    "action": "No red CI or pending rollout this cycle — continue monitoring posture.",
                    "kind": "monitor",
                    "repo": None,
                    "detail": "all observed repos green / no pending security items beyond standing watch",
                    "escalate_to": "org",
                }
            )

        return {"proposals": proposals}


def compose(state: State) -> dict:
    """Phrase the posture + proposals as a concise CTO report. FAIL-SAFE.

    The model (TIER_DEFAULT, metered via ``budget_guard``) is used ONLY to summarize the
    already-gathered facts. On ANY failure (no key, budget, SDK drift) we fall back to a
    DETERMINISTIC text report built directly from deploy/findings/proposals, so a digest is
    always produced. No model train/eval/distill — phrasing only.
    """
    deploy = state.get("deploy") or {}
    security = state.get("security") or []
    findings = state.get("findings") or []
    proposals = state.get("proposals") or []

    with span("cto.compose", findings=len(findings), proposals=len(proposals)):
        facts = _deterministic_report(deploy, security, findings, proposals)
        summary = ""
        try:
            model = budget_guard(AGENT, TIER_DEFAULT)
            prompt = (
                "You are the CTO for the Scheduler product fleet. Write a CONCISE tech + "
                "security posture report from the gathered facts below. Cover, in order: "
                "(1) deploy/CI state of each repo, (2) open security items (especially the "
                "HELD IDOR entitlement rollout), (3) the proposed tech/security actions and "
                "which are human-gated asks for the founder vs resolved inside the org. Do NOT "
                "invent state; only report what the facts show. Propose only — never claim a "
                "merge/deploy was done.\n\n"
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
    """Write a local digest artifact and file the CTO posture digest (report-only on probation).

    - ``write_local_digest`` always runs (succeeds-or-"" ; never raises) so there is a local
      artifact — and the NEXT run's ``read_local_digest("cto")`` continuity — even with zero
      credentials.
    - ``file_digest_issue(..., report_only=_report_only())`` delivers the issue. On probation
      (the default) this returns an honest report-only plan dict with NO GitHub call and NO
      approval interrupt — an unattended run can never hang or write.
    """
    summary = state.get("summary") or ""
    deploy = state.get("deploy") or {}
    security = state.get("security") or []
    findings = state.get("findings") or []
    proposals = state.get("proposals") or []
    report_only = _report_only()

    with span("cto.deliver", report_only=report_only):
        assert_not_model_work(DIGEST_REPO)  # never file into a model-dev repo
        body = (
            summary
            + "\n\n---\n\n## Raw facts\n\n"
            + _deterministic_report(deploy, security, findings, proposals)
        )

        # Local artifact first — always, fail-safe (also seeds next run's continuity).
        digest_path = write_local_digest(AGENT, "CTO: tech + security posture", body)

        # GitHub issue delivery — report-only by default (no write, no interrupt).
        res = file_digest_issue(
            DIGEST_REPO,
            "CTO: tech + security posture (proposal)",
            body,
            labels=["exec:cto"],
            report_only=report_only,
            agent="cto",
            slack_title="💻 CTO: tech + security posture (proposal)",
        )
        delivery = res.get("status") if isinstance(res, dict) else None

        return {
            "report": {
                "delivery": delivery,
                "digest": digest_path,
                "report_only": report_only,
            },
            "report_only": report_only,
        }


def finalize(state: State) -> dict:
    """Terminal node — capture governance (report-only) and emit the verdict."""
    deploy = state.get("deploy") or {}
    findings = state.get("findings") or []
    proposals = state.get("proposals") or []
    prior = state.get("report") or {}
    delivery = prior.get("delivery")
    shay_asks = sum(1 for p in proposals if p.get("escalate_to") == "shay")

    with span("cto.finalize", delivery=delivery, shay_asks=shay_asks):
        governance_capture(
            AGENT,
            {
                "repos": len(deploy),
                "findings": len(findings),
                "proposals": len(proposals),
                "shay_asks": shay_asks,
                "delivery": delivery,
                "report_only": True,
            },
        )
        return {
            "report": {
                "repos": len(deploy),
                "findings": len(findings),
                "proposals": len(proposals),
                "shay_asks": shay_asks,
                "delivery": delivery,
                "digest": prior.get("digest"),
                "report_only": True,
            }
        }


def _budget_route(state: State) -> str:
    """Route past the clock-in gate: clocked in -> gather; clocked out -> END."""
    return "gather" if check_clocked_in(AGENT) else "clocked_out"


# --- Deterministic report helpers (used by compose fallback + the issue appendix) --------
def _fmt_deploy(deploy: dict) -> list[str]:
    lines: list[str] = ["- Deploy / CI state:"]
    if not deploy:
        return ["- Deploy / CI state: (no repos checked)"]
    for repo in TECH_REPOS:
        info = deploy.get(repo) or {}
        if info.get("skipped"):
            lines.append(f"    - {repo}: skipped ({info['skipped']})")
        elif info.get("error"):
            lines.append(f"    - {repo}: error ({info['error']}) — cannot confirm green")
        else:
            lines.append(
                f"    - {repo}: status={info.get('status')} "
                f"conclusion={info.get('conclusion')}"
            )
    return lines


def _fmt_security(security: list) -> list[str]:
    lines: list[str] = ["- Open security items:"]
    if not security:
        return ["- Open security items: (none)"]
    for item in security:
        lines.append(
            f"    - [{item.get('severity')}/{item.get('status')}] {item.get('title')} "
            f"(escalate_to={item.get('escalate_to')})"
        )
    return lines


def _fmt_findings(findings: list) -> list[str]:
    if not findings:
        return ["- Findings: none (no red CI / no pending rollout)"]
    lines = ["- Findings:"]
    for f in findings:
        lines.append(
            f"    - [{f.get('kind')} → {f.get('escalate_to')}] "
            f"{f.get('repo') or '-'}: {f.get('detail')}"
        )
    return lines


def _fmt_proposals(proposals: list) -> list[str]:
    if not proposals:
        return ["- Proposals: none"]
    lines = ["- Proposals (PROPOSE-ONLY — no merge/deploy taken):"]
    for p in proposals:
        lines.append(f"    - [{p.get('escalate_to')}] {p.get('action')}")
    return lines


def _deterministic_report(deploy: dict, security: list, findings: list, proposals: list) -> str:
    """A skimmable plain-text report built ENTIRELY from the gathered dicts (no model)."""
    lines = ["CTO: tech + security posture", ""]
    lines += _fmt_deploy(deploy)
    lines += _fmt_security(security)
    lines += _fmt_findings(findings)
    lines += _fmt_proposals(proposals)
    return "\n".join(lines)


# --- Graph wiring ------------------------------------------------------------------------
builder = StateGraph(State)
builder.add_node("budget_gate", budget_gate)
builder.add_node("gather", gather)
builder.add_node("analyze", analyze)
builder.add_node("propose", propose)
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
builder.add_edge("gather", "analyze")
builder.add_edge("analyze", "propose")
builder.add_edge("propose", "compose")
builder.add_edge("compose", "deliver")
builder.add_edge("deliver", "finalize")
builder.add_edge("finalize", END)

graph = builder.compile()  # NO checkpointer/store — injected by the platform
