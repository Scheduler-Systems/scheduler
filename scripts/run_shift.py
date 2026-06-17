"""Run an agent for a time-boxed, budget-bounded SHIFT (observe / report-only).

A "shift" = the agent works in cycles until EITHER the shift window elapses OR it is
over its token salary (clock-out) — whichever comes first. This is the employee model:
"you can work for N minutes" + "you have a token salary" => self-limiting on time AND cost.

Usage: python scripts/run_shift.py <agent_module> <shift_minutes> [target]
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from importlib import import_module
from langgraph.checkpoint.memory import MemorySaver

from agent_toolkit import check_clocked_in

agent_name = sys.argv[1] if len(sys.argv) > 1 else "android_manual_tester"
shift_minutes = float(sys.argv[2]) if len(sys.argv) > 2 else 5.0
target = sys.argv[3] if len(sys.argv) > 3 else "Scheduler-Systems/scheduler-android"
gap_seconds = 15

mod = import_module(f"graphs.qa.{agent_name}")
graph = mod.builder.compile(checkpointer=MemorySaver())

deadline = time.monotonic() + shift_minutes * 60.0
cycle = 0
print(f"SHIFT START: {agent_name} | {shift_minutes} min | observe-mode | target={target}")
reason = "time-elapsed"
while time.monotonic() < deadline:
    if not check_clocked_in(agent_name):
        reason = "clocked-out (over salary / AGENTS_DISABLED)"
        break
    cycle += 1
    cfg = {"configurable": {"thread_id": f"shift-{agent_name}-{cycle}"}}
    try:
        r = graph.invoke({"mode": "observe", "target": target}, cfg)
        out = (r.get("report") or r.get("summary") or "ok")
        print(f"  cycle {cycle}: {str(out)[:110]}")
    except Exception as e:  # never let one cycle kill the shift
        print(f"  cycle {cycle} error: {str(e)[:120]}")
    if time.monotonic() < deadline:
        time.sleep(gap_seconds)

print(f"SHIFT END: {agent_name} | {cycle} cycles | reason: {reason}")
