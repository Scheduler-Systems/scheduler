"""Safety + behaviour tests for delete_branch and the git_maintainer graph.

The whole point of this agent is destructive (it deletes branches), so the tests
focus on proving it can ONLY delete the provably-safe set. Run:
    .venv/bin/python -m unittest tests.test_git_maintainer -v
"""
import os
import unittest
from unittest import mock

from agent_toolkit import github_ops as go
from agent_toolkit.policy import ModelWorkBlocked
from graphs.qa import git_maintainer as gm

REPO = "gal-run/agent-workforce"


def _fake_client(default_branch="main", sha="deadbeefcafe", merged_ats=()):
    """A fake pygithub client: repo with one branch ref + PRs carrying merged_at."""
    ref = mock.Mock()
    ref.object.sha = sha
    repo = mock.Mock()
    repo.default_branch = default_branch
    repo.get_git_ref.return_value = ref
    repo.get_pulls.return_value = [
        mock.Mock(merged_at=m, state=("closed" if m else "open")) for m in merged_ats
    ]
    client = mock.Mock()
    client.get_repo.return_value = repo
    return client, repo, ref


class DeleteBranchSafetyTests(unittest.TestCase):
    def test_protected_branch_refused_before_client(self):
        ops = go.GitHubOps(report_only=False)
        with mock.patch.object(go.GitHubOps, "_client") as client:
            for b in ("main", "master", "phase-0-foundation", "production"):
                with self.assertRaises(go.GitHubWriteBlocked):
                    ops.delete_branch(REPO, b)
        client.assert_not_called()

    def test_model_repo_blocked(self):
        ops = go.GitHubOps(report_only=False)
        with self.assertRaises(ModelWorkBlocked):
            ops.delete_branch("gal-run/gal-model", "feat/x")

    def test_unlisted_repo_blocked(self):
        ops = go.GitHubOps(report_only=False)
        with self.assertRaises(go.GitHubWriteBlocked):
            ops.delete_branch("Scheduler-Systems/legal", "feat/x")

    def test_report_only_returns_plan_no_client(self):
        ops = go.GitHubOps(report_only=True)
        with mock.patch.object(go.GitHubOps, "_client") as client:
            out = ops.delete_branch(REPO, "feat/x")
        self.assertEqual(out["status"], "report_only")
        client.assert_not_called()

    def test_dynamic_default_branch_refused(self):
        ops = go.GitHubOps(report_only=False)
        client, repo, ref = _fake_client(default_branch="trunk")
        with mock.patch.object(go.GitHubOps, "_client", return_value=client):
            with self.assertRaises(go.GitHubWriteBlocked):
                ops.delete_branch(REPO, "trunk")
        ref.delete.assert_not_called()

    def test_auto_merged_autodeletes_without_gate_and_logs_sha(self):
        ops = go.GitHubOps(report_only=False)
        client, repo, ref = _fake_client(merged_ats=["2026-06-01T00:00:00Z"])
        with mock.patch.dict(os.environ, {"AGENT_AUTONOMY": "auto"}), \
             mock.patch.object(go.GitHubOps, "_client", return_value=client), \
             mock.patch.object(go, "request_approval") as gate:
            out = ops.delete_branch(REPO, "feat/merged")
        gate.assert_not_called()             # provably-safe → no human needed
        ref.delete.assert_called_once()
        self.assertEqual(out["status"], "deleted")
        self.assertTrue(out["merged"] and out["auto"])
        self.assertEqual(out["deleted_sha"], "deadbeefcafe")  # captured before delete

    def test_auto_unmerged_gates_and_does_not_delete(self):
        ops = go.GitHubOps(report_only=False)
        client, repo, ref = _fake_client(merged_ats=[None])  # PR exists, not merged
        with mock.patch.dict(os.environ, {"AGENT_AUTONOMY": "auto"}), \
             mock.patch.object(go.GitHubOps, "_client", return_value=client), \
             mock.patch.object(go, "request_approval", return_value="reject"), \
             mock.patch.object(go, "is_approved", return_value=False):
            with self.assertRaises(go.GitHubWriteBlocked):
                ops.delete_branch(REPO, "feat/wip")
        ref.delete.assert_not_called()       # unmerged is NEVER auto-deleted

    def test_merged_without_auto_tier_still_gates(self):
        ops = go.GitHubOps(report_only=False)
        client, repo, ref = _fake_client(merged_ats=["2026-06-01T00:00:00Z"])
        env = {k: v for k, v in os.environ.items() if k != "AGENT_AUTONOMY"}
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch.object(go.GitHubOps, "_client", return_value=client), \
             mock.patch.object(go, "request_approval", return_value="approve"), \
             mock.patch.object(go, "is_approved", return_value=True):
            out = ops.delete_branch(REPO, "feat/merged")
        ref.delete.assert_called_once()
        self.assertFalse(out["auto"])        # gated path, not auto


class GraphTests(unittest.TestCase):
    def test_classifies_prunes_merged_proposes_orphans(self):
        fake = mock.Mock()
        fake.list_branches.return_value = [
            {"name": "main", "sha": "a", "protected": True, "is_default": True},
            {"name": "feat/merged", "sha": "b", "protected": False, "is_default": False},
            {"name": "feat/orphan", "sha": "c", "protected": False, "is_default": False},
            {"name": "feat/active", "sha": "d", "protected": False, "is_default": False},
        ]

        def merged_pr(repo, name):
            if name == "feat/merged":
                return {"has_pr": True, "merged": True, "open": False, "numbers": [1]}
            if name == "feat/active":
                return {"has_pr": True, "merged": False, "open": True, "numbers": [2]}
            return {"has_pr": False, "merged": False, "open": False, "numbers": []}

        fake.branch_merged_pr.side_effect = merged_pr
        fake.delete_branch.return_value = {
            "status": "deleted", "repo": REPO, "branch": "feat/merged",
            "deleted_sha": "bbbbbbbccccc", "merged": True, "auto": True, "reason": "x",
        }
        fake.open_issue.return_value = {"status": "done", "number": 99, "html_url": "u"}

        with mock.patch.object(gm, "GitHubOps", return_value=fake), \
             mock.patch.object(gm, "governance_capture"):
            out = gm.graph.invoke({"repos": [REPO]})

        self.assertEqual(len(out["pruned"]), 1)                       # merged → pruned
        self.assertEqual(out["pruned"][0]["branch"], "feat/merged")
        proposed = {p["branch"] for p in out["proposals"]}
        self.assertIn("feat/orphan", proposed)                        # no PR → proposed
        self.assertNotIn("feat/active", proposed)                     # open PR → skipped
        self.assertNotIn("main", proposed)                            # default → skipped
        fake.open_issue.assert_called_once()                          # digest filed (proposals exist)

    def test_clean_run_files_no_issue(self):
        fake = mock.Mock()
        fake.list_branches.return_value = [
            {"name": "feat/merged", "sha": "b", "protected": False, "is_default": False},
        ]
        fake.branch_merged_pr.return_value = {"has_pr": True, "merged": True, "open": False, "numbers": [1]}
        fake.delete_branch.return_value = {
            "status": "deleted", "repo": REPO, "branch": "feat/merged",
            "deleted_sha": "bbbbbbbccccc", "merged": True, "auto": True, "reason": "x",
        }
        with mock.patch.object(gm, "GitHubOps", return_value=fake), \
             mock.patch.object(gm, "governance_capture"):
            out = gm.graph.invoke({"repos": [REPO]})
        self.assertEqual(len(out["pruned"]), 1)
        self.assertEqual(out.get("proposals", []), [])
        fake.open_issue.assert_not_called()                          # nothing to propose → no noise


if __name__ == "__main__":
    unittest.main()
