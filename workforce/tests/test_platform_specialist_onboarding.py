"""HR-onboarding tests for Lennox (platform_specialist) — proves the agent went through HR.

Every agent is an EMPLOYEE: it is HIRED (roster row + salary + scorecard + capability grant +
langgraph registration + router wiring), not just deployed. These tests assert Lennox is fully
onboarded so the two CI gates (check_roster_coverage + check_capability_coverage) pass WITH it,
and that the org-chart router wires the CTO↔Lennox edges.

Run: .venv/bin/python -m unittest tests.test_platform_specialist_onboarding -v
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
SLUG = "platform_specialist"

# Load the two gate modules by path (scripts/ is not a package).
def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class LangGraphRegistration(unittest.TestCase):
    def test_platform_specialist_is_a_deployed_graph(self):
        graphs = json.loads((ROOT / "langgraph.json").read_text())["graphs"]
        self.assertIn(SLUG, graphs)
        self.assertEqual(graphs[SLUG], "./graphs/platform/platform_specialist.py:graph")


class RosterCoverage(unittest.TestCase):
    def test_roster_has_lennox_row_with_required_hr_fields(self):
        roster = yaml.safe_load((ROOT / "roster.yaml").read_text())
        agents = roster["agents"]
        self.assertIn(SLUG, agents)
        row = agents[SLUG]
        self.assertEqual(row["name"], "Lennox")
        self.assertEqual(row["grade"], "gemini-2.5-flash")
        self.assertEqual(row["salary_tokens_per_week"], 150000)
        self.assertEqual(row["status"], "probation")
        self.assertEqual(row["hire"], "pending_hr_approval")
        self.assertEqual(row["reports_to"], "cto")
        self.assertIn("scorecard", row)

    def test_lennox_is_in_the_platform_org_group(self):
        roster = yaml.safe_load((ROOT / "roster.yaml").read_text())
        self.assertIn(SLUG, roster["org"]["platform"])

    def test_roster_coverage_gate_passes(self):
        gate = _load("check_roster_coverage")
        self.assertEqual(gate.main(), 0)  # 0 => all deployed graphs rostered (incl. Lennox)


class CapabilityCoverage(unittest.TestCase):
    def _manifest(self):
        return yaml.safe_load((ROOT / "docs" / "governance" / "capabilities.yaml").read_text())

    def test_langsmith_api_key_nhi_is_declared_spend_only(self):
        man = self._manifest()
        nhi = man["identities"]["langsmith_api_key"]
        self.assertEqual(nhi["tier"], "agent")
        self.assertEqual(nhi["kind"], "rest_api_key")
        self.assertIs(nhi["can_buy"], False)      # real boolean false
        self.assertEqual(nhi["issued_by"], "shay")

    def test_lennox_grant_is_report_only_spend_only(self):
        grant = self._manifest()["grants"][SLUG]
        self.assertEqual(grant["posture"], "report_only")
        self.assertIs(grant["can_buy"], False)
        self.assertEqual(grant["funding"], "ring_fenced_pool")
        self.assertIn("langsmith_api_key", grant["identities"])
        caps = {c["capability"] for c in grant["capabilities"]}
        # the granted surface from the approved design
        self.assertIn("read:langsmith", caps)
        self.assertIn("read:financials", caps)
        self.assertIn("propose:platform_maintenance", caps)
        self.assertIn("message:cto", caps)
        self.assertIn("post:slack", caps)
        self.assertIn("write:github_issue", caps)

    def test_lennox_has_no_procurement_or_deploy_capability(self):
        """Spend-only: no buy/deploy/execute verb anywhere in Lennox's grant."""
        grant = self._manifest()["grants"][SLUG]
        for c in grant["capabilities"]:
            verb = c["capability"].split(":", 1)[0]
            self.assertIn(verb, ("read", "propose", "message", "post", "write"))

    def test_capability_coverage_gate_passes(self):
        gate = _load("check_capability_coverage")
        graphs = set(json.loads((ROOT / "langgraph.json").read_text())["graphs"])
        man = self._manifest()
        errors, _ = gate.validate(graphs, man)
        self.assertEqual(errors, [], f"capability gate errors: {errors}")

    def test_cto_can_delegate_down_to_lennox(self):
        """The CTO grant carries message:platform_specialist (delegation DOWN)."""
        cto = self._manifest()["grants"]["cto"]
        caps = {c["capability"] for c in cto["capabilities"]}
        self.assertIn("message:platform_specialist", caps)


class RouterWiring(unittest.TestCase):
    def test_org_chart_wires_cto_as_manager(self):
        from agent_toolkit import collaboration as c
        chart = c.load_org_chart(force=True)
        self.assertEqual(chart.manager_of(SLUG), "cto")
        self.assertIn(SLUG, chart.reports_of("cto"))
        self.assertEqual(chart.dept_of(SLUG), "platform")
        self.assertTrue(chart.is_worker(SLUG))

    def test_lennox_escalates_up_to_cto(self):
        from agent_toolkit import collaboration as c
        c.load_org_chart(force=True)
        target, reason = c.route_collaboration("the langsmith eval gate regressed", SLUG)
        self.assertEqual(target, "cto")
        self.assertIn("escalation", reason)

    def test_cto_delegates_down_to_lennox_on_a_platform_item(self):
        from agent_toolkit import collaboration as c
        c.load_org_chart(force=True)
        # CTO own-lane (deploy keyword) + a platform-specific piece (langsmith/eval gate).
        target, reason = c.route_collaboration(
            "the deploy needs a langsmith eval gate rollback check", "cto")
        self.assertEqual(target, SLUG)
        self.assertIn("delegation", reason)


if __name__ == "__main__":
    unittest.main()
