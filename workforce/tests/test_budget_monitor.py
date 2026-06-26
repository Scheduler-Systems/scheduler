"""Unit tests for the per-agent + fleet spend/health monitor.

Pure tests with an INJECTED usage_reader — no network, no LangSmith. This is the structural
backstop for the metering-bug class the CFO caught by hand (enforcement on a local ledger ~1000x
too low vs the real burn). The headline assertion: real = 20x salary MUST fire an alert.

Proves:
  - over-salary fires (warn + critical bands)
  - under-salary is silent
  - fleet-over fires (sum real vs policy.team_token_budget)
  - None / missing usage is SKIPPED (no crash, no alert, no fleet contamination)
  - the 1000x class: real = 20x salary -> alert
  - check_fleet never raises (fail-safe), even when the reader explodes
  - dedup: same state twice = one alert; clearing then recurring re-fires
"""
from __future__ import annotations

import unittest

from agent_toolkit import budget_monitor  # deps-lane test (like test_payroll_real_spend)


# A roster in payroll.load_roster() shape: {"policy": {...}, "agents": {slug: {salary...}}}.
def _roster(team_budget: int, agents: dict[str, int]) -> dict:
    return {
        "policy": {"team_token_budget": team_budget},
        "agents": {
            name: {"salary_tokens_per_week": salary} for name, salary in agents.items()
        },
    }


def _reader(usage: dict[str, object]):
    """Build an injectable usage_reader from a {agent: tokens|None} map. Unknown agent -> None."""
    return lambda agent: usage.get(agent)


def _by_subject(alerts) -> dict[str, dict]:
    return {a["agent"]: a for a in alerts}


class OverSalaryFires(unittest.TestCase):
    def test_over_salary_fires_critical(self):
        roster = _roster(team_budget=10_000_000, agents={"cfo": 1000})
        alerts = budget_monitor.check_fleet(roster, usage_reader=_reader({"cfo": 5000}))
        by = _by_subject(alerts)
        self.assertIn("cfo", by)
        self.assertEqual(by["cfo"]["level"], "critical")
        self.assertEqual(by["cfo"]["real_tokens"], 5000)
        self.assertEqual(by["cfo"]["limit"], 1000)
        self.assertGreaterEqual(by["cfo"]["pct"], 1.0)

    def test_thousand_x_class_real_20x_salary_alerts(self):
        # THE bug class: salary 80k, real burn 1.6M (20x) — enforcement was reading a local ledger
        # ~1000x too low and stayed silent. The monitor MUST fire.
        roster = _roster(team_budget=10_000_000, agents={"web_automation_engineer": 80_000})
        alerts = budget_monitor.check_fleet(
            roster, usage_reader=_reader({"web_automation_engineer": 1_600_000})
        )
        by = _by_subject(alerts)
        self.assertIn("web_automation_engineer", by)
        self.assertEqual(by["web_automation_engineer"]["level"], "critical")
        self.assertEqual(by["web_automation_engineer"]["pct"], 20.0)

    def test_warn_band_just_below_salary(self):
        # 90% of salary = warn (not yet critical).
        roster = _roster(team_budget=10_000_000, agents={"coo": 1000})
        alerts = budget_monitor.check_fleet(roster, usage_reader=_reader({"coo": 950}))
        by = _by_subject(alerts)
        self.assertIn("coo", by)
        self.assertEqual(by["coo"]["level"], "warn")


class UnderSalaryIsSilent(unittest.TestCase):
    def test_under_salary_no_alert(self):
        roster = _roster(team_budget=10_000_000, agents={"cfo": 1000})
        alerts = budget_monitor.check_fleet(roster, usage_reader=_reader({"cfo": 100}))
        self.assertEqual(alerts, [])

    def test_healthy_agent_not_in_alerts(self):
        roster = _roster(
            team_budget=10_000_000, agents={"healthy": 1000, "spendy": 1000}
        )
        alerts = budget_monitor.check_fleet(
            roster, usage_reader=_reader({"healthy": 10, "spendy": 5000})
        )
        by = _by_subject(alerts)
        self.assertNotIn("healthy", by)
        self.assertIn("spendy", by)


class FleetOverFires(unittest.TestCase):
    def test_fleet_sum_over_team_budget_fires(self):
        # Each agent under its own salary, but together they blow the team budget.
        roster = _roster(
            team_budget=1000, agents={"a": 10_000, "b": 10_000}
        )
        alerts = budget_monitor.check_fleet(
            roster, usage_reader=_reader({"a": 600, "b": 600})
        )
        by = _by_subject(alerts)
        self.assertIn("FLEET", by)
        self.assertEqual(by["FLEET"]["real_tokens"], 1200)
        self.assertEqual(by["FLEET"]["limit"], 1000)
        self.assertEqual(by["FLEET"]["level"], "critical")
        # Neither agent over its own salary -> only the FLEET alert.
        self.assertNotIn("a", by)
        self.assertNotIn("b", by)

    def test_fleet_under_budget_silent(self):
        roster = _roster(team_budget=1_000_000, agents={"a": 10_000, "b": 10_000})
        alerts = budget_monitor.check_fleet(
            roster, usage_reader=_reader({"a": 100, "b": 100})
        )
        self.assertEqual(alerts, [])


class NoneUsageIsSkipped(unittest.TestCase):
    def test_none_usage_skipped_no_crash_no_alert(self):
        roster = _roster(team_budget=10_000_000, agents={"ghost": 1000})
        alerts = budget_monitor.check_fleet(roster, usage_reader=_reader({"ghost": None}))
        self.assertEqual(alerts, [])

    def test_none_agent_does_not_contaminate_fleet(self):
        # 'ghost' reports None (skipped, no fleet contribution); 'real' reports 600.
        # Fleet sum must be 600 (not None+600 crash), under the 1000 budget -> silent.
        roster = _roster(team_budget=1000, agents={"ghost": 5000, "real": 5000})
        alerts = budget_monitor.check_fleet(
            roster, usage_reader=_reader({"ghost": None, "real": 600})
        )
        self.assertEqual(alerts, [])

    def test_reader_that_raises_is_skipped_not_fatal(self):
        def boom(agent):
            if agent == "bad":
                raise RuntimeError("langsmith exploded")
            return 5000

        roster = _roster(team_budget=10_000_000, agents={"bad": 1000, "good": 1000})
        alerts = budget_monitor.check_fleet(roster, usage_reader=boom)
        by = _by_subject(alerts)
        # 'bad' skipped (reader raised), 'good' still evaluated and fires.
        self.assertNotIn("bad", by)
        self.assertIn("good", by)

    def test_no_data_at_all_means_no_fleet_alert(self):
        # Every agent reports None -> no fleet data -> no FLEET alert even with a tiny budget.
        roster = _roster(team_budget=1, agents={"a": 1000, "b": 1000})
        alerts = budget_monitor.check_fleet(
            roster, usage_reader=_reader({"a": None, "b": None})
        )
        self.assertEqual(alerts, [])


class FailSafe(unittest.TestCase):
    def test_check_never_raises_on_bad_roster(self):
        # A garbage roster must not crash the sweep.
        self.assertEqual(budget_monitor.check_fleet({"agents": None}), [])
        self.assertEqual(budget_monitor.check_fleet("not a roster"), [])  # type: ignore[arg-type]

    def test_non_numeric_usage_skipped(self):
        roster = _roster(team_budget=10_000_000, agents={"x": 1000})
        alerts = budget_monitor.check_fleet(
            roster, usage_reader=_reader({"x": "lots"})
        )
        self.assertEqual(alerts, [])


class Dedup(unittest.TestCase):
    def test_same_state_twice_fires_once(self):
        roster = _roster(team_budget=10_000_000, agents={"cfo": 1000})
        reader = _reader({"cfo": 5000})

        alerts1 = budget_monitor.check_fleet(roster, usage_reader=reader)
        fired1, state1 = budget_monitor.dedup(alerts1, last_state={})
        self.assertEqual(len(fired1), 1)  # first time -> fires

        alerts2 = budget_monitor.check_fleet(roster, usage_reader=reader)
        fired2, state2 = budget_monitor.dedup(alerts2, last_state=state1)
        self.assertEqual(fired2, [])  # same band -> silent
        self.assertEqual(state1, state2)

    def test_band_change_refires(self):
        roster = _roster(team_budget=10_000_000, agents={"cfo": 1000})

        # warn band first.
        a_warn = budget_monitor.check_fleet(roster, usage_reader=_reader({"cfo": 950}))
        fired_w, state_w = budget_monitor.dedup(a_warn, last_state={})
        self.assertEqual(fired_w[0]["level"], "warn")

        # escalates to critical -> band changed -> re-fires.
        a_crit = budget_monitor.check_fleet(roster, usage_reader=_reader({"cfo": 5000}))
        fired_c, _ = budget_monitor.dedup(a_crit, last_state=state_w)
        self.assertEqual(len(fired_c), 1)
        self.assertEqual(fired_c[0]["level"], "critical")

    def test_clear_then_recur_refires(self):
        roster = _roster(team_budget=10_000_000, agents={"cfo": 1000})

        a1 = budget_monitor.check_fleet(roster, usage_reader=_reader({"cfo": 5000}))
        _, state1 = budget_monitor.dedup(a1, last_state={})

        # Clears (back under salary): no alert, subject dropped from state.
        a2 = budget_monitor.check_fleet(roster, usage_reader=_reader({"cfo": 100}))
        fired2, state2 = budget_monitor.dedup(a2, last_state=state1)
        self.assertEqual(fired2, [])
        self.assertNotIn("cfo", state2)

        # Recurs: must fire again (the prior alert had cleared).
        a3 = budget_monitor.check_fleet(roster, usage_reader=_reader({"cfo": 5000}))
        fired3, _ = budget_monitor.dedup(a3, last_state=state2)
        self.assertEqual(len(fired3), 1)


class Delivery(unittest.TestCase):
    def test_deliver_uses_injected_poster_and_never_raises(self):
        posted = []

        def poster(agent, title, body):
            posted.append((agent, title, body))
            return {"status": "report_only"}

        roster = _roster(team_budget=10_000_000, agents={"cfo": 1000})
        alerts = budget_monitor.check_fleet(roster, usage_reader=_reader({"cfo": 5000}))
        results = budget_monitor.deliver(alerts, poster=poster)
        self.assertEqual(len(posted), 1)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "report_only")

    def test_deliver_survives_a_failing_poster(self):
        def poster(agent, title, body):
            raise RuntimeError("slack down")

        roster = _roster(team_budget=10_000_000, agents={"cfo": 1000})
        alerts = budget_monitor.check_fleet(roster, usage_reader=_reader({"cfo": 5000}))
        results = budget_monitor.deliver(alerts, poster=poster)  # must NOT raise
        self.assertEqual(results[0]["status"], "error")


class RunOnce(unittest.TestCase):
    def test_run_once_fires_then_dedups_across_sweeps(self):
        import tempfile
        from pathlib import Path

        posted = []

        def poster(agent, title, body):
            posted.append((agent, title, body))
            return {"status": "report_only"}

        roster = _roster(team_budget=10_000_000, agents={"cfo": 1000})
        reader = _reader({"cfo": 5000})

        with tempfile.TemporaryDirectory() as td:
            state_path = Path(td) / "state.json"

            s1 = budget_monitor.run_once(
                roster, usage_reader=reader, poster=poster, state_path=state_path
            )
            self.assertEqual(len(s1["fired"]), 1)
            self.assertEqual(len(posted), 1)

            # Second identical sweep: deduped, nothing new posted.
            s2 = budget_monitor.run_once(
                roster, usage_reader=reader, poster=poster, state_path=state_path
            )
            self.assertEqual(s2["fired"], [])
            self.assertEqual(len(posted), 1)


class TbdSalaryRunawayMustNotBeSilent(unittest.TestCase):
    """A TBD/null-salary agent (payroll.salary -> 0) must NOT be dropped from per-agent
    evaluation. Before the fix, salary<=0 did `continue`, so a runaway burn sat silent —
    precisely the metering gap this module exists to close, and most likely for the
    new/probation hires onboarded with a TBD salary."""

    def _tbd_roster(self, team_budget, agents, per_run_ceiling=None):
        policy = {"team_token_budget": team_budget}
        if per_run_ceiling is not None:
            policy["per_run_token_ceiling"] = per_run_ceiling
        return {
            "policy": policy,
            "agents": {
                name: {"salary_tokens_per_week": salary}
                for name, salary in agents.items()
            },
        }

    def test_tbd_salary_agent_burning_4M_still_alerts(self):
        roster = self._tbd_roster(
            team_budget=5_540_000,
            agents={"new_hire": None, "qa1": 300_000},
        )
        alerts = budget_monitor.check_fleet(
            roster, usage_reader=_reader({"new_hire": 4_000_000, "qa1": 50_000})
        )
        by = _by_subject(alerts)
        self.assertTrue(alerts, "runaway TBD-salary agent (4M) produced NO alert at all")
        self.assertIn("new_hire", by, "over-budget TBD-salary agent was never flagged")
        self.assertEqual(by["new_hire"]["level"], "critical")
        # Default fallback ceiling (no per_run_token_ceiling set) = 1,000,000.
        self.assertEqual(by["new_hire"]["limit"], budget_monitor.DEFAULT_TBD_SALARY_CEILING)

    def test_tbd_salary_under_fallback_ceiling_is_silent(self):
        # A TBD-salary agent burning well under the fallback ceiling stays healthy/silent.
        roster = self._tbd_roster(team_budget=10_000_000, agents={"probie": None})
        alerts = budget_monitor.check_fleet(
            roster, usage_reader=_reader({"probie": 10_000})
        )
        self.assertEqual(alerts, [])

    def test_tbd_salary_uses_per_run_ceiling_when_configured(self):
        # When policy sets per_run_token_ceiling, that is the ceiling used for TBD-salary agents.
        roster = self._tbd_roster(
            team_budget=10_000_000, agents={"probie": None}, per_run_ceiling=50_000
        )
        alerts = budget_monitor.check_fleet(
            roster, usage_reader=_reader({"probie": 60_000})
        )
        by = _by_subject(alerts)
        self.assertIn("probie", by)
        self.assertEqual(by["probie"]["limit"], 50_000)
        self.assertEqual(by["probie"]["level"], "critical")


class NonFiniteUsageNeverAbortsTheSweep(unittest.TestCase):
    """int(inf)/int(-inf) raises OverflowError — an ArithmeticError, NOT a ValueError. Before the
    fix it propagated out of check_fleet and aborted the WHOLE sweep, losing every other agent's
    alert (violating the documented 'check_fleet NEVER raises' contract)."""

    def test_inf_usage_is_skipped_not_fatal(self):
        roster = _roster(team_budget=10_000_000, agents={"good": 1000, "infagent": 1000})
        reader = lambda ag: float("inf") if ag == "infagent" else 5000  # noqa: E731
        alerts = budget_monitor.check_fleet(roster, usage_reader=reader)  # must NOT raise
        by = _by_subject(alerts)
        self.assertIn("good", by)  # over-budget agent still reported
        self.assertNotIn("infagent", by)  # non-finite value skipped, not crashing

    def test_negative_inf_usage_is_skipped_not_fatal(self):
        roster = _roster(team_budget=10_000_000, agents={"good": 1000, "ninf": 1000})
        reader = lambda ag: float("-inf") if ag == "ninf" else 5000  # noqa: E731
        alerts = budget_monitor.check_fleet(roster, usage_reader=reader)
        by = _by_subject(alerts)
        self.assertIn("good", by)
        self.assertNotIn("ninf", by)

    def test_nan_usage_is_skipped_not_fatal(self):
        roster = _roster(team_budget=10_000_000, agents={"good": 1000, "nanagent": 1000})
        reader = lambda ag: float("nan") if ag == "nanagent" else 5000  # noqa: E731
        alerts = budget_monitor.check_fleet(roster, usage_reader=reader)
        by = _by_subject(alerts)
        self.assertIn("good", by)
        self.assertNotIn("nanagent", by)


class DedupSurvivesUnwritableState(unittest.TestCase):
    """Dedup suppression must not depend solely on a writable state file. When the state path is
    unwritable, run_loop's in-memory fallback still suppresses the repeat alert (no Slack spam)."""

    def test_no_repeat_spam_when_state_cannot_persist(self):
        import tempfile
        from pathlib import Path

        posts = []

        def poster(agent, title, body):
            posts.append(title)
            return {"status": "report_only"}

        roster = _roster(team_budget=10_000_000, agents={"cfo": 1000})
        reader = _reader({"cfo": 5000})
        with tempfile.TemporaryDirectory() as td:
            afile = Path(td) / "afile"
            afile.write_text("x")  # parent is a FILE -> mkdir/write fails -> not persisted
            state_path = afile / "state.json"
            # run_loop carries state in memory across sweeps; the disk write fails every time.
            budget_monitor.run_loop(
                interval_s=0,
                iterations=5,
                roster=roster,
                usage_reader=reader,
                poster=poster,
                state_path=state_path,
                sleep=lambda _s: None,
            )
        self.assertEqual(len(posts), 1, "alert spammed every sweep when state could not persist")

    def test_write_state_reports_failure(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as td:
            afile = Path(td) / "afile"
            afile.write_text("x")
            bad_path = afile / "state.json"  # parent is a file -> write fails
            self.assertFalse(budget_monitor._write_state({"cfo": "critical"}, bad_path))
            ok_path = Path(td) / "ok_state.json"
            self.assertTrue(budget_monitor._write_state({"cfo": "critical"}, ok_path))


class ModelDevExcludedFromFleet(unittest.TestCase):
    """A denylisted (model-dev) slug must NOT be costed or alerted, and must not inflate the fleet
    total — mirroring the CFO roll-up (graphs/exec/cfo.py uses assert_not_model_work). Otherwise the
    monitor over-reports vs the CFO and leaks model-dev spend into an Anthropic-terms-boundary role."""

    def test_denylisted_role_excluded_from_fleet_and_per_agent(self):
        roster = {
            "policy": {"team_token_budget": 1000},
            "agents": {
                "real_agent": {"salary_tokens_per_week": 5000},
                "gal-model": {"salary_tokens_per_week": 5000},
            },
        }
        reader = _reader({"real_agent": 600, "gal-model": 600})
        alerts = budget_monitor.check_fleet(roster, usage_reader=reader)
        by = _by_subject(alerts)
        self.assertNotIn("gal-model", by)  # model-dev role never costed/alerted
        self.assertNotIn("FLEET", by)  # fleet reflects only non-model-dev burn (600 <= 1000)

    def test_denylisted_role_does_not_trip_fleet_alert(self):
        # Without the guard, eval-worker's 800 would push the fleet to 1400 > 1000 and fire FLEET.
        roster = {
            "policy": {"team_token_budget": 1000},
            "agents": {
                "qa1": {"salary_tokens_per_week": 5000},
                "eval-worker": {"salary_tokens_per_week": 5000},
            },
        }
        alerts = budget_monitor.check_fleet(
            roster, usage_reader=_reader({"qa1": 600, "eval-worker": 800})
        )
        by = _by_subject(alerts)
        self.assertNotIn("FLEET", by)
        self.assertNotIn("eval-worker", by)


if __name__ == "__main__":
    unittest.main()
