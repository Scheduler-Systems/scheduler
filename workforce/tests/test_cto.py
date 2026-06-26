"""Safety tests for the cloud CTO executive agent.

The CTO reports repo/deploy/security posture as a PROPOSE-ONLY digest. It CONSUMES reports
(its own prior digest + per-repo CI recon) rather than re-doing work, so the tests prove the
load-bearing invariants directly on the pure node cores (no checkpointer, no network):
(1) gather is FAIL-SAFE with no GitHub creds — every ``latest_run`` raise is handled per-repo,
the prior digest is read, repos are model-work guarded; (2) the HELD IDOR security item is
ALWAYS present in the gathered/analyzed/composed output; (3) analyze flags red CI + the pending
rollout and tags each escalate_to org|shay; (4) compose always produces a non-empty summary via
the deterministic fallback when the model is unavailable; (5) deliver stays REPORT-ONLY (no
GitHub write, no approval interrupt); (6) the clock-in gate routes a clocked-out run straight to
END without gathering. Run:
    .venv/bin/python -m unittest tests.test_cto -v
"""
import os
import unittest
from unittest import mock

from graphs.exec import cto as m


# --- gather: fail-safe, IDOR present, model-work guarded --------------------------------
class GatherFailSafeTests(unittest.TestCase):
    def test_gather_survives_no_github_creds(self):
        """Every GitHub recon raising => gather returns structured per-repo errors, never raises."""
        def boom(self, repo, branch="main"):
            raise RuntimeError("no GitHub credentials")

        with mock.patch.object(m, "read_local_digest", return_value="(no digest yet)"), \
                mock.patch.object(m.GitHubOps, "latest_run", boom):
            out = m.gather({})

        # Every tech repo got a structured per-repo error — no crash, all repos present.
        self.assertEqual(set(out["deploy"].keys()), set(m.TECH_REPOS))
        for repo in m.TECH_REPOS:
            self.assertEqual(out["deploy"][repo]["error"], "RuntimeError")

    def test_gather_reads_prior_cto_digest(self):
        """gather reads the CTO's prior local digest for continuity (slug 'cto')."""
        with mock.patch.object(m, "read_local_digest", return_value="PRIOR CTO STATE") as rld, \
                mock.patch.object(m.GitHubOps, "latest_run",
                                  lambda self, repo, branch="main": {"status": "completed",
                                                                     "conclusion": "success"}):
            out = m.gather({})
        rld.assert_called_once_with(m.AGENT)
        self.assertEqual(out["prior"], "PRIOR CTO STATE")

    def test_gather_seeds_the_held_idor_security_item(self):
        """The HELD IDOR entitlement rollout is ALWAYS surfaced as an open security item."""
        with mock.patch.object(m, "read_local_digest", return_value="(no digest yet)"), \
                mock.patch.object(m.GitHubOps, "latest_run",
                                  lambda self, repo, branch="main": {"status": "completed",
                                                                     "conclusion": "success"}):
            out = m.gather({})
        ids = {item.get("id") for item in out["security"]}
        self.assertIn("firestore-idor-entitlement-rollout", ids)
        # Surfaced as a held, human-gated (Shay) high-severity item.
        idor = next(i for i in out["security"] if i["id"] == "firestore-idor-entitlement-rollout")
        self.assertEqual(idor["status"], "held")
        self.assertEqual(idor["escalate_to"], "shay")
        # A copy, not the module constant (downstream mutation can't corrupt it).
        self.assertIsNot(out["security"][0], m.IDOR_SECURITY_ITEM)

    def test_gather_guards_every_repo_against_model_work(self):
        """assert_not_model_work is called on every outward repo string (Anthropic terms)."""
        seen = []

        with mock.patch.object(m, "read_local_digest", return_value="(no digest yet)"), \
                mock.patch.object(m, "assert_not_model_work", side_effect=lambda t: seen.append(t)), \
                mock.patch.object(m.GitHubOps, "latest_run",
                                  lambda self, repo, branch="main": {"status": "completed",
                                                                     "conclusion": "success"}):
            m.gather({})

        for repo in m.TECH_REPOS:
            self.assertIn(repo, seen)

    def test_gather_skips_a_denylisted_repo(self):
        """A repo tripping the model-work denylist is SKIPPED (never read/reported)."""
        target = m.TECH_REPOS[0]

        def guard(t):
            if t == target:
                raise m.ModelWorkBlocked("denylisted")

        with mock.patch.object(m, "read_local_digest", return_value="(no digest yet)"), \
                mock.patch.object(m, "assert_not_model_work", side_effect=guard), \
                mock.patch.object(m.GitHubOps, "latest_run",
                                  lambda self, repo, branch="main": {"status": "completed",
                                                                     "conclusion": "success"}):
            out = m.gather({})

        self.assertEqual(out["deploy"][target], {"skipped": "model_work_denylist"})


# --- analyze: red CI + pending rollout, escalation lanes --------------------------------
class AnalyzeTests(unittest.TestCase):
    def _green(self):
        return {r: {"status": "completed", "conclusion": "success"} for r in m.TECH_REPOS}

    def test_idor_item_is_always_a_pending_finding(self):
        """The HELD IDOR item is carried through analyze as a security_pending finding (→ shay)."""
        out = m.analyze({"deploy": self._green(),
                         "security": [dict(m.IDOR_SECURITY_ITEM)]})
        sec = [f for f in out["findings"] if f["kind"] == "security_pending"]
        self.assertEqual(len(sec), 1)
        self.assertEqual(sec[0]["escalate_to"], "shay")
        self.assertIn("IDOR", sec[0]["detail"])

    def test_red_prod_ci_escalates_to_shay(self):
        """A red CI conclusion on a PROD repo => ci_red finding escalated to Shay (irreversible)."""
        deploy = self._green()
        deploy["Scheduler-Systems/scheduler-api"] = {"status": "completed", "conclusion": "failure"}
        out = m.analyze({"deploy": deploy, "security": []})
        red = [f for f in out["findings"] if f["kind"] == "ci_red"]
        self.assertEqual(len(red), 1)
        self.assertEqual(red[0]["repo"], "Scheduler-Systems/scheduler-api")
        self.assertEqual(red[0]["escalate_to"], "shay")

    def test_red_nonprod_ci_resolved_in_org(self):
        """A red CI on the non-prod platform repo is resolved inside the org (escalate_to org)."""
        deploy = self._green()
        deploy["Scheduler-Systems/qa-agent-platform"] = {"status": "completed",
                                                         "conclusion": "failure"}
        out = m.analyze({"deploy": deploy, "security": []})
        red = [f for f in out["findings"] if f["kind"] == "ci_red"]
        self.assertEqual(len(red), 1)
        self.assertEqual(red[0]["escalate_to"], "org")

    def test_unknown_ci_is_org_recon_gap(self):
        """A per-repo recon error => ci_unknown finding (cannot confirm green) escalated to org."""
        deploy = self._green()
        deploy["Scheduler-Systems/scheduler-web"] = {"error": "RuntimeError"}
        out = m.analyze({"deploy": deploy, "security": []})
        unknown = [f for f in out["findings"] if f["kind"] == "ci_unknown"]
        self.assertEqual(len(unknown), 1)
        self.assertEqual(unknown[0]["escalate_to"], "org")

    def test_skipped_repo_is_not_analyzed(self):
        """A denylist-skipped repo produces no finding (never analyzed/reported)."""
        deploy = self._green()
        deploy["Scheduler-Systems/scheduler-ios"] = {"skipped": "model_work_denylist"}
        out = m.analyze({"deploy": deploy, "security": []})
        repos_in_findings = {f.get("repo") for f in out["findings"]}
        self.assertNotIn("Scheduler-Systems/scheduler-ios", repos_in_findings)

    def test_all_green_no_security_yields_no_ci_findings(self):
        out = m.analyze({"deploy": self._green(), "security": []})
        self.assertEqual(out["findings"], [])


# --- propose: propose-only, escalation tags ---------------------------------------------
class ProposeTests(unittest.TestCase):
    def test_idor_proposal_escalates_to_shay(self):
        findings = [{"kind": "security_pending", "repo": None,
                     "detail": "HELD IDOR rollout", "escalate_to": "shay"}]
        out = m.propose({"findings": findings})
        self.assertEqual(len(out["proposals"]), 1)
        self.assertEqual(out["proposals"][0]["escalate_to"], "shay")
        self.assertEqual(out["proposals"][0]["kind"], "security_pending")

    def test_empty_findings_yields_monitor_proposal(self):
        """No findings => a single org-resolved monitoring proposal (never an empty proposal set)."""
        out = m.propose({"findings": []})
        self.assertEqual(len(out["proposals"]), 1)
        self.assertEqual(out["proposals"][0]["kind"], "monitor")
        self.assertEqual(out["proposals"][0]["escalate_to"], "org")

    def test_red_prod_proposal_is_human_gated(self):
        findings = [{"kind": "ci_red", "repo": "Scheduler-Systems/scheduler-web",
                     "detail": "conclusion=failure", "escalate_to": "shay"}]
        out = m.propose({"findings": findings})
        self.assertEqual(out["proposals"][0]["escalate_to"], "shay")
        self.assertIn("human-gated", out["proposals"][0]["action"])


# --- compose: deterministic fallback, IDOR present --------------------------------------
class ComposeFallbackTests(unittest.TestCase):
    def _state(self):
        deploy = {r: {"status": "completed", "conclusion": "success"} for r in m.TECH_REPOS}
        security = [dict(m.IDOR_SECURITY_ITEM)]
        findings = [{"kind": "security_pending", "repo": None,
                     "detail": "HELD IDOR rollout (schedule_acl)", "escalate_to": "shay"}]
        proposals = [{"action": "Ship the HELD IDOR rollout", "kind": "security_pending",
                      "repo": None, "detail": "x", "escalate_to": "shay"}]
        return {"deploy": deploy, "security": security, "findings": findings,
                "proposals": proposals}

    def test_compose_deterministic_when_model_raises(self):
        """budget_guard raising must NOT crash compose — summary is the deterministic report."""
        with mock.patch.object(m, "budget_guard", side_effect=RuntimeError("no API key")):
            out = m.compose(self._state())
        summary = out["summary"]
        self.assertTrue(summary.strip())                 # never empty
        self.assertIn("IDOR", summary)                   # the security item is present
        self.assertIn("RuntimeError", summary)           # fallback labelled, not faked

    def test_compose_uses_model_output_when_available(self):
        fake_model = mock.MagicMock()
        fake_model.invoke.return_value = mock.MagicMock(content="THE CTO POSTURE")
        with mock.patch.object(m, "budget_guard", return_value=fake_model):
            out = m.compose(self._state())
        self.assertEqual(out["summary"], "THE CTO POSTURE")

    def test_compose_falls_back_when_model_returns_empty(self):
        """An empty model response still yields a non-empty deterministic digest with the IDOR item."""
        fake_model = mock.MagicMock()
        fake_model.invoke.return_value = mock.MagicMock(content="")
        with mock.patch.object(m, "budget_guard", return_value=fake_model):
            out = m.compose(self._state())
        self.assertTrue(out["summary"].strip())
        self.assertIn("IDOR", out["summary"])


# --- deliver: report-only ---------------------------------------------------------------
class DeliverReportOnlyTests(unittest.TestCase):
    def test_deliver_is_report_only_and_never_writes(self):
        """deliver must call file_digest_issue with report_only=True and the cto label."""
        captured = {}

        def fake_file_issue(repo, title, body, *, labels=None, report_only=None, **kwargs):
            captured.update(repo=repo, title=title, labels=labels, report_only=report_only)
            # report_only delivery MUST not enter the approval interrupt or call GitHub.
            assert report_only is True, "deliver must stay report-only on probation"
            return {"status": "report_only", "action": "open_issue", "repo": repo}

        # OPS_REPORT_ONLY unset => report-only default True; local digest stubbed (no FS write).
        env = {k: v for k, v in os.environ.items() if k != "OPS_REPORT_ONLY"}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(m, "write_local_digest", return_value="/tmp/x/latest.md"), \
                mock.patch.object(m, "file_digest_issue", side_effect=fake_file_issue):
            out = m.deliver({"summary": "s", "deploy": {}, "security": [],
                             "findings": [], "proposals": []})

        self.assertTrue(captured["report_only"])
        self.assertEqual(captured["repo"], m.DIGEST_REPO)
        self.assertEqual(captured["title"], "CTO: tech + security posture (proposal)")
        self.assertEqual(captured["labels"], ["exec:cto"])
        self.assertEqual(out["report"]["delivery"], "report_only")
        self.assertTrue(out["report_only"])

    def test_report_only_env_can_be_disabled(self):
        """Only an explicit 0/false/no flips report-only off; everything else stays True."""
        with mock.patch.dict(os.environ, {"OPS_REPORT_ONLY": "0"}):
            self.assertFalse(m._report_only())
        with mock.patch.dict(os.environ, {"OPS_REPORT_ONLY": "false"}):
            self.assertFalse(m._report_only())
        with mock.patch.dict(os.environ, {"OPS_REPORT_ONLY": "1"}):
            self.assertTrue(m._report_only())
        env = {k: v for k, v in os.environ.items() if k != "OPS_REPORT_ONLY"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertTrue(m._report_only())  # unset => report-only


# --- budget gate / clock-in: never hangs, ends on clock-out -----------------------------
class BudgetGateTests(unittest.TestCase):
    def test_clocked_out_ends_without_gather(self):
        """Clocked out: budget_gate reports + governance, the route goes to END (not gather)."""
        with mock.patch.object(m, "check_clocked_in", return_value=False), \
                mock.patch.object(m, "governance_capture") as gov, \
                mock.patch.object(m, "read_local_digest",
                                  side_effect=AssertionError("gather must not run")):
            out = m.budget_gate({})
            route = m._budget_route({})

        self.assertEqual(out["report"], {"clocked_in": False})
        self.assertEqual(route, "clocked_out")
        gov.assert_called_once()
        # governance capture on the clocked-out path is report-only.
        self.assertTrue(gov.call_args[0][1]["report_only"])

    def test_clocked_in_proceeds_to_gather(self):
        with mock.patch.object(m, "check_clocked_in", return_value=True):
            out = m.budget_gate({})
            route = m._budget_route({})
        self.assertEqual(out, {})
        self.assertEqual(route, "gather")


# --- finalize ----------------------------------------------------------------------------
class FinalizeTests(unittest.TestCase):
    def test_finalize_captures_report_only_governance(self):
        proposals = [
            {"escalate_to": "shay", "action": "x"},
            {"escalate_to": "org", "action": "y"},
        ]
        with mock.patch.object(m, "governance_capture") as gov:
            out = m.finalize({"deploy": {"a": {}, "b": {}}, "findings": [{"k": 1}],
                              "proposals": proposals,
                              "report": {"delivery": "report_only", "digest": "/tmp/d"}})
        self.assertTrue(out["report"]["report_only"])
        self.assertEqual(out["report"]["delivery"], "report_only")
        self.assertEqual(out["report"]["repos"], 2)
        self.assertEqual(out["report"]["shay_asks"], 1)  # only the capital/irreversible ask
        gov.assert_called_once()
        self.assertTrue(gov.call_args[0][1]["report_only"])


# --- end-to-end graph: unattended, no creds, never hangs --------------------------------
class GraphInvokeTests(unittest.TestCase):
    def test_graph_compiles_without_checkpointer(self):
        self.assertIsNotNone(m.graph)

    def test_full_run_report_only_no_creds(self):
        """Unattended, no creds: the run completes report-only, never writes, never hangs, and
        the HELD IDOR item rides through into the digest body."""
        def boom(self, repo, branch="main"):
            raise RuntimeError("no GitHub credentials")

        env = {k: v for k, v in os.environ.items() if k != "OPS_REPORT_ONLY"}
        captured = {}

        def fake_file_issue(repo, title, body, *, labels=None, report_only=None, **kwargs):
            captured.update(body=body, report_only=report_only, labels=labels)
            return {"status": "report_only"}

        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(m, "check_clocked_in", return_value=True), \
                mock.patch.object(m, "read_local_digest", return_value="(no digest yet)"), \
                mock.patch.object(m.GitHubOps, "latest_run", boom), \
                mock.patch.object(m, "budget_guard", side_effect=RuntimeError("no model")), \
                mock.patch.object(m, "write_local_digest", return_value="/tmp/cto/latest.md"), \
                mock.patch.object(m, "file_digest_issue", side_effect=fake_file_issue):
            out = m.graph.invoke({})

        self.assertTrue(out["report"]["report_only"])
        self.assertEqual(out["report"]["repos"], len(m.TECH_REPOS))
        self.assertEqual(out["report"]["delivery"], "report_only")
        # The HELD IDOR item is a Shay-escalated proposal in the terminal report.
        self.assertGreaterEqual(out["report"]["shay_asks"], 1)
        # The digest body carried the IDOR item; delivery stayed report-only (no hang/write).
        self.assertIn("IDOR", captured["body"])
        self.assertTrue(captured["report_only"])
        self.assertEqual(captured["labels"], ["exec:cto"])

    def test_clocked_out_graph_ends_without_work(self):
        with mock.patch.object(m, "check_clocked_in", return_value=False), \
                mock.patch.object(m, "read_local_digest") as rld, \
                mock.patch.object(m, "file_digest_issue") as fd:
            out = m.graph.invoke({})
        rld.assert_not_called()   # no prior-digest read on the clocked-out path
        fd.assert_not_called()    # no delivery on the clocked-out path
        self.assertEqual(out["report"], {"clocked_in": False})


if __name__ == "__main__":
    unittest.main()
