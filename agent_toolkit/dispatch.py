"""Remote-runner dispatch.

Heavy test execution (build/test/emulator/Patrol/Playwright) must run on ARC self-hosted
runners / GAL Swarm / GitHub Actions — NEVER inside the LangGraph agent container
(orchestrate-local, execute-on-cluster). The agent only orchestrates: it dispatches the
job and reads results.
"""
import os

import httpx


def dispatch_github_workflow(
    repo: str, workflow: str, ref: str = "main", inputs: dict | None = None
) -> bool:
    """Trigger a GitHub Actions workflow_dispatch. Returns True on success (HTTP 204)."""
    token = os.environ.get("GITHUB_DISPATCH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("No GITHUB_DISPATCH_TOKEN / GITHUB_TOKEN in env")
    resp = httpx.post(
        f"https://api.github.com/repos/{repo}/actions/workflows/{workflow}/dispatches",
        headers={
            "authorization": f"Bearer {token}",
            "accept": "application/vnd.github+json",
            "x-github-api-version": "2022-11-28",
        },
        json={"ref": ref, "inputs": inputs or {}},
        timeout=30.0,
    )
    return resp.status_code == 204
