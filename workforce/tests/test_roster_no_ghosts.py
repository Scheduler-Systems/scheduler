"""FINDING 1 — the roster lists NO undeployed "ghost" employees.

The HR coverage gate (scripts/check_roster_coverage.py) enforces one direction: every DEPLOYED
graph has a roster row. It does NOT catch the OTHER direction — a rostered "employee" (a salary +
scorecard + status row in ``agents:``) that has NO deployed graph. ``git_sync_auditor`` and
``memory_sync`` were exactly that: LOCAL-only launchd workers (not in langgraph.json) carried as
roster employees, which looked like idle deployed agents and risked a future re-deploy landing
against the wrong record.

These tests assert the reconciliation holds:
  * every ``agents:`` row is a DEPLOYED graph (no ghost employees) — the reverse-direction check;
  * the two known local-only agents are NOT in ``agents:`` nor in any ``org:`` routing list;
  * both coverage gates still pass (exit 0).
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
LOCAL_ONLY_AGENTS = ("git_sync_auditor", "memory_sync")


def _load():
    graphs = set(json.loads((ROOT / "langgraph.json").read_text())["graphs"])
    roster = yaml.safe_load((ROOT / "roster.yaml").read_text())
    return graphs, roster


class NoGhostEmployees(unittest.TestCase):
    def test_every_rostered_employee_is_a_deployed_graph(self):
        """The reverse of the HR gate: no ``agents:`` row without a deployed graph (no ghosts)."""
        graphs, roster = _load()
        rostered = set((roster.get("agents") or {}).keys())
        ghosts = sorted(rostered - graphs)
        self.assertEqual(
            ghosts, [],
            f"roster.yaml lists employees with NO deployed graph (ghosts): {ghosts}. "
            f"A rostered employee must be a deployed graph; local-only agents belong in "
            f"docs/ops-fleet/local-only-agents.md, not on the deployed-workforce roster.",
        )

    def test_local_only_agents_are_not_rostered_employees(self):
        _, roster = _load()
        agents = set((roster.get("agents") or {}).keys())
        for a in LOCAL_ONLY_AGENTS:
            self.assertNotIn(
                a, agents,
                f"'{a}' is a LOCAL-only launchd agent (not a deployed graph) — it must NOT be an "
                f"agents: employee row. See docs/ops-fleet/local-only-agents.md.",
            )

    def test_local_only_agents_are_not_in_any_org_routing_list(self):
        _, roster = _load()
        org = roster.get("org") or {}
        for group, members in org.items():
            if not isinstance(members, list):
                continue  # scalar org entries (hr_ops_manager/team_lead descriptions) are not lists
            for a in LOCAL_ONLY_AGENTS:
                self.assertNotIn(
                    a, members,
                    f"'{a}' is local-only and must not be in org.{group} — dept_of(it) must be None "
                    f"so it is never a delegation target.",
                )

    def test_local_only_agents_are_genuinely_not_deployed(self):
        """Sanity: the two agents really are absent from langgraph.json (the premise of the fix)."""
        graphs, _ = _load()
        for a in LOCAL_ONLY_AGENTS:
            self.assertNotIn(a, graphs, f"premise broken: '{a}' IS a deployed graph — re-roster it")

    def test_local_only_doc_exists(self):
        self.assertTrue(
            (ROOT / "docs" / "ops-fleet" / "local-only-agents.md").is_file(),
            "docs/ops-fleet/local-only-agents.md must document the local-only agents",
        )


class CoverageGatesStillGreen(unittest.TestCase):
    """Both gates must still exit 0 after the reconciliation (deployed graphs stay covered)."""

    def _run_gate(self, script: str) -> int:
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts" / script)],
            capture_output=True, text=True,
        ).returncode

    def test_roster_coverage_gate_passes(self):
        self.assertEqual(self._run_gate("check_roster_coverage.py"), 0)

    def test_capability_coverage_gate_passes(self):
        self.assertEqual(self._run_gate("check_capability_coverage.py"), 0)


class PayrollBudgetReconciled(unittest.TestCase):
    """FINDING 2 — the ghost removal silently broke the roster's own payroll<->cap invariant.

    The two coverage gates are DIRECTIONAL (graph<->roster-row); NEITHER reconciles the MONEY.
    roster.yaml line ~18 self-documents that ``policy.team_token_budget`` IS the sum of the
    departmental salaries ("= board 0.26M + exec 0.48M + growth 1.25M + qa 2.5M + ops 1.05M").
    The budget layer treats ``team_token_budget`` as the HARD CAP and the CFO flags
    ``salary_allocation_over_cap`` when sum(agents: salaries) > team_token_budget.

    Removing git_sync_auditor + memory_sync (150k each) dropped the real ``agents:`` salary
    total from 6,680,000 to 6,380,000, but ``team_token_budget`` was left at 5,540,000 and the
    line-18 decomposition comment was NOT updated (it still claims ops=1.05M when org.ops is now
    0.90M, and omits the executive CISO/CLO + platform additions entirely). Nothing in CI caught
    it: every existing budget test mocks ``team_token_budget`` with a synthetic value, so the REAL
    on-disk roster sum-vs-cap invariant is unguarded. This test pins it on the real roster (no
    mocks) so a future hire/fire that changes a salary must also re-balance the cap.
    """

    def test_team_token_budget_equals_sum_of_agent_salaries(self):
        roster = yaml.safe_load((ROOT / "roster.yaml").read_text())
        agents = roster.get("agents") or {}
        cap = int(roster.get("policy", {}).get("team_token_budget"))
        total_salary = sum(int((a or {}).get("salary_tokens_per_week") or 0)
                           for a in agents.values())
        self.assertEqual(
            total_salary, cap,
            f"roster payroll/cap drift: sum(agents: salaries)={total_salary:,} but "
            f"policy.team_token_budget={cap:,} (delta {total_salary - cap:+,}). roster.yaml's "
            f"own comment says the cap IS the sum of department salaries, and the budget layer "
            f"treats it as the hard cap — so a salary change (e.g. removing the ghost agents) "
            f"must re-balance the cap. Either fix team_token_budget or the salaries.",
        )


if __name__ == "__main__":
    unittest.main()
