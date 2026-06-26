"""Safety tests for the git_sync_auditor. It is STRICTLY READ-ONLY, so the tests
prove (a) it surfaces the maintainer's protected/unpushed/dirty/orphan signals and
(b) it NEVER invokes a destructive or network git verb. Run:
    .venv/bin/python -m unittest tests.test_git_sync_auditor -v
"""
import os
import unittest
from unittest import mock

from graphs.ops import git_sync_auditor as a
from graphs.local import git_local_maintainer as glm

# Destructive/network SUBCOMMANDS the read-only auditor must never run as args[0],
# plus destructive FLAGS it must never pass anywhere. Matched as whole tokens so that
# read-only plumbing like `merge-base` (NOT `merge`) and `rev-list` are correctly allowed.
_DESTRUCTIVE_VERBS = {
    "push", "fetch", "pull", "commit", "merge", "rebase", "reset", "checkout",
    "clean", "gc", "prune", "worktree", "stash",  # 'stash list' is allowed explicitly below
}
_DESTRUCTIVE_FLAGS = {"--force", "--force-with-lease", "-f", "remove"}


def _guard_git(rc_text_for):
    """Build a glm._git side_effect that ASSERTS no destructive verb/flag is ever passed,
    then delegates to `rc_text_for(repo, args) -> (rc, text)` for the read-only reply.

    Token-precise: the destructive *subcommand* is args[0] (so `merge-base` and `rev-list`
    are NOT mistaken for `merge`/`reset`), and destructive flags are matched as whole tokens
    anywhere. `stash list` (read-only) is the sole allowed use of an otherwise-blocked verb.
    """
    def fake(repo, *args, **kwargs):
        verb = args[0] if args else ""
        if verb == "stash":
            assert args[1:2] == ("list",), f"non-read-only stash used: {args}"
        else:
            assert verb not in _DESTRUCTIVE_VERBS, f"destructive git verb used: {args}"
        for bad in _DESTRUCTIVE_FLAGS:
            assert bad not in args, f"destructive git flag used: {args}"
        assert verb != "branch" or ("-d" not in args and "-D" not in args), \
            f"branch delete attempted: {args}"
        return rc_text_for(repo, args)
    return fake


class AuditProtectedTests(unittest.TestCase):
    def test_protected_branch_finding(self):
        """_protected_activity → (True, '2 unpushed commit(s)') yields protected branch."""
        def reply(repo, args):
            if args[:2] == ("remote", "get-url"):
                return (0, "url")
            if args[0] == "status":
                return (0, "")
            if args[0] == "stash":
                return (0, "")
            if args[:2] == ("symbolic-ref", "--short"):
                return (0, "feat/x")
            if args[0] == "for-each-ref":
                return (0, "feat/x|[ahead 2]")
            if args[0] == "rev-list":
                return (0, "2")
            return (0, "")
        with mock.patch.object(glm, "_git", side_effect=_guard_git(reply)), \
             mock.patch.object(glm, "_protected_activity", return_value=(True, "2 unpushed commit(s)")):
            out = a.audit({"root": "/w", "repos": ["/w/r"]})
        branch = out["findings"][0]["branches"][0]
        self.assertTrue(branch["protected"])
        self.assertEqual(branch["protected_reason"], "2 unpushed commit(s)")
        self.assertEqual(branch["ahead"], 2)
        self.assertEqual(branch["unpushed"], 2)
        # ahead + unpushed, has remote, clean → 'unpushed' (worst-of) classification.
        self.assertEqual(out["findings"][0]["classification"], "unpushed")


class AuditReadOnlyTests(unittest.TestCase):
    def test_audit_never_invokes_destructive_verb(self):
        """patch glm._git with a side_effect that raises if any destructive verb appears;
        assert audit still completes for a representative repo."""
        def reply(repo, args):
            if args[:2] == ("remote", "get-url"):
                return (0, "url")
            if args[0] == "status":
                return (0, " M tracked.py")     # dirty
            if args[0] == "stash":
                return (0, "stash@{0}: WIP")
            if args[:2] == ("symbolic-ref", "--short"):
                return (0, "main")
            if args[0] == "for-each-ref":
                return (0, "main|\nfeat/y|[ahead 1, behind 3]")
            if args[0] == "rev-list":
                return (0, "1")
            return (0, "")
        with mock.patch.dict(os.environ, {}, clear=False), \
             mock.patch.object(glm, "_git", side_effect=_guard_git(reply)), \
             mock.patch.object(glm, "_protected_activity", return_value=(False, "")):
            # Ensure the optional fetch is OFF so no network verb is attempted.
            os.environ.pop("GIT_SYNC_AUDITOR_FETCH", None)
            out = a.audit({"root": "/w", "repos": ["/w/r"]})
        self.assertEqual(len(out["findings"]), 1)  # completed without assertion failure
        self.assertEqual(out["findings"][0]["dirty"], 1)

    def test_fetch_disabled_by_default(self):
        """With the env unset, audit must not even attempt a fetch (the guard would raise)."""
        def reply(repo, args):
            if args[:2] == ("remote", "get-url"):
                return (0, "url")
            if args[0] == "for-each-ref":
                return (0, "main|")
            if args[0] == "rev-list":
                return (0, "0")
            return (0, "")
        with mock.patch.object(glm, "_git", side_effect=_guard_git(reply)), \
             mock.patch.object(glm, "_protected_activity", return_value=(False, "")):
            os.environ.pop("GIT_SYNC_AUDITOR_FETCH", None)
            out = a.audit({"root": "/w", "repos": ["/w/r"]})
        self.assertEqual(out["findings"][0]["classification"], "in_sync")


class AuditClassificationTests(unittest.TestCase):
    def test_orphan_no_remote_when_remote_missing_with_commits(self):
        """remote get-url fails (rc!=0) and there are local commits → orphan_no_remote."""
        def reply(repo, args):
            if args[:2] == ("remote", "get-url"):
                return (1, "")                  # no origin
            if args[0] == "status":
                return (0, "")
            if args[0] == "stash":
                return (0, "")
            if args[:2] == ("symbolic-ref", "--short"):
                return (0, "main")
            if args[0] == "for-each-ref":
                return (0, "main|")
            if args[0] == "rev-list":
                return (0, "5")                 # local commits not on any remote
            return (0, "")
        with mock.patch.object(glm, "_git", side_effect=_guard_git(reply)), \
             mock.patch.object(glm, "_protected_activity", return_value=(False, "")):
            out = a.audit({"root": "/w", "repos": ["/w/r"]})
        f = out["findings"][0]
        self.assertFalse(f["has_remote"])
        self.assertEqual(f["classification"], "orphan_no_remote")
        self.assertEqual(f["branches"][0]["unpushed"], 5)

    def test_dirty_detection_from_porcelain(self):
        """Tracked edits in porcelain → dirty count and 'dirty' classification."""
        def reply(repo, args):
            if args[:2] == ("remote", "get-url"):
                return (0, "url")
            if args[0] == "status":
                return (0, " M a.py\nM  b.py\n?? untracked.py")  # 2 tracked, 1 untracked
            if args[0] == "stash":
                return (0, "")
            if args[:2] == ("symbolic-ref", "--short"):
                return (0, "main")
            if args[0] == "for-each-ref":
                return (0, "main|")
            if args[0] == "rev-list":
                return (0, "0")
            return (0, "")
        with mock.patch.object(glm, "_git", side_effect=_guard_git(reply)), \
             mock.patch.object(glm, "_protected_activity", return_value=(False, "")):
            out = a.audit({"root": "/w", "repos": ["/w/r"]})
        f = out["findings"][0]
        self.assertEqual(f["dirty"], 2)               # untracked '??' excluded
        self.assertEqual(f["classification"], "dirty")

    def test_gone_upstream_merged_vs_unmerged(self):
        """ALIGNMENT WITH THE MAINTAINER: a gone-upstream branch is only ``merged=True``
        when ``merge-base --is-ancestor`` succeeds; merged-status is probed read-only via
        the SAME test the maintainer uses, so the auditor can't overstate 'safe to clean'."""
        def make_reply(merged_rc):
            def reply(repo, args):
                if args[:2] == ("remote", "get-url"):
                    return (0, "url")
                if args[0] == "status":
                    return (0, "")
                if args[0] == "stash":
                    return (0, "")
                if args[:2] == ("symbolic-ref", "--short"):
                    # _default_branch asks for refs/remotes/origin/HEAD; current HEAD asks for HEAD.
                    if "refs/remotes/origin/HEAD" in args:
                        return (0, "origin/main")
                    return (0, "main")
                if args[0] == "for-each-ref":
                    return (0, "old/feature|[gone]")
                if args[0] == "rev-list":
                    return (0, "0")           # nothing unpushed → not protected by that path
                if args[0] == "merge-base":
                    return (merged_rc, "")    # 0 = is an ancestor (merged); 1 = not merged
                return (0, "")
            return reply

        # gone + merged → merged True (the maintainer WOULD clean it)
        with mock.patch.object(glm, "_git", side_effect=_guard_git(make_reply(0))), \
             mock.patch.object(glm, "_protected_activity", return_value=(False, "")):
            out = a.audit({"root": "/w", "repos": ["/w/r"]})
        b = out["findings"][0]["branches"][0]
        self.assertTrue(b["upstream_gone"])
        self.assertTrue(b["merged"])

        # gone + NOT merged → merged False (the maintainer would only PROPOSE it)
        with mock.patch.object(glm, "_git", side_effect=_guard_git(make_reply(1))), \
             mock.patch.object(glm, "_protected_activity", return_value=(False, "")):
            out = a.audit({"root": "/w", "repos": ["/w/r"]})
        b = out["findings"][0]["branches"][0]
        self.assertTrue(b["upstream_gone"])
        self.assertFalse(b["merged"])

    def test_detached_head(self):
        """symbolic-ref failing → detached True and empty branch."""
        def reply(repo, args):
            if args[:2] == ("remote", "get-url"):
                return (0, "url")
            if args[0] == "status":
                return (0, "")
            if args[0] == "stash":
                return (0, "")
            if args[:2] == ("symbolic-ref", "--short"):
                return (1, "fatal: ref HEAD is not a symbolic ref")
            if args[0] == "for-each-ref":
                return (0, "")
            if args[0] == "rev-list":
                return (0, "0")
            return (0, "")
        with mock.patch.object(glm, "_git", side_effect=_guard_git(reply)), \
             mock.patch.object(glm, "_protected_activity", return_value=(False, "")):
            out = a.audit({"root": "/w", "repos": ["/w/r"]})
        f = out["findings"][0]
        self.assertTrue(f["detached"])
        self.assertEqual(f["branch"], "")


class DiscoverTests(unittest.TestCase):
    def test_discover_drops_model_repo(self):
        """Belt-and-braces: a /gal-model path that slipped through glm.discover is dropped."""
        with mock.patch.object(
            glm, "discover",
            return_value={"root": "/w", "repos": ["/w/scheduler-api", "/w/gal-model"]},
        ):
            out = a.discover({"root": "/w"})
        self.assertIn("/w/scheduler-api", out["repos"])
        self.assertNotIn("/w/gal-model", out["repos"])


class ReportTests(unittest.TestCase):
    _FINDINGS = [
        {"repo": "a", "branch": "main", "has_remote": True, "dirty": 0, "stashes": 0,
         "detached": False, "classification": "in_sync",
         "branches": [{"name": "main", "ahead": 0, "behind": 0, "unpushed": 0,
                       "upstream_gone": False, "protected": False, "protected_reason": ""}]},
        {"repo": "b", "branch": "feat/x", "has_remote": True, "dirty": 0, "stashes": 1,
         "detached": False, "classification": "unpushed",
         "branches": [{"name": "feat/x", "ahead": 2, "behind": 0, "unpushed": 2,
                       "upstream_gone": False, "protected": True,
                       "protected_reason": "2 unpushed commit(s)"}]},
        {"repo": "c", "branch": "main", "has_remote": True, "dirty": 0, "stashes": 0,
         "detached": False, "classification": "in_sync",
         "branches": [{"name": "old/gone", "ahead": 0, "behind": 0, "unpushed": 0,
                       "upstream_gone": True, "merged": True,
                       "protected": False, "protected_reason": ""}]},
        {"repo": "d", "branch": "main", "has_remote": False, "dirty": 0, "stashes": 0,
         "detached": False, "classification": "orphan_no_remote",
         "branches": [{"name": "main", "ahead": 0, "behind": 0, "unpushed": 4,
                       "upstream_gone": False, "merged": False, "protected": True,
                       "protected_reason": "4 unpushed commit(s)"}]},
        # gone but NOT merged → must be 'needs review', NOT 'safe for the maintainer to clean'.
        {"repo": "e", "branch": "main", "has_remote": True, "dirty": 0, "stashes": 0,
         "detached": False, "classification": "in_sync",
         "branches": [{"name": "gone/unmerged", "ahead": 0, "behind": 0, "unpushed": 0,
                       "upstream_gone": True, "merged": False,
                       "protected": False, "protected_reason": ""}]},
    ]

    def test_report_writes_digest_and_captures_governance(self):
        with mock.patch.object(a, "write_local_digest", return_value="/tmp/x/latest.md") as wld, \
             mock.patch.object(a, "governance_capture") as gov:
            out = a.report({"findings": self._FINDINGS})
        # digest written via the shared helper
        wld.assert_called_once()
        self.assertEqual(wld.call_args[0][0], "git-sync-auditor")
        self.assertEqual(out["report"]["digest"], "/tmp/x/latest.md")
        # governance captured report-only
        gov.assert_called_once()
        agent_name, decision = gov.call_args[0]
        self.assertEqual(agent_name, "git_sync_auditor")
        self.assertTrue(decision["report_only"])
        self.assertEqual(decision["repos"], 5)
        self.assertEqual(decision["in_sync"], 3)        # a, c, e
        self.assertEqual(decision["unpushed"], 1)
        self.assertEqual(decision["orphan"], 1)
        # protected_count = the two protected branches (b + d)
        self.assertEqual(decision["protected_count"], 2)
        self.assertEqual(out["report"]["protected_count"], 2)

    def test_stale_requires_merged_gone_unmerged_goes_to_review(self):
        """ALIGNMENT: only gone+merged+not-protected counts as 'safe for the maintainer to
        clean' (stale). A gone-but-NOT-merged branch must be surfaced as 'needs review',
        matching the maintainer's gone-upstream-unmerged proposal — never 'safe to clean'."""
        captured_body = {}

        def fake_wld(agent, title, body, **kw):
            captured_body["body"] = body
            return "/tmp/x/latest.md"

        with mock.patch.object(a, "write_local_digest", side_effect=fake_wld), \
             mock.patch.object(a, "governance_capture") as gov:
            out = a.report({"findings": self._FINDINGS})

        # counts: exactly one stale (c: gone+merged) and one gone-unmerged (e: gone+not-merged)
        self.assertEqual(out["report"]["stale_count"], 1)
        self.assertEqual(out["report"]["gone_unmerged_count"], 1)
        _, decision = gov.call_args[0]
        self.assertEqual(decision["stale_count"], 1)
        self.assertEqual(decision["gone_unmerged_count"], 1)

        body = captured_body["body"]
        # The merged branch is the ONLY one offered as safe to clean.
        self.assertIn("`old/gone`", body)
        # The unmerged-but-gone branch must NOT be presented under the "safe to clean" header;
        # it belongs to the "Needs review" section instead.
        stale_header = "🧹 Stale"
        review_header = "🟡 Needs review"
        stale_idx = body.index(stale_header)
        review_idx = body.index(review_header)
        orphan_idx = body.index("🧭 Orphan")
        stale_section = body[stale_idx:review_idx]
        review_section = body[review_idx:orphan_idx]
        self.assertIn("old/gone", stale_section)
        self.assertNotIn("gone/unmerged", stale_section)
        self.assertIn("gone/unmerged", review_section)

    def test_report_is_fail_safe_when_digest_write_returns_empty(self):
        """write_local_digest never raises and may return '' — report still completes."""
        with mock.patch.object(a, "write_local_digest", return_value=""), \
             mock.patch.object(a, "governance_capture"):
            out = a.report({"findings": self._FINDINGS})
        self.assertEqual(out["report"]["digest"], "")


class GraphTests(unittest.TestCase):
    def test_graph_compiles_without_checkpointer(self):
        self.assertIsNotNone(a.graph)


if __name__ == "__main__":
    unittest.main()
