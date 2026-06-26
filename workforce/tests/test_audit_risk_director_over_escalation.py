"""FAILING TEST — escalation-discipline regression in audit_risk_director.

The board's escalation rule (docs/governance/delegation.yaml + agent_toolkit/lanes.py) is:
only a genuine BRIGHT-LINE item (capital / legal / irreversible — a real founder decision)
is addressed to the founder via ``escalate_to: "shay"``. Everything operational stays
``"org"`` — resolved inside the org by the responsible officer.

A single agent running OVER ITS WEEKLY TOKEN SALARY (``payroll.is_over_budget`` =
spend >= salary) is an OPERATIONAL budget breach, NOT a bright-line owner decision. It is the
CFO/board's job to resolve it inside the org — exactly the control the audit director itself
proposes ("freeze/raise review: cap or re-approve the agent's salary"). Capping or benching a
salary needs no owner sign-off. Per the delegation mandate, ``set_budget`` is decided by the
BOARD; only ``bet_the_company_spend`` (a single spend above ``max_board_spend_usd``) is
``owner_reserved``. The CFO graph already gets this right: an over-budget agent => ``"org"``;
only a budget INCREASE (capital) => ``"shay"`` (see graphs/exec/cfo.py:351).

But audit_risk_director hardcodes EVERY over-budget agent and any fleet-cap breach as
``material: True`` (graphs/board/audit_risk_director.py:447,459), which ``propose`` maps to
``escalate_to: "shay"`` (line 187). That is the "Shay, urgent, act now" over-escalation the
fleet was hardened against — pushing a routine burn condition at an unreachable founder.

This module asserts the CORRECT discipline. It FAILS against the current code (which escalates
operational over-budget to Shay) and PASSES once the over-escalation is fixed, while the
genuinely bright-line axes (an open security IDOR, a broken report-only safety gate, and a true
budget-INCREASE-above-board-cap ask) still reach Shay.

Run: .venv/bin/python -m unittest tests.test_audit_risk_director_over_escalation -v
"""
import unittest

from graphs.board import audit_risk_director as m
from agent_toolkit import lanes


class OverBudgetIsOperationalNotFounderTests(unittest.TestCase):
    """A routine over-budget AGENT is org-internal — NOT a founder ask."""

    def test_single_over_budget_agent_routes_org_not_shay(self):
        budget = {
            "team_cap": 4_800_000,
            "fleet_spent": 1_000,
            "fleet_over_cap": False,
            "over_budget_agents": [
                {"agent": "spender", "spent_tokens": 5_000, "salary_tokens": 1_000}
            ],
            "note": None,
        }
        findings = m.analyze({"cfo": "(no digest yet)", "cto": "(no digest yet)",
                              "budget": budget})["findings"]
        proposals = m.propose({"findings": findings})["proposals"]

        budget_props = [p for p in proposals if p["axis"] == "budget"]
        self.assertTrue(budget_props, "an over-budget agent should still produce a finding")
        for p in budget_props:
            self.assertEqual(
                p["escalate_to"], "org",
                "a routine over-budget agent is an OPERATIONAL budget breach the CFO/board "
                "resolve inside the org (cap/bench/re-grade) — it must NOT be addressed to Shay",
            )

    def test_fleet_over_team_cap_routes_org_not_shay(self):
        budget = {
            "team_cap": 1_000,
            "fleet_spent": 5_000,
            "fleet_over_cap": True,
            "over_budget_agents": [],
            "note": None,
        }
        findings = m.analyze({"cfo": "(no digest yet)", "cto": "(no digest yet)",
                              "budget": budget})["findings"]
        proposals = m.propose({"findings": findings})["proposals"]

        budget_props = [p for p in proposals if p["axis"] == "budget"]
        self.assertTrue(budget_props)
        for p in budget_props:
            self.assertEqual(
                p["escalate_to"], "org",
                "the fleet exceeding its own token cap is the board's re-balance to make "
                "inside the org — only a spend ABOVE max_board_spend_usd is owner-reserved",
            )

    def test_cfo_over_budget_signal_routes_org_not_shay(self):
        findings = m.analyze({
            "cfo": "Two agents are OVER BUDGET this week.",
            "cto": "(no digest yet)",
            "budget": {"team_cap": 4_800_000, "fleet_spent": 1, "fleet_over_cap": False,
                       "over_budget_agents": [], "note": None},
        })["findings"]
        proposals = m.propose({"findings": findings})["proposals"]
        budget_props = [p for p in proposals if p["axis"] == "budget"]
        self.assertTrue(budget_props)
        for p in budget_props:
            self.assertEqual(p["escalate_to"], "org")

    def test_over_budget_axis_raises_no_founder_ask(self):
        """The BUDGET axis must raise ZERO founder asks — over-budget is org-internal.

        NOTE (step-3 relocation): the standing held IDOR is now ALWAYS surfaced from the lane
        registry (``lanes`` owns the IDOR dossier, not the CTO digest), so it is a security ask on
        EVERY cycle until it ships — even when the CTO has not filed a digest. This test therefore
        isolates the BUDGET axis: an over-budget cycle contributes NO founder ask of its own
        (operational burn = org-internal). The relocated standing IDOR ask is asserted separately
        in ``StandingIdorSurvivesCtoOffboardTests`` below.
        """
        budget = {
            "team_cap": 1_000, "fleet_spent": 9_000, "fleet_over_cap": True,
            "over_budget_agents": [
                {"agent": "a", "spent_tokens": 5_000, "salary_tokens": 1_000},
                {"agent": "b", "spent_tokens": 3_000, "salary_tokens": 1_000},
            ],
            "note": None,
        }
        findings = m.analyze({"cfo": "(no digest yet)", "cto": "(no digest yet)",
                              "budget": budget})["findings"]
        proposals = m.propose({"findings": findings})["proposals"]
        budget_props = [p for p in proposals if p["axis"] == "budget"]
        self.assertEqual(
            lanes.founder_ask_count(budget_props), 0,
            "the over-budget axis must raise NO founder asks — it is org-internal",
        )


class GenuineBrightLineStillReachesShayTests(unittest.TestCase):
    """The real bright-line axes must STILL reach Shay (no under-escalation regression)."""

    def test_open_security_idor_still_escalates_to_shay(self):
        findings = m.analyze({
            "cfo": "(no digest yet)",
            "cto": "Open IDOR #1487 still un-remediated in production.",
            "budget": {"over_budget_agents": [], "fleet_over_cap": False,
                       "team_cap": 4_800_000, "fleet_spent": 1, "note": None},
        })["findings"]
        proposals = m.propose({"findings": findings})["proposals"]
        sec = [p for p in proposals if p["axis"] == "security"]
        self.assertTrue(sec, "an open security IDOR must be surfaced")
        self.assertEqual(
            sec[0]["escalate_to"], "shay",
            "an open, un-remediated security risk IS a bright-line founder item",
        )


if __name__ == "__main__":
    unittest.main()
