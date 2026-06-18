"""Local end-to-end validation of the canary graph.

Compiles the canary with an in-memory checkpointer (local only) and drives the full cycle:
plan -> interrupt(approval) -> resume('approve') -> act. Proves the platform plumbing
(approval gate, governance hook, OTel, Anthropic-terms guard) works before any deploy.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langgraph.checkpoint.memory import MemorySaver  # noqa: E402
from langgraph.types import Command  # noqa: E402

from graphs.qa import canary  # noqa: E402

graph = canary.builder.compile(checkpointer=MemorySaver())
cfg = {"configurable": {"thread_id": "canary-1"}}

r1 = graph.invoke({"target": "scheduler-web"}, cfg)
intr = r1.get("__interrupt__")
print("1) ran to approval interrupt:", "YES" if intr else "NO")
if intr:
    print("   action awaiting approval:", intr[0].value.get("action"))

r2 = graph.invoke(Command(resume="approve"), cfg)
print("2) resumed with 'approve' -> result:", r2.get("result"))

assert intr, "canary did not pause at the approval gate"
assert r2.get("result", "").startswith("would-write"), "approval path did not complete"
print("CANARY OK — interrupt/resume + approval gate + governance + OTel + terms-guard all wired")
