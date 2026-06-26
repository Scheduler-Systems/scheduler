"""A2A governance gate — make agent-to-agent (and agent-to-human) conversation a GOVERNED surface.

No new policy engine: an A2A turn is governed by the artifacts already built this session.
  * WHO-MAY-TALK — the sender must hold a `message:<target>` capability grant (capabilities.yaml,
    CI-enforced allow-list). An agent calling `/a2a/{target}` without it is denied BEFORE the
    message leaves (default-deny). Stops an android tester from DMing the board.
  * HITL — an OUTWARD turn (to the human, or a public/customer Slack surface) is a `message_to_person`
    action routed through hitl.human_gate() before delivery; INTERNAL agent→agent turns are autonomous.
  * AUDIT — every turn appends a hash-chained entry keyed by the A2A contextId (the conversation/thread)
    → tamper-evident record. The LangGraph Store namespace ("a2a_audit", contextId) is the durable sink.

Pure functions (no IO) so it is unit-tested directly; hitl/authority are loaded by path so this
imports without the heavy agent_toolkit package (deps-free CI venv). Call `gate_a2a` immediately
before any `a2a_client.a2a_send`.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import pathlib
from typing import Any


def _sibling(mod_name: str):
    """Load a sibling module by path (avoids agent_toolkit/__init__ which pulls heavy ML deps)."""
    spec = importlib.util.spec_from_file_location(mod_name, pathlib.Path(__file__).with_name(f"{mod_name}.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _message_targets(agent: str, capabilities: dict[str, Any]) -> set[str]:
    """The set of targets this agent may `message:` (from its capability grant)."""
    grant = (capabilities.get("grants") or {}).get(agent) or {}
    targets = set()
    for c in grant.get("capabilities") or []:
        cap = str(c.get("capability", ""))
        if cap.startswith("message:"):
            targets.add(cap.split(":", 1)[1].strip())
    return targets


def is_outward(target: str) -> bool:
    """Outward = reaches the human or a public/customer surface (gets HITL). Internal agent→agent is not."""
    t = str(target).strip().lower()
    return t == "human" or t.startswith("slack:") or t.startswith("external:")


def may_message(from_agent: str, target: str, capabilities: dict[str, Any]) -> tuple[bool, str]:
    """Capability check (default-deny): does `from_agent` hold `message:<target>`?"""
    targets = _message_targets(from_agent, capabilities)
    if target in targets:
        return True, f"{from_agent} may message {target}"
    return False, f"{from_agent} has no 'message:{target}' grant — denied (default-deny)"


def _audit_entry(seq: int, from_agent: str, target: str, capability_ok: bool,
                 hitl_record: Any, approver: str, prev_hash: str) -> dict[str, Any]:
    body = {"seq": seq, "from": from_agent, "to": target, "capability_ok": capability_ok,
            "hitl": hitl_record, "approver": approver, "prev_hash": prev_hash}
    body["hash"] = hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()
    return body


def gate_a2a(from_agent: str, target: str, text: str, *, capabilities: dict[str, Any],
             mandate: dict[str, Any] | None = None, report_only: bool = True,
             seq: int = 0, prev_hash: str = "") -> dict[str, Any]:
    """Govern one A2A turn. Returns {allowed, approver, reason, audit, hitl}.

    allowed=False means do NOT send (capability denied, or HITL blocked in live mode).
    """
    ok, reason = may_message(from_agent, target, capabilities)
    if not ok:
        return {"allowed": False, "approver": None, "reason": reason,
                "audit": _audit_entry(seq, from_agent, target, False, None, "denied", prev_hash),
                "hitl": None}

    hitl_record = None
    approver = "auto"
    if is_outward(target):
        hitl = _sibling("hitl")
        action = {"kind": "message_to_person", "outward": True, "capability": f"message:{target}",
                  "target": target}
        try:
            hitl_record = hitl.human_gate(action, agent=from_agent, report_only=report_only, mandate=mandate)
        except Exception as exc:
            # Cannot obtain human approval (no LangGraph runtime / interrupt) → FAIL-CLOSED:
            # an outward turn must never be delivered without the human gate actually running.
            return {"allowed": False, "approver": "human",
                    "reason": f"HITL unavailable — fail-closed ({type(exc).__name__})",
                    "audit": _audit_entry(seq, from_agent, target, True, {"hitl_error": str(exc)[:80]},
                                          "human", prev_hash),
                    "hitl": None}
        approver = hitl_record.get("approver", "owner")
        # In LIVE mode a human-required outward turn must be approved before it can be delivered.
        if not report_only and hitl_record.get("blocked"):
            return {"allowed": False, "approver": approver, "reason": "HITL: awaiting human approval",
                    "audit": _audit_entry(seq, from_agent, target, True, hitl_record, approver, prev_hash),
                    "hitl": hitl_record}

    return {"allowed": True, "approver": approver,
            "reason": "internal agent→agent (autonomous)" if not is_outward(target) else "outward — HITL applied",
            "audit": _audit_entry(seq, from_agent, target, True, hitl_record, approver, prev_hash),
            "hitl": hitl_record}
