"""Human-in-the-loop gate — the PEP-side enforcement of the governance HITL policy.

An agent action that is **outward-facing or irreversible** (an OSS/external-repo contribution,
a message to a person, a public post, an account/permission change, a paying-customer action,
or real-money spend) NEVER fires on an agent's own authority. The agent does the work, then this
gate **stops and waits for a human** to approve / edit / reject. Fail-closed: no approval, no action.

Two halves, matching the PEP/PDP split:
  * ``human_required(action)`` — the DECISION (PDP). The ratified policy of which actions need a
    human (founder-approved 2026-06-06). Pure, no IO, no langgraph — unit-tested directly. Later
    this delegates to GAL ``/enforcement/check`` so the policy is centrally governed.
  * ``human_gate(action, ...)`` — the ENFORCEMENT (PEP). On ``report_only`` (probation default) it
    RECORDS that the action would need approval and returns without blocking (agents don't act yet).
    When live, it calls LangGraph ``interrupt()`` to actually pause the run until a human resumes it.

``interrupt`` is lazy-imported so this module + the pure decision logic work without langgraph
installed (e.g. CI's deterministic test venv).

Three-tier consequence model (see docs/governance/gal-governance-everywhere.md §4):
  autonomous (safe/reversible/internal) · human-in-the-loop (outward/irreversible) · founder-gated.
"""
from __future__ import annotations

from typing import Any

# The ratified "always needs a human" categories (founder-approved 2026-06-06). An action whose
# ``kind`` is one of these ALWAYS requires a human, regardless of other attributes.
HUMAN_REQUIRED_KINDS: frozenset[str] = frozenset({
    "oss_contribution",            # any push / PR / comment to a public or external repo
    "message_to_person",           # email, Slack DM, external reply — anything reaching a human
    "publish",                     # public post / publish
    "account_change",              # account settings
    "permission_change",           # access-control / sharing / roles
    "paying_customer_action",      # anything touching a paying customer
    "spend_money",                 # moving real money (also blocked by the spend-only verb allow-list)
})

# Verb prefixes that are inherently internal + reversible → autonomous when the target is internal.
_INTERNAL_SAFE_VERBS: frozenset[str] = frozenset({"read", "propose"})


def human_required(action: dict[str, Any]) -> tuple[bool, str]:
    """The PDP decision. Returns ``(required, reason)``.

    ``action`` fields (all optional except ``kind``):
      * ``kind``        — semantic kind (see HUMAN_REQUIRED_KINDS) or a verb-ish hint.
      * ``outward``     — bool: does this reach outside the company / a human / the public?
      * ``external``    — bool: target is an external/public repo or surface.
      * ``capability``  — the capability string (e.g. ``"write:github_issue"``) if known.

    Default-deny on ambiguity: if it looks outward and isn't clearly internal+reversible, gate it.
    """
    kind = str(action.get("kind", "")).strip().lower()
    if kind in HUMAN_REQUIRED_KINDS:
        return True, f"'{kind}' is a ratified human-in-the-loop action"

    external = bool(action.get("external")) or bool(action.get("public"))
    outward = bool(action.get("outward")) or external

    cap = str(action.get("capability", ""))
    verb = cap.split(":", 1)[0].strip().lower() if cap else ""

    # An internal, reversible read/propose never needs a human.
    if verb in _INTERNAL_SAFE_VERBS and not outward:
        return False, "internal, reversible action (autonomous)"

    # Anything that reaches outside the company / a person / the public is gated.
    if outward:
        return True, "outward-facing or irreversible — reaches a person or the public"

    # An external write/push/post is gated even if 'kind' wasn't a known category.
    if external and verb in {"write", "post", "git"}:
        return True, "external write/post/push — outward-facing"

    return False, "internal action (autonomous)"


def human_gate(
    action: dict[str, Any],
    *,
    agent: str,
    report_only: bool = True,
    on_record: Any = None,
    mandate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Enforce the HITL policy for ``action`` performed by ``agent``.

    report_only=True (probation default): does NOT block — records that the action WOULD need a
    human and returns ``{"status": "auto"|"would_require_human", "blocked": False, ...}``.
    report_only=False (live): for a human-required action, calls LangGraph ``interrupt()`` to pause
    the run until the approver approves/edits/rejects, then returns the decision.

    ``mandate`` (optional, delegation.yaml): when supplied, the **approver** is resolved through the
    delegation router — usually an agent-OFFICER (cfo/cto/hr/...), the OWNER only at the bright line.
    Without it, the approver defaults to ``"owner"`` (pre-delegation behaviour).

    ``on_record`` (optional callable) receives the record dict for delivery/audit (e.g. Slack,
    write_local_digest) — kept injectable so this module stays import-light and testable.
    """
    required, reason = human_required(action)
    approver, approver_tier = "owner", "owner"
    if mandate is not None:
        verdict = _route(action, mandate)
        approver, approver_tier = verdict["approver"], verdict["tier"]
    record = {
        "agent": agent,
        "action": action,
        "reason": reason,
        "required": required,
        "approver": approver,
        "approver_tier": approver_tier,
    }
    if callable(on_record):
        try:
            on_record(record)
        except Exception:
            # delivery/audit is best-effort; never let it block or crash the gate
            pass

    if not required:
        return {**record, "status": "auto", "blocked": False}

    if report_only:
        # Probation: surface the would-be approval, do not actually pause (agents don't act yet).
        return {**record, "status": "would_require_human", "blocked": False, "mode": "report_only"}

    # Live: pause the runtime until a human resumes with their decision. Fail-closed.
    decision = _interrupt(record)
    approved = bool(isinstance(decision, dict) and decision.get("approved"))
    return {
        **record,
        "status": "approved" if approved else "rejected",
        "blocked": not approved,
        "decision": decision,
    }


def _route(action: dict[str, Any], mandate: dict[str, Any]) -> dict[str, Any]:
    """Resolve the approver via the sibling delegation router, loaded by path so this stays
    import-light (no agent_toolkit package __init__, which pulls heavy ML deps)."""
    import importlib.util
    import pathlib

    auth_path = pathlib.Path(__file__).with_name("authority.py")
    spec = importlib.util.spec_from_file_location("authority", auth_path)
    authority = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(authority)
    return authority.route(action, mandate)


def _interrupt(payload: dict[str, Any]) -> Any:
    """Pause the LangGraph run for human review (lazy import so the module loads without langgraph)."""
    try:
        from langgraph.types import interrupt  # type: ignore
    except Exception as exc:  # pragma: no cover - only hit outside a langgraph runtime
        raise RuntimeError(
            "human_gate(report_only=False) requires a LangGraph runtime with a checkpointer "
            "(interrupt() unavailable). Run report-only, or invoke inside a deployed graph."
        ) from exc
    return interrupt(payload)
