"""Safety tests for Lior, the cloud CISO (security_officer) executive agent.

The CISO reports OPERATIONAL security posture as a PROPOSE-ONLY digest. It CONSUMES the deployed
surface (graphs + grants + event/webhook seam) rather than re-doing work. The tests prove the
load-bearing invariants on the pure node cores (no checkpointer, no network):
(1) the module exposes NO mutating/deploy/file/sign/send/rotate/create_cron path; (2) gather is
FAIL-SAFE — an unreadable surface degrades to a single honest 'unverifiable', never a false
'secure'; (3) the secure-by-design review FLAGS a missing-signature / replay-style finding;
(4) propose emits PROPOSALS only, IDOR escalates to Shay; (5) compose always yields a non-empty
summary via the deterministic fallback; (6) deliver stays REPORT-ONLY (durable record, no code
write, no approval interrupt) and honors clock-in. Run:
    .venv/bin/python -m unittest tests.test_security_officer -v
"""
import os
import unittest
from unittest import mock

from graphs.exec import security_officer as m


# --- NO MUTATING PATH: the bright line — nothing that deploys/rotates/files/signs/sends ---------
class NoMutatingPathTests(unittest.TestCase):
    FORBIDDEN = ("deploy", "rotate", "file_", "sign", "send", "create_cron", "kill", "disable",
                 "submit", "transfer", "buy", "purchase", "merge", "push")

    def test_module_exposes_no_mutating_callable(self):
        """No module-level callable name implies a deploy/rotate/file/sign/send/create_cron action.

        ``file_digest_issue`` (a durable RECORD, not a code action) is the ONLY allowed outward seam
        and is imported, not defined here; we assert no LOCALLY-DEFINED function is a mutating verb."""
        for name in dir(m):
            obj = getattr(m, name)
            if callable(obj) and getattr(obj, "__module__", None) == m.__name__:
                low = name.lower()
                for verb in self.FORBIDDEN:
                    self.assertNotIn(
                        verb, low,
                        f"security_officer defines '{name}' implying a mutating/{verb} action")

    def test_no_send_or_deploy_symbol_imported(self):
        """The agent never imports a deploy/rotate/send capability into its namespace."""
        for forbidden in ("dispatch_github_workflow", "request_approval"):
            self.assertFalse(hasattr(m, forbidden),
                             f"security_officer must not import {forbidden} (no mutate/interrupt path)")

    def test_only_outward_seam_is_a_durable_record(self):
        """The single delivery seam is file_digest_issue (a RECORD), with write_local_digest local."""
        self.assertTrue(hasattr(m, "file_digest_issue"))
        self.assertTrue(hasattr(m, "write_local_digest"))


# --- gather: fail-safe, unverifiable rather than a false 'secure', IDOR standing ----------------
class GatherFailSafeTests(unittest.TestCase):
    def test_gather_unverifiable_when_surface_unreadable(self):
        """An unreadable surface => a single honest 'unverifiable' marker, never a crash/false pass."""
        with mock.patch.object(m, "read_local_digest", return_value="(no digest yet)"), \
                mock.patch.object(m, "_read", side_effect=OSError("no file")):
            out = m.gather({})
        self.assertIsNotNone(out["surface"].get("unverifiable"))
        self.assertEqual(out["surface"]["graphs"], {})

    def test_gather_seeds_the_held_idor_compliance_item(self):
        """The HELD Firestore IDOR #1487 is ALWAYS surfaced as a standing HARD-GATE item (→ shay)."""
        with mock.patch.object(m, "read_local_digest", return_value="(no digest yet)"), \
                mock.patch.object(m, "_read", side_effect=OSError("x")):
            out = m.gather({})
        ids = {i.get("id") for i in out["standing"]}
        self.assertIn("firestore-idor-1487", ids)
        idor = next(i for i in out["standing"] if i["id"] == "firestore-idor-1487")
        self.assertEqual(idor["status"], "held")
        self.assertEqual(idor["escalate_to"], "shay")
        self.assertIsNot(out["standing"][0], m.IDOR_COMPLIANCE_ITEM)  # a copy, not the constant

    def test_gather_reads_real_surface_when_present(self):
        """With the real repo files present, gather builds a graphs map + an event-seam review."""
        with mock.patch.object(m, "read_local_digest", return_value="(no digest yet)"):
            out = m.gather({})
        # The real langgraph.json has many graphs; the agent reviewed them (no unverifiable).
        self.assertIsNone(out["surface"].get("unverifiable"))
        self.assertIn("security_officer", out["surface"]["graphs"])
        self.assertIn("event_seam", out["surface"])


# --- analyze: the KEYSTONE secure-by-design review flags replay/missing-signature ---------------
class SecureByDesignReviewTests(unittest.TestCase):
    def _seam(self, **over):
        base = {"module_found": True, "signature_verified": True, "replay_window": True,
                "ssrf_reachable": False, "egress_allowlist": True}
        base.update(over)
        return base

    def test_flags_missing_signature_replay_style_finding(self):
        """A webhook seam with NO signature verification AND no replay window => the replay findings."""
        surface = {"graphs": {}, "event_seam": self._seam(signature_verified=False,
                                                           replay_window=False)}
        out = m.analyze({"surface": surface, "standing": []})
        kinds = {f["kind"] for f in out["findings"]}
        self.assertIn("missing_signature", kinds)   # the missing-signature finding
        self.assertIn("replay_window_missing", kinds)  # the replay-style finding
        # Both are the irreversible-class security gap → escalate to Shay.
        for f in out["findings"]:
            if f["kind"] in ("missing_signature", "replay_window_missing"):
                self.assertEqual(f["escalate_to"], "shay")
                self.assertIn("replay", f["detail"].lower())

    def test_flags_ssrf_when_fetch_has_no_egress_allowlist(self):
        surface = {"graphs": {}, "event_seam": self._seam(ssrf_reachable=True,
                                                          egress_allowlist=False)}
        out = m.analyze({"surface": surface, "standing": []})
        self.assertIn("ssrf_risk", {f["kind"] for f in out["findings"]})

    def test_flags_grant_coverage_gap_and_posture_breach(self):
        surface = {"graphs": {
            "ungranted": {"module": "x", "grant": None},
            "live": {"module": "y", "grant": {"posture": "live"}},  # not report_only
        }, "event_seam": self._seam()}
        out = m.analyze({"surface": surface, "standing": []})
        kinds = {f["kind"] for f in out["findings"]}
        self.assertIn("grant_coverage_gap", kinds)
        self.assertIn("posture_breach", kinds)

    def test_idor_carried_as_compliance_pending_to_shay(self):
        out = m.analyze({"surface": {"graphs": {}, "event_seam": self._seam()},
                         "standing": [dict(m.IDOR_COMPLIANCE_ITEM)]})
        comp = [f for f in out["findings"] if f["kind"] == "compliance_pending"]
        self.assertEqual(len(comp), 1)
        self.assertEqual(comp[0]["escalate_to"], "shay")
        self.assertIn("IDOR", comp[0]["detail"])

    def test_unverifiable_surface_yields_one_honest_finding_not_a_clean_pass(self):
        out = m.analyze({"surface": {"unverifiable": "could not read"}, "standing": []})
        self.assertEqual(len(out["findings"]), 1)
        self.assertEqual(out["findings"][0]["kind"], "unverifiable")

    def test_clean_surface_no_standing_yields_no_findings(self):
        out = m.analyze({"surface": {"graphs": {
            "ok": {"module": "x", "grant": {"posture": "report_only", "identities": []}}},
            "event_seam": self._seam()}, "standing": []})
        self.assertEqual(out["findings"], [])


# --- propose: propose-only, escalation + proposal-type tags ------------------------------------
class ProposeTests(unittest.TestCase):
    def test_every_proposal_is_a_propose_verb_never_a_mutation(self):
        findings = [
            {"kind": "missing_signature", "target": "event_receiver", "detail": "x", "escalate_to": "shay"},
            {"kind": "over_privilege", "target": "a", "detail": "y", "escalate_to": "shay"},
            {"kind": "compliance_pending", "target": "firestore-idor-1487", "detail": "IDOR", "escalate_to": "shay"},
        ]
        out = m.propose({"findings": findings})
        for p in out["proposals"]:
            self.assertTrue(p["action"].startswith("propose:"),
                            f"proposal is not propose-only: {p['action']}")
            self.assertIn(p["proposal_type"],
                          ("threat_model", "security_finding", "secret_rotation", "incident_response"))

    def test_idor_proposal_is_incident_response_to_shay(self):
        out = m.propose({"findings": [
            {"kind": "compliance_pending", "target": "firestore-idor-1487", "detail": "IDOR", "escalate_to": "shay"}]})
        self.assertEqual(out["proposals"][0]["proposal_type"], "incident_response")
        self.assertEqual(out["proposals"][0]["escalate_to"], "shay")
        self.assertIn("human deploys", out["proposals"][0]["action"])

    def test_empty_findings_yields_monitor_threat_model_proposal(self):
        out = m.propose({"findings": []})
        self.assertEqual(len(out["proposals"]), 1)
        self.assertEqual(out["proposals"][0]["kind"], "monitor")
        self.assertEqual(out["proposals"][0]["proposal_type"], "threat_model")
        self.assertEqual(out["proposals"][0]["escalate_to"], "org")


# --- compose: deterministic fallback, never empty ---------------------------------------------
class ComposeFallbackTests(unittest.TestCase):
    def _state(self):
        return {"surface": {"graphs": {"a": {}}, "event_seam": {"signature_verified": False}},
                "standing": [dict(m.IDOR_COMPLIANCE_ITEM)],
                "findings": [{"kind": "missing_signature", "target": "event_receiver",
                              "detail": "missing HMAC signature — replayable", "escalate_to": "shay"}],
                "proposals": [{"action": "propose:security_finding — require HMAC", "kind": "missing_signature",
                               "proposal_type": "security_finding", "target": "event_receiver",
                               "detail": "x", "escalate_to": "shay"}]}

    def test_compose_deterministic_when_model_raises(self):
        with mock.patch.object(m, "budget_guard", side_effect=RuntimeError("no API key")):
            out = m.compose(self._state())
        self.assertTrue(out["summary"].strip())
        self.assertIn("IDOR", out["summary"])
        self.assertIn("RuntimeError", out["summary"])

    def test_compose_uses_model_when_available(self):
        fake = mock.MagicMock()
        fake.invoke.return_value = mock.MagicMock(content="THE CISO POSTURE")
        with mock.patch.object(m, "budget_guard", return_value=fake):
            out = m.compose(self._state())
        self.assertEqual(out["summary"], "THE CISO POSTURE")


# --- deliver: report-only durable record, honors clock-in -------------------------------------
class DeliverReportOnlyTests(unittest.TestCase):
    def test_deliver_is_report_only_durable_record(self):
        captured = {}

        def fake_file_issue(repo, title, body, *, labels=None, report_only=None, agent=None,
                            record_kind=None, **kwargs):
            captured.update(repo=repo, title=title, labels=labels, report_only=report_only,
                            agent=agent, record_kind=record_kind, body=body)
            assert report_only is True, "deliver must stay report-only on probation"
            return {"status": "report_only", "action": "open_issue", "repo": repo}

        env = {k: v for k, v in os.environ.items() if k != "OPS_REPORT_ONLY"}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(m, "write_local_digest", return_value="/tmp/x/latest.md"), \
                mock.patch.object(m, "file_digest_issue", side_effect=fake_file_issue):
            out = m.deliver({"summary": "s", "surface": {}, "standing": [], "findings": [], "proposals": []})

        self.assertTrue(captured["report_only"])
        self.assertEqual(captured["repo"], m.DIGEST_REPO)
        self.assertEqual(captured["agent"], "security_officer")
        self.assertEqual(captured["record_kind"], "ciso-posture")
        self.assertIn("exec:security_officer", captured["labels"])
        self.assertEqual(out["report"]["delivery"], "report_only")
        self.assertTrue(out["report_only"])

    def test_report_only_env_toggle(self):
        with mock.patch.dict(os.environ, {"OPS_REPORT_ONLY": "0"}):
            self.assertFalse(m._report_only())
        env = {k: v for k, v in os.environ.items() if k != "OPS_REPORT_ONLY"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertTrue(m._report_only())


# --- budget gate / clock-in: never hangs, ends on clock-out -----------------------------------
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


# --- end-to-end: unattended, no creds, never hangs, runs read-only + emits proposals -----------
class GraphInvokeTests(unittest.TestCase):
    def test_graph_compiles_without_checkpointer(self):
        self.assertIsNotNone(m.graph)

    def test_full_run_report_only_no_creds_emits_proposals(self):
        """Unattended, no creds: read-only run completes report-only, never writes, never hangs, and
        the IDOR HARD-GATE rides through as a Shay-escalated proposal in the digest."""
        env = {k: v for k, v in os.environ.items() if k != "OPS_REPORT_ONLY"}
        captured = {}

        def fake_file_issue(repo, title, body, *, labels=None, report_only=None, **kwargs):
            captured.update(body=body, report_only=report_only, labels=labels)
            return {"status": "report_only"}

        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(m, "check_clocked_in", return_value=True), \
                mock.patch.object(m, "read_local_digest", return_value="(no digest yet)"), \
                mock.patch.object(m, "budget_guard", side_effect=RuntimeError("no model")), \
                mock.patch.object(m, "write_local_digest", return_value="/tmp/security_officer/latest.md"), \
                mock.patch.object(m, "file_digest_issue", side_effect=fake_file_issue):
            out = m.graph.invoke({})

        self.assertTrue(out["report"]["report_only"])
        self.assertEqual(out["report"]["delivery"], "report_only")
        self.assertGreaterEqual(out["report"]["proposals"], 1)  # emitted proposals
        self.assertGreaterEqual(out["report"]["shay_asks"], 1)  # the IDOR HARD-GATE ask
        self.assertIn("IDOR", captured["body"])
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
