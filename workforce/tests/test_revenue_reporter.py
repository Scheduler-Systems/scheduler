"""Safety tests for the cloud revenue_reporter agent.

It reports money (RevenueCat) + deploy state + pipeline as a weekly digest, so the tests
prove the load-bearing invariants directly on the pure node cores (no checkpointer, no
network): (1) gather is FAIL-SAFE with no RC/GitHub creds; (2) compose always produces a
non-empty summary via the deterministic fallback when the model is unavailable; (3) deliver
stays REPORT-ONLY (no GitHub write, no approval interrupt); (4) the clock-in gate routes a
clocked-out run straight to END without gathering. Run:
    .venv/bin/python -m unittest tests.test_revenue_reporter -v
"""
import os
import threading
import time
import unittest
from unittest import mock

from graphs.ops import revenue_reporter as m


class GatherFailSafeTests(unittest.TestCase):
    def test_gather_survives_no_rc_and_no_github_creds(self):
        """No RC key + every GitHub read raising => gather returns dicts and never raises."""
        def boom(self, repo, branch="main"):
            raise RuntimeError("no GitHub credentials")

        with mock.patch.object(
            m.revenuecat, "metrics_overview",
            return_value={"ok": False, "metrics": {}, "raw": [], "error": "key not set"},
        ), mock.patch.object(m.GitHubOps, "latest_run", boom), \
                mock.patch.object(m.work_board, "fetch_open_issues",
                                  side_effect=RuntimeError("gh missing")):
            out = m.gather({})

        # RC degraded but structured.
        self.assertFalse(out["rc"]["ok"])
        # Every product repo got a structured per-repo error — no crash, all repos present.
        self.assertEqual(set(out["deploy"].keys()), set(m.SCHEDULER_REPOS))
        for repo in m.SCHEDULER_REPOS:
            self.assertEqual(out["deploy"][repo]["error"], "RuntimeError")
        # Pipeline degraded to the honest unavailable note.
        self.assertEqual(out["pipeline"], {"note": "unavailable"})

    def test_gather_never_hangs_on_a_stalled_gh_subprocess(self):
        """NEVER-HANGS: work_board.fetch_open_issues shells out to `gh` with no subprocess
        timeout. If gh stalls (network/auth-prompt), gather must still return promptly via
        the wall-clock-bounded pipeline recon, degrading pipeline to {"note": "unavailable"}.
        """
        release = threading.Event()

        def stalled_fetch():
            # Stand-in for a wedged gh subprocess: blocks until the test releases it so the
            # abandoned worker thread can exit cleanly (no leaked sleep).
            release.wait(timeout=10)
            return []

        with mock.patch.object(m.revenuecat, "metrics_overview",
                               return_value={"ok": False, "metrics": {}, "error": "x"}), \
                mock.patch.object(m.GitHubOps, "latest_run",
                                  lambda self, repo, branch="main": {"status": None}), \
                mock.patch.object(m.work_board, "fetch_open_issues", side_effect=stalled_fetch), \
                mock.patch.object(m, "_pipeline_timeout", return_value=0.2):
            start = time.time()
            try:
                out = m.gather({})
            finally:
                release.set()  # let the abandoned worker finish
            elapsed = time.time() - start

        # gather returned well under the 10s stall — it did NOT block on the wedged subprocess.
        self.assertLess(elapsed, 3.0, "gather hung on a stalled gh subprocess")
        self.assertEqual(out["pipeline"], {"note": "unavailable"})
        # The rest of gather still produced structured results.
        self.assertEqual(set(out["deploy"].keys()), set(m.SCHEDULER_REPOS))

    def test_fetch_pipeline_bounds_a_stalled_call(self):
        """_fetch_pipeline returns promptly and degrades when the underlying call stalls."""
        release = threading.Event()

        def stalled():
            release.wait(timeout=10)
            return []

        with mock.patch.object(m.work_board, "fetch_open_issues", side_effect=stalled), \
                mock.patch.object(m, "_pipeline_timeout", return_value=0.2):
            start = time.time()
            try:
                result = m._fetch_pipeline()
            finally:
                release.set()
            elapsed = time.time() - start

        self.assertLess(elapsed, 3.0)
        self.assertEqual(result, {"note": "unavailable"})

    def test_fetch_pipeline_counts_when_fast(self):
        """When the call returns quickly, _fetch_pipeline aggregates per-repo counts."""
        class _Item:
            def __init__(self, repo):
                self.repo = repo

        items = [_Item("a"), _Item("a"), _Item("b")]
        with mock.patch.object(m.work_board, "fetch_open_issues", return_value=items):
            result = m._fetch_pipeline()
        self.assertEqual(result["open_items"], 3)
        self.assertEqual(result["by_repo"], {"a": 2, "b": 1})

    def test_gather_guards_every_repo_against_model_work(self):
        """assert_not_model_work is called on every outward repo string (Anthropic terms)."""
        seen = []

        def record(target):
            seen.append(target)

        with mock.patch.object(m, "assert_not_model_work", side_effect=record), \
                mock.patch.object(m.revenuecat, "metrics_overview",
                                  return_value={"ok": False, "metrics": {}, "error": "x"}), \
                mock.patch.object(m.GitHubOps, "latest_run",
                                  lambda self, repo, branch="main": {"status": "completed"}), \
                mock.patch.object(m.work_board, "fetch_open_issues", return_value=[]):
            m.gather({})

        for repo in m.SCHEDULER_REPOS:
            self.assertIn(repo, seen)


class ComposeFallbackTests(unittest.TestCase):
    def test_compose_deterministic_when_model_raises(self):
        """budget_guard raising must NOT crash compose — summary is the deterministic report."""
        rc = {"ok": True, "metrics": {"mrr": 1234, "active_subscriptions": 42}, "raw": []}
        deploy = {r: {"status": "completed", "conclusion": "success"} for r in m.SCHEDULER_REPOS}
        pipeline = {"open_items": 7, "by_repo": {}}

        with mock.patch.object(m, "budget_guard", side_effect=RuntimeError("no API key")):
            out = m.compose({"rc": rc, "deploy": deploy, "pipeline": pipeline})

        summary = out["summary"]
        self.assertTrue(summary.strip())                 # never empty
        self.assertIn("mrr", summary)                    # built from the gathered facts
        self.assertIn("RuntimeError", summary)           # fallback labelled, not faked

    def test_compose_uses_model_output_when_available(self):
        """When the model works, its phrasing is used (still fail-safe wrapped)."""
        fake_model = mock.MagicMock()
        fake_model.invoke.return_value = mock.MagicMock(content="THE WEEKLY SUMMARY")

        with mock.patch.object(m, "budget_guard", return_value=fake_model):
            out = m.compose({"rc": {"ok": True, "metrics": {}}, "deploy": {}, "pipeline": {}})

        self.assertEqual(out["summary"], "THE WEEKLY SUMMARY")

    def test_compose_falls_back_when_model_returns_empty(self):
        """An empty model response still yields a non-empty deterministic digest."""
        fake_model = mock.MagicMock()
        fake_model.invoke.return_value = mock.MagicMock(content="")

        with mock.patch.object(m, "budget_guard", return_value=fake_model):
            out = m.compose({"rc": {"ok": False, "error": "x"}, "deploy": {}, "pipeline": {}})

        self.assertTrue(out["summary"].strip())


class DeliverReportOnlyTests(unittest.TestCase):
    def test_deliver_is_report_only_and_never_writes(self):
        """deliver must call file_digest_issue with report_only=True and write nothing live."""
        captured = {}

        def fake_file_issue(repo, title, body, *, labels=None, report_only=None, **kwargs):
            captured["repo"] = repo
            captured["labels"] = labels
            captured["report_only"] = report_only
            # report_only delivery MUST not enter the approval interrupt or call GitHub.
            assert report_only is True, "deliver must stay report-only on probation"
            return {"status": "report_only", "action": "open_issue", "repo": repo}

        # OPS_REPORT_ONLY unset => report-only default True; local digest stubbed (no FS write).
        env = {k: v for k, v in os.environ.items() if k != "OPS_REPORT_ONLY"}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(m, "write_local_digest", return_value="/tmp/x/latest.md"), \
                mock.patch.object(m, "file_digest_issue", side_effect=fake_file_issue):
            out = m.deliver({"summary": "s", "rc": {"ok": True, "metrics": {}},
                             "deploy": {}, "pipeline": {}})

        self.assertTrue(captured["report_only"])
        self.assertEqual(captured["repo"], m.DIGEST_REPO)
        self.assertEqual(captured["labels"], ["report:weekly"])
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


class BudgetGateTests(unittest.TestCase):
    def test_clocked_out_ends_without_gather(self):
        """Clocked out: budget_gate reports + governance, the route goes to END (not gather)."""
        with mock.patch.object(m, "check_clocked_in", return_value=False), \
                mock.patch.object(m, "governance_capture") as gov, \
                mock.patch.object(m.revenuecat, "metrics_overview",
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


class FinalizeTests(unittest.TestCase):
    def test_finalize_captures_report_only_governance(self):
        with mock.patch.object(m, "governance_capture") as gov:
            out = m.finalize({"rc": {"ok": True}, "deploy": {"a": {}, "b": {}},
                              "report": {"delivery": "report_only", "digest": "/tmp/d"}})
        self.assertTrue(out["report"]["report_only"])
        self.assertEqual(out["report"]["delivery"], "report_only")
        self.assertEqual(out["report"]["repos"], 2)
        gov.assert_called_once()
        self.assertTrue(gov.call_args[0][1]["report_only"])


class GraphCompileTests(unittest.TestCase):
    def test_graph_compiles_without_checkpointer(self):
        self.assertIsNotNone(m.graph)


if __name__ == "__main__":
    unittest.main()
