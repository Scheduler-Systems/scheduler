"""Safety tests for Lex, the cloud CLO (clo) executive agent.

The CLO reviews the LEGAL surface as a PROPOSE-ONLY / HITL digest of FLAGS + DRAFTS, synthesizing
four legal sub-reviewer lenses. The tests prove the load-bearing invariants on the pure node cores
(no checkpointer, no network):
(1) the module exposes NO file/sign/send/submit/bind/buy/deploy path (it never binds the company);
(2) analyze applies the four lenses and FLAGS an OVERCLAIM and a PRIVACY/breach-notification issue,
routing the overclaim to the CMO; (3) the IDOR is read as the breach-NOTIFICATION legal angle and
escalates to Shay (never auto-notifies); (4) propose emits DRAFTS only; (5) compose always yields a
non-empty summary via the deterministic fallback; (6) deliver stays REPORT-ONLY (durable record, no
code write, no approval interrupt) and honors clock-in. Run:
    .venv/bin/python -m unittest tests.test_clo -v
"""
import os
import unittest
from unittest import mock

from graphs.exec import clo as m


# --- NO BINDING PATH: never file/sign/send/submit/bind/buy/deploy ------------------------------
class NoBindingPathTests(unittest.TestCase):
    FORBIDDEN = ("file_", "sign", "send", "submit", "bind", "notify_", "buy", "purchase",
                 "deploy", "rotate", "create_cron", "transfer", "merge", "push")

    def test_module_exposes_no_binding_callable(self):
        """No locally-defined callable implies a file/sign/send/submit/bind/buy/deploy action.

        ``file_digest_issue`` (a durable RECORD) is the only outward seam and is imported, not
        defined here — so we scan only LOCALLY-defined functions."""
        for name in dir(m):
            obj = getattr(m, name)
            if callable(obj) and getattr(obj, "__module__", None) == m.__name__:
                low = name.lower()
                for verb in self.FORBIDDEN:
                    self.assertNotIn(
                        verb, low, f"clo defines '{name}' implying a binding/{verb} action")

    def test_no_send_or_deploy_symbol_imported(self):
        for forbidden in ("dispatch_github_workflow", "request_approval"):
            self.assertFalse(hasattr(m, forbidden),
                             f"clo must not import {forbidden} (no bind/mutate/interrupt path)")


# --- gather: fail-safe legal surface + standing IDOR breach-notification item ------------------
class GatherTests(unittest.TestCase):
    def test_gather_seeds_idor_breach_notification_item(self):
        with mock.patch.object(m, "read_local_digest", return_value="(no digest yet)"):
            out = m.gather({})
        ids = {i.get("id") for i in out["standing"]}
        self.assertIn("idor-1487-breach-notification", ids)
        item = next(i for i in out["standing"] if i["id"] == "idor-1487-breach-notification")
        self.assertEqual(item["escalate_to"], "shay")   # the decision to notify BINDS → Shay
        self.assertIsNot(out["standing"][0], m.IDOR_NOTIFICATION_ITEM)

    def test_gather_uses_known_at_risk_defaults_with_no_input(self):
        """A zero-input run reviews the known at-risk public claims (standing overclaim posture)."""
        with mock.patch.object(m, "read_local_digest", return_value="(no digest yet)"):
            out = m.gather({})
        self.assertTrue(out["surface"]["marketing_claims"])  # default at-risk claims present
        self.assertFalse(out["surface"]["privacy_policy_present"])

    def test_gather_accepts_injected_surface(self):
        with mock.patch.object(m, "read_local_digest", return_value="(no digest yet)"):
            out = m.gather({"privacy_policy_present": True, "billing_terms_match_tos": False,
                            "marketing_claims": ["totally fine"], "contractor_terms_present": True})
        self.assertTrue(out["surface"]["privacy_policy_present"])
        self.assertFalse(out["surface"]["billing_terms_match_tos"])
        self.assertEqual(out["surface"]["marketing_claims"], ["totally fine"])


# --- analyze: the four lenses, overclaim → CMO, breach-notification → Shay ---------------------
class LensReviewTests(unittest.TestCase):
    def test_flags_overclaim_and_routes_to_cmo(self):
        """The legal-document-auditor lens flags an overclaim and routes it to the CMO peer."""
        out = m.analyze({"surface": {
            "privacy_policy_present": True, "billing_terms_match_tos": True,
            "contractor_terms_present": True,
            "marketing_claims": ["AI scheduling builds your roster automatically",
                                 "Simple shift planning"]}, "standing": []})
        over = [f for f in out["findings"] if f["kind"] == "overclaim"]
        self.assertEqual(len(over), 1)                       # only the AI-scheduling claim
        self.assertEqual(over[0]["route_peer"], "cmo")       # routed to the CMO peer
        self.assertEqual(over[0]["lens"], "legal-document-auditor")
        self.assertEqual(out["lenses"]["legal-document-auditor"], over)

    def test_flags_privacy_gap_via_compliance_lens(self):
        out = m.analyze({"surface": {
            "privacy_policy_present": False, "billing_terms_match_tos": True,
            "contractor_terms_present": True, "marketing_claims": []}, "standing": []})
        priv = [f for f in out["findings"] if f["kind"] == "privacy_gap"]
        self.assertEqual(len(priv), 1)
        self.assertEqual(priv[0]["lens"], "legal-compliance-specialist")

    def test_billing_tos_mismatch_is_corporate_lawyer_lens_to_shay(self):
        out = m.analyze({"surface": {
            "privacy_policy_present": True, "billing_terms_match_tos": False,
            "contractor_terms_present": True, "marketing_claims": []}, "standing": []})
        bill = [f for f in out["findings"] if f["kind"] == "billing_tos_mismatch"]
        self.assertEqual(len(bill), 1)
        self.assertEqual(bill[0]["lens"], "corporate-lawyer")
        self.assertEqual(bill[0]["escalate_to"], "shay")

    def test_idor_read_as_breach_notification_to_shay(self):
        """The SAME IDOR is read here as the breach-NOTIFICATION legal angle (twin of the CISO item)."""
        out = m.analyze({"surface": {
            "privacy_policy_present": True, "billing_terms_match_tos": True,
            "contractor_terms_present": True, "marketing_claims": []},
            "standing": [dict(m.IDOR_NOTIFICATION_ITEM)]})
        bn = [f for f in out["findings"] if f["kind"] == "breach_notification"]
        self.assertEqual(len(bn), 1)
        self.assertEqual(bn[0]["escalate_to"], "shay")
        self.assertEqual(bn[0]["lens"], "legal-compliance-specialist")
        self.assertIn("notification", bn[0]["detail"].lower())

    def test_all_four_lenses_are_tracked(self):
        out = m.analyze({"surface": {
            "privacy_policy_present": False, "billing_terms_match_tos": False,
            "contractor_terms_present": False,
            "marketing_claims": ["Built-in time tracking and clock-in"]},
            "standing": [dict(m.IDOR_NOTIFICATION_ITEM)]})
        for lens in m.LEGAL_LENSES:
            self.assertIn(lens, out["lenses"])
        # every lens fired at least once in this all-bad surface
        self.assertTrue(all(out["lenses"][lens] for lens in m.LEGAL_LENSES))


# --- propose: drafts only, never binds --------------------------------------------------------
class ProposeTests(unittest.TestCase):
    def test_every_proposal_is_propose_only_draft(self):
        findings = [
            {"kind": "breach_notification", "area": "privacy", "lens": "legal-compliance-specialist",
             "target": "idor", "detail": "x", "escalate_to": "shay"},
            {"kind": "overclaim", "area": "marketing", "lens": "legal-document-auditor",
             "target": "copy", "claim": "AI scheduling", "detail": "y", "escalate_to": "org", "route_peer": "cmo"},
        ]
        out = m.propose({"findings": findings})
        for p in out["proposals"]:
            self.assertTrue(p["action"].startswith("propose:"),
                            f"proposal is not propose-only: {p['action']}")
            self.assertIn(p["proposal_type"], ("legal_review", "legal_finding", "compliance"))

    def test_breach_notification_proposal_keeps_decision_with_human(self):
        out = m.propose({"findings": [
            {"kind": "breach_notification", "area": "privacy", "lens": "legal-compliance-specialist",
             "target": "idor", "detail": "x", "escalate_to": "shay"}]})
        p = out["proposals"][0]
        self.assertEqual(p["proposal_type"], "compliance")
        self.assertEqual(p["escalate_to"], "shay")
        self.assertIn("a human decides", p["action"].lower())

    def test_overclaim_proposal_carries_cmo_peer(self):
        out = m.propose({"findings": [
            {"kind": "overclaim", "area": "marketing", "lens": "legal-document-auditor",
             "target": "copy", "claim": "AI scheduling", "detail": "y", "escalate_to": "org", "route_peer": "cmo"}]})
        self.assertEqual(out["proposals"][0]["route_peer"], "cmo")

    def test_empty_findings_yields_monitor_legal_review(self):
        out = m.propose({"findings": []})
        self.assertEqual(out["proposals"][0]["kind"], "monitor")
        self.assertEqual(out["proposals"][0]["proposal_type"], "legal_review")


# --- compose: deterministic fallback ----------------------------------------------------------
class ComposeFallbackTests(unittest.TestCase):
    def _state(self):
        return {"surface": {"privacy_policy_present": False, "billing_terms_match_tos": True,
                            "contractor_terms_present": True, "marketing_claims": ["AI scheduling"]},
                "lenses": {l: [] for l in m.LEGAL_LENSES},
                "standing": [dict(m.IDOR_NOTIFICATION_ITEM)],
                "findings": [{"kind": "breach_notification", "area": "privacy",
                              "lens": "legal-compliance-specialist", "target": "idor",
                              "detail": "breach notification assessment", "escalate_to": "shay"}],
                "proposals": [{"action": "propose:compliance — DRAFT", "kind": "breach_notification",
                               "proposal_type": "compliance", "area": "privacy", "lens": "x",
                               "target": "idor", "detail": "x", "escalate_to": "shay", "route_peer": None}]}

    def test_compose_deterministic_when_model_raises(self):
        with mock.patch.object(m, "budget_guard", side_effect=RuntimeError("no key")):
            out = m.compose(self._state())
        self.assertTrue(out["summary"].strip())
        self.assertIn("RuntimeError", out["summary"])

    def test_compose_uses_model_when_available(self):
        fake = mock.MagicMock()
        fake.invoke.return_value = mock.MagicMock(content="THE CLO POSTURE")
        with mock.patch.object(m, "budget_guard", return_value=fake):
            out = m.compose(self._state())
        self.assertEqual(out["summary"], "THE CLO POSTURE")


# --- deliver: report-only durable record ------------------------------------------------------
class DeliverReportOnlyTests(unittest.TestCase):
    def test_deliver_is_report_only_durable_record(self):
        captured = {}

        def fake_file_issue(repo, title, body, *, labels=None, report_only=None, agent=None,
                            record_kind=None, **kwargs):
            captured.update(repo=repo, labels=labels, report_only=report_only, agent=agent,
                            record_kind=record_kind)
            assert report_only is True
            return {"status": "report_only", "repo": repo}

        env = {k: v for k, v in os.environ.items() if k != "OPS_REPORT_ONLY"}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(m, "write_local_digest", return_value="/tmp/x/latest.md"), \
                mock.patch.object(m, "file_digest_issue", side_effect=fake_file_issue):
            out = m.deliver({"summary": "s", "surface": {}, "lenses": {}, "standing": [],
                             "findings": [], "proposals": []})

        self.assertTrue(captured["report_only"])
        self.assertEqual(captured["agent"], "clo")
        self.assertEqual(captured["record_kind"], "clo-posture")
        self.assertIn("exec:clo", captured["labels"])
        self.assertTrue(out["report_only"])


# --- budget gate / clock-in -------------------------------------------------------------------
class BudgetGateTests(unittest.TestCase):
    def test_clocked_out_ends_without_gather(self):
        with mock.patch.object(m, "check_clocked_in", return_value=False), \
                mock.patch.object(m, "governance_capture") as gov, \
                mock.patch.object(m, "read_local_digest",
                                  side_effect=AssertionError("gather must not run")):
            out = m.budget_gate({})
            route = m._budget_route({})
        self.assertEqual(out["report"], {"clocked_in": False})
        self.assertEqual(route, "clocked_out")
        gov.assert_called_once()
        self.assertTrue(gov.call_args[0][1]["report_only"])

    def test_clocked_in_proceeds_to_gather(self):
        with mock.patch.object(m, "check_clocked_in", return_value=True):
            self.assertEqual(m.budget_gate({}), {})
            self.assertEqual(m._budget_route({}), "gather")


# --- end-to-end: unattended, no creds, never hangs, read-only + emits proposals ---------------
class GraphInvokeTests(unittest.TestCase):
    def test_graph_compiles_without_checkpointer(self):
        self.assertIsNotNone(m.graph)

    def test_full_run_report_only_no_creds_flags_overclaim_and_privacy(self):
        env = {k: v for k, v in os.environ.items() if k != "OPS_REPORT_ONLY"}
        captured = {}

        def fake_file_issue(repo, title, body, *, labels=None, report_only=None, **kwargs):
            captured.update(body=body, report_only=report_only, labels=labels)
            return {"status": "report_only"}

        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(m, "check_clocked_in", return_value=True), \
                mock.patch.object(m, "read_local_digest", return_value="(no digest yet)"), \
                mock.patch.object(m, "budget_guard", side_effect=RuntimeError("no model")), \
                mock.patch.object(m, "write_local_digest", return_value="/tmp/clo/latest.md"), \
                mock.patch.object(m, "file_digest_issue", side_effect=fake_file_issue):
            out = m.graph.invoke({})

        self.assertTrue(out["report"]["report_only"])
        self.assertEqual(out["report"]["delivery"], "report_only")
        self.assertGreaterEqual(out["report"]["proposals"], 1)
        # The default at-risk run flags an overclaim routed to the CMO + the IDOR breach-notif → Shay.
        self.assertGreaterEqual(out["report"]["cmo_routed"], 1)
        self.assertGreaterEqual(out["report"]["shay_asks"], 1)
        self.assertTrue(captured["report_only"])

    def test_clocked_out_graph_ends_without_work(self):
        with mock.patch.object(m, "check_clocked_in", return_value=False), \
                mock.patch.object(m, "read_local_digest") as rld, \
                mock.patch.object(m, "file_digest_issue") as fd:
            out = m.graph.invoke({})
        rld.assert_not_called()
        fd.assert_not_called()
        self.assertEqual(out["report"], {"clocked_in": False})


if __name__ == "__main__":
    unittest.main()
