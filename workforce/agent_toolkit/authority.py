"""Delegation router — turns the enterprise OWNER out of the operational loop.

The owner (Shay) sets a delegation mandate (docs/governance/delegation.yaml) ONCE; from then on
the agent org decides within it. ``route(decision, mandate)`` answers "who approves THIS decision?"
— almost always an agent-officer (cfo/cto/hr/ceo/board), the owner only at the bright line.

Safety invariants (all default-deny / fail-safe toward the owner; hardened after adversarial
red-team 2026-06-06):
  * ``owner_reserved`` decisions ALWAYS route to the owner — by ``kind`` AND by force-flags (a
    flag counts when PRESENT and not literally ``False``, so a falsy 0/""/None can't suppress it).
  * Spend amounts must be FINITE and NON-NEGATIVE; NaN / ±inf / negative / unparseable all
    fail-closed to the owner (NaN previously threaded between the two numeric guards). A spend
    above ``max_board_spend_usd`` is bet-the-company → owner. Missing/invalid caps fail closed.
  * An UNKNOWN decision kind, or one that can't be shown within limit, escalates UP — never
    auto-approved by an officer.
  * The mandate is live only when the OWNER granted it: ``status: granted`` AND ``granted_by`` ==
    the owner. While not granted the router is INERT — every verdict is the owner with
    ``active=False`` (``would_be`` records who WOULD decide once granted).

Editing the mandate itself is ``change_mandate`` — owner-reserved. ``constitution_paths()`` flags a
diff touching ``docs/governance/`` so a merge gate routes it to the owner, never to an officer.

Pure (no IO) so it is unit-tested directly. Pairs with hitl.py (the pause that waits for the
approver this router names) and capabilities.yaml (what each agent may DO; this is who may DECIDE).
"""
from __future__ import annotations

import math
from typing import Any

# Force-detect owner-reserved decisions regardless of the self-asserted ``kind`` (defense in depth).
RESERVED_FLAGS: tuple[str, ...] = (
    "touches_billing",
    "touches_paying_customers",
    "moves_real_money",
    "changes_entity",
    "changes_captable",
    "changes_mandate",
    "security_rules",
    "appoints_board",
)

# Editing anything here is a constitution change (owner-reserved), not routine docs.
GOVERNANCE_PATHS: tuple[str, ...] = ("docs/governance/",)


def _verdict(approver: str, tier: str, reason: str, *, active: bool,
             within_limit: bool | None = None, would_be: str | None = None) -> dict[str, Any]:
    v = {"approver": approver, "tier": tier, "reason": reason, "active": active}
    if within_limit is not None:
        v["within_limit"] = within_limit
    if would_be is not None:
        v["would_be"] = would_be
    return v


def _finite_nonneg(v: Any) -> float | None:
    """Parse v as a finite, non-negative float; None if NaN/inf/negative/unparseable (→ fail closed)."""
    if isinstance(v, bool):  # bool is an int subclass — don't accept True/False as an amount
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) and f >= 0 else None


def _flagged_reserved(decision: dict[str, Any]) -> str | None:
    """A force-flag counts when PRESENT and not literally False (a falsy 0/''/None still flags)."""
    for flag in RESERVED_FLAGS:
        if flag in decision and decision[flag] is not False:
            return flag
    return None


def _within_limit(decision: dict[str, Any], caps: dict[str, Any]) -> bool:
    """Default-deny: True only if the decision is provably within an officer's limit."""
    amt = decision.get("amount_usd")
    if amt is not None:
        a = _finite_nonneg(amt)
        cap = _finite_nonneg(caps.get("max_officer_spend_usd"))
        if a is None or cap is None:   # bad amount or missing/invalid cap → deny
            return False
        return a <= cap
    # Non-spend decisions must assert policy compliance explicitly (audited); absence = deny.
    return decision.get("within_policy") is True


def _is_granted(mandate: dict[str, Any]) -> bool:
    """Live only if the OWNER granted it: status granted AND granted_by == the owner."""
    owner = mandate.get("owner")
    return bool(owner) and mandate.get("status") == "granted" and mandate.get("granted_by") == owner


def route(decision: dict[str, Any], mandate: dict[str, Any]) -> dict[str, Any]:
    """Return the approval verdict for ``decision`` under ``mandate``.

    ``decision`` fields: ``kind`` (required), optional ``amount_usd``, ``within_policy`` (bool),
    and any RESERVED_FLAGS. ``mandate`` = parsed delegation.yaml.
    """
    kind = str(decision.get("kind", "")).strip()
    reserved = set(mandate.get("owner_reserved") or [])
    caps = mandate.get("mandate") or {}
    granted = _is_granted(mandate)

    def to_owner(reason: str, within: bool | None = None) -> dict[str, Any]:
        # active reflects whether delegation is LIVE; inert (proposed) → active=False everywhere.
        return _verdict("owner", "owner", reason, active=granted, within_limit=within)

    # 1) Force-flags → owner, no matter what `kind` claims.
    flag = _flagged_reserved(decision)
    if flag:
        return to_owner(f"force-flagged '{flag}' — owner-reserved (bright line), never delegable")

    # 2) Owner-reserved by kind → owner, always.
    if kind in reserved:
        return to_owner(f"'{kind}' is owner-reserved (bright line) — never delegable")

    # 3) Spend validity + bet-the-company. NaN/inf/negative/unparseable all fail closed to owner.
    amt = decision.get("amount_usd")
    if amt is not None:
        a = _finite_nonneg(amt)
        board_cap = _finite_nonneg(caps.get("max_board_spend_usd"))
        if a is None:
            return to_owner("invalid spend amount (non-finite/negative/unparseable) — default-deny", within=False)
        if board_cap is None:
            return to_owner("spend cap misconfigured — default-deny to owner", within=False)
        if a > board_cap:
            return to_owner("spend exceeds board authority — bet-the-company, owner-reserved", within=False)

    # 4) Find the delegated lane. Unknown decision → default-deny up to the owner.
    lane = (mandate.get("authorities") or {}).get(kind)
    if not lane:
        return to_owner(f"no delegated authority for '{kind}' — default-deny, owner decides", within=False)

    decider = lane.get("decider", "owner")
    within = _within_limit(decision, caps)

    # 5) INERT until the owner grants the mandate: owner decides, but record who WOULD.
    if not granted:
        return _verdict("owner", "owner",
                        "delegation mandate not yet granted by the owner — owner decides (inert)",
                        active=False, within_limit=within, would_be=decider)

    # 6) Granted + within limit → the officer decides. Over limit → escalate up the chain.
    if within:
        return _verdict(decider, "officer", f"within {decider}'s delegated authority",
                        active=True, within_limit=True)

    chain = lane.get("escalates_to") or ["owner"]
    nxt = chain[0]
    tier = "owner" if nxt == "owner" else ("board" if nxt == "board" else "officer")
    return _verdict(nxt, tier, f"exceeds {decider}'s limit — escalates to {nxt}",
                    active=True, within_limit=False)


def reaches_owner(decision: dict[str, Any], mandate: dict[str, Any]) -> bool:
    """Does this decision require the OWNER (vs. an agent-officer)? (Independent of granted state —
    while inert, everything reaches the owner; once granted, only the bright line does.)"""
    return route(decision, mandate)["approver"] == "owner"


def constitution_paths(paths: Any) -> list[str]:
    """The subset of ``paths`` that touch the governance dir — editing them is ``change_mandate``
    (owner-reserved). A merge gate must route any non-empty result to the owner, never an officer."""
    return [p for p in (paths or []) if any(g in str(p) for g in GOVERNANCE_PATHS)]
