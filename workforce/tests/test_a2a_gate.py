"""Unit tests for the A2A governance gate (agent_toolkit/a2a_gate.py).

Governed agent-to-agent conversation: capability check (who-may-talk, default-deny), HITL on
outward (to the human), and a hash-chained audit. Loaded by path so it runs in the deps-free venv.
"""
from __future__ import annotations

import copy
import importlib.util
import pathlib
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "agent_toolkit" / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


G = _load("a2a_gate")
CAPS = yaml.safe_load((ROOT / "docs" / "governance" / "capabilities.yaml").read_text())


def _granted_mandate():
    m = copy.deepcopy(yaml.safe_load((ROOT / "docs" / "governance" / "delegation.yaml").read_text()))
    m["status"], m["granted_by"] = "granted", "shay"
    return m


class WhoMayTalk(unittest.TestCase):
    def test_internal_grant_allows_autonomous(self):
        v = G.gate_a2a("qa_lead_aggregator", "ceo", "verdict", capabilities=CAPS)
        self.assertTrue(v["allowed"])
        self.assertEqual(v["approver"], "auto")

    def test_no_grant_denies_default_deny(self):
        v = G.gate_a2a("android_manual_tester", "ceo", "hi", capabilities=CAPS)
        self.assertFalse(v["allowed"])

    def test_no_message_human_grant_denies(self):
        v = G.gate_a2a("web_automation_engineer", "human", "hi", capabilities=CAPS)
        self.assertFalse(v["allowed"])


class OutwardIsHITL(unittest.TestCase):
    def test_outward_to_human_is_hitl_gated(self):
        v = G.gate_a2a("ceo", "human", "board update", capabilities=CAPS, mandate=_granted_mandate())
        self.assertTrue(v["allowed"])  # report-only records, doesn't block
        self.assertIsNotNone(v["hitl"])
        self.assertEqual(v["approver"], "owner")  # founder at the bright line

    def test_internal_is_not_hitl(self):
        v = G.gate_a2a("qa_lead_aggregator", "ceo", "verdict", capabilities=CAPS, mandate=_granted_mandate())
        self.assertIsNone(v["hitl"])

    def test_live_mode_blocks_unapproved_outward(self):
        # live (report_only=False): a human-required outward turn must not auto-deliver
        v = G.gate_a2a("ceo", "human", "x", capabilities=CAPS, mandate=_granted_mandate(), report_only=False)
        self.assertFalse(v["allowed"])  # blocked pending human approval


class Audit(unittest.TestCase):
    def test_every_turn_has_a_hash_chained_audit_entry(self):
        v1 = G.gate_a2a("qa_lead_aggregator", "ceo", "a", capabilities=CAPS, seq=0, prev_hash="")
        v2 = G.gate_a2a("qa_lead_aggregator", "ceo", "b", capabilities=CAPS, seq=1, prev_hash=v1["audit"]["hash"])
        self.assertIn("hash", v1["audit"])
        self.assertEqual(v2["audit"]["prev_hash"], v1["audit"]["hash"])  # chain links
        self.assertNotEqual(v1["audit"]["hash"], v2["audit"]["hash"])

    def test_denied_turn_is_audited_too(self):
        v = G.gate_a2a("android_manual_tester", "ceo", "x", capabilities=CAPS)
        self.assertFalse(v["audit"]["capability_ok"])
        self.assertEqual(v["audit"]["approver"], "denied")


class TargetValidation(unittest.TestCase):
    def test_outward_detection(self):
        self.assertTrue(G.is_outward("human"))
        self.assertTrue(G.is_outward("slack:#marketing"))
        self.assertFalse(G.is_outward("cfo"))


if __name__ == "__main__":
    unittest.main()
