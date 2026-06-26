"""Safety tests for Lennox — the AI / LangSmith Platform Specialist (PROPOSE-ONLY).

Lennox OWNS the LangSmith runtime but is read-only + propose-only: it reads the eval gate,
the feedback ledger, deployment revisions / cron health, and cost vs budget, and emits
PROPOSALS (rollback / block-prompt / cost / health) — it NEVER deploys, creates a cron,
mutates config, or moves money. These tests prove the load-bearing invariants on the pure
node cores (no checkpointer, no network), all MOCKED:

  (1) the reads DEGRADE to "unverifiable" with no creds (like store_health_checker) and the
      run never raises;
  (2) Lennox NEVER calls a deploy / cron-create / config-mutation path — there is none reachable;
  (3) assert_not_model_work REFUSES a model-dev target (fail closed) — the model summary is not
      sent and no model-dev string is judged;
  (4) the clock-in kill-switch ends the run without any read/deliver;
  (5) the digest routes through file_digest_record(agent="platform_specialist",
      record_kind="platform-health"), report-only;
  (6) analyze flags an eval regression / missing cron / over-budget and tags escalate_to org|shay.

Run: .venv/bin/python -m unittest tests.test_platform_specialist -v
"""
import os
import unittest
from unittest import mock

from graphs.platform import platform_specialist as m


# --- the LangSmith reads degrade fail-safe (no creds => unverifiable) --------------------
class FailSafeReadsTests(unittest.TestCase):
    def test_feedback_unverifiable_without_client(self):
        out = m.read_feedback_ledger(client=None)
        self.assertFalse(out["ok"])
        self.assertIn("unverifiable", out)

    def test_deployment_unverifiable_without_creds(self):
        out = m.read_deployment_state(client=None)
        self.assertFalse(out["ok"])
        self.assertIn("unverifiable", out)

    def test_feedback_read_failure_is_unverifiable_not_crash(self):
        client = mock.MagicMock()
        client.list_feedback.side_effect = RuntimeError("offline")
        out = m.read_feedback_ledger(client=client)
        self.assertFalse(out["ok"])
        self.assertIn("unverifiable", out)

    def test_feedback_mean_computed_from_scores(self):
        client = mock.MagicMock()
        client.list_feedback.return_value = [
            {"key": "pii_leakage", "score": 1.0},
            {"key": "pii_leakage", "score": 0.0},
            {"key": "prompt_injection", "score": 1.0},
        ]
        out = m.read_feedback_ledger(client=client)
        self.assertTrue(out["ok"])
        self.assertEqual(out["n"], 3)
        self.assertAlmostEqual(out["mean"], (1.0 + 0.0 + 1.0) / 3)
        self.assertAlmostEqual(out["by_key"]["pii_leakage"], 0.5)

    def test_deployment_reads_assistants_and_crons(self):
        client = mock.MagicMock()
        client.assistants_search.return_value = [{"graph_id": "daily_digest"}, {"graph_id": "ceo"}]
        client.crons_search.return_value = [{"assistant_id": "daily_digest", "schedule": "0 8 * * *"}]
        out = m.read_deployment_state(client=client)
        self.assertTrue(out["ok"])
        self.assertEqual(set(out["assistants"]), {"daily_digest", "ceo"})
        self.assertEqual(out["crons"], [{"assistant": "daily_digest", "schedule": "0 8 * * *"}])


# --- gather: fully fail-safe, never raises, never hits a write path ----------------------
class GatherFailSafeTests(unittest.TestCase):
    def test_gather_survives_no_creds(self):
        """gather completes with all surfaces unverifiable-or-degraded, never raises."""
        with mock.patch.object(m, "read_local_digest", return_value="(no digest yet)"), \
                mock.patch.object(m, "_langsmith_client", return_value=None), \
                mock.patch.object(m, "read_deployment_state",
                                  return_value={"ok": False, "unverifiable": "no creds"}), \
                mock.patch.object(m, "read_eval_health",
                                  return_value={"ok": False, "unverifiable": "no eval"}):
            out = m.gather({})
        self.assertIn("surface", out)
        self.assertFalse(out["surface"]["eval"]["ok"])
        self.assertFalse(out["surface"]["deployment"]["ok"])


# --- analyze: regression / missing cron / over-budget, escalation lanes ------------------
class AnalyzeTests(unittest.TestCase):
    def _healthy_surface(self):
        return {
            "eval": {"ok": True, "aggregate": 0.9, "n_scored": 5, "n_total": 5},
            "feedback": {"ok": True, "n": 4, "mean": 0.95, "by_key": {}},
            "deployment": {"ok": True, "assistants": ["daily_digest"],
                           "crons": [{"assistant": "daily_digest", "schedule": "0 8 * * *"}]},
            "cost": {"ok": True, "alerts": []},
        }

    def test_healthy_surface_yields_no_findings(self):
        out = m.analyze({"surface": self._healthy_surface()})
        self.assertEqual(out["findings"], [])

    def test_eval_regression_escalates_to_shay(self):
        surface = self._healthy_surface()
        surface["eval"]["aggregate"] = 0.2  # below the 0.60 floor
        out = m.analyze({"surface": surface})
        regs = [f for f in out["findings"] if f["kind"] == "eval_regression"]
        self.assertEqual(len(regs), 1)
        self.assertEqual(regs[0]["severity"], "high")
        self.assertEqual(regs[0]["escalate_to"], "shay")

    def test_eval_unverifiable_is_org_recon_gap(self):
        surface = self._healthy_surface()
        surface["eval"] = {"ok": False, "unverifiable": "no creds"}
        out = m.analyze({"surface": surface})
        unv = [f for f in out["findings"] if f["kind"] == "eval_unverifiable"]
        self.assertEqual(len(unv), 1)
        self.assertEqual(unv[0]["escalate_to"], "org")

    def test_missing_cron_for_deployed_agent_is_flagged_org(self):
        surface = self._healthy_surface()
        # daily_digest is deployed but has NO cron registered
        surface["deployment"] = {"ok": True, "assistants": ["daily_digest"], "crons": []}
        out = m.analyze({"surface": surface})
        cm = [f for f in out["findings"] if f["kind"] == "cron_missing"]
        self.assertEqual(len(cm), 1)
        self.assertIn("daily_digest", cm[0]["detail"])
        self.assertEqual(cm[0]["escalate_to"], "org")

    def test_no_cron_flag_for_undeployed_agent(self):
        """If an EXPECTED cron agent is not even deployed, no missing-cron flag (not its fault)."""
        surface = self._healthy_surface()
        surface["deployment"] = {"ok": True, "assistants": [], "crons": []}
        out = m.analyze({"surface": surface})
        self.assertEqual([f for f in out["findings"] if f["kind"] == "cron_missing"], [])

    def test_feedback_regression_escalates_to_shay(self):
        surface = self._healthy_surface()
        surface["feedback"] = {"ok": True, "n": 10, "mean": 0.3, "by_key": {}}
        out = m.analyze({"surface": surface})
        fr = [f for f in out["findings"] if f["kind"] == "feedback_regression"]
        self.assertEqual(len(fr), 1)
        self.assertEqual(fr[0]["escalate_to"], "shay")

    def test_critical_cost_alert_escalates_to_shay(self):
        surface = self._healthy_surface()
        surface["cost"] = {"ok": True, "alerts": [
            {"level": "critical", "agent": "FLEET", "message": "FLEET over budget"}]}
        out = m.analyze({"surface": surface})
        cost = [f for f in out["findings"] if f["kind"] == "cost_over_budget"]
        self.assertEqual(len(cost), 1)
        self.assertEqual(cost[0]["severity"], "high")
        self.assertEqual(cost[0]["escalate_to"], "shay")

    def test_warn_cost_alert_is_org(self):
        surface = self._healthy_surface()
        surface["cost"] = {"ok": True, "alerts": [
            {"level": "warn", "agent": "ceo", "message": "ceo near budget"}]}
        out = m.analyze({"surface": surface})
        cost = [f for f in out["findings"] if f["kind"] == "cost_over_budget"]
        self.assertEqual(cost[0]["escalate_to"], "org")


# --- propose: propose-only, never an empty set, escalation tags --------------------------
class ProposeTests(unittest.TestCase):
    def test_eval_regression_proposal_is_human_gated(self):
        findings = [{"kind": "eval_regression", "severity": "high",
                     "detail": "x", "escalate_to": "shay"}]
        out = m.propose({"findings": findings})
        self.assertEqual(out["proposals"][0]["escalate_to"], "shay")
        self.assertIn("roll back", out["proposals"][0]["action"].lower())

    def test_empty_findings_yields_monitor_proposal(self):
        out = m.propose({"findings": []})
        self.assertEqual(len(out["proposals"]), 1)
        self.assertEqual(out["proposals"][0]["kind"], "monitor")
        self.assertEqual(out["proposals"][0]["escalate_to"], "org")

    def test_cron_missing_proposal_is_org(self):
        findings = [{"kind": "cron_missing", "severity": "medium",
                     "detail": "x", "escalate_to": "org"}]
        out = m.propose({"findings": findings})
        self.assertEqual(out["proposals"][0]["escalate_to"], "org")
        self.assertIn("setup_crons", out["proposals"][0]["action"])


# --- compose: deterministic fallback + Anthropic-terms fail-closed -----------------------
class ComposeTests(unittest.TestCase):
    def _state(self, surface=None):
        surface = surface or {"eval": {"ok": True, "aggregate": 0.9, "n_scored": 5, "n_total": 5},
                              "feedback": {"ok": False, "unverifiable": "no creds"},
                              "deployment": {"ok": False, "unverifiable": "no creds"},
                              "cost": {"ok": True, "alerts": []}}
        return {"surface": surface, "findings": [], "proposals": [
            {"action": "monitor", "kind": "monitor", "severity": "ok",
             "detail": "ok", "escalate_to": "org"}]}

    def test_compose_deterministic_when_model_raises(self):
        with mock.patch.object(m, "budget_guard", side_effect=RuntimeError("no API key")):
            out = m.compose(self._state())
        self.assertTrue(out["summary"].strip())
        self.assertIn("RuntimeError", out["summary"])
        self.assertIn(out["severity"], ("ok", "medium", "high"))

    def test_compose_uses_model_when_available(self):
        fake_model = mock.MagicMock()
        fake_model.invoke.return_value = mock.MagicMock(content="THE PLATFORM HEALTH")
        with mock.patch.object(m, "budget_guard", return_value=fake_model):
            out = m.compose(self._state())
        self.assertEqual(out["summary"], "THE PLATFORM HEALTH")

    def test_compose_refuses_model_on_model_dev_content_fail_closed(self):
        """If the gathered facts carry a model-dev string, the paid model is NEVER called."""
        # Inject model-dev content into a finding detail so it lands in the deterministic facts.
        state = self._state()
        state["findings"] = [{"kind": "x", "severity": "high",
                              "detail": "fine-tune the gal-model classifier",
                              "escalate_to": "org"}]
        called = {"model": False}

        def boom_model(*a, **k):
            called["model"] = True
            raise AssertionError("model must NOT be called on model-dev content")

        with mock.patch.object(m, "budget_guard", side_effect=boom_model):
            out = m.compose(state)
        self.assertFalse(called["model"])                 # model never invoked
        self.assertIn("REFUSED", out["summary"])          # fail-closed, labelled
        self.assertIn("ModelWorkBlocked", out["summary"])

    def test_severity_high_when_any_high_finding(self):
        state = self._state()
        state["findings"] = [{"kind": "eval_regression", "severity": "high",
                              "detail": "clean detail", "escalate_to": "shay"}]
        with mock.patch.object(m, "budget_guard", side_effect=RuntimeError("no key")):
            out = m.compose(state)
        self.assertEqual(out["severity"], "high")


# --- deliver: report-only, routes through file_digest_record, NO mutation path -----------
class DeliverReportOnlyTests(unittest.TestCase):
    def test_deliver_routes_through_file_digest_record_report_only(self):
        captured = {}

        def fake_record(repo, title, body, *, agent=None, record_kind=None, labels=None,
                        report_only=None, slack_title=None, **kw):
            captured.update(repo=repo, agent=agent, record_kind=record_kind,
                            report_only=report_only, labels=labels, title=title)
            assert report_only is True, "deliver must stay report-only on probation"
            return {"status": "report_only"}

        env = {k: v for k, v in os.environ.items() if k != "OPS_REPORT_ONLY"}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(m, "write_local_digest", return_value="/tmp/x/latest.md"), \
                mock.patch.object(m, "file_digest_record", side_effect=fake_record):
            out = m.deliver({"summary": "s", "severity": "ok", "surface": {},
                             "findings": [], "proposals": []})

        self.assertTrue(captured["report_only"])
        self.assertEqual(captured["repo"], m.DIGEST_REPO)
        self.assertEqual(captured["agent"], "platform_specialist")
        self.assertEqual(captured["record_kind"], "platform-health")
        self.assertEqual(out["report"]["delivery"], "report_only")
        self.assertTrue(out["report_only"])

    def test_high_severity_adds_human_required_label(self):
        captured = {}

        def fake_record(repo, title, body, *, agent=None, record_kind=None, labels=None,
                        report_only=None, slack_title=None, **kw):
            captured["labels"] = labels
            return {"status": "report_only"}

        with mock.patch.object(m, "write_local_digest", return_value="/tmp/x/latest.md"), \
                mock.patch.object(m, "file_digest_record", side_effect=fake_record):
            m.deliver({"summary": "s", "severity": "high", "surface": {},
                       "findings": [], "proposals": []})
        self.assertIn("gate:human-required", captured["labels"])

    def test_report_only_env_toggle(self):
        with mock.patch.dict(os.environ, {"OPS_REPORT_ONLY": "0"}):
            self.assertFalse(m._report_only())
        env = {k: v for k, v in os.environ.items() if k != "OPS_REPORT_ONLY"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertTrue(m._report_only())


# --- budget gate / clock-in kill-switch: ends without work -------------------------------
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


# --- end-to-end: unattended, no creds, never hangs, never mutates ------------------------
class GraphInvokeTests(unittest.TestCase):
    def test_graph_compiles_without_checkpointer(self):
        self.assertIsNotNone(m.graph)

    def test_full_run_report_only_no_creds_no_mutation(self):
        """Unattended, no creds: completes report-only, never writes config/deploys, never hangs.

        Critically: there is NO deploy / cron-create / config-mutation function on the module to
        even call — the only delivery is file_digest_record (a durable RECORD). We assert it is
        report-only and that the run terminates with a verdict.
        """
        env = {k: v for k, v in os.environ.items() if k != "OPS_REPORT_ONLY"}
        captured = {}

        def fake_record(repo, title, body, *, agent=None, record_kind=None, report_only=None, **kw):
            captured.update(report_only=report_only, agent=agent, record_kind=record_kind, body=body)
            return {"status": "report_only"}

        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(m, "check_clocked_in", return_value=True), \
                mock.patch.object(m, "read_local_digest", return_value="(no digest yet)"), \
                mock.patch.object(m, "_langsmith_client", return_value=None), \
                mock.patch.object(m, "read_deployment_state",
                                  return_value={"ok": False, "unverifiable": "no creds"}), \
                mock.patch.object(m, "read_eval_health",
                                  return_value={"ok": False, "unverifiable": "no eval"}), \
                mock.patch.object(m, "budget_guard", side_effect=RuntimeError("no model")), \
                mock.patch.object(m, "write_local_digest", return_value="/tmp/p/latest.md"), \
                mock.patch.object(m, "file_digest_record", side_effect=fake_record):
            out = m.graph.invoke({})

        self.assertTrue(out["report"]["report_only"])
        self.assertEqual(captured["agent"], "platform_specialist")
        self.assertEqual(captured["record_kind"], "platform-health")
        self.assertTrue(captured["report_only"])
        self.assertEqual(out["report"]["delivery"], "report_only")

    def test_clocked_out_graph_ends_without_work(self):
        with mock.patch.object(m, "check_clocked_in", return_value=False), \
                mock.patch.object(m, "read_local_digest") as rld, \
                mock.patch.object(m, "file_digest_record") as fd:
            out = m.graph.invoke({})
        rld.assert_not_called()
        fd.assert_not_called()
        self.assertEqual(out["report"], {"clocked_in": False})

    def test_no_deploy_or_config_mutation_function_exists(self):
        """Lennox has NO deploy / cron-create / config-write entry point (read+propose only)."""
        forbidden = ("deploy", "create_cron", "crons_create", "rollback_revision",
                     "mutate_config", "set_retention", "apply_config", "push_revision")
        for name in forbidden:
            self.assertFalse(hasattr(m, name), f"Lennox must NOT expose a mutation path: {name}")


if __name__ == "__main__":
    unittest.main()
