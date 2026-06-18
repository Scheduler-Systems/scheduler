"""Safety tests for the GitHub write surface (stdlib unittest — no new deps).

Run: .venv/bin/python -m unittest tests.test_github_ops -v
"""
import unittest
from unittest import mock

from agent_toolkit import github_ops as go
from agent_toolkit.policy import ModelWorkBlocked


class AllowListTests(unittest.TestCase):
    def test_unlisted_repo_blocked(self):
        with self.assertRaises(go.GitHubWriteBlocked):
            go.assert_allowed_repo("Scheduler-Systems/some-random-repo")

    def test_model_repo_blocked(self):
        # Anthropic-terms guard fires before the allow-list verdict.
        with self.assertRaises(ModelWorkBlocked):
            go.assert_allowed_repo("gal-run/gal-model")

    def test_allowed_repo_passes(self):
        go.assert_allowed_repo("Scheduler-Systems/scheduler-web")  # no raise


class MergeGuardTests(unittest.TestCase):
    def test_merge_blocked_on_prod_repo_before_anything_else(self):
        ops = go.GitHubOps(report_only=False)
        # Should raise purely from the prod-repo guard — no token, no gate needed.
        with self.assertRaises(go.GitHubWriteBlocked):
            ops.merge_pr("Scheduler-Systems/scheduler-web", 1)

    def test_merge_allowed_on_nonprod_repo_is_gated(self):
        ops = go.GitHubOps(report_only=False)
        with mock.patch.object(go, "request_approval", return_value="reject"), \
             mock.patch.object(go, "is_approved", return_value=False):
            with self.assertRaises(go.GitHubWriteBlocked):
                ops.merge_pr("gal-run/agent-workforce", 1)


class ReportOnlyTests(unittest.TestCase):
    def test_report_only_returns_plan_without_gate_or_client(self):
        ops = go.GitHubOps(report_only=True)
        with mock.patch.object(go, "request_approval") as gate, \
             mock.patch.object(go.GitHubOps, "_client") as client:
            out = ops.open_issue("Scheduler-Systems/scheduler-web", "t", "b")
        self.assertEqual(out["status"], "report_only")
        self.assertEqual(out["action"], "open_issue")
        gate.assert_not_called()
        client.assert_not_called()


class FailClosedTests(unittest.TestCase):
    def test_no_token_raises_not_configured(self):
        ops = go.GitHubOps(report_only=False)
        with mock.patch.object(go, "request_approval", return_value="approve"), \
             mock.patch.object(go, "is_approved", return_value=True), \
             mock.patch.object(go, "_token", return_value=None):
            with self.assertRaises(go.GitHubNotConfigured):
                ops.open_issue("Scheduler-Systems/scheduler-web", "t", "b")


class GateTests(unittest.TestCase):
    def test_rejection_blocks_and_never_calls_client(self):
        ops = go.GitHubOps(report_only=False)
        with mock.patch.object(go, "request_approval", return_value="reject"), \
             mock.patch.object(go, "is_approved", return_value=False), \
             mock.patch.object(go.GitHubOps, "_client") as client:
            with self.assertRaises(go.GitHubWriteBlocked):
                ops.open_pr("Scheduler-Systems/scheduler-web", "h", "main", "t", "b")
        client.assert_not_called()

    def test_approval_executes_and_normalizes_result(self):
        ops = go.GitHubOps(report_only=False)
        fake_pr = mock.Mock(number=42, html_url="https://x/pr/42", sha=None, merged=None)
        fake_repo = mock.Mock()
        fake_repo.create_pull.return_value = fake_pr
        fake_client = mock.Mock()
        fake_client.get_repo.return_value = fake_repo
        with mock.patch.object(go, "request_approval", return_value="approve"), \
             mock.patch.object(go, "is_approved", return_value=True), \
             mock.patch.object(go.GitHubOps, "_client", return_value=fake_client):
            out = ops.open_pr("Scheduler-Systems/scheduler-web", "feat/x", "main", "t", "b")
        fake_client.get_repo.assert_called_once_with("Scheduler-Systems/scheduler-web")
        fake_repo.create_pull.assert_called_once()
        self.assertEqual(out, {"status": "done", "number": 42,
                               "html_url": "https://x/pr/42", "sha": None, "merged": None})


if __name__ == "__main__":
    unittest.main()
