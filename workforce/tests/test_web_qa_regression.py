"""Tests for web_qa_regression graph. stdlib unittest, no network, no real model calls.

Exercises the REAL hardened recon/verdict/report logic (in-progress skip, unconfigured vs
error, NEW-vs-still, open-issue dedup) by mocking only the GitHub client + model seams.

Run: PYTHONPATH=. .venv/bin/python -m unittest tests.test_web_qa_regression -v
"""
import importlib.util
import os
import pathlib
import unittest
from unittest import mock

_SPEC = importlib.util.spec_from_file_location(
    "web_qa_regression", pathlib.Path("graphs/qa/web_qa_regression.py")
)
wqr = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(wqr)

from agent_toolkit import github_ops as go


def _run(status, conclusion, *, name="CI", path="gate.yml", head_sha="abc", run_id=1, html_url="https://x/run/1"):
    """Build a fake pygithub WorkflowRun."""
    return mock.Mock(
        status=status, conclusion=conclusion, name=name, path=path,
        head_sha=head_sha, id=run_id, html_url=html_url,
    )


def _client_returning(runs, issues=None):
    """A fake GitHub client whose repo yields ``runs`` and (optionally) ``issues``."""
    repo = mock.Mock()
    repo.get_workflow_runs.return_value = runs
    repo.get_issues.return_value = issues or []
    client = mock.Mock()
    client.get_repo.return_value = repo
    return client


class CompletedRunSelectionTests(unittest.TestCase):
    """The core fix: an in-progress run must NEVER read as green."""

    def test_in_progress_run_is_skipped_not_green(self):
        # Newest run is in-progress (conclusion=None); older completed run failed.
        runs = [
            _run("in_progress", None, head_sha="new", run_id=2),
            _run("completed", "failure", head_sha="old", run_id=1),
        ]
        client = _client_returning(runs)
        with mock.patch.object(go.GitHubOps, "_client", return_value=client):
            out = wqr._latest_completed_run("Scheduler-Systems/scheduler-web", "main")
        self.assertEqual(out["conclusion"], "failure")
        self.assertEqual(out["head_sha"], "old")

    def test_select_prefers_ci_workflow_when_matching(self):
        runs = [
            _run("completed", "success", path="docs.yml", head_sha="d"),
            _run("completed", "failure", path="gate.yml", head_sha="g"),
        ]
        chosen = wqr._select_completed_run(runs, "gate.yml")
        self.assertEqual(chosen.conclusion, "failure")
        self.assertEqual(chosen.head_sha, "g")

    def test_select_falls_back_to_newest_completed_when_no_hint_match(self):
        runs = [
            _run("completed", "success", path="docs.yml", head_sha="d"),
            _run("completed", "failure", path="lint.yml", head_sha="l"),
        ]
        chosen = wqr._select_completed_run(runs, "gate.yml")
        self.assertEqual(chosen.head_sha, "d")  # newest completed, hint not found

    def test_no_completed_run_returns_none_conclusion(self):
        runs = [_run("queued", None), _run("in_progress", None)]
        client = _client_returning(runs)
        with mock.patch.object(go.GitHubOps, "_client", return_value=client):
            out = wqr._latest_completed_run("Scheduler-Systems/scheduler-web", "main")
        self.assertIsNone(out["conclusion"])

    def test_latest_run_respects_allow_list(self):
        with self.assertRaises(go.GitHubWriteBlocked):
            wqr._latest_completed_run("Scheduler-Systems/some-random-repo", "main")

    def test_transient_error_retries_then_raises(self):
        client = mock.Mock()
        client.get_repo.side_effect = RuntimeError("503 transient")
        with mock.patch.object(go.GitHubOps, "_client", return_value=client), \
                mock.patch.object(wqr.time, "sleep"):  # no real backoff sleep in tests
            with self.assertRaises(RuntimeError):
                wqr._latest_completed_run("Scheduler-Systems/scheduler-web", "main")
        # bounded retry: _client called _READ_RETRIES times
        self.assertEqual(client.get_repo.call_count, wqr._READ_RETRIES)


class CheckVerdictTests(unittest.TestCase):
    def test_in_progress_only_yields_unknown_not_green(self):
        runs = [_run("in_progress", None)]
        client = _client_returning(runs)
        with mock.patch.object(go.GitHubOps, "_client", return_value=client):
            chk = wqr.check({"target": "Scheduler-Systems/scheduler-web", "branch": "main"})
        self.assertEqual(chk["conclusion"], "")
        v = wqr.verdict({"target": "Scheduler-Systems/scheduler-web", "branch": "main", **chk})
        self.assertEqual(v["verdict"], "unknown")
        self.assertNotEqual(v["verdict"], "green")

    def test_unconfigured_token_is_not_an_error_verdict(self):
        def _raise(*a, **k):
            raise go.GitHubNotConfigured("no token in env")

        with mock.patch.object(go.GitHubOps, "_client", side_effect=_raise):
            chk = wqr.check({"target": "Scheduler-Systems/scheduler-web", "branch": "main"})
        self.assertEqual(chk["conclusion"], "unconfigured")
        v = wqr.verdict({"target": "Scheduler-Systems/scheduler-web", "branch": "main", **chk})
        self.assertEqual(v["verdict"], "unconfigured")

    def test_genuine_recon_failure_is_error(self):
        with mock.patch.object(wqr, "_latest_completed_run", side_effect=ValueError("boom")):
            out = wqr.check({"target": "Scheduler-Systems/scheduler-web", "branch": "main"})
        self.assertTrue(out["conclusion"].startswith("error:"))
        v = wqr.verdict({"target": "Scheduler-Systems/scheduler-web", "branch": "main", **out})
        self.assertEqual(v["verdict"], "error")

    def test_new_vs_still_failing(self):
        base = {"target": "Scheduler-Systems/scheduler-web", "branch": "main",
                "conclusion": "failure", "head_sha": "sha-2"}
        with mock.patch.object(wqr, "_triage_regression", return_value="t"):
            v_new = wqr.verdict({**base, "last_reported_sha": "sha-1"})
            v_same = wqr.verdict({**base, "last_reported_sha": "sha-2"})
        self.assertTrue(v_new["is_new"])
        self.assertFalse(v_same["is_new"])


class ReportDedupTests(unittest.TestCase):
    def test_dedup_skips_when_open_issue_exists(self):
        existing = mock.Mock(title="QA: regression on main", number=42, pull_request=None)
        client = _client_returning([], issues=[existing])
        with mock.patch.object(go.GitHubOps, "_client", return_value=client), \
                mock.patch.object(wqr.GitHubOps, "open_issue") as open_issue:
            out = wqr.report({
                "target": "Scheduler-Systems/scheduler-web", "branch": "main",
                "verdict": "REGRESSION", "is_new": True, "head_sha": "z",
            })
        self.assertEqual(out["issue"]["status"], "deduped")
        self.assertEqual(out["issue"]["existing_issue"], 42)
        open_issue.assert_not_called()

    def test_files_issue_when_none_open(self):
        client = _client_returning([], issues=[])  # no existing open issue
        with mock.patch.object(go.GitHubOps, "_client", return_value=client), \
                mock.patch.object(wqr.GitHubOps, "open_issue",
                                  return_value={"status": "report_only"}) as open_issue:
            out = wqr.report({
                "target": "Scheduler-Systems/scheduler-web", "branch": "main",
                "verdict": "REGRESSION", "is_new": True, "head_sha": "z",
                "triage": "summary here",
            })
        open_issue.assert_called_once()
        self.assertEqual(out["issue"]["status"], "report_only")

    def test_no_op_when_green(self):
        out = wqr.report({"target": "Scheduler-Systems/scheduler-web", "verdict": "green"})
        self.assertEqual(out["issue"]["status"], "no-op (green)")


class GraphTests(unittest.TestCase):
    """End-to-end through the compiled graph (kill-switch on so no real model/IO is hit)."""

    def test_clocked_out_skips_everything(self):
        with mock.patch.dict(os.environ, {"AGENTS_DISABLED": "1"}):
            out = wqr.graph.invoke({"target": "Scheduler-Systems/scheduler-web"})
        self.assertEqual(out["verdict"], "skipped")
        self.assertEqual(out["issue"]["status"], "skipped (clocked out)")

    def test_green_run_opens_no_issue(self):
        runs = [_run("completed", "success", head_sha="ok")]
        client = _client_returning(runs)
        with mock.patch.object(wqr, "check_clocked_in", return_value=True), \
                mock.patch.object(go.GitHubOps, "_client", return_value=client):
            out = wqr.graph.invoke({"target": "Scheduler-Systems/scheduler-web"})
        self.assertEqual(out["verdict"], "green")
        self.assertEqual(out["issue"]["status"], "no-op (green)")

    def test_regression_files_issue_record_writes_under_report_only(self):
        # RECORD vs CODE boundary: a QA bug issue is a durable RECORD, not a code action, so
        # open_issue WRITES even under report_only=True — the QA finding is captured in GitHub
        # instead of scrolling away. (Code actions like open_pr/merge stay gated elsewhere.)
        runs = [_run("completed", "failure", head_sha="bad")]
        fake_issue = mock.Mock(number=21, html_url="https://x/i/21", sha=None, merged=None)
        client = _client_returning(runs, issues=[])
        client.get_repo.return_value.create_issue.return_value = fake_issue
        with mock.patch.object(wqr, "check_clocked_in", return_value=True), \
                mock.patch.object(go.GitHubOps, "_client", return_value=client), \
                mock.patch.object(go.GitHubOps, "_is_report_only", return_value=True), \
                mock.patch.object(wqr, "_triage_regression", return_value="triage text"):
            out = wqr.graph.invoke({"target": "Scheduler-Systems/scheduler-web"})
        self.assertEqual(out["verdict"], "REGRESSION")
        self.assertEqual(out["issue"]["status"], "done")        # the record actually wrote
        client.get_repo.return_value.create_issue.assert_called_once()


if __name__ == "__main__":
    unittest.main()
