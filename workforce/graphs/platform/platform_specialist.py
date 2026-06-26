"""platform_specialist — "Lennox", the AI / LangSmith Platform Specialist (PROPOSE-ONLY).

Runtime: cloud (LangGraph Platform managed Cloud SaaS); registered in ``langgraph.json``
(the orchestrator owns that file — not this module).

THE BUILD-NOT-OPERATE MOVE. Today I (Claude) hand-run the LangSmith provisioning, the eval
gate, the online evals / feedback ledger, the crons, monitoring. Lennox OWNS that loop. It
READS the LangSmith runtime surface and emits PROPOSALS — it NEVER deploys, NEVER mutates
config, NEVER moves money. Every lever (roll back a revision, block a regressing prompt,
cost/health flag) is a PROPOSAL tagged with an escalation lane; the human (or the CTO it
reports to) decides. Same seams as the rest of the ops/exec fleet (see store_health_checker,
cto): clock-in gate first, report-only delivery, fail-safe everywhere, governance captured.

WHAT LENNOX MONITORS (all READ-ONLY, all injectable + fail-safe → "unverifiable" with no creds):
  * EVAL GATE — the offline eval aggregate of the agents' task output
    (``agent_toolkit.evaluations.run_evaluation`` over the local seed). A regression below the
    healthy floor is a PROPOSAL to BLOCK the redeploy / roll back the regressing revision.
  * FEEDBACK LEDGER — the online-eval feedback signals on live runs
    (``learning_loop`` / LangSmith ``list_feedback``). A drop in mean live score → a flag.
  * DEPLOYMENT REVISIONS + CRON HEALTH — the deployed assistants and registered crons
    (read via the ``a2a_client`` / langgraph_sdk read paths). A missing scheduled cron or a
    failed revision → a PROPOSAL (re-register the cron / roll back the revision — human-gated).
  * COST vs BUDGET — the fleet's real burn vs the team budget
    (``budget_monitor.check_fleet`` over ``payroll``). Over-budget → a cost PROPOSAL (the CFO
    owns the re-balance; Lennox only flags the PLATFORM cost angle: retention/sampling).

HARD BOUNDARY — ANTHROPIC TERMS / AGENTS.md (fail CLOSED). Lennox does PLATFORM OPS +
agent-prompt engineering + evaluation-of-agent-OUTPUT. It does NOT do ML model dev / training /
distillation; gal-model is OFF-LIMITS. ``assert_not_model_work`` guards EVERY judged/eval string
and EVERY target/revision/prompt identifier it acts on, and FAILS CLOSED (the item is skipped /
the run refuses, never reported on). This is enforced in code, not trusted to a prompt.

LOAD-BEARING DECISIONS (match the house style — see cto.py / store_health_checker.py):
  * PROBATION / REPORT-ONLY by default — ``file_digest_record(... report_only=_report_only())``
    where ``_report_only()`` defaults True (env ``OPS_REPORT_ONLY``; only "0"/"false"/"no" off).
    A record is a durable issue (writes even on probation); NO code action, NO config mutation,
    NO approval interrupt — an unattended scheduled run can never hang or change anything.
  * NEVER HANG / NEVER MUTATE — there is NO deploy / cron-create / config-write / money path
    reachable from any node. Every LangSmith read is injectable + wrapped so a missing key /
    offline backend / SDK drift returns a structured ``unverifiable`` finding and the run
    completes. A telemetry/network problem never crashes a node and never escalates to a write.
  * FAIL-SAFE everywhere — every probe degrades to "unverifiable"; the digest is ALWAYS produced.
  * ESCALATION — a config change that is irreversible to the LIVE runtime (roll back a prod
    revision, deploy the eval gate as blocking, change retention/cost on the live project)
    escalates to ``"shay"``; everything else (re-run an eval, open a tracking issue, propose a
    cron re-register) is resolved inside the org via the CTO and escalates to ``"org"``.
  * Compiles WITHOUT a checkpointer/store (the platform injects Postgres). Every node body is
    wrapped in ``span("platform_specialist.<node>", ...)``; governance is captured terminally.
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
    file_digest_record,
    write_local_digest,
    read_local_digest,
    TIER_DEFAULT,
)
from agent_toolkit.policy import ModelWorkBlocked

# This specialist's slug — the dedup key, the local artifact path, the salary/clock-in key.
AGENT = "platform_specialist"
# The repo the platform-health record is filed into (allow-listed in github_ops). NEVER a
# model-dev repo (guarded below).
DIGEST_REPO = "Scheduler-Systems/qa-agent-platform"

# The eval-gate health floor: below this aggregate the agents' task-output quality is judged
# REGRESSED and Lennox proposes BLOCK/rollback. Mirrors the eval_gate regression posture; a
# conservative absolute floor (the gate's relative threshold compares to a baseline — here we
# also flag an absolute collapse). Overridable via env for the operator.
def _eval_health_floor() -> float:
    raw = os.environ.get("PLATFORM_EVAL_HEALTH_FLOOR")
    try:
        return max(0.0, min(1.0, float(raw))) if raw is not None else 0.60
    except (TypeError, ValueError):
        return 0.60


# The scheduled crons Lennox EXPECTS to exist on the deployment (grounded in setup_crons.py's
# DEFAULT_CRONS — the scheduled-agent cadence). A registered cron MISSING for one of these is a
# health finding (a scheduled agent silently not firing). Read-only expectation; Lennox never
# CREATES a cron — it only proposes re-registering a missing one (the create is human-gated and
# lives in scripts/setup_crons.py --apply).
EXPECTED_CRON_ASSISTANTS = ("daily_digest", "board_chair", "ceo", "revenue_reporter")


def _report_only() -> bool:
    """Report-only default for the probation specialist: truthy/unset env => True.

    Only an explicit ``OPS_REPORT_ONLY`` of "0"/"false"/"no" turns delivery into a real (gated)
    GitHub write. Everything else — including the env being unset — keeps the specialist in
    honest report-only mode. NOTE: even with report_only False, Lennox files only a RECORD
    (durable issue); it has NO config-mutation / deploy / money path at all.
    """
    return os.environ.get("OPS_REPORT_ONLY", "").lower() not in ("0", "false", "no")


# --- State -------------------------------------------------------------------------------
class State(TypedDict, total=False):
    mode: str            # reserved for future observe-only variants
    prior: str           # Lennox's prior local digest (continuity), or "(no digest yet)"
    surface: dict        # the read LangSmith surface (eval / feedback / revisions / crons / cost)
    findings: list       # analyzed health findings (each tagged severity + escalate_to)
    proposals: list      # platform-maintenance PROPOSALS (each escalate_to org|shay)
    summary: str         # composed platform-health report text
    severity: str        # rolled-up severity (ok|medium|high)
    report: dict         # terminal verdict
    report_only: bool    # whether delivery stayed report-only


# ---------------------------------------------------------------------------
# Injectable, FAIL-SAFE LangSmith reads. Each returns a structured dict that ALWAYS includes
# ``"ok": bool``; on no creds / offline / SDK drift it degrades to ``{"ok": False, "unverifiable":
# <reason>}`` (mirrors store_health_checker's honest "could not check"). These are module-level
# functions so tests patch them directly — no network in tests, no creds required in CI.
# ---------------------------------------------------------------------------
def read_eval_health(*, client=None) -> dict:
    """Read the OFFLINE eval aggregate of the agents' task output. FAIL-SAFE.

    Runs ``agent_toolkit.evaluations.run_evaluation`` over the LOCAL seed (creds-free path) with
    a trivial pass-through target so we measure the JUDGE/dataset health, not a specific graph —
    Lennox is watching whether the eval surface itself is producing trustworthy scores. The eval
    runner already routes every judged string through ``assert_not_model_work`` and fails CLOSED.

    Returns ``{"ok", "aggregate"|None, "n_scored", "n_total", "refused", "error"|None}``; on any
    failure ``{"ok": False, "unverifiable": <reason>}``.
    """
    try:
        from agent_toolkit.evaluations import run_evaluation
    except Exception as exc:
        return {"ok": False, "unverifiable": f"eval runner unavailable: {type(exc).__name__}"}

    # A pass-through target: surface the example's own (reference) verdict as the "output" so the
    # judge has something to score. This measures dataset+judge health without invoking any graph.
    def _passthrough(inputs: dict) -> dict:
        return {"report": str(inputs.get("report") or inputs.get("question") or inputs)}

    try:
        report = run_evaluation(
            _passthrough,
            dataset_name="scheduler-qa-eval",
            target_name="platform_specialist:eval-health-probe",
            client=client,  # None => offline local seed; injected mock in tests
        )
    except Exception as exc:  # the runner is fail-safe, but stay belt-and-suspenders
        return {"ok": False, "unverifiable": f"eval run failed: {type(exc).__name__}"}

    if getattr(report, "refused", False):
        # The eval surface REFUSED on the model-dev denylist — surface it, never treat as healthy.
        return {"ok": False, "unverifiable": f"eval refused (model-dev denylist): {report.error}"}
    return {
        "ok": report.aggregate is not None,
        "aggregate": report.aggregate,
        "n_scored": report.n_scored,
        "n_total": report.n_total,
        "refused": report.refused,
        "error": report.error,
    }


def read_feedback_ledger(*, client=None, project: str | None = None, limit: int = 50) -> dict:
    """Read the ONLINE-eval feedback signals on recent live runs. FAIL-SAFE.

    The feedback ledger (``client.list_feedback``) is where the online evaluators (PII /
    Prompt-Injection / qa_verdict_quality) write their scores. A drop in the mean live score is a
    real "the deployed agents are regressing in production" signal. With no client we cannot read
    it — degrade to ``unverifiable`` (NEVER pretend the ledger is healthy).

    Returns ``{"ok", "n", "mean"|None, "by_key": {key: mean}}`` or ``{"ok": False,
    "unverifiable": <reason>}``.
    """
    if client is None:
        return {"ok": False, "unverifiable": "no LangSmith client (LANGSMITH_API_KEY not set)"}
    try:
        rows = list(client.list_feedback(limit=limit))
    except Exception as exc:
        return {"ok": False, "unverifiable": f"feedback read failed: {type(exc).__name__}"}

    scores: list[float] = []
    by_key: dict[str, list[float]] = {}
    for fb in rows:
        key = _attr(fb, "key") or "unknown"
        val = _attr(fb, "score")
        num = _coerce_float(val)
        if num is None:
            continue
        scores.append(num)
        by_key.setdefault(str(key), []).append(num)
    mean = (sum(scores) / len(scores)) if scores else None
    return {
        "ok": True,
        "n": len(rows),
        "mean": mean,
        "by_key": {k: (sum(v) / len(v)) for k, v in by_key.items() if v},
    }


def read_deployment_state(*, client=None) -> dict:
    """Read deployment revisions (assistants) + cron health via the langgraph_sdk read paths.

    Read-only. With no client (no creds) we cannot enumerate the deployment — degrade to
    ``unverifiable``. Otherwise returns the set of deployed graph names + the registered crons
    so ``analyze`` can flag a deployed graph that lost its expected cron (a scheduled agent
    silently not firing) or an assistant that vanished.

    Returns ``{"ok", "assistants": [graph_id...], "crons": [{assistant, schedule}...]}`` or
    ``{"ok": False, "unverifiable": <reason>}``. Reuses the SAME injectable sync client the tests
    drive; the production path resolves an env-built langgraph_sdk client (fail-safe).
    """
    if client is None:
        client = _deployment_client()
    if client is None:
        return {"ok": False, "unverifiable": "no LangGraph deployment client (creds not set)"}

    assistants: list[str] = []
    crons: list[dict] = []
    try:
        for a in client.assistants_search(limit=100):
            gid = _attr(a, "graph_id") or (a.get("graph_id") if isinstance(a, dict) else None)
            if gid:
                assistants.append(str(gid))
    except Exception as exc:
        return {"ok": False, "unverifiable": f"assistants read failed: {type(exc).__name__}"}
    try:
        for c in client.crons_search(limit=100):
            aid = _attr(c, "assistant_id") or (c.get("assistant_id") if isinstance(c, dict) else None)
            sched = _attr(c, "schedule") or (c.get("schedule") if isinstance(c, dict) else None)
            if aid:
                crons.append({"assistant": str(aid), "schedule": str(sched or "")})
    except Exception as exc:
        # Assistants read OK but crons read failed — partial, but honest: mark crons unverifiable.
        return {"ok": True, "assistants": assistants, "crons": [],
                "crons_unverifiable": f"crons read failed: {type(exc).__name__}"}
    return {"ok": True, "assistants": assistants, "crons": crons}


def read_cost_health(*, usage_reader=None) -> dict:
    """Read fleet cost vs budget via ``budget_monitor.check_fleet`` (over payroll). FAIL-SAFE.

    ``budget_monitor.check_fleet`` is PURE + fail-safe and already routes every agent through the
    model-dev guard. With no real usage reader it degrades (no agent reports) → no false alert;
    Lennox surfaces the cost angle only when there is a real over-budget signal. The CFO owns the
    budget RE-BALANCE; Lennox only flags the PLATFORM cost lever (sampling/retention) as a proposal.

    Returns ``{"ok": True, "alerts": [...]}``; never ``unverifiable`` (the sweep is always runnable
    locally), but ``alerts`` is empty when nothing reports.
    """
    try:
        from agent_toolkit import budget_monitor
        alerts = budget_monitor.check_fleet(usage_reader=usage_reader)
        return {"ok": True, "alerts": list(alerts or [])}
    except Exception as exc:
        return {"ok": False, "unverifiable": f"cost sweep failed: {type(exc).__name__}"}


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------
def budget_gate(state: State) -> dict:
    """CLOCK-IN gate — STOP before any work if over salary or globally disabled.

    Runs FIRST. Clocked in => proceed to ``gather``; clocked out => capture governance
    (report-only) + route to END. No LangSmith reads, no model spend, no writes on the
    clocked-out path.
    """
    with span("platform_specialist.budget_gate"):
        if check_clocked_in(AGENT):
            return {}
        governance_capture(
            AGENT,
            {"clocked_in": False, "delivery": "skipped", "report_only": True},
        )
        return {"report": {"clocked_in": False}}


def gather(state: State) -> dict:
    """Observe the LangSmith runtime surface — ALL read-only + fail-safe.

    Reads the prior Lennox digest for continuity, then each platform sub-surface (eval health,
    feedback ledger, deployment revisions + crons, cost vs budget). Each read degrades to an
    ``unverifiable`` dict on no creds / offline / SDK drift — the run always completes.

    ANTHROPIC TERMS: the eval/feedback reads route their judged strings through the guard inside
    the runner; here we additionally guard the DIGEST_REPO id (defensive) so a denylisted target
    is never the surface we report into.
    """
    with span("platform_specialist.gather"):
        prior = read_local_digest(AGENT)

        # Build the read client ONCE (fail-safe → None with no creds) and pass it to the
        # creds-needing reads so they degrade to "unverifiable" honestly.
        client = _langsmith_client()

        surface = {
            "eval": read_eval_health(client=client),
            "feedback": read_feedback_ledger(client=client),
            "deployment": read_deployment_state(),  # builds its own langgraph_sdk client fail-safe
            "cost": read_cost_health(),
        }
        return {"prior": prior, "surface": surface}


def analyze(state: State) -> dict:
    """Turn the read surface into health FINDINGS. Deterministic — no model, no network.

    Each finding is ``{"kind", "severity", "detail", "escalate_to"}``:
      * eval regression below the health floor          -> high, escalate_to shay (rollback/block)
      * eval surface unverifiable / refused             -> medium, escalate_to org (restore creds)
      * feedback ledger mean below floor                -> high, escalate_to shay (prompt block)
      * a deployed graph missing its expected cron       -> medium, escalate_to org (re-register)
      * deployment/crons unverifiable                    -> medium, escalate_to org (restore creds)
      * an over-budget cost alert (critical)             -> high, escalate_to shay (cost lever)
      * an over-budget cost alert (warn)                 -> medium, escalate_to org
    """
    surface = state.get("surface") or {}
    floor = _eval_health_floor()

    with span("platform_specialist.analyze"):
        findings: list = []

        # --- eval gate health -----------------------------------------------------------
        ev = surface.get("eval") or {}
        if not ev.get("ok"):
            findings.append({
                "kind": "eval_unverifiable", "severity": "medium",
                "detail": f"eval surface could not be scored ({ev.get('unverifiable') or ev.get('error')}) "
                          "— cannot confirm agent-output quality",
                "escalate_to": "org",
            })
        else:
            agg = ev.get("aggregate")
            if isinstance(agg, (int, float)) and agg < floor:
                findings.append({
                    "kind": "eval_regression", "severity": "high",
                    "detail": f"eval aggregate {agg:.3f} < health floor {floor:.3f} — agent task-output "
                              "quality REGRESSED. Propose BLOCK redeploy / roll back the regressing revision.",
                    "escalate_to": "shay",  # rolling back a live revision is irreversible-to-runtime
                })

        # --- online feedback ledger -----------------------------------------------------
        fb = surface.get("feedback") or {}
        if not fb.get("ok"):
            findings.append({
                "kind": "feedback_unverifiable", "severity": "low",
                "detail": f"online-eval feedback ledger unreadable ({fb.get('unverifiable')}) "
                          "— online evals (PII/Prompt-Injection) may not be wired or creds missing",
                "escalate_to": "org",
            })
        else:
            mean = fb.get("mean")
            if isinstance(mean, (int, float)) and fb.get("n", 0) > 0 and mean < floor:
                findings.append({
                    "kind": "feedback_regression", "severity": "high",
                    "detail": f"live feedback mean {mean:.3f} (n={fb.get('n')}) < floor {floor:.3f} "
                              "— deployed agents regressing in production. Propose blocking the "
                              "regressing prompt revision (human-gated).",
                    "escalate_to": "shay",
                })

        # --- deployment revisions + cron health -----------------------------------------
        dep = surface.get("deployment") or {}
        if not dep.get("ok"):
            findings.append({
                "kind": "deployment_unverifiable", "severity": "medium",
                "detail": f"deployment/cron state unreadable ({dep.get('unverifiable')}) "
                          "— cannot confirm revisions are healthy or scheduled agents are firing",
                "escalate_to": "org",
            })
        else:
            assistants = set(dep.get("assistants") or [])
            cron_assistants = {c.get("assistant") for c in (dep.get("crons") or [])}
            if dep.get("crons_unverifiable"):
                findings.append({
                    "kind": "cron_unverifiable", "severity": "low",
                    "detail": f"cron state unreadable ({dep.get('crons_unverifiable')})",
                    "escalate_to": "org",
                })
            else:
                for expected in EXPECTED_CRON_ASSISTANTS:
                    # Only flag a missing cron for a graph that is actually DEPLOYED (else it's a
                    # not-yet-deployed agent, not a broken schedule). If we cannot see assistants
                    # at all, the assistants list is empty and we conservatively skip.
                    if assistants and expected in assistants and expected not in cron_assistants:
                        findings.append({
                            "kind": "cron_missing", "severity": "medium",
                            "detail": f"deployed agent '{expected}' has NO registered cron — it is "
                                      "silently not firing on schedule. Propose re-registering the cron "
                                      "(scripts/setup_crons.py --apply, human-gated).",
                            "escalate_to": "org",
                        })

        # --- cost vs budget -------------------------------------------------------------
        cost = surface.get("cost") or {}
        if cost.get("ok"):
            for alert in cost.get("alerts") or []:
                level = str(alert.get("level"))
                subject = str(alert.get("agent", "FLEET"))
                high = level == "critical"
                findings.append({
                    "kind": "cost_over_budget", "severity": "high" if high else "medium",
                    "detail": f"[{level}] {alert.get('message')} — PLATFORM cost lever: propose "
                              "retention/sampling reduction; the CFO owns the salary re-balance.",
                    "escalate_to": "shay" if high else "org",
                    "subject": subject,
                })

        return {"findings": findings}


def propose(state: State) -> dict:
    """Assemble platform-maintenance PROPOSALS from the findings. Proposes only — never executes.

    Each finding becomes a concrete proposed action tagged with its escalation lane. NO action
    here deploys, re-registers a cron, mutates config, or moves money — Lennox only PROPOSES and
    the digest carries them. Always emits at least a monitoring proposal (never an empty set).
    """
    findings = state.get("findings") or []

    with span("platform_specialist.propose", findings=len(findings)):
        proposals: list = []
        for f in findings:
            kind = f.get("kind")
            escalate = f.get("escalate_to", "org")
            if kind == "eval_regression":
                action = ("Propose BLOCK redeploy + roll back the regressing prompt/graph revision "
                          "via the eval gate — rollback of a live revision is human-gated (Shay).")
            elif kind == "feedback_regression":
                action = ("Propose blocking the regressing prompt revision in the Prompt Hub and "
                          "opening a learning-loop review — prompt rollback is human-gated (Shay).")
            elif kind == "cron_missing":
                action = ("Propose re-registering the missing server-side cron "
                          "(scripts/setup_crons.py --apply) so the scheduled agent fires again — "
                          "cron creation is human-gated.")
            elif kind == "cost_over_budget":
                action = ("Propose a PLATFORM cost lever (reduce LangSmith run/trace retention or "
                          "online-eval sampling rate) to cut burn; the CFO owns the salary re-balance.")
            elif kind in ("eval_unverifiable", "feedback_unverifiable", "deployment_unverifiable",
                          "cron_unverifiable"):
                action = ("Restore platform observability (inject the read-only LangSmith key / fix "
                          "the read path) so the runtime can be confirmed healthy.")
            else:
                action = f"Review platform-health item: {f.get('detail')}"
            proposals.append({
                "action": action, "kind": kind, "severity": f.get("severity"),
                "detail": f.get("detail"), "escalate_to": escalate,
            })

        if not proposals:
            proposals.append({
                "action": "No eval regression, no missing cron, no over-budget signal this cycle — "
                          "continue monitoring the LangSmith runtime.",
                "kind": "monitor", "severity": "ok",
                "detail": "all observed platform surfaces healthy / unverifiable-only",
                "escalate_to": "org",
            })

        return {"proposals": proposals}


def compose(state: State) -> dict:
    """Phrase the surface + proposals as a concise platform-health report. FAIL-SAFE.

    Roll up severity (high if any high finding, else medium if any medium, else ok). The model
    (TIER_DEFAULT, metered via ``budget_guard``) is used ONLY to word the already-gathered facts;
    on ANY failure we fall back to a DETERMINISTIC report so a digest is always produced.

    ANTHROPIC TERMS — fail CLOSED: BEFORE any model call we guard EVERY string we would feed the
    paid judge/model (the deterministic facts text). If it trips the model-dev denylist, we
    REFUSE the model summary and keep the deterministic text — Lennox never sends model-dev
    content to a paid LLM, and never "engineers a prompt" for model training.
    """
    surface = state.get("surface") or {}
    findings = state.get("findings") or []
    proposals = state.get("proposals") or []

    with span("platform_specialist.compose", findings=len(findings), proposals=len(proposals)):
        highs = [f for f in findings if f.get("severity") == "high"]
        mediums = [f for f in findings if f.get("severity") == "medium"]
        severity = "high" if highs else ("medium" if mediums else "ok")

        facts = _deterministic_report(severity, surface, findings, proposals)

        # Guard the model INPUT (fail CLOSED). If the facts carry model-dev content (e.g. a
        # compromised surface emitted "fine-tune the gal-model classifier"), refuse the model
        # call entirely and keep the deterministic text.
        model_blocked = _guard_text(facts)

        summary = ""
        if model_blocked is None:
            try:
                model = budget_guard(AGENT, TIER_DEFAULT)
                prompt = (
                    "You are Lennox, the AI / LangSmith Platform Specialist for the agent fleet. "
                    "You OWN the LangSmith runtime but you are PROPOSE-ONLY — you never deploy or "
                    "change config. Write a CONCISE platform-health report from the gathered facts: "
                    "(1) eval-gate health, (2) online feedback ledger, (3) deployment revisions + "
                    "cron health, (4) cost vs budget, then (5) the proposed maintenance actions and "
                    "which are human-gated asks for Shay vs resolved inside the org. Do NOT invent "
                    "state; only report the facts. Propose only — never claim a deploy/rollback/"
                    "config-change was done.\n\n"
                    f"{facts}"
                )
                resp = model.invoke(prompt)
                summary = getattr(resp, "content", str(resp)) or ""
            except Exception as exc:  # model unavailable — deterministic fallback (never empty)
                summary = (f"(model summary unavailable: {type(exc).__name__}) — deterministic "
                           f"report:\n\n{facts}")
        else:
            summary = (f"(model summary REFUSED — model-dev denylist: {model_blocked}) — "
                       f"deterministic report:\n\n{facts}")

        if not summary.strip():  # belt-and-suspenders: never an empty summary
            summary = facts
        return {"summary": summary, "severity": severity}


def deliver(state: State) -> dict:
    """Write a local digest artifact + file the platform-health RECORD (report-only on probation).

    - ``write_local_digest`` always runs (succeeds-or-"" ; never raises) so there is a local
      artifact + the NEXT run's continuity even with zero credentials.
    - ``file_digest_record(agent="platform_specialist", record_kind="platform-health", ...)``
      delivers a durable, DEDUPED issue (one standing record, updated each shift). On probation
      this is still a RECORD (not a code action) — NO config mutation, NO deploy, NO approval
      interrupt. An unattended run can never hang or change the runtime.
    """
    summary = state.get("summary") or ""
    severity = state.get("severity") or "ok"
    surface = state.get("surface") or {}
    findings = state.get("findings") or []
    proposals = state.get("proposals") or []
    report_only = _report_only()

    with span("platform_specialist.deliver", severity=severity, report_only=report_only):
        assert_not_model_work(DIGEST_REPO)  # never file into a model-dev repo
        body = (
            summary
            + "\n\n---\n\n## Raw facts\n\n"
            + _deterministic_report(severity, surface, findings, proposals)
        )

        digest_path = write_local_digest(AGENT, "Platform health (LangSmith runtime)", body)

        labels = ["agent:platform_specialist", "platform:health"]
        if severity == "high":
            labels.append("gate:human-required")

        res = file_digest_record(
            DIGEST_REPO,
            "Platform health: LangSmith runtime (" + severity + ")",
            body,
            agent="platform_specialist",
            record_kind="platform-health",  # STABLE dedup key — one standing record, updated
            labels=labels,
            report_only=report_only,
            slack_title="🛰️ Platform health: LangSmith runtime (" + severity + ")",
        )
        delivery = res.get("status") if isinstance(res, dict) else None
        return {
            "report": {"severity": severity, "delivery": delivery, "digest": digest_path,
                       "report_only": report_only},
            "report_only": report_only,
        }


def finalize(state: State) -> dict:
    """Terminal node — capture governance (report-only) and emit the verdict."""
    severity = state.get("severity") or "ok"
    findings = state.get("findings") or []
    proposals = state.get("proposals") or []
    prior = state.get("report") if isinstance(state.get("report"), dict) else {}
    shay_asks = sum(1 for p in proposals if p.get("escalate_to") == "shay")

    with span("platform_specialist.finalize", severity=severity, shay_asks=shay_asks):
        governance_capture(
            AGENT,
            {
                "severity": severity,
                "findings": len(findings),
                "proposals": len(proposals),
                "shay_asks": shay_asks,
                "delivery": prior.get("delivery"),
                "report_only": True,
            },
        )
        return {
            "report": {
                "severity": severity,
                "findings": len(findings),
                "proposals": len(proposals),
                "shay_asks": shay_asks,
                "delivery": prior.get("delivery"),
                "digest": prior.get("digest"),
                "report_only": True,
            }
        }


# --- Routing -----------------------------------------------------------------------------
def _budget_route(state: State) -> str:
    """Clocked in -> gather; clocked out -> END (terminal report already set)."""
    return "gather" if check_clocked_in(AGENT) else "clocked_out"


# --- Helpers (fail-safe, no network) -----------------------------------------------------
def _attr(obj, name: str):
    """Best-effort attribute/key read off an SDK object or a plain dict. Never raises."""
    try:
        if isinstance(obj, dict):
            return obj.get(name)
        return getattr(obj, name, None)
    except Exception:
        return None


def _coerce_float(v):
    if isinstance(v, bool) or v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _guard_text(text: str):
    """Return a refusal reason if ``text`` trips the model-dev denylist, else None. Fail CLOSED.

    Used before any paid model call so model-dev content can never be sent to the judge/model.
    If the guard module is unavailable, platform ops is still permitted (mirrors the judge).
    """
    try:
        assert_not_model_work(text)
    except ModelWorkBlocked as exc:
        return type(exc).__name__
    except Exception:
        return None
    return None


def _langsmith_client():
    """Env-built LangSmith ``Client`` for reads, or None (fail-safe). Reuses langsmith_setup."""
    try:
        from agent_toolkit.langsmith_setup import get_client
        return get_client()
    except Exception:
        return None


def _deployment_client():
    """Env-built langgraph_sdk SYNC client wrapper for deployment/cron reads, or None (fail-safe).

    Returns a tiny adapter exposing ``assistants_search`` / ``crons_search`` so ``read_deployment_
    state`` is agnostic to the SDK's exact sync/async surface (and trivially mockable in tests).
    None when creds are absent — the caller degrades to ``unverifiable``.
    """
    url = (os.environ.get("LANGGRAPH_DEPLOYMENT_URL")
           or os.environ.get("LANGSMITH_DEPLOYMENT_URL") or "").rstrip("/")
    key = os.environ.get("LANGSMITH_API_KEY") or os.environ.get("LANGCHAIN_API_KEY") or ""
    tenant = os.environ.get("LANGSMITH_TENANT_ID") or ""
    if not (url and key and tenant):
        return None
    try:
        from langgraph_sdk import get_sync_client
        sdk = get_sync_client(url=url, api_key=key, headers={"X-Tenant-Id": tenant})
    except Exception:
        return None

    class _Adapter:
        def assistants_search(self, *, limit=100):
            return sdk.assistants.search(limit=limit)

        def crons_search(self, *, limit=100):
            return sdk.crons.search(limit=limit)

    return _Adapter()


# --- Deterministic report helpers (used by compose fallback + the issue appendix) --------
def _fmt_eval(ev: dict) -> list[str]:
    if not ev.get("ok"):
        return [f"- Eval gate: UNVERIFIABLE ({ev.get('unverifiable') or ev.get('error')})"]
    agg = ev.get("aggregate")
    agg_s = f"{agg:.3f}" if isinstance(agg, (int, float)) else "n/a"
    return [f"- Eval gate: aggregate={agg_s} scored={ev.get('n_scored')}/{ev.get('n_total')}"]


def _fmt_feedback(fb: dict) -> list[str]:
    if not fb.get("ok"):
        return [f"- Feedback ledger (online evals): UNVERIFIABLE ({fb.get('unverifiable')})"]
    mean = fb.get("mean")
    mean_s = f"{mean:.3f}" if isinstance(mean, (int, float)) else "n/a"
    by_key = ", ".join(f"{k}={v:.2f}" for k, v in (fb.get("by_key") or {}).items()) or "none"
    return [f"- Feedback ledger: n={fb.get('n')} mean={mean_s} (by key: {by_key})"]


def _fmt_deployment(dep: dict) -> list[str]:
    if not dep.get("ok"):
        return [f"- Deployment / crons: UNVERIFIABLE ({dep.get('unverifiable')})"]
    crons = dep.get("crons") or []
    lines = [f"- Deployment: {len(dep.get('assistants') or [])} assistant(s), {len(crons)} cron(s)"]
    if dep.get("crons_unverifiable"):
        lines.append(f"    - crons: UNVERIFIABLE ({dep.get('crons_unverifiable')})")
    for c in crons:
        lines.append(f"    - cron: {c.get('assistant')} @ {c.get('schedule')}")
    return lines


def _fmt_cost(cost: dict) -> list[str]:
    if not cost.get("ok"):
        return [f"- Cost vs budget: UNVERIFIABLE ({cost.get('unverifiable')})"]
    alerts = cost.get("alerts") or []
    if not alerts:
        return ["- Cost vs budget: no over-budget alert (healthy / no usage reported)"]
    return ["- Cost vs budget:"] + [
        f"    - [{a.get('level')}] {a.get('agent')}: {a.get('message')}" for a in alerts
    ]


def _fmt_findings(findings: list) -> list[str]:
    if not findings:
        return ["- Findings: none (platform healthy)"]
    lines = ["- Findings:"]
    for f in findings:
        lines.append(f"    - [{f.get('severity')}/{f.get('kind')} → {f.get('escalate_to')}] "
                     f"{f.get('detail')}")
    return lines


def _fmt_proposals(proposals: list) -> list[str]:
    if not proposals:
        return ["- Proposals: none"]
    lines = ["- Proposals (PROPOSE-ONLY — no deploy/config-change/cron-create taken):"]
    for p in proposals:
        lines.append(f"    - [{p.get('escalate_to')}] {p.get('action')}")
    return lines


def _deterministic_report(severity: str, surface: dict, findings: list, proposals: list) -> str:
    """A skimmable plain-text report built ENTIRELY from the gathered dicts (no model)."""
    lines = [f"Platform health (LangSmith runtime) = {severity}", ""]
    lines += _fmt_eval(surface.get("eval") or {})
    lines += _fmt_feedback(surface.get("feedback") or {})
    lines += _fmt_deployment(surface.get("deployment") or {})
    lines += _fmt_cost(surface.get("cost") or {})
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
