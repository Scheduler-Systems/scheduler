"""Canary 'hello-gate' graph — validates a fresh deployment end-to-end.

Run this FIRST on any new deployment to prove the platform works:
- compiles WITHOUT a checkpointer/store (managed platform injects Postgres)
- exercises the human-in-the-loop approval gate (interrupt -> Command(resume))
- emits an OTel span and a GAL governance capture
- exercises the Anthropic-terms guard
"""
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END

from agent_toolkit import request_approval, span, governance_capture, assert_not_model_work
from agent_toolkit.approval import is_approved


class State(TypedDict, total=False):
    target: str
    approved: bool
    result: str


def plan(state: State) -> dict:
    target = state.get("target", "scheduler-web")
    assert_not_model_work(target)  # Anthropic-terms guard
    with span("canary.plan", target=target):
        return {"target": target}


def gate(state: State) -> dict:
    decision = request_approval(
        action="canary_write",
        payload={"target": state.get("target"), "note": "hello-gate validation"},
        risk="low",
    )
    return {"approved": is_approved(decision)}


def act(state: State) -> dict:
    with span("canary.act", approved=state.get("approved", False)):
        result = "would-write (approved)" if state.get("approved") else "skipped (not approved)"
        governance_capture("canary_hello_gate", {"target": state.get("target"), "result": result})
        return {"result": result}


builder = StateGraph(State)
builder.add_node("plan", plan)
builder.add_node("gate", gate)
builder.add_node("act", act)
builder.add_edge(START, "plan")
builder.add_edge("plan", "gate")
builder.add_edge("gate", "act")
builder.add_edge("act", END)

graph = builder.compile()  # NO checkpointer/store — injected by the platform
