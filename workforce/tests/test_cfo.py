"""Tests for the CFO officer — propose-only spend monitoring + budget allocation.

The CFO never moves money or edits the roster; it proposes an allocation that fits the team
budget cap, benches un-scheduled agents, and escalates only budget INCREASES (capital) to Shay.
Run: .venv/bin/python -m unittest tests.test_cfo -v
"""
import os
import unittest
from unittest import mock

from graphs.exec import cfo as m


def _card(salary=0, spent=0, schedule="daily", over=False, real=None):
    return {
        "role": "r", "grade": "gemini-2.5-flash", "schedule": schedule, "status": "probation",
        "scorecard": {}, "salary_tokens": salary, "spent_tokens": spent,
        "remaining_tokens": salary - spent, "over_budget": over,
        "langsmith": ({"total_tokens": real} if real is not None else None),
    }


class AnalyzeTests(unittest.TestCase):
    def test_flags_over_budget_and_overloaded(self):
        spend = {"agents": {
            "a": _card(salary=100, spent=150, over=True),       # over budget
            "b": _card(salary=100, spent=10, real=500),          # overloaded (real >> salary)
            "c": _card(salary=100, spent=10),                    # fine
        }, "by_class": {}}
        with mock.patch.object(m, "load_budget_policy", return_value={"team_token_budget": 1000}):
            out = m.analyze({"spend": spend, "revenue": {"ok": False}})
        kinds = {(x["agent"], x["kind"]) for x in out["analysis"]["anomalies"]}
        self.assertIn(("a", "over_budget"), kinds)
        self.assertIn(("b", "overloaded"), kinds)
        self.assertNotIn("c", {a["agent"] for a in out["analysis"]["anomalies"]})
        self.assertEqual(out["analysis"]["total_salary"], 300)


class ProposeTests(unittest.TestCase):
    def _propose(self, spend, analysis):
        # budget_guard raises => deterministic proposal must still stand (no model dependency).
        with mock.patch.object(m, "budget_guard", side_effect=RuntimeError("no key")):
            return m.propose({"spend": spend, "analysis": analysis})

    def test_total_scaled_under_team_budget(self):
        spend = {"agents": {"a": _card(salary=300, schedule="daily"),
                            "b": _card(salary=300, schedule="daily")}}
        out = self._propose(spend, {"team_budget": 400, "anomalies": []})
        total = sum(p["proposed_tokens"] for p in out["proposals"])
        self.assertLessEqual(total, 400)
        self.assertTrue(out["rationale"].startswith("(model rationale unavailable"))

    def test_unscheduled_is_benched_at_zero(self):
        spend = {"agents": {"idle": _card(salary=500, schedule="")}}
        out = self._propose(spend, {"team_budget": 10_000, "anomalies": []})
        p = out["proposals"][0]
        self.assertEqual(p["action"], "bench")
        self.assertEqual(p["proposed_tokens"], 0)
        self.assertEqual(p["escalate_to"], "org")

    def test_increase_escalates_to_shay_only(self):
        spend = {"agents": {"hot": _card(salary=100, spent=200, over=True, schedule="daily"),
                            "ok": _card(salary=100, schedule="daily")}}
        out = self._propose(spend, {"team_budget": 10_000, "anomalies": [{"agent": "hot"}]})
        by = {p["agent"]: p for p in out["proposals"]}
        self.assertEqual(by["hot"]["action"], "increase")
        self.assertEqual(by["hot"]["escalate_to"], "shay")   # capital decision
        self.assertEqual(by["ok"]["escalate_to"], "org")     # everything else stays in the org


class DeliverTests(unittest.TestCase):
    def test_deliver_is_report_only_by_default(self):
        seen = {}
        def fake_file(repo, title, body, labels=None, report_only=None, **kwargs):
            seen["report_only"] = report_only
            return {"status": "report_only"}
        env = dict(os.environ); env.pop("OPS_REPORT_ONLY", None)
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch.object(m, "write_local_digest", return_value="/tmp/cfo.md"), \
             mock.patch.object(m, "file_digest_issue", side_effect=fake_file):
            out = m.deliver({"spend": {}, "revenue": {"ok": False}, "analysis": {}, "proposals": []})
        self.assertTrue(seen["report_only"])          # report-only by default
        self.assertTrue(out["report_only"])
        self.assertEqual(out["report"]["delivery"], "report_only")


class BudgetGateTests(unittest.TestCase):
    def test_clocked_out_ends_without_work(self):
        with mock.patch.object(m, "check_clocked_in", return_value=False), \
             mock.patch.object(m, "governance_capture"):
            out = m.budget_gate({})
            self.assertTrue(out["report_only"])
            self.assertEqual(m._budget_route({}), "clocked_out")


class GatherFailsafeTests(unittest.TestCase):
    def test_roster_load_failure_degrades(self):
        with mock.patch.object(m.payroll, "load_roster", side_effect=RuntimeError("boom")), \
             mock.patch.object(m.revenuecat, "metrics_overview", return_value={"ok": False, "error": "x"}), \
             mock.patch.object(m, "read_local_digest", return_value="(no digest yet)"):
            out = m.gather({})
        self.assertEqual(out["spend"]["agents"], {})       # degraded, did not raise


if __name__ == "__main__":
    unittest.main()
