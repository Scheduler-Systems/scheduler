"""fleet_control — the human override surface (kill switch) for the agent company.

Shay (founder + investor) has full override at all times. This is the one place to stop agents.

    python scripts/fleet_control.py status            # show kill-switch + bench state
    python scripts/fleet_control.py kill-all [reason]  # FLEET STOP: every agent refuses to clock in
    python scripts/fleet_control.py revive-all         # release the fleet kill switch
    python scripts/fleet_control.py bench <agent> [reason]   # stop ONE agent
    python scripts/fleet_control.py unbench <agent>          # revive ONE agent

State lives in .payroll/ (FLEET_DISABLED, benched.json) so it survives across processes and is
honored by every scheduled/unattended run. (Env equivalents: AGENTS_DISABLED, AGENTS_BENCHED.)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_toolkit import budget  # noqa: E402


def _status() -> None:
    benched = sorted(budget.benched_agents())
    print("fleet kill switch :", "ENGAGED (agents STOPPED)" if budget.fleet_disabled() else "off (agents may run)")
    print("  FLEET_DISABLED file:", budget.FLEET_DISABLED_FILE, "exists" if budget.FLEET_DISABLED_FILE.exists() else "absent")
    print("  AGENTS_DISABLED env:", "set" if os.environ.get("AGENTS_DISABLED") else "unset")
    print("benched agents    :", ", ".join(benched) if benched else "(none)")


def main(argv: list) -> int:
    cmd = argv[1] if len(argv) > 1 else "status"
    if cmd == "status":
        _status()
    elif cmd == "kill-all":
        budget.disable_fleet(" ".join(argv[2:]) or "manual")
        print("FLEET STOPPED. All agents will refuse to clock in. Revive with: fleet_control.py revive-all")
        _status()
    elif cmd == "revive-all":
        budget.enable_fleet()
        print("Fleet kill switch released.")
        _status()
    elif cmd == "bench" and len(argv) > 2:
        budget.bench(argv[2], " ".join(argv[3:]))
        print(f"Benched {argv[2]}.")
        _status()
    elif cmd == "unbench" and len(argv) > 2:
        budget.unbench(argv[2])
        print(f"Un-benched {argv[2]}.")
        _status()
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
