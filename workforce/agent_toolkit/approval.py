"""Human-in-the-loop approval gate — the single primitive every irreversible action uses.

Nothing the agents do that is outward-facing or irreversible (PR merge, issue/comment
creation, email/social send, deploy, delete) may proceed without passing through here.
Implemented with LangGraph's `interrupt()`: the graph pauses, a human reviews, and the
run is resumed with `Command(resume=<decision>)`.
"""
from typing import Any

from langgraph.types import interrupt


def request_approval(action: str, payload: dict, *, risk: str = "high") -> dict:
    """Pause the graph until a human approves/rejects/edits `action`.

    Returns the resume value. Treat anything that is not an explicit approve as a reject.
    """
    return interrupt(
        {
            "type": "approval_request",
            "action": action,
            "risk": risk,
            "payload": payload,
            "instructions": (
                "Respond with one of: 'approve' | 'reject' | {\"decision\": \"edit\", ...}. "
                "No send/publish/merge/delete proceeds without an explicit 'approve'."
            ),
        }
    )


def is_approved(decision: Any) -> bool:
    """Conservative check: only an explicit approve counts; default deny."""
    if decision == "approve":
        return True
    if isinstance(decision, dict) and decision.get("decision") == "approve":
        return True
    return False
