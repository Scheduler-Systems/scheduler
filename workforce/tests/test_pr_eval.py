"""Tests for the DETERMINISTIC pr_eval core (no langgraph, no network, no LLM).

pr_eval is the brain of the board's "agents decide on PRs" step. These tests pin the
load-bearing safety invariant — what is and is NOT auto-merge-safe — by driving the gather
layer with an INJECTED fake ``gh`` runner (so there is no network, no ``gh`` install needed).

We prove:
  (1) a production-repo PR targeting main → safe_to_automerge False + a gate_reason naming the
      prod-deploy/customer-facing merge (the HARD GATE);
  (2) a docs/tooling PR in a non-prod allow-listed repo with green CI + a clean merge state →
      safe_to_automerge True (the only auto-mergeable class);
  (3) a gate-relevant diff (e.g. firestore.rules / auth) is HELD even in a non-prod repo;
  (4) failing / pending / unknown CI is never auto-merge-safe;
  (5) the gather layer is injectable and tolerates gh failures → UNKNOWN, not a crash.

Run (no langgraph needed):
    PYTHONPATH=. python3 -m pytest tests/test_pr_eval.py -q
    # or, with no pytest:  PYTHONPATH=. python3 -m unittest tests.test_pr_eval -v
"""
from __future__ import annotations

import json
import unittest

from agent_toolkit import pr_eval


def _make_runner(view: dict, *, diff: str = "", checks: str = "", checks_rc: int = 0,
                 fail: set[str] | None = None):
    """Build a fake ``gh`` runner returning canned (rc, stdout) per subcommand.

    ``fail`` is a set of subcommands ("view"/"diff"/"checks") to simulate failing (rc=1).
    This is the seam that lets the test exercise the full decision with NO network.
    """
    fail = fail or set()

    def runner(args: list[str]) -> "tuple[int, str]":
        # args looks like ["pr", "view"/"diff"/"checks", "<n>", "--repo", ...]
        sub = args[1] if len(args) > 1 else ""
        if sub in fail:
            return 1, f"simulated gh {sub} failure"
        if sub == "view":
            return 0, json.dumps(view)
        if sub == "diff":
            return 0, diff
        if sub == "checks":
            return checks_rc, checks
        return 1, "unexpected"

    return runner


def _clean_view(**over) -> dict:
    """A green, clean, mergeable PR view; override fields per test."""
    v = {
        "number": 42,
        "title": "docs: improve quickstart",
        "body": "Small docs tidy-up.",
        "state": "OPEN",
        "isDraft": False,
        "baseRefName": "main",
        "headRefName": "docs/quickstart",
        "mergeable": "MERGEABLE",
        "mergeStateStatus": "CLEAN",
        "author": {"login": "someone"},
        "additions": 10,
        "deletions": 2,
        "changedFiles": 1,
        "files": [{"path": "docs/quickstart.md"}],
        "url": "https://github.com/x/y/pull/42",
        "labels": [],
    }
    v.update(over)
    return v


class ProductionRepoGate(unittest.TestCase):
    def test_prod_repo_main_is_held(self):
        """A PR to main of a PRODUCTION repo is NEVER auto-merge-safe (HARD GATE)."""
        view = _clean_view(
            number=1487,
            title="fix: schedule overlap",
            baseRefName="main",
            files=[{"path": "services/api/schedule.go"}],
        )
        runner = _make_runner(view, checks="schedule-test\tpass\n", checks_rc=0)
        res = pr_eval.evaluate_pr("Scheduler-Systems/scheduler-api", 1487, runner=runner)

        self.assertFalse(res["safe_to_automerge"])
        self.assertTrue(res["gate_reason"])
        self.assertIn("production repo", res["gate_reason"])
        self.assertEqual(res["pr"], 1487)
        self.assertEqual(res["repo"], "Scheduler-Systems/scheduler-api")


class DocsNonProdAutoMerge(unittest.TestCase):
    def test_docs_nonprod_green_is_safe(self):
        """A docs PR in a non-prod allow-listed repo, green CI + CLEAN merge → safe."""
        view = _clean_view(
            number=7,
            title="docs: tighten contributing guide",
            files=[{"path": "docs/contributing.md"}, {"path": "README.md"}],
        )
        runner = _make_runner(view, checks="lint\tpass\nbuild\tpass\n", checks_rc=0)
        res = pr_eval.evaluate_pr("Scheduler-Systems/qa-agent-platform", 7, runner=runner)

        self.assertTrue(res["safe_to_automerge"], res["gate_reason"])
        self.assertEqual(res["gate_reason"], "")
        self.assertEqual(res["blast_radius"], pr_eval.BLAST_LOW)
        self.assertIn(res["verdict"], pr_eval._NON_BLOCKING_VERDICTS)

    def test_tooling_tests_nonprod_green_is_safe(self):
        """A tooling/test-only PR (no gate paths) in a non-prod repo, green → safe."""
        view = _clean_view(
            number=8,
            title="chore: add unit tests for the scheduler helper",
            files=[{"path": "packages/core/helper_test.go"}, {"path": "docs/notes.md"}],
        )
        runner = _make_runner(view, checks="test\tpass\n", checks_rc=0)
        res = pr_eval.evaluate_pr("Scheduler-Systems/workspace-governance", 8, runner=runner)
        self.assertTrue(res["safe_to_automerge"], res["gate_reason"])


class GateRelevantDiffHeld(unittest.TestCase):
    def test_security_rules_diff_is_held_even_nonprod(self):
        """A diff touching firestore.rules is gate-relevant → HELD even in a non-prod repo."""
        view = _clean_view(
            number=9,
            title="chore: tweak rules",
            files=[{"path": "apps/web/firestore.rules"}],
        )
        runner = _make_runner(view, checks="rules-test\tpass\n", checks_rc=0)
        res = pr_eval.evaluate_pr("Scheduler-Systems/qa-agent-platform", 9, runner=runner)
        self.assertFalse(res["safe_to_automerge"])
        self.assertEqual(res["blast_radius"], pr_eval.BLAST_HIGH)
        self.assertIn("gate-relevant", res["gate_reason"])

    def test_auth_path_diff_is_held(self):
        view = _clean_view(number=10, files=[{"path": "apps/web/src/auth/login.ts"}])
        runner = _make_runner(view, checks="test\tpass\n", checks_rc=0)
        res = pr_eval.evaluate_pr("Scheduler-Systems/qa-agent-platform", 10, runner=runner)
        self.assertFalse(res["safe_to_automerge"])
        self.assertIn("gate-relevant", res["gate_reason"])


class CiAndMergeStateGuards(unittest.TestCase):
    def test_failing_ci_not_safe(self):
        view = _clean_view(number=11)
        runner = _make_runner(view, checks="lint\tfail\n", checks_rc=1)
        res = pr_eval.evaluate_pr("Scheduler-Systems/qa-agent-platform", 11, runner=runner)
        self.assertFalse(res["safe_to_automerge"])
        self.assertNotEqual(res["verdict"], pr_eval.VERDICT_APPROVE)

    def test_pending_ci_not_safe(self):
        view = _clean_view(number=12)
        runner = _make_runner(view, checks="build\tpending\n", checks_rc=1)
        res = pr_eval.evaluate_pr("Scheduler-Systems/qa-agent-platform", 12, runner=runner)
        self.assertFalse(res["safe_to_automerge"])

    def test_dirty_merge_state_not_safe(self):
        view = _clean_view(number=13, mergeStateStatus="DIRTY", mergeable="CONFLICTING")
        runner = _make_runner(view, checks="test\tpass\n", checks_rc=0)
        res = pr_eval.evaluate_pr("Scheduler-Systems/qa-agent-platform", 13, runner=runner)
        self.assertFalse(res["safe_to_automerge"])
        self.assertIn("not CLEAN", res["gate_reason"])

    def test_draft_not_safe(self):
        view = _clean_view(number=14, isDraft=True, mergeStateStatus="DRAFT")
        runner = _make_runner(view, checks="test\tpass\n", checks_rc=0)
        res = pr_eval.evaluate_pr("Scheduler-Systems/qa-agent-platform", 14, runner=runner)
        self.assertFalse(res["safe_to_automerge"])


class GatherFailSoft(unittest.TestCase):
    def test_gh_view_failure_is_unknown_not_crash(self):
        """A gh failure degrades to UNKNOWN/not-safe — never raises."""
        runner = _make_runner(_clean_view(), fail={"view", "diff", "checks"})
        res = pr_eval.evaluate_pr("Scheduler-Systems/qa-agent-platform", 99, runner=runner)
        self.assertFalse(res["safe_to_automerge"])
        self.assertEqual(res["verdict"], pr_eval.VERDICT_UNKNOWN)
        self.assertIn("pr_view_failed", res["evidence"])


if __name__ == "__main__":
    unittest.main()
