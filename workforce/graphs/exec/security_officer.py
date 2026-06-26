"""security_officer — Lior, the Chief Information Security Officer (CISO), PROPOSE-ONLY.

Runtime: cloud/CI (LangGraph Platform managed Cloud SaaS); registered in ``langgraph.json``
(the orchestrator owns that file — not this module).

Lior is a C-SUITE officer: a peer of the CTO, reporting to the CEO, with a DOTTED LINE to the
audit_risk_director (Reese) on the board. Lior owns OPERATIONAL security and CONSUMES the fleet's
state rather than re-doing work:

  * THE KEYSTONE — a secure-by-design review of every new graph / endpoint / capability grant. It
    reads the deployed graph set (langgraph.json), the capability manifest (capabilities.yaml), and
    the event-receiver / webhook seam, then runs a DETERMINISTIC checklist that would have caught the
    real replay / SSRF classes (missing webhook-signature verification, no replay/nonce window, an
    SSRF-reachable fetch, a secret-bearing identity granted to a propose-only agent, a non-report_only
    posture). Each gap is a security FINDING.
  * VULN / SENTRY-SECURITY TRIAGE — surfaces security-labelled issues for triage (fail-safe; honest
    "unverifiable" when the source is not wired).
  * SECRET-HYGIENE / ROTATION PROPOSALS — proposes rotations (never rotates a live secret itself).
  * SECURITY HARD-GATE COMPLIANCE PREP — carries the HELD Firestore IDOR (#1487) rollout as a standing
    compliance-dossier item until a human ships the gated multi-step deploy.
  * INCIDENT-RESPONSE RUNBOOK — can RECOMMEND the kill switch (AGENTS_DISABLED / fleet_control.py); a
    HUMAN pulls it. Lior never disables the fleet.
  * PROMPT-INJECTION / PII POLICY — owns the POLICY, paired with Lennox (platform_specialist), who owns
    the runtime evaluators. Lior proposes the policy; Lennox runs the evaluator.

LOAD-BEARING DECISIONS (match the ops-fleet house style — cto.py / store_health_checker.py):

  * PROPOSE-ONLY. Lior NEVER deploys a fix, rotates a live secret, files a regulatory submission,
    sends anything, or pulls the kill switch. Every action is a PROPOSAL in a digest. No mutating /
    deploy / file / sign / send / rotate / create_cron function is reachable from ANY node — the only
    outward seam is ``file_digest_record`` (a durable RECORD, not a code action) + Slack mirror.

  * PROBATION / REPORT-ONLY by default. Delivery goes through ``file_digest_issue(...,
    report_only=_report_only())`` (env ``OPS_REPORT_ONLY``; truthy/unset => True). On probation the
    delivery is an honest report-only plan dict — NO code write and NO approval interrupt — so a
    scheduled unattended run can never hang.

  * NEVER HANG / FAIL-SAFE. No reachable ``request_approval``/interrupt on the scheduled path. With no
    credentials the run still completes: every read (manifest, graphs, prior digest, vuln source, model
    summary) is wrapped so a missing key / offline / SDK drift degrades to a structured
    ``"unverifiable"`` signal and the node moves on — Lior NEVER pretends a surface is secure when it
    could not verify it.

  * ANTHROPIC-TERMS / ML BOUNDARY. ``assert_not_model_work`` guards every outward repo/graph string
    before any read/report; gal-model / denylisted ids are SKIPPED, never reviewed/reported.

  * INVESTOR ESCALATION. Only capital/irreversible/legal items are "asks for Shay". The IDOR
    production-deploy and any live-secret rotation are irreversible/security-gated, so they escalate to
    ``"shay"``; everything else (raise a tracking issue, add a signature check, draft a threat model)
    is resolved inside the org and escalates to ``"org"``.

  * Compiles WITHOUT a checkpointer/store (the platform injects Postgres). Every node body is wrapped
    in ``span("security_officer.<node>", ...)``; governance is captured (report_only=True) terminally.
"""
from __future__ import annotations

import json
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
from agent_toolkit.policy import ModelWorkBlocked

# This officer's slug (prior-digest read + local artifact path + digest attribution).
AGENT = "security_officer"
# The repo the CISO posture digest issue is filed into (allow-listed in github_ops).
DIGEST_REPO = "Scheduler-Systems/qa-agent-platform"

# Repo paths (worktree root) that ground the secure-by-design review. Read FAIL-SAFE — a missing
# file degrades to an "unverifiable" review, never a crash and never a false "secure".
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
LANGGRAPH_PATH = os.path.join(_REPO_ROOT, "langgraph.json")
MANIFEST_PATH = os.path.join(_REPO_ROOT, "docs", "governance", "capabilities.yaml")

# Identities that carry a SECRET that can write/mutate outward — a propose-only agent should never
# hold one (least-privilege). Used by the secure-by-design grant review. (model_inference /
# openclaw_slack_bot / github_app are the propose-only baseline and are NOT in this set.)
_SECRET_BEARING_IDENTITIES = frozenset()  # baseline: none flagged secret-bearing for propose-only

# THE STANDING SECURITY HARD-GATE COMPLIANCE ITEM: the Firestore IDOR (#1487) entitlement rollout is
# fixed (server-maintained schedule_acl, validated 20/20) but HELD — NOT deployed to production, so
# the live IDOR remains open until a human ships the gated multi-step rollout. Lior carries this as a
# compliance dossier item every run until it ships; the deploy is irreversible to prod → Shay.
IDOR_COMPLIANCE_ITEM = {
    "id": "firestore-idor-1487",
    "title": "HARD-GATE: Firestore IDOR #1487 breach-exposure remediation HELD (not deployed)",
    "severity": "high",
    "status": "held",
    "detail": (
        "Server-maintained schedule_acl rules close the live #1487 IDOR and validated 20/20, but "
        "are NOT deployed to production — the IDOR (cross-tenant schedule read) stays OPEN until the "
        "gated multi-step rollout ships. Security HARD-GATE; deploy is irreversible to paying "
        "customers → human-gated (Shay). Dossier: credentialed prod-snapshot replay + sign-off."
    ),
    "escalate_to": "shay",
}


def _report_only() -> bool:
    """Report-only default for the probation officer: truthy/unset env => True.

    Only an explicit ``OPS_REPORT_ONLY`` of "0"/"false"/"no" turns delivery into a real (gated)
    GitHub write. Everything else — including the env being unset — keeps the officer in honest
    report-only mode (no code write, no approval interrupt).
    """
    return os.environ.get("OPS_REPORT_ONLY", "").lower() not in ("0", "false", "no")


class State(TypedDict, total=False):
    mode: str
    prior: str            # prior local digest (continuity), or "(no digest yet)"
    surface: dict         # the reviewed surface (graphs, grants, event-seam) or {"unverifiable": ...}
    standing: list        # standing security items (the IDOR compliance dossier, + derived)
    findings: list        # secure-by-design + triage findings (each escalate_to org|shay)
    proposals: list       # security proposals (threat_model / finding / rotation / incident_response)
    summary: str          # composed CISO posture text
    report: dict          # terminal verdict
    report_only: bool


def budget_gate(state: State) -> dict:
    """CLOCK-IN gate — STOP before any work if over salary or globally disabled.

    Runs FIRST. Clocked in => proceed to ``gather``; clocked out => governance (report-only) + END.
    No reads, no model spend, no writes on the clocked-out path.
    """
    with span("security_officer.budget_gate"):
        if check_clocked_in(AGENT):
            return {}
        governance_capture(
            AGENT,
            {"clocked_in": False, "delivery": "skipped", "report_only": True},
        )
        return {"report": {"clocked_in": False}}


def gather(state: State) -> dict:
    """Observe the security surface: prior digest + the deployed graphs / grants / event-seam.

    Every read FAIL-SAFE. The review surface is built ENTIRELY from on-disk artifacts that are
    present in the repo (langgraph.json + capabilities.yaml), so it works with ZERO credentials —
    a missing/unreadable file degrades the WHOLE surface to a single honest ``unverifiable`` warning
    ("could not read the deployed surface — security review could not run"), NEVER a false "secure".
    """
    with span("security_officer.gather"):
        prior = read_local_digest(AGENT)

        surface: dict = {"graphs": {}, "event_seam": {}, "unverifiable": None}
        try:
            graphs = json.loads(_read(LANGGRAPH_PATH)).get("graphs") or {}
            manifest = _safe_yaml(_read(MANIFEST_PATH))
            grants = (manifest.get("grants") or {}) if isinstance(manifest, dict) else {}

            reviewed: dict = {}
            for name, target in graphs.items():
                try:
                    assert_not_model_work(name)   # never review/report a model-dev graph
                except ModelWorkBlocked:
                    reviewed[name] = {"skipped": "model_work_denylist"}
                    continue
                reviewed[name] = {
                    "module": target,
                    "grant": grants.get(name),     # None => no grant (a coverage gap is a finding)
                }
            surface["graphs"] = reviewed
            # The event-receiver / webhook seam is the SSRF / replay surface. We do not call it; we
            # note whether the signed-webhook + replay-window guards are KNOWN-present (the repo's
            # event_receiver hardening) so analyze can flag if a NEW endpoint lacks them.
            surface["event_seam"] = _review_event_seam()
        except Exception as exc:  # unreadable surface — honest unverifiable, never a false pass
            surface = {"graphs": {}, "event_seam": {},
                       "unverifiable": f"could not read the deployed surface ({type(exc).__name__})"}

        # The HELD IDOR rollout is a STANDING compliance item — surface it every run until shipped
        # (a copy so downstream mutation can't corrupt the module constant).
        standing = [dict(IDOR_COMPLIANCE_ITEM)]
        return {"prior": prior, "surface": surface, "standing": standing}


def analyze(state: State) -> dict:
    """Secure-by-design review + triage. Deterministic — no model, no network.

    The KEYSTONE: for every deployed graph/grant, run the checklist that would have caught the real
    replay / SSRF classes:
      - a grant referencing a SECRET-BEARING identity on a propose-only agent (over-privilege),
      - a non-report_only posture (probation breach),
      - a coverage gap (a deployed graph with NO capability grant — default-deny breach),
      - the event/webhook seam MISSING signature verification or a replay/nonce window (the
        missing-signature / replay finding — exactly the class that bit the prod-snapshot replay),
      - an SSRF-reachable fetch with no allow-list on the same seam.
    Plus carry the HELD IDOR compliance item as a pending HARD-GATE finding. When the surface is
    ``unverifiable`` we emit ONE honest finding rather than pretend a clean review.
    """
    surface = state.get("surface") or {}
    standing = state.get("standing") or []

    with span("security_officer.analyze"):
        findings: list = []

        if surface.get("unverifiable"):
            findings.append({
                "kind": "unverifiable", "target": None,
                "detail": f"could not run the secure-by-design review: {surface['unverifiable']}",
                "escalate_to": "org",
            })
        else:
            for name, info in (surface.get("graphs") or {}).items():
                if not isinstance(info, dict) or info.get("skipped"):
                    continue
                grant = info.get("grant")
                if grant is None:
                    findings.append({
                        "kind": "grant_coverage_gap", "target": name,
                        "detail": f"deployed graph '{name}' has NO capability grant (default-deny breach)",
                        "escalate_to": "org",
                    })
                    continue
                if grant.get("posture") != "report_only":
                    findings.append({
                        "kind": "posture_breach", "target": name,
                        "detail": f"grant '{name}' posture={grant.get('posture')!r} is not report_only on probation",
                        "escalate_to": "shay",
                    })
                over = [i for i in (grant.get("identities") or []) if i in _SECRET_BEARING_IDENTITIES]
                if over:
                    findings.append({
                        "kind": "over_privilege", "target": name,
                        "detail": f"propose-only agent '{name}' holds secret-bearing identity {over}",
                        "escalate_to": "shay",
                    })

            # The event/webhook seam — the missing-signature / replay-window / SSRF review. This is
            # the finding that would have CAUGHT the replay/SSRF that bit the credentialed snapshot.
            seam = surface.get("event_seam") or {}
            if seam and not seam.get("signature_verified"):
                findings.append({
                    "kind": "missing_signature", "target": "event_receiver",
                    "detail": "webhook endpoint accepts events WITHOUT verifying an HMAC signature — "
                              "forgeable / replayable (the replay class). Require a signed-webhook check.",
                    "escalate_to": "shay",
                })
            if seam and not seam.get("replay_window"):
                findings.append({
                    "kind": "replay_window_missing", "target": "event_receiver",
                    "detail": "webhook endpoint has NO replay/nonce/timestamp window — a captured "
                              "request can be replayed. Require a bounded replay window + nonce.",
                    "escalate_to": "shay",
                })
            if seam and seam.get("ssrf_reachable") and not seam.get("egress_allowlist"):
                findings.append({
                    "kind": "ssrf_risk", "target": "event_receiver",
                    "detail": "a server-side fetch reachable from the event seam has NO egress "
                              "allow-list — SSRF-reachable. Require an outbound allow-list.",
                    "escalate_to": "shay",
                })

        # Standing HARD-GATE compliance items (the HELD IDOR dossier).
        for item in standing:
            if item.get("status") in ("held", "pending", "open"):
                findings.append({
                    "kind": "compliance_pending", "target": item.get("id"),
                    "detail": f"{item.get('title')} — {item.get('detail')}",
                    "escalate_to": item.get("escalate_to", "shay"),
                })

        return {"findings": findings}


def propose(state: State) -> dict:
    """Assemble security PROPOSALS from the findings. PROPOSES ONLY — never executes.

    Each finding becomes a concrete proposed action tagged with its escalation lane AND its proposal
    TYPE (threat_model / security_finding / secret_rotation / incident_response), mirroring Lior's
    capability grants. Lior NEVER deploys a fix, rotates a secret, or pulls the kill switch here.
    """
    findings = state.get("findings") or []

    with span("security_officer.propose", findings=len(findings)):
        proposals: list = []
        for f in findings:
            kind = f.get("kind")
            escalate = f.get("escalate_to", "org")
            if kind == "missing_signature":
                action = ("propose:security_finding — require HMAC signature verification on the "
                          "webhook endpoint before processing (closes the replay/forgery class). "
                          "Code-fix is human-gated; Lior proposes only.")
                ptype = "security_finding"
            elif kind == "replay_window_missing":
                action = ("propose:threat_model — add a bounded replay window + nonce to the event "
                          "seam so a captured request cannot be replayed. Propose-only.")
                ptype = "threat_model"
            elif kind == "ssrf_risk":
                action = ("propose:security_finding — add an outbound egress allow-list to the "
                          "server-side fetch (closes the SSRF class). Propose-only.")
                ptype = "security_finding"
            elif kind == "over_privilege":
                action = (f"propose:secret_rotation/least-privilege — revoke the secret-bearing "
                          f"identity from '{f.get('target')}' (propose-only; a human rotates/revokes).")
                ptype = "secret_rotation"
            elif kind == "posture_breach":
                action = (f"propose:security_finding — restore report_only posture on '{f.get('target')}' "
                          "(probation breach). Human-gated.")
                ptype = "security_finding"
            elif kind == "grant_coverage_gap":
                action = (f"propose:security_finding — add a least-privilege capability grant for "
                          f"'{f.get('target')}' (default-deny coverage gap). Propose-only.")
                ptype = "security_finding"
            elif kind == "compliance_pending":
                action = ("propose:incident_response/compliance — ship the HELD Firestore IDOR #1487 "
                          "remediation via the gated multi-step deploy; prep the breach-exposure "
                          "dossier (credentialed prod-snapshot replay + sign-off). Production deploy "
                          "is human-gated (Shay). Lior RECOMMENDS; a human deploys.")
                ptype = "incident_response"
            elif kind == "unverifiable":
                action = ("propose:security_finding — restore review visibility (inject least-privilege "
                          "read of the deployed surface) so the secure-by-design review can run.")
                ptype = "security_finding"
            else:
                action = f"propose:security_finding — review security item: {f.get('detail')}"
                ptype = "security_finding"
            proposals.append({
                "action": action, "kind": kind, "proposal_type": ptype,
                "target": f.get("target"), "detail": f.get("detail"), "escalate_to": escalate,
            })

        # Always-on continuity proposal: keep the secure-by-design watch running (org-resolved).
        if not proposals:
            proposals.append({
                "action": "propose:threat_model — no new secure-by-design gap this cycle; continue "
                          "the keystone review of every new graph/endpoint/grant + prompt-injection/"
                          "PII policy (paired with Lennox's runtime evaluators).",
                "kind": "monitor", "proposal_type": "threat_model", "target": None,
                "detail": "no open security finding beyond standing watch", "escalate_to": "org",
            })

        return {"proposals": proposals}


def compose(state: State) -> dict:
    """Phrase the posture + proposals as a concise CISO report. FAIL-SAFE.

    The model (TIER_DEFAULT, metered via ``budget_guard``) is used ONLY to summarize already-gathered
    facts. On ANY failure (no key, budget, SDK drift) we fall back to a DETERMINISTIC text report
    built directly from the surface/findings/proposals, so a digest is always produced. No model
    train/eval/distill — phrasing only.
    """
    surface = state.get("surface") or {}
    standing = state.get("standing") or []
    findings = state.get("findings") or []
    proposals = state.get("proposals") or []

    with span("security_officer.compose", findings=len(findings), proposals=len(proposals)):
        facts = _deterministic_report(surface, standing, findings, proposals)
        summary = ""
        try:
            model = budget_guard(AGENT, TIER_DEFAULT)
            prompt = (
                "You are the CISO (Chief Information Security Officer) for the Scheduler product "
                "fleet. Write a CONCISE operational-security posture report from the gathered facts "
                "below. Cover, in order: (1) the secure-by-design review of the deployed graphs / "
                "grants / event-webhook seam (call out any missing-signature / replay / SSRF / "
                "over-privilege / coverage gap), (2) the open security HARD-GATE compliance items "
                "(especially the HELD Firestore IDOR #1487), (3) the proposed security actions and "
                "which are human-gated asks for the founder vs resolved inside the org. Do NOT invent "
                "state. PROPOSE ONLY — never claim a fix/rotation/deploy was done.\n\n"
                f"{facts}"
            )
            resp = model.invoke(prompt)
            summary = getattr(resp, "content", str(resp)) or ""
        except Exception as exc:  # model unavailable — deterministic fallback (never empty)
            summary = (
                f"(model summary unavailable: {type(exc).__name__}) — deterministic report:\n\n{facts}"
            )

        if not summary.strip():
            summary = facts
        return {"summary": summary}


def deliver(state: State) -> dict:
    """Write a local digest + file the CISO posture digest as a DURABLE RECORD (report-only on probation).

    - ``write_local_digest`` always runs (never raises) so there is a local artifact and the NEXT
      run's continuity even with zero credentials.
    - ``file_digest_issue(..., agent=AGENT, report_only=_report_only())`` delivers the issue via the
      durable record path. On probation (default) this returns an honest report-only plan dict with
      NO code write and NO approval interrupt — an unattended run can never hang or write. A digest is
      a RECORD, not a mutating/deploy action.
    """
    summary = state.get("summary") or ""
    surface = state.get("surface") or {}
    standing = state.get("standing") or []
    findings = state.get("findings") or []
    proposals = state.get("proposals") or []
    report_only = _report_only()

    with span("security_officer.deliver", report_only=report_only):
        assert_not_model_work(DIGEST_REPO)  # never file into a model-dev repo
        body = (
            summary
            + "\n\n---\n\n## Raw facts\n\n"
            + _deterministic_report(surface, standing, findings, proposals)
        )

        digest_path = write_local_digest(AGENT, "CISO: operational security posture", body)

        res = file_digest_issue(
            DIGEST_REPO,
            "CISO: operational security posture (proposal)",
            body,
            labels=["exec:security_officer", "security"],
            report_only=report_only,
            agent=AGENT,
            record_kind="ciso-posture",
            slack_title="🛡️ CISO: operational security posture (proposal)",
        )
        delivery = res.get("status") if isinstance(res, dict) else None
        return {
            "report": {"delivery": delivery, "digest": digest_path, "report_only": report_only},
            "report_only": report_only,
        }


def finalize(state: State) -> dict:
    """Terminal node — capture governance (report-only) and emit the verdict."""
    surface = state.get("surface") or {}
    findings = state.get("findings") or []
    proposals = state.get("proposals") or []
    prior = state.get("report") or {}
    delivery = prior.get("delivery")
    shay_asks = sum(1 for p in proposals if p.get("escalate_to") == "shay")

    with span("security_officer.finalize", delivery=delivery, shay_asks=shay_asks):
        governance_capture(
            AGENT,
            {
                "graphs_reviewed": len((surface.get("graphs") or {})),
                "findings": len(findings),
                "proposals": len(proposals),
                "shay_asks": shay_asks,
                "delivery": delivery,
                "report_only": True,
            },
        )
        return {
            "report": {
                "graphs_reviewed": len((surface.get("graphs") or {})),
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


# --- read helpers (fail-safe; SSRF/replay review surface) --------------------------------
def _read(path: str) -> str:
    """Read a repo file as text. Raises on failure (caller's try/except degrades to unverifiable)."""
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _safe_yaml(text: str) -> dict:
    """Parse YAML to a dict; ``{}`` on any failure (the gate treats a missing grant as a finding)."""
    try:
        import yaml
        data = yaml.safe_load(text)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _review_event_seam() -> dict:
    """Statically review the event-receiver / webhook seam for the replay/SSRF guards.

    Reads the repo's event_receiver module text (if present) and looks for the KNOWN hardening
    markers — a signature check, a replay/nonce window, and an egress allow-list. The point is that
    a NEW endpoint added without these markers is flagged by analyze (the missing-signature / replay
    / SSRF findings). FAIL-SAFE: if the module is absent/unreadable we report the guards as NOT
    verified (so analyze raises the finding) rather than silently assuming they are present.
    """
    candidates = [
        os.path.join(_REPO_ROOT, "scripts", "event_receiver.py"),
        os.path.join(_REPO_ROOT, "agent_toolkit", "event_receiver.py"),
    ]
    text = ""
    for p in candidates:
        try:
            text = _read(p)
            if text:
                break
        except Exception:
            continue
    low = text.lower()
    return {
        "module_found": bool(text),
        "signature_verified": ("hmac" in low and "signature" in low) or "verify_signature" in low,
        "replay_window": ("replay" in low and ("nonce" in low or "timestamp" in low or "window" in low)),
        "ssrf_reachable": ("requests.get" in low or "urlopen" in low or "httpx" in low),
        "egress_allowlist": ("allowlist" in low or "allow_list" in low or "egress" in low),
    }


# --- Deterministic report helpers (used by compose fallback + the issue appendix) --------
def _fmt_surface(surface: dict) -> list[str]:
    if surface.get("unverifiable"):
        return [f"- Secure-by-design review: UNVERIFIABLE — {surface['unverifiable']}"]
    graphs = surface.get("graphs") or {}
    seam = surface.get("event_seam") or {}
    lines = [f"- Secure-by-design review: {len(graphs)} deployed graph(s) reviewed."]
    lines.append(
        "    - event/webhook seam: "
        f"signature_verified={seam.get('signature_verified')} "
        f"replay_window={seam.get('replay_window')} "
        f"ssrf_reachable={seam.get('ssrf_reachable')} "
        f"egress_allowlist={seam.get('egress_allowlist')}"
    )
    return lines


def _fmt_standing(standing: list) -> list[str]:
    if not standing:
        return ["- Security HARD-GATE compliance items: (none)"]
    lines = ["- Security HARD-GATE compliance items:"]
    for item in standing:
        lines.append(
            f"    - [{item.get('severity')}/{item.get('status')}] {item.get('title')} "
            f"(escalate_to={item.get('escalate_to')})"
        )
    return lines


def _fmt_findings(findings: list) -> list[str]:
    if not findings:
        return ["- Findings: none (secure-by-design review clean / no pending compliance)"]
    lines = ["- Findings:"]
    for f in findings:
        lines.append(
            f"    - [{f.get('kind')} → {f.get('escalate_to')}] {f.get('target') or '-'}: {f.get('detail')}"
        )
    return lines


def _fmt_proposals(proposals: list) -> list[str]:
    if not proposals:
        return ["- Proposals: none"]
    lines = ["- Proposals (PROPOSE-ONLY — no fix/rotation/deploy/kill-switch taken):"]
    for p in proposals:
        lines.append(f"    - [{p.get('escalate_to')}/{p.get('proposal_type')}] {p.get('action')}")
    return lines


def _deterministic_report(surface: dict, standing: list, findings: list, proposals: list) -> str:
    """A skimmable plain-text report built ENTIRELY from the gathered dicts (no model)."""
    lines = ["CISO: operational security posture", ""]
    lines += _fmt_surface(surface)
    lines += _fmt_standing(standing)
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
