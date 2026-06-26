#!/usr/bin/env python3
"""HR coverage gate — no agent deploys without going through HR.

Every deployed agent (a graph in ``langgraph.json``) MUST have an employee row in
``roster.yaml``. An agent is an employee: it gets hired (an approval-gated roster entry +
a token-budget salary + a scorecard), not just merged. This gate FAILS CI when a graph has
no roster row, so a new agent can never bypass the HR/hire process again.

(See the workspace AGENTS.md "WHY YOU ARE HERE" principle: build + HIRE agents, don't just
deploy code.)
"""
from __future__ import annotations

import json
import pathlib
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent


def main() -> int:
    graphs = set(json.loads((ROOT / "langgraph.json").read_text())["graphs"])
    roster = yaml.safe_load((ROOT / "roster.yaml").read_text())
    rostered = set((roster.get("agents") or {}).keys())

    missing = sorted(graphs - rostered)
    if missing:
        print("❌ ROSTER COVERAGE FAILED — deployed graphs with NO roster.yaml entry (bypassed HR):")
        for m in missing:
            print(f"   - {m}")
        print("\nEvery agent is an employee: hire it via HR (an approval-gated roster row +")
        print("salary + scorecard) BEFORE adding the graph. See AGENTS.md. Do not bypass.")
        return 1

    pending = sorted(k for k, a in (roster.get("agents") or {}).items()
                     if isinstance(a, dict) and a.get("hire") == "pending_hr_approval"
                     and k in graphs)
    print(f"✅ roster coverage OK: all {len(graphs)} deployed graphs are rostered.")
    if pending:
        print(f"   ⏳ {len(pending)} awaiting HR ratification (hire: pending_hr_approval): {', '.join(pending)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
