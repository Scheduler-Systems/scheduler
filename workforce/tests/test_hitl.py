"""Unit tests for the human-in-the-loop gate (agent_toolkit/hitl.py).

Verifies the ratified 'always needs a human' policy (the PDP decision) and that the gate
records-but-never-blocks in report-only mode (probation). Loaded by path so it runs in the
deterministic deps-free venv as well as CI (no langgraph import needed for the pure logic).
"""
from __future__ import annotations

import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "hitl", ROOT / "agent_toolkit" / "hitl.py"
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
human_required = _mod.human_required
human_gate = _mod.human_gate
HUMAN_REQUIRED_KINDS = _mod.HUMAN_REQUIRED_KINDS


class Decision(unittest.TestCase):
    def test_every_ratified_kind_requires_human(self):
        for kind in HUMAN_REQUIRED_KINDS:
            req, _ = human_required({"kind": kind})
            self.assertTrue(req, f"{kind} must require a human")

    def test_oss_contribution_requires_human(self):
        req, reason = human_required({"kind": "oss_contribution"})
        self.assertTrue(req)
        self.assertIn("human-in-the-loop", reason)

    def test_message_to_person_requires_human(self):
        self.assertTrue(human_required({"kind": "message_to_person"})[0])

    def test_internal_read_is_autonomous(self):
        self.assertFalse(human_required({"kind": "read", "capability": "read:repo"})[0])

    def test_internal_propose_draft_is_autonomous(self):
        # a draft that is NOT sent stays autonomous
        self.assertFalse(human_required({"capability": "propose:content_draft"})[0])

    def test_outward_flag_gates_anything(self):
        self.assertTrue(human_required({"capability": "post:slack", "outward": True})[0])

    def test_external_write_gated(self):
        self.assertTrue(human_required({"capability": "write:github_issue", "external": True})[0])

    def test_internal_post_is_autonomous(self):
        # posting to an internal channel (no outward/external) is not gated
        self.assertFalse(human_required({"capability": "post:slack"})[0])

    def test_spend_money_requires_human(self):
        self.assertTrue(human_required({"kind": "spend_money"})[0])


class Gate(unittest.TestCase):
    def test_report_only_never_blocks_even_when_required(self):
        res = human_gate({"kind": "oss_contribution"}, agent="sales_dev", report_only=True)
        self.assertEqual(res["status"], "would_require_human")
        self.assertFalse(res["blocked"])
        self.assertEqual(res["mode"], "report_only")

    def test_autonomous_action_passes(self):
        res = human_gate({"capability": "read:repo"}, agent="cfo", report_only=True)
        self.assertEqual(res["status"], "auto")
        self.assertFalse(res["blocked"])

    def test_on_record_callback_receives_record(self):
        seen = {}
        human_gate({"kind": "publish"}, agent="cmo", report_only=True,
                   on_record=lambda r: seen.update(r))
        self.assertEqual(seen.get("agent"), "cmo")
        self.assertTrue(seen.get("required"))

    def test_on_record_failure_is_swallowed(self):
        def boom(_):
            raise ValueError("delivery down")
        # must not raise — audit/delivery is best-effort
        res = human_gate({"kind": "publish"}, agent="x", report_only=True, on_record=boom)
        self.assertEqual(res["status"], "would_require_human")

    def test_live_mode_without_langgraph_raises_not_silently_proceeds(self):
        # fail-closed: live human-required action with no runtime must error, never auto-proceed
        with self.assertRaises(RuntimeError):
            human_gate({"kind": "message_to_person"}, agent="sales_dev", report_only=False)

    def test_live_mode_autonomous_action_does_not_interrupt(self):
        # an autonomous action needs no human even in live mode
        res = human_gate({"capability": "read:repo"}, agent="cfo", report_only=False)
        self.assertEqual(res["status"], "auto")


class GateRoutesToOfficer(unittest.TestCase):
    """With a granted mandate, the approver is an agent-officer — the owner only at the bright line."""

    def _granted_mandate(self):
        import copy
        import yaml
        m = yaml.safe_load((ROOT / "docs" / "governance" / "delegation.yaml").read_text())
        m = copy.deepcopy(m)
        m["status"] = "granted"
        m["granted_by"] = "shay"
        return m

    def test_decision_routes_to_officer_not_owner(self):
        # a delegated non-spend lane resolves to an officer (real spend caps are 0 — nothing delegated)
        res = human_gate({"kind": "hire_fire", "within_policy": True}, agent="hr_ops_manager",
                         report_only=True, mandate=self._granted_mandate())
        self.assertEqual(res["approver"], "hr_ops_manager")
        self.assertEqual(res["approver_tier"], "officer")

    def test_billing_still_reaches_owner(self):
        res = human_gate({"kind": "spend", "amount_usd": 5, "touches_billing": True},
                         agent="cfo", report_only=True, mandate=self._granted_mandate())
        self.assertEqual(res["approver"], "owner")

    def test_without_mandate_defaults_to_owner(self):
        res = human_gate({"kind": "oss_contribution"}, agent="sales_dev", report_only=True)
        self.assertEqual(res["approver"], "owner")


if __name__ == "__main__":
    unittest.main()
