"""GAL governance hook — capture every agent run's terminal decision to the governance plane.

Layered as cross-cutting middleware (call from each graph's terminal node) so all agents
are auditable through GAL without bespoke wiring.

Fail-safe: no-op until GAL_GOVERNANCE_ENDPOINT is set (the agent-governance epic,
go-services#37, is not yet built). NEVER block or break an agent because capture failed.
"""
import os

import httpx


def capture(agent: str, decision: dict) -> None:
    endpoint = os.environ.get("GAL_GOVERNANCE_ENDPOINT")
    if not endpoint:
        return
    try:
        httpx.post(
            f"{endpoint.rstrip('/')}/v1/agent-runs",
            json={"agent": agent, "decision": decision},
            headers={"authorization": f"Bearer {os.environ.get('GAL_GOVERNANCE_TOKEN', '')}"},
            timeout=5.0,
        )
    except Exception:
        pass  # fail-safe
