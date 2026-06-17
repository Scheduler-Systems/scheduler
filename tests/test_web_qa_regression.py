"""Tests for web_qa_regression graph + github_ops.latest_run. stdlib unittest, no network.

Run: .venv/bin/python -m unittest tests.test_web_qa_regression -v
"""
import importlib.util
import pathlib
import unittest
from unittest import mock

_SPEC = importlib.util.spec_from_file_location(
    "web_qa_regression", pathlib.Path("graphs/qa/web_qa_regression.py")
)
wqr = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(wqr)

from agent_toolkit import github_ops as go


class LatestRunTests(unittest.TestCase):
    def test_reads_latest_conclusion(self):
        run = mock.Mock(status="completed", conclusion="failure",
                        html_url="https://x/run/1", name="tests", head_sha="abc")
        repo = mock.Mock()
        repo.get_workflow_runs.return_value = [run]
        client = mock.Mock()
        client.get_repo.return_value = repo
        with mock.patch.object(go.GitHubOps, "_client", return_value=client):
            out = go.GitHubOps().latest_run("Scheduler-Systems/scheduler-web", "main")
        self.assertEqual(out["conclusion"], "failure")
        self.assertEqual(out["html_url"], "https://x/run/1")

    def test_latest_run_respects_allow_list(self):
        with self.assertRaises(go.GitHubWriteBlocked):
            go.GitHubOps().latest_run("Scheduler-Systems/some-random-repo", "main")


class RegressionGraphTests(unittest.TestCase):
    def test_green_opens_no_issue(self):
        with mock.patch.object(wqr, "GitHubOps") as M:
            M.return_value.latest_run.return_value = {"conclusion": "success", "html_url": "u"}
            out = wqr.graph.invoke({"target": "Scheduler-Systems/scheduler-web"})
        self.assertEqual(out["verdict"], "green")
        self.assertEqual(out["issue"]["status"], "no-op (green)")
        M.return_value.open_issue.assert_not_called()

    def test_regression_opens_issue(self):
        with mock.patch.object(wqr, "GitHubOps") as M:
            M.return_value.latest_run.return_value = {"conclusion": "failure", "html_url": "u"}
            M.return_value.open_issue.return_value = {"status": "done", "number": 99}
            out = wqr.graph.invoke({})  # defaults to scheduler-web@main
        self.assertEqual(out["verdict"], "REGRESSION")
        M.return_value.open_issue.assert_called_once()
        self.assertEqual(out["issue"]["number"], 99)


if __name__ == "__main__":
    unittest.main()
