"""FAILING TEST — proves the git_maintainer destructive-prune path BYPASSES the safety floor.

The per-agent write gate (agent_toolkit/write_gate.py) is the company's report-only floor:
  * default-DENY — empty/unset AGENTS_WRITE_ENABLED ⇒ NOBODY writes;
  * OPS_REPORT_ONLY (unset/truthy) ⇒ EVERYONE report-only (the master floor);
  * check_clocked_in False (kill switch / bench / over-budget) ⇒ no write even for a
    write-enabled agent.

git_maintainer is a TIER-2 agent: it is NOT in TIER1_WRITE_ENABLED and is NOT on the default
AGENTS_WRITE_ENABLED allowlist, so the floor's intent is that it stays report-only (proposes
prunes) until a human graduates it. But ``graphs/qa/git_maintainer.act`` performs the
DESTRUCTIVE ``GitHubOps().delete_branch(...)`` (a CODE action) gated ONLY by
``GITHUB_OPS_REPORT_ONLY`` + ``AGENT_AUTONOMY=auto`` — it NEVER consults
``write_enabled("git_maintainer")``, ``report_only_for(...)``, ``check_clocked_in(...)``, or the
master ``OPS_REPORT_ONLY`` floor. There is also no budget/clock-in gate node in the graph
(unlike email_triage's ``budget_gate``).

Net effect (the fail-open): with ``AGENT_AUTONOMY=auto`` and ``GITHUB_OPS_REPORT_ONLY`` unset
(the per-agent floor lifted ONLY for the digest seam, NOT for this CODE path), git_maintainer
auto-DELETES a remote branch even though
  (a) ``OPS_REPORT_ONLY=1`` — the master report-only floor is ENGAGED, and
  (b) ``AGENTS_WRITE_ENABLED`` is EMPTY — git_maintainer is NOT write-enabled, and
  (c) ``check_clocked_in("git_maintainer")`` is False — the kill switch / over-budget STOP.

Each of (a)/(b)/(c) MUST independently keep this agent report-only per the floor's contract.
This test asserts the SAFE behaviour (no delete under any of those) and therefore FAILS on the
current code, demonstrating the fail-open. Run:
    .venv/bin/python -m unittest tests.test_git_maintainer_floor_failopen -v
"""
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from agent_toolkit import github_ops as go
from agent_toolkit import budget
from graphs.qa import git_maintainer as gm

REPO = "Scheduler-Systems/qa-agent-platform"
# A genuinely stale, unprotected, merged branch — clears _prune_guard so it is a prune CANDIDATE.
STALE_BRANCH = "chore/old-merged-cleanup"
STALE_SHA = "deadbeefcafe1234"


def _stale_iso() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()


def _client_with_mergeable_branch():
    """Fake pygithub client whose branch is the head of a long-merged PR (auto-prune-safe)."""
    ref = mock.Mock()
    ref.object.sha = STALE_SHA
    merged_at = datetime.now(timezone.utc) - timedelta(days=90)
    pr = mock.Mock(merged_at=merged_at, state="closed", labels=[],
                   updated_at=merged_at, created_at=merged_at)
    repo = mock.Mock()
    repo.default_branch = "main"
    repo.get_git_ref.return_value = ref
    repo.get_pulls.return_value = [pr]
    client = mock.Mock()
    client.get_repo.return_value = repo
    return client, repo, ref


def _floor_env(**overrides):
    """Master floor ENGAGED + per-agent allowlist EMPTY; AGENT_AUTONOMY=auto, GITHUB_OPS_REPORT_ONLY unset."""
    env = dict(os.environ)
    for k in ("OPS_REPORT_ONLY", "AGENTS_WRITE_ENABLED", "GITHUB_OPS_REPORT_ONLY", "AGENT_AUTONOMY"):
        env.pop(k, None)
    env["OPS_REPORT_ONLY"] = "1"          # master floor ENGAGED — everyone report-only
    env["AGENT_AUTONOMY"] = "auto"        # scheduled/unattended autonomy
    # GITHUB_OPS_REPORT_ONLY intentionally UNSET (the CODE path's only real gate is now off)
    env.update(overrides)
    return env


class GitMaintainerFloorFailOpenTests(unittest.TestCase):
    """Each test engages a DIFFERENT arm of the safety floor and asserts NO destructive delete."""

    def _run_act_and_assert_no_delete(self, *, clocked_in: bool, msg: str):
        client, repo, ref = _client_with_mergeable_branch()
        state = {
            # A prune CANDIDATE already (as 'sweep' would have produced for a stale merged branch).
            "prune_candidates": [{"repo": REPO, "branch": STALE_BRANCH, "sha": STALE_SHA}],
            "proposals": [],
            "errors": [],
        }
        with mock.patch.dict(os.environ, _floor_env(), clear=True), \
             mock.patch.object(go.GitHubOps, "_client", return_value=client), \
             mock.patch.object(budget, "check_clocked_in", return_value=clocked_in):
            out = gm.act(state)

        # SAFE expectation per the floor: the branch is PROPOSED, never auto-deleted.
        deleted = [p for p in out.get("pruned", [])]
        ref.delete.assert_not_called()  # the destructive remote delete must NOT have fired
        self.assertEqual(deleted, [], msg)

    def test_master_floor_engaged_blocks_destructive_prune(self):
        # OPS_REPORT_ONLY=1 is the master report-only floor — it must stop this CODE delete too.
        # (clocked_in left True to isolate the floor arm.)
        self._run_act_and_assert_no_delete(
            clocked_in=True,
            msg="FAIL-OPEN: git_maintainer auto-deleted a branch while OPS_REPORT_ONLY=1 "
                "(master floor engaged) — the destructive prune ignores the report-only floor.",
        )

    def test_kill_switch_blocks_destructive_prune(self):
        # check_clocked_in False (kill switch / bench / over-budget) MUST stop the write.
        self._run_act_and_assert_no_delete(
            clocked_in=False,
            msg="FAIL-OPEN: git_maintainer auto-deleted a branch while check_clocked_in is False "
                "(kill switch / over-budget) — the destructive prune ignores the kill switch.",
        )

    def test_not_write_enabled_blocks_destructive_prune(self):
        # git_maintainer is NOT on AGENTS_WRITE_ENABLED (empty) — the per-agent floor says
        # report-only. Lift ONLY the master floor (as a graduation step for OTHER agents would)
        # and prove the un-graduated git_maintainer still must not auto-delete.
        client, repo, ref = _client_with_mergeable_branch()
        state = {
            "prune_candidates": [{"repo": REPO, "branch": STALE_BRANCH, "sha": STALE_SHA}],
            "proposals": [], "errors": [],
        }
        env = _floor_env(OPS_REPORT_ONLY="0")  # master floor LIFTED, but allowlist still EMPTY
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch.object(go.GitHubOps, "_client", return_value=client), \
             mock.patch.object(budget, "check_clocked_in", return_value=True):
            out = gm.act(state)
        ref.delete.assert_not_called()
        self.assertEqual(
            out.get("pruned", []), [],
            "FAIL-OPEN: git_maintainer (NOT on AGENTS_WRITE_ENABLED) auto-deleted a branch — "
            "the destructive prune never consults the per-agent write allowlist.",
        )


if __name__ == "__main__":
    unittest.main()
