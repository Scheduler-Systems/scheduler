"""Shift dispatcher — fired on a cadence by launchd.

Each invocation runs the NEXT worker's 5-minute observe shift (round-robin over the
roster). Self-limiting: every shift is bounded by time (5 min) AND the worker's token
salary (clock-out), and the whole fleet stops if AGENTS_DISABLED is set.
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
os.makedirs(os.path.join(REPO, ".payroll"), exist_ok=True)
STATE = os.path.join(REPO, ".payroll", "shift_state.json")
SHIFT_MINUTES = "5"

# (agent module, target repo) — round-robin order
WORKERS = [
    ("web_automation_engineer", "Scheduler-Systems/scheduler-web"),
    ("web_manual_tester", "Scheduler-Systems/scheduler-web"),
    ("android_automation_engineer", "Scheduler-Systems/scheduler-android"),
    ("android_manual_tester", "Scheduler-Systems/scheduler-android"),
    ("ios_automation_engineer", "Scheduler-Systems/scheduler-ios"),
    ("ios_manual_tester", "Scheduler-Systems/scheduler-ios"),
]

if os.environ.get("AGENTS_DISABLED"):
    print("[shift] AGENTS_DISABLED is set — skipping this shift.")
    sys.exit(0)

idx = 0
try:
    idx = int(json.load(open(STATE)).get("next", 0))
except Exception:
    idx = 0
idx %= len(WORKERS)
agent, target = WORKERS[idx]
try:
    json.dump({"next": (idx + 1) % len(WORKERS)}, open(STATE, "w"))
except Exception:
    pass

print(f"[shift] dispatching {agent} for a {SHIFT_MINUTES}-min observe shift (target {target})")
subprocess.run([sys.executable, os.path.join(HERE, "run_shift.py"), agent, SHIFT_MINUTES, target], cwd=REPO)
