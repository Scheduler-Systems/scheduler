"""Tests for the human-override kill switch (fleet-wide + per-agent) wired into check_clocked_in.

Run: .venv/bin/python -m unittest tests.test_kill_switch -v
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_toolkit import budget


class KillSwitchTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        d = Path(self._tmp.name)
        # Point the control-plane files at a temp dir so we never touch the real .payroll.
        self._p1 = mock.patch.object(budget, "FLEET_DISABLED_FILE", d / "FLEET_DISABLED")
        self._p2 = mock.patch.object(budget, "BENCHED_FILE", d / "benched.json")
        self._p1.start(); self._p2.start()
        # Clear env switches so files are the only signal.
        self._env = mock.patch.dict(os.environ, {}, clear=False)
        self._env.start()
        os.environ.pop("AGENTS_DISABLED", None)
        os.environ.pop("AGENTS_BENCHED", None)

    def tearDown(self):
        self._p1.stop(); self._p2.stop(); self._env.stop(); self._tmp.cleanup()

    def test_fleet_kill_stops_everyone(self):
        # Over-budget check would otherwise pass; the fleet switch wins and is checked first.
        with mock.patch.object(budget.payroll, "is_over_budget", return_value=False):
            self.assertTrue(budget.check_clocked_in("cfo"))
            budget.disable_fleet("test")
            self.assertTrue(budget.fleet_disabled())
            self.assertFalse(budget.check_clocked_in("cfo"))    # STOPPED
            self.assertFalse(budget.check_clocked_in("anyone")) # STOPPED
            budget.enable_fleet()
            self.assertTrue(budget.check_clocked_in("cfo"))

    def test_env_kill_switch(self):
        with mock.patch.object(budget.payroll, "is_over_budget", return_value=False), \
             mock.patch.dict(os.environ, {"AGENTS_DISABLED": "1"}):
            self.assertFalse(budget.check_clocked_in("cfo"))

    def test_per_agent_bench(self):
        with mock.patch.object(budget.payroll, "is_over_budget", return_value=False):
            budget.bench("web_automation_engineer", "flaky")
            self.assertTrue(budget.is_benched("web_automation_engineer"))
            self.assertFalse(budget.check_clocked_in("web_automation_engineer"))  # benched -> STOP
            self.assertTrue(budget.check_clocked_in("cfo"))                       # others unaffected
            budget.unbench("web_automation_engineer")
            self.assertTrue(budget.check_clocked_in("web_automation_engineer"))

    def test_benched_file_corrupt_is_failsafe(self):
        budget.BENCHED_FILE.write_text("{not json", encoding="utf-8")
        with mock.patch.object(budget.payroll, "is_over_budget", return_value=False):
            self.assertEqual(budget.benched_agents(), set())          # no crash, empty
            self.assertTrue(budget.check_clocked_in("cfo"))

    def test_bench_persists_to_file(self):
        budget.bench("coo")
        data = json.loads(budget.BENCHED_FILE.read_text(encoding="utf-8"))
        self.assertIn("coo", data)


if __name__ == "__main__":
    unittest.main()
