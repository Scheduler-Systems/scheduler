"""Regression: the budget kill-switch must enforce on the REAL LangSmith burn, not the local
ledger (which is per-container/ephemeral and undercounts — the gap the CFO caught: metered 16k vs
real 15.8M). is_over_budget → effective_spent = max(local ledger, real LangSmith), fail-safe.
"""
from __future__ import annotations

import unittest
from unittest import mock

from agent_toolkit import payroll  # deps-lane test (like test_cfo / test_kill_switch)

AGENT = "zz_metering_test_agent"  # unique → not in the on-disk ledger (local spent == 0)
ROSTER = {"agents": {AGENT: {"salary_tokens_per_week": 1000}}}


class RealSpendEnforcement(unittest.TestCase):
    def setUp(self):
        payroll._REAL_SPEND_CACHE.clear()

    def test_over_budget_on_real_burn_even_when_local_ledger_is_low(self):
        # local ledger ~0, but LangSmith says the agent really burned 5000 > salary 1000 → STOP.
        with mock.patch.object(payroll, "reconcile_with_langsmith", return_value={"total_tokens": 5000}):
            self.assertTrue(payroll.is_over_budget(AGENT, roster=ROSTER))
            self.assertGreaterEqual(payroll.effective_spent(AGENT), 5000)

    def test_not_over_when_real_burn_under_salary(self):
        with mock.patch.object(payroll, "reconcile_with_langsmith", return_value={"total_tokens": 500}):
            self.assertFalse(payroll.is_over_budget(AGENT, roster=ROSTER))

    def test_fail_safe_falls_back_to_local_when_langsmith_unavailable(self):
        # No real data (missing creds / network) → enforce on the local ledger (prior behavior).
        with mock.patch.object(payroll, "reconcile_with_langsmith", return_value=None):
            self.assertEqual(payroll.effective_spent(AGENT), payroll.spent(AGENT))
            self.assertFalse(payroll.is_over_budget(AGENT, roster=ROSTER))

    def test_effective_spent_is_max_of_local_and_real(self):
        with mock.patch.object(payroll, "reconcile_with_langsmith", return_value={"total_tokens": 42}):
            self.assertEqual(payroll.effective_spent(AGENT), max(payroll.spent(AGENT), 42))

    def test_real_spend_is_cached(self):
        # Within the TTL the reconcile is called once, then served from cache.
        calls = {"n": 0}

        def fake(agent, **kw):
            calls["n"] += 1
            return {"total_tokens": 100}

        with mock.patch.object(payroll, "reconcile_with_langsmith", side_effect=fake):
            payroll.effective_spent(AGENT)
            payroll.effective_spent(AGENT)
            self.assertEqual(calls["n"], 1)


if __name__ == "__main__":
    unittest.main()
