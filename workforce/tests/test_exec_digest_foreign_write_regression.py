"""REGRESSION: the exec/ops digest wiring must NOT mutate a FOREIGN issue under report_only.

The working-tree wiring made ``ops_report.file_digest_issue`` (the seam EVERY exec/CFO/CTO/
audit/ops/marketing/sales graph calls) DELEGATE to ``file_digest_record`` whenever ``agent`` is
set. That turned the seam from CREATE-ONLY (the pre-change path called ``open_issue`` with NO
``dedup_key`` — it could only file a fresh issue and could NEVER touch a pre-existing one) into
FIND-OR-UPDATE (``open_issue(dedup_key=...)`` scans the repo's OPEN issues and can comment on /
re-label one). RECORD writes skip the human gate under ``report_only=True`` by design.

The ONLY thing standing between a probation digest and a foreign-issue mutation is
``github_ops._is_fleet_owned_record``. With ``GITHUB_FLEET_LOGINS`` UNSET — the live deployed
posture (the var is referenced nowhere but github_ops.py and is set in no env/config) — that
guard's strong signal (author ∈ fleet-login allow-list) is inert, and ownership reduces to a
single label check: any open issue carrying the ``agent:<slug>`` label is treated as "ours".

A human routinely applies an ``agent:<slug>`` label when triaging a fleet digest into their own
thread; the invisible dedup marker is derivable from the (LLM-controlled) title. So a probation
CFO digest finds that human issue, judges it fleet-owned, and APPENDS a comment + adds labels —
with NO human gate. That is a foreign-issue write slipping through under report_only, i.e. the
HITL "never touch foreign state without sign-off" line moving.

These tests FAIL against the current code (documenting the regression). They should PASS once
the ownership guard is hardened so the label-fallback alone can never authorize mutating an
issue the fleet did not provably create (e.g. require fleet-login authorship for any find-or-
update; treat the label-only path as create-fresh, never comment-on-existing).

Run: <venv>/bin/python -m unittest tests.test_exec_digest_foreign_write_regression -v
"""
import os
import unittest
from unittest import mock

from agent_toolkit import github_ops as go
from agent_toolkit import ops_report
from agent_toolkit.ops_report import _title_kind
from tests.test_github_records import _make_issue, _make_client

REPO = "Scheduler-Systems/qa-agent-platform"
CFO_TITLE = "CFO: spend + budget allocation (proposal)"


class ExecDigestMustNotMutateForeignIssueUnderReportOnly(unittest.TestCase):
    def setUp(self):
        # The live deployed posture: no fleet-login allow-list configured.
        self._saved = os.environ.pop("GITHUB_FLEET_LOGINS", None)

    def tearDown(self):
        if self._saved is not None:
            os.environ["GITHUB_FLEET_LOGINS"] = self._saved

    def test_human_issue_with_triage_label_is_not_commented_on(self):
        """A HUMAN-authored issue carrying an ``agent:cfo`` triage label (and quoting the
        invisible marker) must be left UNTOUCHED by a probation CFO digest. Today it is mutated."""
        marker = go._record_marker(f"record:cfo:{_title_kind(CFO_TITLE)}")
        human = _make_issue(
            number=1487,
            body="# Human-owned thread: do not auto-edit\n" + marker,
            author="shay-human",
            labels=["agent:cfo"],  # human-applied triage label
        )
        created = []
        client, repo = _make_client(existing_issues=[human], created_holder=created)
        ops = go.GitHubOps(report_only=True, gh_client=client)
        with mock.patch("agent_toolkit.github_ops.GitHubOps", return_value=ops), \
             mock.patch.object(go, "request_approval") as gate, \
             mock.patch("agent_toolkit.slack_tool.post_digest", return_value={"status": "posted"}):
            out = ops_report.file_digest_issue(
                REPO, CFO_TITLE, "spend ok this shift", labels=["exec:cfo"],
                report_only=True, agent="cfo",
            )
        gate.assert_not_called()  # record path takes no human gate at all
        # The HITL invariant: a probation digest never mutates a foreign issue, and never
        # silently latches onto one — it should file its OWN fresh fleet record instead.
        self.assertEqual(len(human._comments), 0,
                         "FOREIGN-ISSUE WRITE: probation digest commented on a human-authored issue")
        self.assertEqual(human._labels, ["agent:cfo"],
                         "FOREIGN-ISSUE WRITE: probation digest re-labelled a human-authored issue")
        self.assertNotEqual(out.get("number"), 1487,
                            "FOREIGN-ISSUE WRITE: digest deduped onto the human issue #1487")

    def test_ghost_authored_issue_with_label_falls_through_login_allowlist(self):
        """Even WITH ``GITHUB_FLEET_LOGINS`` set (the intended-secure posture), a foreign issue
        whose author is unknown (deleted/ghost user → ``issue.user`` is None, or a minimal API
        payload) falls THROUGH the authoritative login check to the weaker label path and is
        mutated. The login allow-list must be authoritative, not bypassable by a missing author."""
        marker = go._record_marker(f"record:cfo:{_title_kind(CFO_TITLE)}")
        ghost = _make_issue(number=900, body="foreign\n" + marker, author=None,
                            labels=["agent:cfo"])
        ghost.user = None  # ghost/deleted author → _issue_author_login() returns None
        created = []
        client, repo = _make_client(existing_issues=[ghost], created_holder=created)
        ops = go.GitHubOps(report_only=True, gh_client=client)
        with mock.patch.dict(os.environ, {"GITHUB_FLEET_LOGINS": "scheduler-fleet[bot]"}, clear=False):
            with mock.patch("agent_toolkit.github_ops.GitHubOps", return_value=ops), \
                 mock.patch.object(go, "request_approval"), \
                 mock.patch("agent_toolkit.slack_tool.post_digest", return_value={"status": "posted"}):
                ops_report.file_digest_issue(
                    REPO, CFO_TITLE, "spend ok", labels=["exec:cfo"],
                    report_only=True, agent="cfo",
                )
        self.assertEqual(len(ghost._comments), 0,
                         "FALL-THROUGH: fleet-login allow-list set, yet a ghost-authored foreign "
                         "issue was mutated via the label fallback (line ~249 fall-through)")


class CodeActionsMustStillBeGated(unittest.TestCase):
    """SANITY (passes today): the wiring does NOT let PR/merge/push slip through. file_digest_record
    hardcodes action=open_issue, and CODE actions stay report-only plans under report_only."""

    def test_pr_branch_file_stay_report_only_plans(self):
        client, repo = _make_client()
        ops = go.GitHubOps(report_only=True, gh_client=client)
        with mock.patch.object(go, "request_approval") as gate:
            pr = ops.open_pr(REPO, "feat/x", "main", "t", "b")
            br = ops.create_branch(REPO, "feat/x")
            pf = ops.put_file(REPO, "feat/x", "f.py", "x", "m")
        gate.assert_not_called()
        repo.create_pull.assert_not_called()
        self.assertEqual(pr["status"], "report_only")
        self.assertEqual(br["status"], "report_only")
        self.assertEqual(pf["status"], "report_only")


if __name__ == "__main__":
    unittest.main()
