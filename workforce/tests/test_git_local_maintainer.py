"""Safety tests for the local git-maintainer. It pushes, removes worktrees, and
deletes branches — so the tests prove each destructive step (a) is skipped in
dry-run and (b) only touches the provably-safe set. Run:
    .venv/bin/python -m unittest tests.test_git_local_maintainer -v
"""
import os
import unittest
from unittest import mock

from graphs.local import git_local_maintainer as m


def _clear_dry(env=None):
    env = dict(os.environ if env is None else env)
    env.pop("GIT_MAINTAINER_DRY_RUN", None)
    return env


class ActSafetyTests(unittest.TestCase):
    def test_dry_run_deletes_nothing(self):
        state = {"prune_candidates": [{"repo_dir": "/r", "rel": "r", "branch": "feat/x", "sha": "abc1234ff"}],
                 "deleted_local": [], "proposals": []}
        with mock.patch.dict(os.environ, {"GIT_MAINTAINER_DRY_RUN": "1"}), \
             mock.patch.object(m, "_git") as g:
            out = m.act(state)
        g.assert_not_called()
        self.assertTrue(out["deleted_local"][0]["dry_run"])

    def test_real_prune_uses_safe_d_never_force(self):
        state = {"prune_candidates": [{"repo_dir": "/r", "rel": "r", "branch": "feat/x", "sha": "abc"}],
                 "deleted_local": [], "proposals": []}
        with mock.patch.dict(os.environ, _clear_dry(), clear=True), \
             mock.patch.object(m, "_git", return_value=(0, "")) as g:
            m.act(state)
        called = g.call_args[0]
        self.assertIn("-d", called)        # safe delete (refuses unmerged)
        self.assertNotIn("-D", called)     # never force-delete


class BackupSafetyTests(unittest.TestCase):
    def test_dry_run_pushes_nothing(self):
        def fake_git(repo, *a, **k):
            if a[:2] == ("remote", "get-url"):
                return (0, "url")
            if a[0] == "for-each-ref":
                return (0, "feat/x")
            if a[0] == "rev-list":
                return (0, "3")
            if a[0] == "push":
                raise AssertionError("push must not happen in dry-run")
            return (0, "")
        with mock.patch.dict(os.environ, {"GIT_MAINTAINER_DRY_RUN": "1"}), \
             mock.patch.object(m, "_git", side_effect=fake_git):
            out = m.backup({"root": "/w", "repos": ["/w/r"], "backed_up": [], "errors": []})
        self.assertEqual(out["backed_up"][0]["commits"], 3)
        self.assertTrue(out["backed_up"][0]["dry_run"])

    def test_real_backup_targets_backup_ref_with_lease(self):
        seen = {}
        def fake_git(repo, *a, **k):
            if a[:2] == ("remote", "get-url"):
                return (0, "url")
            if a[0] == "for-each-ref":
                return (0, "feat/x")
            if a[0] == "rev-list":
                return (0, "2")
            if a[0] == "push":
                seen["push"] = a
                return (0, "")
            return (0, "")
        with mock.patch.dict(os.environ, _clear_dry(), clear=True), \
             mock.patch.object(m, "_git", side_effect=fake_git):
            m.backup({"root": "/w", "repos": ["/w/r"], "backed_up": [], "errors": []})
        self.assertIn("--force-with-lease", seen["push"])           # safe, not raw --force
        self.assertTrue(any("refs/backup/auto/" in x for x in seen["push"]))  # backup ns, not a real branch


class WorktreeSafetyTests(unittest.TestCase):
    _LIST = ("worktree /r\nbranch refs/heads/main\n\n"
             "worktree /r/wt/x\nbranch refs/heads/feat/x\n")

    def test_main_and_dirty_never_removed(self):
        def fake_git(repo, *a, **k):
            if a[:2] == ("worktree", "list"):
                return (0, self._LIST)
            if a[0] == "status":
                return (0, " M file")           # dirty linked worktree
            if a[0] == "symbolic-ref":
                return (0, "main")
            if a[0] == "merge-base":
                return (1, "")                  # not merged
            if a[:2] == ("worktree", "remove"):
                raise AssertionError("must not remove main or dirty worktree")
            return (0, "")
        with mock.patch.object(m, "_git", side_effect=fake_git), \
             mock.patch.object(m, "_gh_pr_state", return_value="OPEN"):
            out = m.worktrees({"root": "/", "repos": ["/r"], "worktrees_removed": [], "proposals": []})
        self.assertEqual(out["worktrees_removed"], [])
        self.assertTrue(any(p["kind"].startswith("worktree") for p in out["proposals"]))

    def test_clean_merged_worktree_removed(self):
        removed = {"yes": False}
        def fake_git(repo, *a, **k):
            if a[:2] == ("worktree", "list"):
                return (0, "worktree /r\nbranch refs/heads/main\n\nworktree /r/wt/d\nbranch refs/heads/feat/done\n")
            if a[0] == "status":
                return (0, "")                  # clean
            if a[0] == "symbolic-ref":
                return (0, "main")
            if a[0] == "merge-base":
                return (0, "")                  # merged into default
            if a[:2] == ("worktree", "remove"):
                removed["yes"] = True
                return (0, "")
            return (0, "")
        with mock.patch.dict(os.environ, _clear_dry(), clear=True), \
             mock.patch.object(m, "_git", side_effect=fake_git), \
             mock.patch.object(m, "_gh_pr_state", return_value=""):
            out = m.worktrees({"root": "/", "repos": ["/r"], "worktrees_removed": [], "proposals": []})
        self.assertTrue(removed["yes"])
        self.assertEqual(len(out["worktrees_removed"]), 1)
        self.assertEqual(out["worktrees_removed"][0]["why"], "merged into default")


if __name__ == "__main__":
    unittest.main()
