"""clo — Lex, the Chief Legal Officer (CLO), PROPOSE-ONLY / HITL.

Runtime: cloud/CI (LangGraph Platform managed Cloud SaaS); registered in ``langgraph.json``
(the orchestrator owns that file — not this module).

Lex is a C-SUITE officer reporting to the CEO. Lex owns the LEGAL surface of the company and
CONSUMES the relevant state rather than re-doing work. It is the LEGAL twin of the CISO security
angle: where Lior (security_officer) reads the IDOR as a SECURITY item, Lex reads the SAME item as a
breach-NOTIFICATION-obligation legal item — and never DECIDES to notify.

Lex owns:
  * PRIVACY / GDPR + Israeli Privacy Protection Law — privacy-policy adequacy review.
  * IDOR breach-NOTIFICATION legal angle — reads the security item, drafts the notification-obligation
    assessment (GDPR Art.33/34 + Israeli PPA 2018 reg.11 timelines). NEVER decides to notify.
  * RevenueCat BILLING / refund / pricing TERMS vs the published ToS (consistency review).
  * ToS / contract review.
  * Contractor-vs-employee CLASSIFICATION (Israeli labor law).
  * The PUBLIC-CLAIM / OVERCLAIM review of marketing + website copy (flags to the CMO).

Lex uses the FOUR legal specialist agent-types as its SUB-REVIEWERS / lenses — corporate-lawyer,
legal-compliance-specialist, legal-document-auditor, hebrew-legal-translator (defined under
``.claude/agents/``) — and SYNTHESIZES their output into a single legal-posture digest of FLAGS +
DRAFT remediations. Each lens is applied deterministically here (the lenses are advisory review
perspectives, not callable graphs), so the synthesis runs FAIL-SAFE with zero credentials.

LOAD-BEARING DECISIONS (match the ops-fleet house style — cto.py / security_officer.py):

  * PROPOSE-ONLY / HITL. Lex REVIEWS + FLAGS + DRAFTS. It NEVER files a regulatory submission, signs a
    contract, sends a breach notice, binds the company, or takes any outward legal action — all of
    those are a Shay LEGAL HARD-GATE. No file / sign / send / submit / bind / buy / deploy function is
    reachable from ANY node; the only outward seam is ``file_digest_record`` (a durable RECORD) + the
    Slack mirror.

  * PROBATION / REPORT-ONLY by default. Delivery goes through ``file_digest_issue(...,
    report_only=_report_only())`` (env ``OPS_REPORT_ONLY``; truthy/unset => True). On probation the
    delivery is an honest report-only plan dict — NO code write, NO approval interrupt — so a
    scheduled unattended run can never hang.

  * NEVER HANG / FAIL-SAFE. No reachable approval/interrupt on the scheduled path; every read (the
    legal surface, prior digest, model summary) is wrapped; missing inputs degrade to deterministic
    flags, never a crash. A telemetry/network problem never crashes a node.

  * ANTHROPIC-TERMS / ML BOUNDARY. ``assert_not_model_work`` guards the digest repo string before any
    write; Lex does no model train/eval/distill — phrasing/synthesis only.

  * ESCALATION. Legal items that BIND the company (file a regulator, sign, send a breach notice) are
    irreversible/legal and escalate to ``"shay"`` (the LEGAL HARD-GATE). An overclaim flag is routed to
    the CMO (its peer in the marketing lane) and otherwise resolved inside the org (``"org"``).

  * Compiles WITHOUT a checkpointer/store (the platform injects Postgres). Every node body is wrapped
    in ``span("clo.<node>", ...)``; governance is captured (report_only=True) terminally.
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

# This officer's slug (prior-digest read + local artifact path + digest attribution).
AGENT = "clo"
# The repo the CLO posture digest issue is filed into (allow-listed in github_ops).
DIGEST_REPO = "Scheduler-Systems/qa-agent-platform"

# The FOUR legal specialist sub-reviewer lenses (the .claude/agents legal agent-types Lex synthesizes).
LEGAL_LENSES = (
    "corporate-lawyer",
    "legal-compliance-specialist",
    "legal-document-auditor",
    "hebrew-legal-translator",
)

# The LEGAL twin of the CISO security item: the Firestore IDOR #1487 is a personal-data BREACH-
# EXPOSURE, so it carries a notification-OBLIGATION assessment under GDPR Art.33/34 and the Israeli
# Privacy Protection Regulations 2018. Lex DRAFTS the assessment; it NEVER decides to notify (binding
# the company = a Shay LEGAL HARD-GATE). Standing item every run until the exposure is remediated.
IDOR_NOTIFICATION_ITEM = {
    "id": "idor-1487-breach-notification",
    "title": "BREACH-NOTIFICATION assessment: Firestore IDOR #1487 (cross-tenant personal data)",
    "area": "privacy",
    "status": "open",
    "detail": (
        "The #1487 IDOR exposes cross-tenant schedule data (personal data of data subjects). A "
        "notification-obligation assessment is required: GDPR Art.33 (supervisory authority, 72h) / "
        "Art.34 (data subjects, high risk) and Israeli Privacy Protection Regulations 2018 reg.11. "
        "Lex DRAFTS the assessment; the DECISION to notify a regulator or data subjects BINDS the "
        "company → Shay LEGAL HARD-GATE. Lex never sends a notice."
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
    surface: dict         # the reviewed legal surface (privacy/billing/marketing/labor inputs)
    lenses: dict          # per-lens (sub-reviewer) output Lex synthesizes
    standing: list        # standing legal items (the IDOR breach-notification assessment)
    findings: list        # legal findings (each escalate_to org|shay, routed peer cmo for overclaim)
    proposals: list       # legal proposals (legal_review / legal_finding / compliance) — DRAFTS only
    summary: str          # composed CLO posture text
    report: dict          # terminal verdict
    report_only: bool


def budget_gate(state: State) -> dict:
    """CLOCK-IN gate — STOP before any work if over salary or globally disabled.

    Runs FIRST. Clocked in => proceed to ``gather``; clocked out => governance (report-only) + END.
    No reads, no model spend, no writes on the clocked-out path.
    """
    with span("clo.budget_gate"):
        if check_clocked_in(AGENT):
            return {}
        governance_capture(
            AGENT,
            {"clocked_in": False, "delivery": "skipped", "report_only": True},
        )
        return {"report": {"clocked_in": False}}


def gather(state: State) -> dict:
    """Observe the LEGAL surface (privacy / billing / marketing / labor inputs). FAIL-SAFE.

    The surface is injectable (so a marketing/website/contract/privacy change can drive a run) and
    degrades to honest defaults when an input is absent. Each input names whether the corresponding
    legal artifact is KNOWN-present so analyze can flag a gap (a missing privacy policy, a billing/ToS
    mismatch, an overclaiming marketing string) rather than assume compliance.

    Inputs (all optional in ``state``):
      - ``privacy_policy_present``  : bool   — is a published privacy policy adequacy-reviewed?
      - ``billing_terms_match_tos`` : bool   — do the RC billing/refund/pricing terms match the ToS?
      - ``marketing_claims``        : list   — public-claim strings to overclaim-review.
      - ``contractor_terms_present``: bool   — are contractor agreements classification-reviewed?
    """
    with span("clo.gather"):
        prior = read_local_digest(AGENT)

        surface = {
            # Default to the KNOWN at-risk posture (overclaim history + IDOR breach) so a zero-input
            # scheduled run still raises the standing legal flags instead of a false "all clear".
            "privacy_policy_present": bool(state.get("privacy_policy_present", False)),
            "billing_terms_match_tos": bool(state.get("billing_terms_match_tos", True)),
            "marketing_claims": list(state.get("marketing_claims") or _DEFAULT_MARKETING_CLAIMS),
            "contractor_terms_present": bool(state.get("contractor_terms_present", True)),
        }

        standing = [dict(IDOR_NOTIFICATION_ITEM)]
        return {"prior": prior, "surface": surface, "standing": standing}


def analyze(state: State) -> dict:
    """Apply the four legal-specialist lenses and synthesize FLAGS. Deterministic — no model.

    Each lens is a sub-reviewer perspective; Lex runs them over the surface and collects findings:
      - corporate-lawyer          → RevenueCat billing/refund/pricing terms vs published ToS; ToS.
      - legal-compliance-specialist → privacy/GDPR + Israeli Privacy Law adequacy; breach-notification.
      - legal-document-auditor    → public-claim / OVERCLAIM review of marketing + website copy.
      - hebrew-legal-translator   → contractor-vs-employee classification under Israeli labor law.
    The IDOR is read here as the breach-NOTIFICATION legal angle (the twin of Lior's security item).
    """
    surface = state.get("surface") or {}
    standing = state.get("standing") or []

    with span("clo.analyze"):
        findings: list = []
        lenses: dict = {lens: [] for lens in LEGAL_LENSES}

        # legal-compliance-specialist: privacy-policy adequacy (GDPR + Israeli Privacy Law).
        if not surface.get("privacy_policy_present"):
            f = {"kind": "privacy_gap", "area": "privacy", "lens": "legal-compliance-specialist",
                 "target": "privacy-policy",
                 "detail": "no adequacy-reviewed published privacy policy — GDPR Arts.12-14 + Israeli "
                           "Privacy Protection Law disclosure duties unmet. DRAFT a compliant policy.",
                 "escalate_to": "org"}
            findings.append(f)
            lenses["legal-compliance-specialist"].append(f)

        # corporate-lawyer: RC billing/refund/pricing terms vs the published ToS.
        if not surface.get("billing_terms_match_tos"):
            f = {"kind": "billing_tos_mismatch", "area": "billing", "lens": "corporate-lawyer",
                 "target": "revenuecat-terms",
                 "detail": "RevenueCat billing/refund/pricing terms do NOT match the published ToS — "
                           "consumer-law / unfair-terms exposure. DRAFT aligned ToS + refund clause.",
                 "escalate_to": "shay"}
            findings.append(f)
            lenses["corporate-lawyer"].append(f)

        # legal-document-auditor: public-claim / OVERCLAIM review of marketing + website copy. An
        # overclaim is routed to the CMO (peer in the marketing lane), not Shay.
        for claim in surface.get("marketing_claims") or []:
            if _is_overclaim(claim):
                f = {"kind": "overclaim", "area": "marketing", "lens": "legal-document-auditor",
                     "target": "marketing-copy", "claim": claim,
                     "detail": f"public claim '{claim}' may overstate a shipped capability "
                               "(false-advertising / consumer-protection exposure). Flag to the CMO; "
                               "DRAFT corrected copy.",
                     "escalate_to": "org", "route_peer": "cmo"}
                findings.append(f)
                lenses["legal-document-auditor"].append(f)

        # hebrew-legal-translator: contractor-vs-employee classification (Israeli labor law).
        if not surface.get("contractor_terms_present"):
            f = {"kind": "classification_risk", "area": "labor", "lens": "hebrew-legal-translator",
                 "target": "contractor-agreements",
                 "detail": "no classification-reviewed contractor agreements — Israeli labor-law "
                           "misclassification (employee-in-substance) exposure. DRAFT compliant terms.",
                 "escalate_to": "org"}
            findings.append(f)
            lenses["hebrew-legal-translator"].append(f)

        # The IDOR breach-NOTIFICATION assessment (the legal twin of the CISO security item).
        for item in standing:
            if item.get("status") in ("open", "pending", "held"):
                f = {"kind": "breach_notification", "area": item.get("area", "privacy"),
                     "lens": "legal-compliance-specialist", "target": item.get("id"),
                     "detail": f"{item.get('title')} — {item.get('detail')}",
                     "escalate_to": item.get("escalate_to", "shay")}
                findings.append(f)
                lenses["legal-compliance-specialist"].append(f)

        return {"findings": findings, "lenses": lenses}


def propose(state: State) -> dict:
    """Synthesize the lens findings into legal PROPOSALS — DRAFTS + FLAGS only. Never binds.

    Each finding becomes a proposed action tagged with its escalation lane, proposal TYPE
    (legal_review / legal_finding / compliance), and — for an overclaim — the PEER it routes to
    (the CMO). Lex NEVER files, signs, sends, or binds here.
    """
    findings = state.get("findings") or []

    with span("clo.propose", findings=len(findings)):
        proposals: list = []
        for f in findings:
            kind = f.get("kind")
            escalate = f.get("escalate_to", "org")
            if kind == "breach_notification":
                action = ("propose:compliance — DRAFT the breach-notification-obligation assessment "
                          "(GDPR Art.33/34 + Israeli PPR 2018 reg.11) for the #1487 IDOR exposure. The "
                          "DECISION to notify a regulator / data subjects BINDS the company → Shay "
                          "LEGAL HARD-GATE. Lex drafts; a human decides + sends.")
                ptype = "compliance"
            elif kind == "billing_tos_mismatch":
                action = ("propose:legal_review — DRAFT aligned RevenueCat billing/refund/pricing terms "
                          "+ ToS. Signing/publishing the ToS BINDS the company → human-gated. Draft only.")
                ptype = "legal_review"
            elif kind == "privacy_gap":
                action = ("propose:compliance — DRAFT a GDPR + Israeli-Privacy-Law-compliant privacy "
                          "policy. Publishing it is a human gate. Draft only.")
                ptype = "compliance"
            elif kind == "overclaim":
                action = (f"propose:legal_finding — FLAG overclaim to the CMO: '{f.get('claim')}'. "
                          "DRAFT corrected, defensible copy. Lex flags + drafts; the CMO/human edits.")
                ptype = "legal_finding"
            elif kind == "classification_risk":
                action = ("propose:legal_review — DRAFT classification-compliant contractor terms "
                          "(Israeli labor law). Signing BINDS the company → human-gated. Draft only.")
                ptype = "legal_review"
            else:
                action = f"propose:legal_finding — review legal item: {f.get('detail')}"
                ptype = "legal_finding"
            proposals.append({
                "action": action, "kind": kind, "proposal_type": ptype, "area": f.get("area"),
                "lens": f.get("lens"), "target": f.get("target"), "detail": f.get("detail"),
                "escalate_to": escalate, "route_peer": f.get("route_peer"),
            })

        if not proposals:
            proposals.append({
                "action": "propose:legal_review — no new legal flag this cycle; continue the privacy / "
                          "billing-vs-ToS / overclaim / classification watch. Review + flag + draft "
                          "only; never file/sign/send/bind (Shay LEGAL HARD-GATE).",
                "kind": "monitor", "proposal_type": "legal_review", "area": None, "lens": None,
                "target": None, "detail": "no open legal finding beyond standing watch",
                "escalate_to": "org", "route_peer": None,
            })

        return {"proposals": proposals}


def compose(state: State) -> dict:
    """Phrase the legal posture + proposals as a concise CLO digest. FAIL-SAFE.

    The model (TIER_DEFAULT, metered via ``budget_guard``) is used ONLY to phrase already-gathered
    facts. On ANY failure we fall back to a DETERMINISTIC report so a digest is always produced. No
    model train/eval/distill — phrasing/synthesis only.
    """
    surface = state.get("surface") or {}
    lenses = state.get("lenses") or {}
    standing = state.get("standing") or []
    findings = state.get("findings") or []
    proposals = state.get("proposals") or []

    with span("clo.compose", findings=len(findings), proposals=len(proposals)):
        facts = _deterministic_report(surface, lenses, standing, findings, proposals)
        summary = ""
        try:
            model = budget_guard(AGENT, TIER_DEFAULT)
            prompt = (
                "You are the CLO (Chief Legal Officer) for the Scheduler product company. You have "
                "synthesized four legal sub-reviewers (corporate-lawyer, legal-compliance-specialist, "
                "legal-document-auditor, hebrew-legal-translator). Write a CONCISE legal-posture "
                "digest of FLAGS + DRAFT remediations from the facts below. Cover, in order: (1) "
                "privacy/GDPR + Israeli Privacy Law, (2) the IDOR #1487 breach-NOTIFICATION-obligation "
                "assessment, (3) RevenueCat billing/refund/pricing vs ToS, (4) public-claim/OVERCLAIM "
                "review (flag to the CMO), (5) contractor classification. Make clear what is a Shay "
                "LEGAL HARD-GATE. Do NOT invent state. REVIEW + FLAG + DRAFT only — never claim a "
                "filing/signature/notice/binding action was taken.\n\n"
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
    """Write a local digest + file the CLO posture digest as a DURABLE RECORD (report-only on probation).

    A digest is a RECORD, not a binding legal action; it writes via the durable record path. On
    probation (default) it returns an honest report-only plan dict with NO code write and NO approval
    interrupt — an unattended run can never hang or write. Lex never files/signs/sends here.
    """
    summary = state.get("summary") or ""
    surface = state.get("surface") or {}
    lenses = state.get("lenses") or {}
    standing = state.get("standing") or []
    findings = state.get("findings") or []
    proposals = state.get("proposals") or []
    report_only = _report_only()

    with span("clo.deliver", report_only=report_only):
        assert_not_model_work(DIGEST_REPO)  # never file into a model-dev repo
        body = (
            summary
            + "\n\n---\n\n## Raw facts\n\n"
            + _deterministic_report(surface, lenses, standing, findings, proposals)
        )

        digest_path = write_local_digest(AGENT, "CLO: legal posture (flags + drafts)", body)

        res = file_digest_issue(
            DIGEST_REPO,
            "CLO: legal posture — flags + draft remediations (proposal)",
            body,
            labels=["exec:clo", "legal"],
            report_only=report_only,
            agent=AGENT,
            record_kind="clo-posture",
            slack_title="⚖️ CLO: legal posture — flags + drafts (proposal)",
        )
        delivery = res.get("status") if isinstance(res, dict) else None
        return {
            "report": {"delivery": delivery, "digest": digest_path, "report_only": report_only},
            "report_only": report_only,
        }


def finalize(state: State) -> dict:
    """Terminal node — capture governance (report-only) and emit the verdict."""
    findings = state.get("findings") or []
    proposals = state.get("proposals") or []
    prior = state.get("report") or {}
    delivery = prior.get("delivery")
    shay_asks = sum(1 for p in proposals if p.get("escalate_to") == "shay")
    cmo_routed = sum(1 for p in proposals if p.get("route_peer") == "cmo")

    with span("clo.finalize", delivery=delivery, shay_asks=shay_asks):
        governance_capture(
            AGENT,
            {
                "findings": len(findings),
                "proposals": len(proposals),
                "shay_asks": shay_asks,
                "cmo_routed": cmo_routed,
                "delivery": delivery,
                "report_only": True,
            },
        )
        return {
            "report": {
                "findings": len(findings),
                "proposals": len(proposals),
                "shay_asks": shay_asks,
                "cmo_routed": cmo_routed,
                "delivery": delivery,
                "digest": prior.get("digest"),
                "report_only": True,
            }
        }


def _budget_route(state: State) -> str:
    """Route past the clock-in gate: clocked in -> gather; clocked out -> END."""
    return "gather" if check_clocked_in(AGENT) else "clocked_out"


# --- overclaim heuristics + defaults -----------------------------------------------------
# Grounded in the verified Scheduler claims-truth note: the listing OVERCLAIMS time-tracking +
# AI scheduling (the product does per-user shift scheduling, NOT time-tracking/clock or AI
# scheduling). A claim hitting one of these tokens is flagged for the CMO.
_OVERCLAIM_TOKENS = ("time tracking", "time-tracking", "clock in", "clock-in", "ai scheduling",
                     "ai-powered scheduling", "offline", "automatic scheduling", "flat rate",
                     "guaranteed", "best in class", "100%", "fully automated")

# A zero-input scheduled run reviews the KNOWN at-risk public claims so a flag is raised even with
# no injected marketing copy (the listing's standing overclaim posture).
_DEFAULT_MARKETING_CLAIMS = (
    "AI scheduling that builds your roster automatically",
    "Built-in time tracking and clock-in",
)


def _is_overclaim(claim: str) -> bool:
    low = (claim or "").strip().lower()
    return any(tok in low for tok in _OVERCLAIM_TOKENS)


# --- Deterministic report helpers (used by compose fallback + the issue appendix) --------
def _fmt_surface(surface: dict) -> list[str]:
    return [
        "- Legal surface reviewed:",
        f"    - privacy policy adequacy-reviewed: {surface.get('privacy_policy_present')}",
        f"    - RC billing/refund/pricing match ToS: {surface.get('billing_terms_match_tos')}",
        f"    - contractor terms classification-reviewed: {surface.get('contractor_terms_present')}",
        f"    - marketing claims reviewed: {len(surface.get('marketing_claims') or [])}",
    ]


def _fmt_lenses(lenses: dict) -> list[str]:
    lines = ["- Sub-reviewer lenses (synthesized):"]
    for lens in LEGAL_LENSES:
        hits = lenses.get(lens) or []
        lines.append(f"    - {lens}: {len(hits)} flag(s)")
    return lines


def _fmt_standing(standing: list) -> list[str]:
    if not standing:
        return ["- Standing legal items: (none)"]
    lines = ["- Standing legal items:"]
    for item in standing:
        lines.append(
            f"    - [{item.get('area')}/{item.get('status')}] {item.get('title')} "
            f"(escalate_to={item.get('escalate_to')})"
        )
    return lines


def _fmt_findings(findings: list) -> list[str]:
    if not findings:
        return ["- Findings: none (legal review clean)"]
    lines = ["- Findings:"]
    for f in findings:
        peer = f" → peer:{f.get('route_peer')}" if f.get("route_peer") else ""
        lines.append(
            f"    - [{f.get('kind')} → {f.get('escalate_to')}{peer}] "
            f"({f.get('lens')}) {f.get('target') or '-'}: {f.get('detail')}"
        )
    return lines


def _fmt_proposals(proposals: list) -> list[str]:
    if not proposals:
        return ["- Proposals: none"]
    lines = ["- Proposals (PROPOSE-ONLY / DRAFTS — no filing/signature/notice/binding taken):"]
    for p in proposals:
        peer = f"/peer:{p.get('route_peer')}" if p.get("route_peer") else ""
        lines.append(f"    - [{p.get('escalate_to')}/{p.get('proposal_type')}{peer}] {p.get('action')}")
    return lines


def _deterministic_report(surface: dict, lenses: dict, standing: list,
                          findings: list, proposals: list) -> str:
    """A skimmable plain-text report built ENTIRELY from the gathered dicts (no model)."""
    lines = ["CLO: legal posture (flags + draft remediations)", ""]
    lines += _fmt_surface(surface)
    lines += _fmt_lenses(lenses)
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
