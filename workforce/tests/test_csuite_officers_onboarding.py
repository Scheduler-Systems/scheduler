"""HR-onboarding tests for Lior (security_officer / CISO) and Lex (clo / CLO).

Every agent is an EMPLOYEE: it is HIRED (roster row + salary + scorecard + capability grant +
langgraph registration + router wiring), not just deployed. These tests assert BOTH officers are
fully onboarded so the two CI gates (check_roster_coverage + check_capability_coverage) pass WITH
them included, and that the org-chart router wires the CEO↔officer edges (escalation up, delegation
down) and Lex's overclaim hand-off to the CMO — every routed edge gate-allowed.

Run: .venv/bin/python -m unittest tests.test_csuite_officers_onboarding -v
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
LIOR = "security_officer"
LEX = "clo"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_sibling(name, relpath):
    spec = importlib.util.spec_from_file_location(name, ROOT / relpath)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# =================================================================================================
# 1. LANGGRAPH REGISTRATION — both officers are deployed graphs
# =================================================================================================
class LangGraphRegistration(unittest.TestCase):
    def test_both_officers_are_deployed_graphs(self):
        graphs = json.loads((ROOT / "langgraph.json").read_text())["graphs"]
        self.assertEqual(graphs[LIOR], "./graphs/exec/security_officer.py:graph")
        self.assertEqual(graphs[LEX], "./graphs/exec/clo.py:graph")


# =================================================================================================
# 2. ROSTER COVERAGE — both have an HR row in the executive group; the gate passes
# =================================================================================================
class RosterCoverage(unittest.TestCase):
    def _roster(self):
        return yaml.safe_load((ROOT / "roster.yaml").read_text())

    def test_lior_row_has_required_hr_fields(self):
        row = self._roster()["agents"][LIOR]
        self.assertEqual(row["name"], "Lior")
        self.assertEqual(row["grade"], "gemini-2.5-flash")
        self.assertEqual(row["salary_tokens_per_week"], 120000)
        self.assertEqual(row["status"], "probation")
        self.assertEqual(row["hire"], "pending_hr_approval")
        self.assertEqual(row["reports_to"], "ceo")
        self.assertIn("scorecard", row)

    def test_lex_row_has_required_hr_fields(self):
        row = self._roster()["agents"][LEX]
        self.assertEqual(row["name"], "Lex")
        self.assertEqual(row["grade"], "gemini-2.5-flash")
        self.assertEqual(row["salary_tokens_per_week"], 120000)
        self.assertEqual(row["status"], "probation")
        self.assertEqual(row["hire"], "pending_hr_approval")
        self.assertEqual(row["reports_to"], "ceo")
        self.assertIn("scorecard", row)

    def test_both_are_in_the_executive_org_group(self):
        org = self._roster()["org"]["executive"]
        self.assertIn(LIOR, org)
        self.assertIn(LEX, org)

    def test_roster_coverage_gate_passes(self):
        self.assertEqual(_load("check_roster_coverage").main(), 0)


# =================================================================================================
# 3. CAPABILITY COVERAGE — agent-only, spend-only, report-only grants; the gate passes
# =================================================================================================
class CapabilityCoverage(unittest.TestCase):
    def _manifest(self):
        return yaml.safe_load((ROOT / "docs" / "governance" / "capabilities.yaml").read_text())

    def test_lior_grant_is_report_only_spend_only_no_secret_identity(self):
        grant = self._manifest()["grants"][LIOR]
        self.assertEqual(grant["posture"], "report_only")
        self.assertIs(grant["can_buy"], False)
        self.assertEqual(grant["funding"], "ring_fenced_pool")
        # NO secret-bearing identity — only the propose-only baseline.
        self.assertEqual(set(grant["identities"]),
                         {"model_inference", "openclaw_slack_bot", "github_app"})
        caps = {c["capability"] for c in grant["capabilities"]}
        for expected in ("read:repo", "read:ci", "read:fleet_state", "read:git",
                         "propose:threat_model", "propose:security_finding",
                         "propose:secret_rotation", "propose:incident_response",
                         "post:slack", "message:cto", "message:ceo",
                         "message:audit_risk_director", "message:platform_specialist",
                         "message:human", "write:github_issue"):
            self.assertIn(expected, caps, f"Lior missing {expected}")

    def test_lex_grant_is_report_only_spend_only(self):
        grant = self._manifest()["grants"][LEX]
        self.assertEqual(grant["posture"], "report_only")
        self.assertIs(grant["can_buy"], False)
        caps = {c["capability"] for c in grant["capabilities"]}
        for expected in ("read:repo", "read:fleet_state", "propose:legal_review",
                         "propose:legal_finding", "propose:compliance", "post:slack",
                         "message:cmo", "message:ceo", "message:cto",
                         "message:audit_risk_director", "message:human", "write:github_issue"):
            self.assertIn(expected, caps, f"Lex missing {expected}")

    def test_neither_officer_has_a_procurement_or_mutating_verb(self):
        """Allow-listed verbs only (read/post/propose/write/git/message) — never buy/deploy/file/send."""
        for slug in (LIOR, LEX):
            for c in self._manifest()["grants"][slug]["capabilities"]:
                verb = c["capability"].split(":", 1)[0]
                self.assertIn(verb, ("read", "post", "propose", "write", "git", "message"),
                              f"{slug} has non-allow-listed verb in {c['capability']}")

    def test_ceo_can_delegate_down_to_both_officers(self):
        ceo = self._manifest()["grants"]["ceo"]
        caps = {c["capability"] for c in ceo["capabilities"]}
        self.assertIn(f"message:{LIOR}", caps)
        self.assertIn(f"message:{LEX}", caps)

    def test_capability_coverage_gate_passes_with_both_officers(self):
        gate = _load("check_capability_coverage")
        graphs = set(json.loads((ROOT / "langgraph.json").read_text())["graphs"])
        self.assertIn(LIOR, graphs)
        self.assertIn(LEX, graphs)
        errors, _ = gate.validate(graphs, self._manifest())
        self.assertEqual(errors, [], f"capability gate errors: {errors}")


# =================================================================================================
# 4. ROUTER WIRING — both report to CEO; escalate up; CEO delegates down; Lex routes overclaim→CMO
# =================================================================================================
C = _load_sibling("collaboration", "agent_toolkit/collaboration.py")
G = _load_sibling("a2a_gate", "agent_toolkit/a2a_gate.py")
CAPS = yaml.safe_load((ROOT / "docs" / "governance" / "capabilities.yaml").read_text())


class RouterWiring(unittest.TestCase):
    def setUp(self):
        C.load_org_chart(force=True)

    def _gate(self, frm, tgt):
        src = C.ROLE_TO_GRAPH.get(frm, frm)
        dst = C.ROLE_TO_GRAPH.get(tgt, tgt)
        return G.gate_a2a(src, dst, "x", capabilities=CAPS, report_only=True)

    def test_both_officers_report_to_the_ceo(self):
        chart = C.load_org_chart()
        self.assertEqual(chart.manager_of(LIOR), "ceo")
        self.assertEqual(chart.manager_of(LEX), "ceo")
        self.assertEqual(chart.dept_of(LIOR), "executive")
        self.assertEqual(chart.dept_of(LEX), "executive")
        self.assertIn(LIOR, chart.reports_of("ceo"))
        self.assertIn(LEX, chart.reports_of("ceo"))

    def test_lior_escalates_up_to_ceo(self):
        target, reason = C.route_collaboration(
            "a missing webhook signature replay security incident beyond my scope", LIOR)
        self.assertEqual(target, "ceo")
        self.assertIn("escalation", reason)
        self.assertTrue(self._gate(LIOR, "ceo")["allowed"])

    def test_lex_escalates_up_to_ceo(self):
        target, reason = C.route_collaboration(
            "a gdpr privacy compliance contract legal issue beyond me", LEX)
        self.assertEqual(target, "ceo")
        self.assertIn("escalation", reason)
        self.assertTrue(self._gate(LEX, "ceo")["allowed"])

    def test_ceo_delegates_down_to_lior_on_a_security_item(self):
        # CEO-lane keyword (decision/priority/proposal) + a security piece -> delegate to Lior.
        target, reason = C.route_collaboration(
            "decision: this threat model vuln secret rotation proposal needs an owner", "ceo")
        self.assertEqual(target, LIOR)
        self.assertIn("delegation", reason)
        self.assertTrue(self._gate("ceo", LIOR)["allowed"])

    def test_ceo_delegates_down_to_lex_on_a_legal_item(self):
        target, reason = C.route_collaboration(
            "decision on this legal privacy gdpr compliance proposal", "ceo")
        self.assertEqual(target, LEX)
        self.assertIn("delegation", reason)
        self.assertTrue(self._gate("ceo", LEX)["allowed"])

    def test_lex_overclaim_handoff_to_cmo_is_gate_allowed(self):
        # Lex flags an overclaim to the CMO (the analyze finding sets route_peer=cmo); the grant
        # must allow the message:cmo edge so the watcher does not drop the hand-off.
        self.assertTrue(self._gate(LEX, "cmo")["allowed"])

    def test_lior_dotted_line_to_audit_risk_director_is_gate_allowed(self):
        self.assertTrue(self._gate(LIOR, "audit_risk_director")["allowed"])

    def test_lior_pairs_with_platform_specialist_gate_allowed(self):
        # Prompt-injection/PII POLICY pairing with Lennox (who owns the runtime evaluators).
        self.assertTrue(self._gate(LIOR, "platform_specialist")["allowed"])

    def test_an_ungranted_officer_edge_is_denied(self):
        # Lior holds no message:cmo grant — a security→marketing edge must be default-denied.
        self.assertFalse(self._gate(LIOR, "cmo")["allowed"])
        # Lex holds no message:platform_specialist grant.
        self.assertFalse(self._gate(LEX, "platform_specialist")["allowed"])


if __name__ == "__main__":
    unittest.main()
