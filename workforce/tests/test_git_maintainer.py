"""Safety + behaviour tests for delete_branch and the git_maintainer graph.

The whole point of this agent is destructive (it deletes branches), so the tests
focus on proving it can ONLY delete the provably-safe set. Run:
    .venv/bin/python -m unittest tests.test_git_maintainer -v
"""
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from agent_toolkit import github_ops as go
from agent_toolkit import budget
from agent_toolkit.policy import ModelWorkBlocked
from graphs.qa import git_maintainer as gm

REPO = "Scheduler-Systems/qa-agent-platform"


def _graduated_env(**overrides):
    """Env that GRADUATES git_maintainer past the per-agent write floor so its destructive prune
    may fire: master floor LIFTED (OPS_REPORT_ONLY=0) + git_maintainer named on the allowlist.
    The kill switch (check_clocked_in) is mocked True by ``_write_enabled`` below. This is the
    explicit precondition the floor now requires before ``act`` will auto-delete anything."""
    env = {k: v for k, v in os.environ.items()
           if k not in ("OPS_REPORT_ONLY", "AGENTS_WRITE_ENABLED")}
    env["OPS_REPORT_ONLY"] = "0"
    env["AGENTS_WRITE_ENABLED"] = "git_maintainer"
    env.update(overrides)
    return env


def _write_enabled():
    """A context manager stack that makes ``write_gate.write_enabled('git_maintainer')`` True:
    graduated env + clocked-in. Used by the tests that prove ``act`` CAN prune the safe set."""
    return mock.patch.object(budget, "check_clocked_in", return_value=True)


def _iso(days_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


# A timestamp well past the idle window — used for "genuinely stale" merged branches.
_STALE = _iso(90)
# A timestamp inside the idle window — "still live locally".
_RECENT = _iso(1)


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
            # 'chore/...' is NOT a protected pattern and is stale → genuinely auto-prunable.
            {"name": "chore/old-merged", "sha": "b", "protected": False, "is_default": False},
            {"name": "chore/orphan", "sha": "c", "protected": False, "is_default": False},
            {"name": "chore/active", "sha": "d", "protected": False, "is_default": False},
        ]

        def merged_pr(repo, name):
            if name == "chore/old-merged":
                return {"has_pr": True, "merged": True, "open": False, "numbers": [1],
                        "labels": [], "last_activity": _STALE}
            if name == "chore/active":
                return {"has_pr": True, "merged": False, "open": True, "numbers": [2],
                        "labels": [], "last_activity": _RECENT}
            return {"has_pr": False, "merged": False, "open": False, "numbers": [],
                    "labels": [], "last_activity": None}

        fake.branch_merged_pr.side_effect = merged_pr
        fake.delete_branch.return_value = {
            "status": "deleted", "repo": REPO, "branch": "chore/old-merged",
            "deleted_sha": "bbbbbbbccccc", "merged": True, "auto": True, "reason": "x",
        }
        fake.open_issue.return_value = {"status": "done", "number": 99, "html_url": "u"}

        # PRECONDITION: git_maintainer graduated past the floor so the stale merged branch prunes.
        with mock.patch.dict(os.environ, _graduated_env(), clear=True), _write_enabled(), \
             mock.patch.object(gm, "GitHubOps", return_value=fake), \
             mock.patch.object(gm, "governance_capture"):
            out = gm.graph.invoke({"repos": [REPO]})

        self.assertEqual(len(out["pruned"]), 1)                       # merged+stale+unprotected → pruned
        self.assertEqual(out["pruned"][0]["branch"], "chore/old-merged")
        proposed = {p["branch"] for p in out["proposals"]}
        self.assertIn("chore/orphan", proposed)                       # no PR → proposed
        self.assertNotIn("chore/active", proposed)                    # open PR → skipped
        self.assertNotIn("main", proposed)                            # default → skipped
        fake.open_issue.assert_called_once()                          # digest filed (proposals exist)

    def test_clean_run_files_no_issue(self):
        fake = mock.Mock()
        fake.list_branches.return_value = [
            {"name": "chore/old-merged", "sha": "b", "protected": False, "is_default": False},
        ]
        fake.branch_merged_pr.return_value = {"has_pr": True, "merged": True, "open": False,
                                              "numbers": [1], "labels": [], "last_activity": _STALE}
        fake.delete_branch.return_value = {
            "status": "deleted", "repo": REPO, "branch": "chore/old-merged",
            "deleted_sha": "bbbbbbbccccc", "merged": True, "auto": True, "reason": "x",
        }
        # PRECONDITION: git_maintainer graduated past the floor so the stale merged branch prunes.
        with mock.patch.dict(os.environ, _graduated_env(), clear=True), _write_enabled(), \
             mock.patch.object(gm, "GitHubOps", return_value=fake), \
             mock.patch.object(gm, "governance_capture"):
            out = gm.graph.invoke({"repos": [REPO]})
        self.assertEqual(len(out["pruned"]), 1)
        self.assertEqual(out.get("proposals", []), [])
        fake.open_issue.assert_not_called()                          # nothing to propose → no noise


class PruneGuardUnitTests(unittest.TestCase):
    """The guard helper in isolation — the protected-pattern + activity + held-label logic."""

    def test_active_worktree_branch_is_protected_pattern(self):
        # The literal branch of THIS active worktree — feat/* → never auto-prune.
        self.assertTrue(gm._matches_protected_pattern("feat/ops-fleet-prod-harden"))
        self.assertTrue(gm._prune_guard("feat/ops-fleet-prod-harden",
                                        {"merged": True, "labels": [], "last_activity": _STALE}))

    def test_fix_security_branch_is_protected_pattern(self):
        # The HELD Firestore IDOR security branch — fix/* (and 'security'/'idor' sensitive).
        self.assertTrue(gm._matches_protected_pattern("fix/firestore-idor-acl-1487"))
        self.assertTrue(gm._matches_protected_pattern("hardening/security-rules"))
        self.assertTrue(gm._prune_guard("fix/firestore-idor-acl-1487",
                                        {"merged": True, "labels": [], "last_activity": _STALE}))

    def test_held_label_blocks_even_unprotected_name(self):
        guard = gm._prune_guard("chore/x",
                                {"merged": True, "labels": ["gate:human-required"],
                                 "last_activity": _STALE})
        self.assertIn("held", guard.lower())

    def test_recent_activity_blocks_even_unprotected_name(self):
        guard = gm._prune_guard("chore/x",
                                {"merged": True, "labels": [], "last_activity": _RECENT})
        self.assertIn("recent", guard.lower())

    def test_unknown_timestamp_treated_as_recent(self):
        # Conservative: can't prove idle → propose, don't prune.
        self.assertTrue(gm._prune_guard("chore/x",
                                        {"merged": True, "labels": [], "last_activity": None}))

    def test_genuinely_stale_unprotected_branch_passes(self):
        # The ONLY shape that may auto-prune: unprotected name, no held label, idle > window.
        self.assertEqual(gm._prune_guard("chore/old-cleanup",
                                         {"merged": True, "labels": [], "last_activity": _STALE}),
                         "")

    def test_default_and_classic_protected_names_blocked(self):
        for b in ("main", "master", "production", "release"):
            self.assertTrue(gm._prune_guard(b, {"merged": True, "labels": [], "last_activity": _STALE}))
        self.assertTrue(gm._prune_guard("trunk", {"merged": True, "labels": [],
                                                  "last_activity": _STALE}, default_branch="trunk"))


class SweepGuardTests(unittest.TestCase):
    """The guard wired into the graph's sweep — proves the two named hazards never enter
    the auto-delete set, while a genuinely-stale merged branch still does."""

    def _run_sweep(self, branches, prs):
        fake = mock.Mock()
        fake.list_branches.return_value = branches
        fake.branch_merged_pr.side_effect = lambda repo, name: prs[name]
        with mock.patch.object(gm, "GitHubOps", return_value=fake):
            return gm.sweep({"repos": [REPO]})

    def test_active_worktree_branch_proposed_not_pruned(self):
        out = self._run_sweep(
            [{"name": "feat/ops-fleet-prod-harden", "sha": "aa", "protected": False, "is_default": False}],
            {"feat/ops-fleet-prod-harden": {"has_pr": True, "merged": True, "open": False,
                                            "numbers": [7], "labels": [], "last_activity": _STALE}},
        )
        self.assertEqual(out["prune_candidates"], [])                 # NEVER auto-deletes a live worktree branch
        self.assertEqual(len(out["proposals"]), 1)
        self.assertEqual(out["proposals"][0]["branch"], "feat/ops-fleet-prod-harden")

    def test_held_security_branch_proposed_not_pruned(self):
        out = self._run_sweep(
            [{"name": "fix/firestore-idor-acl-1487", "sha": "bb", "protected": False, "is_default": False}],
            {"fix/firestore-idor-acl-1487": {"has_pr": True, "merged": True, "open": False,
                                             "numbers": [8], "labels": ["gate:human-required"],
                                             "last_activity": _STALE}},
        )
        self.assertEqual(out["prune_candidates"], [])                 # HELD security branch never auto-deleted
        self.assertEqual(len(out["proposals"]), 1)
        self.assertEqual(out["proposals"][0]["branch"], "fix/firestore-idor-acl-1487")

    def test_genuinely_stale_merged_branch_still_pruned(self):
        out = self._run_sweep(
            [{"name": "chore/old-cleanup", "sha": "cc", "protected": False, "is_default": False}],
            {"chore/old-cleanup": {"has_pr": True, "merged": True, "open": False,
                                   "numbers": [9], "labels": [], "last_activity": _STALE}},
        )
        self.assertEqual(len(out["prune_candidates"]), 1)             # stale + unprotected → genuinely prunable
        self.assertEqual(out["prune_candidates"][0]["branch"], "chore/old-cleanup")
        self.assertEqual(out["proposals"], [])


class ActDefenseInDepthTests(unittest.TestCase):
    """Even if a protected-pattern branch is hand-injected straight into prune_candidates,
    act() must STILL refuse to delete it (second layer) and propose it instead."""

    def test_act_reblocks_protected_pattern_candidate(self):
        fake = mock.Mock()
        with mock.patch.object(gm, "GitHubOps", return_value=fake):
            out = gm.act({"prune_candidates": [
                {"repo": REPO, "branch": "feat/ops-fleet-prod-harden", "sha": "aa"},
                {"repo": REPO, "branch": "fix/firestore-idor-acl-1487", "sha": "bb"},
            ], "proposals": [], "errors": []})
        fake.delete_branch.assert_not_called()                       # no delete attempted at all
        self.assertEqual(out["pruned"], [])
        proposed = {p["branch"] for p in out["proposals"]}
        self.assertEqual(proposed, {"feat/ops-fleet-prod-harden", "fix/firestore-idor-acl-1487"})

    def test_act_still_deletes_unprotected_candidate(self):
        # PRECONDITION: git_maintainer is GRADUATED past the per-agent write floor (master floor
        # lifted + on the allowlist + clocked-in). Only then may the destructive prune fire.
        fake = mock.Mock()
        fake.delete_branch.return_value = {
            "status": "deleted", "repo": REPO, "branch": "chore/old-cleanup",
            "deleted_sha": "ccccccc", "merged": True, "auto": True, "reason": "x",
        }
        with mock.patch.dict(os.environ, _graduated_env(), clear=True), _write_enabled(), \
             mock.patch.object(gm, "GitHubOps", return_value=fake):
            out = gm.act({"prune_candidates": [
                {"repo": REPO, "branch": "chore/old-cleanup", "sha": "cc"},
            ], "proposals": [], "errors": []})
        fake.delete_branch.assert_called_once()
        self.assertEqual(len(out["pruned"]), 1)

    def test_act_floor_blocks_prune_when_not_write_enabled(self):
        # The floor: with git_maintainer NOT write-enabled (default — not on the allowlist), the
        # destructive prune is withheld and the candidate is PROPOSED, never deleted.
        fake = mock.Mock()
        env = {k: v for k, v in os.environ.items()
               if k not in ("OPS_REPORT_ONLY", "AGENTS_WRITE_ENABLED")}
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch.object(gm, "GitHubOps", return_value=fake):
            out = gm.act({"prune_candidates": [
                {"repo": REPO, "branch": "chore/old-cleanup", "sha": "cc"},
            ], "proposals": [], "errors": []})
        fake.delete_branch.assert_not_called()
        self.assertEqual(out["pruned"], [])
        self.assertEqual({p["branch"] for p in out["proposals"]}, {"chore/old-cleanup"})


class BranchMergedPrSignalsTests(unittest.TestCase):
    """branch_merged_pr now surfaces labels + last_activity for the guard (still read-only)."""

    def test_surfaces_labels_and_last_activity(self):
        lbl = mock.Mock()
        lbl.name = "gate:human-required"
        pr = mock.Mock(merged_at=datetime(2026, 6, 1, tzinfo=timezone.utc), state="closed",
                       number=5, labels=[lbl],
                       updated_at=datetime(2026, 6, 3, tzinfo=timezone.utc),
                       created_at=datetime(2026, 5, 20, tzinfo=timezone.utc))
        repo = mock.Mock()
        repo.get_pulls.return_value = [pr]
        client = mock.Mock()
        client.get_repo.return_value = repo
        ops = go.GitHubOps(report_only=False)
        with mock.patch.object(go.GitHubOps, "_client", return_value=client):
            out = ops.branch_merged_pr(REPO, "fix/firestore-idor-acl-1487")
        self.assertTrue(out["merged"])
        self.assertIn("gate:human-required", out["labels"])
        self.assertTrue(out["last_activity"].startswith("2026-06-03"))  # most-recent stamp


if __name__ == "__main__":
    unittest.main()
