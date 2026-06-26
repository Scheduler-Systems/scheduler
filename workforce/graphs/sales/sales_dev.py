"""sales_dev — the Sales & Lead Gen agent (the operations map's empty, revenue-adjacent area).

Owns lead qualification, pipeline review, and follow-up DRAFTS — the 9 processes that were
100% manual/founder. PROPOSE-ONLY / PROBATION, and critically NEVER auto-sends outreach
(the "no send without approval" rule): every proposed touch is a DRAFT a human approves.

Pattern mirrors the rest of the fleet: budget_gate → gather → qualify → propose → deliver,
FAIL-SAFE throughout (a missing CRM key / network error degrades to the declared baseline and
still produces a non-empty proposal set). report-only delivery via file_digest_issue.

Data sources (FAIL-SAFE, both optional):
  * Brevo CRM — contacts/deals when ``BREVO_API_KEY`` is set (read-only).
  * declared funnel baseline — so the agent always has something to reason over.
"""
from __future__ import annotations

import os
from typing_extensions import TypedDict

import httpx
from langgraph.graph import StateGraph, START, END

from agent_toolkit import (
    span, governance_capture, budget_guard, check_clocked_in,
    write_local_digest, file_digest_issue, TIER_DEFAULT,
)

_AGENT = "sales_dev"
DIGEST_REPO = "Scheduler-Systems/qa-agent-platform"  # allow-listed, no-prod-deploy

# Declared baseline (verified facts; the agent never invents pipeline numbers). Kept conservative
# until the CRM read is wired — the agent's value is qualification + drafts, not fabricated stats.
_BASELINE = {
    "channels": ["LinkedIn (B2B shift-scheduling teams)", "Brevo email outreach", "inbound app trials"],
    "icp": "operations/HR leads at 10-100 employee shift-based businesses",
    "known_gaps": ["lead_qualification_manual", "no_deal_pipeline", "no_automated_followups"],
}


def _report_only() -> bool:
    return os.environ.get("OPS_REPORT_ONLY", "").lower() not in ("0", "false", "no")


class State(TypedDict, total=False):
    crm: dict
    findings: dict
    proposals: list
    summary: str
    report_only: bool
    delivery: str


def budget_gate(state: State) -> dict:
    if not check_clocked_in(_AGENT):
        governance_capture(_AGENT, {"decision": "clocked_out", "report_only": True})
        return {"delivery": "skipped", "report_only": True}
    return {}


def _budget_route(state: State) -> str:
    return "clocked_out" if state.get("delivery") == "skipped" else "gather"


def gather(state: State) -> dict:
    """Read the CRM (Brevo) if configured — FAIL-SAFE — else fall back to the declared baseline."""
    with span("sales_dev.gather"):
        crm = {"source": "declared_baseline", "contacts": None, "ok": False}
        key = os.environ.get("BREVO_API_KEY", "").strip()
        if key:
            try:
                r = httpx.get("https://api.brevo.com/v3/contacts", params={"limit": 1},
                              headers={"api-key": key, "accept": "application/json"}, timeout=20.0)
                if r.status_code // 100 == 2:
                    crm = {"source": "brevo", "ok": True, "contacts": (r.json() or {}).get("count")}
                else:
                    crm = {"source": "brevo", "ok": False, "error": f"HTTP {r.status_code}"}
            except Exception as exc:  # noqa: BLE001
                crm = {"source": "brevo", "ok": False, "error": f"request failed: {type(exc).__name__}"}
        return {"crm": crm}


def qualify(state: State) -> dict:
    """Identify the lead-gen gaps + a prioritized focus. Deterministic + FAIL-SAFE."""
    with span("sales_dev.qualify"):
        crm = state.get("crm") or {}
        findings = {
            "crm_source": crm.get("source"),
            "crm_contacts": crm.get("contacts"),
            "icp": _BASELINE["icp"],
            "gaps": list(_BASELINE["known_gaps"]),
            # The honest top priority: with ~0.4% paid conversion, qualify inbound trials HARD
            # before spending on cold outreach.
            "priority": "qualify inbound app-trial signups against ICP before any cold outreach",
        }
        return {"findings": findings}


def propose(state: State) -> dict:
    """Draft 3 concrete, propose-only sales actions. NEVER sends. Optional model phrasing."""
    with span("sales_dev.propose"):
        findings = state.get("findings") or {}
        proposals = [
            {"action": "Stand up lead qualification", "draft": True,
             "what": "Score inbound app-trial signups against ICP (team size, shift-based, role) and tag hot leads in Brevo.",
             "why": "Paid conversion ~0.4% — qualifying inbound before cold outreach is the cheapest lift.",
             "escalate_to": "org"},
            {"action": "Define a 3-stage deal pipeline", "draft": True,
             "what": "Trial → Qualified → Demo/Close, tracked in Brevo; weekly review surfaces stuck deals.",
             "why": "No pipeline today; deals are invisible, so follow-up is ad hoc.", "escalate_to": "org"},
            {"action": "Draft an automated follow-up sequence (DRAFTS ONLY)", "draft": True,
             "what": "3-touch sequence for qualified trials; each message is a DRAFT a human approves before send.",
             "why": "Follow-ups are manual; drafting them is safe and frees the founder.",
             "escalate_to": "shay", "note": "NO auto-send — approval required per policy."},
        ]
        # Optional one-line model rationale (phrasing only; deterministic proposals stand on failure).
        try:
            m = budget_guard(_AGENT, TIER_DEFAULT)
            r = m.invoke("In ONE short, plain sentence, summarize this sales focus for the team "
                         f"(no emoji, no fluff): {findings.get('priority')}")
            rationale = (getattr(r, "content", str(r)) or "").strip()
        except Exception:  # noqa: BLE001
            rationale = findings.get("priority", "")
        return {"proposals": proposals, "summary_hint": rationale}


def deliver(state: State) -> dict:
    """Report-only delivery: local digest + file_digest_issue (GitHub gated, Slack posted)."""
    with span("sales_dev.deliver"):
        findings = state.get("findings") or {}
        proposals = state.get("proposals") or []
        body_lines = ["# Sales & Lead Gen — proposals (propose-only, drafts; nothing sent)",
                      f"CRM: {findings.get('crm_source')} · ICP: {findings.get('icp')}",
                      f"Priority: {findings.get('priority')}", "", "## Proposed actions"]
        for i, p in enumerate(proposals, 1):
            body_lines.append(f"{i}. {p['action']} — {p['what']} (why: {p['why']}; → {p['escalate_to']})")
        body = "\n".join(body_lines)
        report_only = _report_only()
        write_local_digest(_AGENT, "Sales & Lead Gen proposals", body)
        res = file_digest_issue(
            DIGEST_REPO, "Sales & Lead Gen — proposals (drafts)", body,
            labels=["sales:proposals"], report_only=report_only, agent=_AGENT,
            slack_title="Sales & Lead Gen — proposals (drafts)",
        )
        delivery = res.get("status") if isinstance(res, dict) else None
        governance_capture(_AGENT, {"decision": "proposed", "report_only": report_only,
                                    "n_proposals": len(proposals)})
        return {"summary": body, "report_only": report_only, "delivery": delivery}


# --- Graph wiring ------------------------------------------------------------------------
builder = StateGraph(State)
builder.add_node("budget_gate", budget_gate)
builder.add_node("gather", gather)
builder.add_node("qualify", qualify)
builder.add_node("propose", propose)
builder.add_node("deliver", deliver)

builder.add_edge(START, "budget_gate")
builder.add_conditional_edges("budget_gate", _budget_route, {"gather": "gather", "clocked_out": END})
builder.add_edge("gather", "qualify")
builder.add_edge("qualify", "propose")
builder.add_edge("propose", "deliver")
builder.add_edge("deliver", END)

graph = builder.compile()  # NO checkpointer/store — injected by the platform
