"""Close-the-loop for the EXEC/OPS digest path — ``ops_report.file_digest_issue``.

Every C-suite / board / ops / marketing graph delivers its digest through
``ops_report.file_digest_issue(..., agent="cfo", report_only=True)``. Historically that path
forwarded ``agent=`` for Slack routing + the attribution label but did NOT pass a ``dedup_key``,
so each shift filed a BRAND-NEW GitHub issue (the #33/#35/#43 duplicate spam) — and worse, when
the prior behaviour suppressed the GitHub write entirely the exec decisions were lost to Slack.

After wiring, ``file_digest_issue`` delegates to the durable RECORD path (``file_digest_record``):

  * the digest is captured as a durable GitHub issue EVEN under ``report_only=True`` (a record is
    not an irreversible code action — the HITL line is unchanged);
  * it is DEDUPED per ``(agent, kind)`` so re-runs UPDATE the same issue instead of duplicating;
  * Slack delivery is preserved (the digest is still mirrored to the agent's channel);
  * CODE actions (open PR / merge / push) STAY gated under report_only; and
  * the find-or-update is authorship-guarded so a record can never overwrite a human issue.

All tests inject a MOCKED GitHub client — NO real network, NO real writes.

Run: ../../.venv/bin/python -m unittest tests.test_exec_digest_records -v
"""
import unittest
from unittest import mock

from agent_toolkit import github_ops as go
from agent_toolkit import ops_report

# Reuse the mock GitHub plumbing from the records test (same _make_issue/_make_client semantics).
from tests.test_github_records import _make_issue, _make_client


REPO = "Scheduler-Systems/qa-agent-platform"
CFO_TITLE = "CFO: spend + budget allocation (proposal)"


def _make_growing_client(store):
    """A mock Github client whose repo's OPEN issues are ``store`` and whose ``create_issue``
    APPENDS to ``store`` — so an issue filed on shift 1 is visible to shift 2's find-or-update.

    Created issues carry the fleet-bot author + the composed (marker-carrying) body + the passed
    labels mirrored into BOTH ``_labels`` and ``.labels`` (so the label-attribution ownership
    check sees them, exactly like the deployed surface)."""
    repo = mock.Mock()
    repo.get_issues.side_effect = lambda state="open": list(store)

    def _create_issue(title, body, labels):
        iss = _make_issue(number=len(store) + 100, body=body,
                          labels=list(labels or []), author="fleet[bot]")
        store.append(iss)
        return iss
    repo.create_issue.side_effect = _create_issue
    client = mock.Mock()
    client.get_repo.return_value = repo
    return client, repo


class ExecDigestWritesDedupedRecordUnderReportOnly(unittest.TestCase):
    """A CFO/exec digest via file_digest_issue(report_only=True) writes a deduped GitHub record
    AND still posts Slack — the close-the-loop that ends Slack-only exec decisions."""

    def test_exec_digest_writes_record_and_posts_slack(self):
        created = []
        client, repo = _make_client(created_holder=created)
        ops = go.GitHubOps(report_only=True, gh_client=client)
        with mock.patch("agent_toolkit.github_ops.GitHubOps", return_value=ops), \
             mock.patch.object(go, "request_approval") as gate, \
             mock.patch("agent_toolkit.slack_tool.post_digest", return_value={"status": "posted"}):
            out = ops_report.file_digest_issue(
                REPO, CFO_TITLE, "spend ok this shift",
                labels=["exec:cfo"], report_only=True, agent="cfo",
                slack_title="💰 CFO update",
            )
        # A durable record was written on probation — NOT a report-only plan.
        gate.assert_not_called()                  # record → no approval interrupt
        repo.create_issue.assert_called_once()    # a REAL (mocked) write happened
        self.assertEqual(out["status"], "done")
        # Slack delivery preserved.
        self.assertEqual(out["slack"], "posted")
        # Per-agent attribution label reaches GitHub (CFO distinguishable from CTO).
        self.assertIn("exec:cfo", created[0]._labels)
        self.assertIn(go.agent_label("cfo"), created[0]._labels)  # agent:cfo
        # The issue carries the hidden dedup marker so the NEXT shift finds-or-updates it.
        from agent_toolkit.ops_report import _title_kind
        marker = go._record_marker(f"record:cfo:{_title_kind(CFO_TITLE)}")
        self.assertIn(marker, created[0].body)

    def test_dedup_key_is_stable_per_agent_and_kind_across_reruns(self):
        """Two shifts of the SAME exec digest must produce ONE issue (find-or-update), not two."""
        # One shared list = the repo's open issues AND the created-issue holder, so an issue
        # created on shift 1 is visible (and find-or-updatable) on shift 2. _make_client's
        # _create_issue stamps the fleet-bot author + composed (marker-carrying) body.
        issues = []
        client, repo = _make_growing_client(issues)
        # One stateless ops instance reused across both shifts (built from the REAL class BEFORE
        # patching, so the seam's `GitHubOps(...)` resolves to this instance — not a recursion).
        ops = go.GitHubOps(report_only=True, gh_client=client)

        with mock.patch("agent_toolkit.github_ops.GitHubOps", return_value=ops), \
             mock.patch("agent_toolkit.slack_tool.post_digest", return_value={"status": "posted"}):
            out1 = ops_report.file_digest_issue(
                REPO, CFO_TITLE, "shift 1: spend ok", labels=["exec:cfo"],
                report_only=True, agent="cfo",
            )
            out2 = ops_report.file_digest_issue(
                REPO, CFO_TITLE, "shift 2: spend up 4%", labels=["exec:cfo"],
                report_only=True, agent="cfo",
            )
        self.assertEqual(len(issues), 1,
                         f"filed {len(issues)} issues across 2 shifts; expected 1 (dedup).")
        self.assertFalse(out1["deduped"])   # shift 1 → created
        self.assertTrue(out2["deduped"])    # shift 2 → found-and-updated
        # The single issue got exactly one update comment (shift 2's changed content).
        self.assertEqual(len(issues[0]._comments), 1)
        self.assertIn("shift 2", issues[0]._comments[0])

    def test_distinct_kinds_for_same_agent_do_not_collide(self):
        """A stable kind per (agent, title): two DIFFERENT digests by one agent stay separate."""
        issues = []
        client, repo = _make_growing_client(issues)
        ops = go.GitHubOps(report_only=True, gh_client=client)

        with mock.patch("agent_toolkit.github_ops.GitHubOps", return_value=ops), \
             mock.patch("agent_toolkit.slack_tool.post_digest", return_value={"status": "posted"}):
            ops_report.file_digest_issue(REPO, CFO_TITLE, "burn", agent="cfo", report_only=True)
            ops_report.file_digest_issue(REPO, "CFO: weekly forecast", "forecast",
                                         agent="cfo", report_only=True)
        # Two distinct kinds → two distinct issues (no false-merge).
        self.assertEqual(len(issues), 2)


class ExecDigestExplicitRecordKind(unittest.TestCase):
    def test_explicit_record_kind_overrides_title_slug(self):
        created = []
        client, repo = _make_client(created_holder=created)
        ops = go.GitHubOps(report_only=True, gh_client=client)
        with mock.patch("agent_toolkit.github_ops.GitHubOps", return_value=ops), \
             mock.patch("agent_toolkit.slack_tool.post_digest", return_value={"status": "posted"}):
            ops_report.file_digest_issue(
                REPO, CFO_TITLE, "spend ok", agent="cfo", report_only=True,
                record_kind="cfo-burn",
            )
        self.assertIn(go._record_marker("record:cfo:cfo-burn"), created[0].body)

    def test_related_refs_cross_linked_on_exec_path(self):
        created = []
        client, repo = _make_client(created_holder=created)
        ops = go.GitHubOps(report_only=True, gh_client=client)
        with mock.patch("agent_toolkit.github_ops.GitHubOps", return_value=ops), \
             mock.patch("agent_toolkit.slack_tool.post_digest", return_value={"status": "posted"}):
            ops_report.file_digest_issue(
                REPO, "Audit-Risk: weekly review", "IDOR still open in prod",
                agent="audit_risk_director", report_only=True,
                related=[1487, "Scheduler-Systems/scheduler-api#21"],
            )
        body = created[0].body
        self.assertIn("Related:", body)
        self.assertIn("#1487", body)
        self.assertIn("Scheduler-Systems/scheduler-api#21", body)


class ExecDigestKeepsHitlLineIntact(unittest.TestCase):
    """The wiring must NOT move the HITL line: records write on probation, CODE stays gated."""

    def test_code_action_still_blocked_under_report_only(self):
        # Routing the exec DIGEST to records must not relax CODE actions: open_pr stays a plan.
        client, repo = _make_client()
        ops = go.GitHubOps(report_only=True, gh_client=client)
        with mock.patch.object(go, "request_approval") as gate:
            out = ops.open_pr(REPO, "feat/x", "main", "t", "b")
        gate.assert_not_called()
        repo.create_pull.assert_not_called()
        self.assertEqual(out["status"], "report_only")
        self.assertEqual(out["action"], "open_pr")

    def test_exec_digest_does_not_overwrite_human_issue_with_same_marker(self):
        """Authorship guard holds on the exec path: a probation digest can't latch onto and
        overwrite a human-authored issue that merely carries the (invisible) dedup marker."""
        from agent_toolkit.ops_report import _title_kind
        key = f"record:cfo:{_title_kind(CFO_TITLE)}"
        marker = go._record_marker(key)
        human = _make_issue(
            number=1487,
            body="# SECURITY: live Firestore IDOR still open in prod\nowner=shay …\n" + marker,
            author="shay-human", labels=[],
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
        gate.assert_not_called()  # record → no gate, so ownership is the only guard
        # The human issue is untouched: no comment, no body edit.
        self.assertIn("SECURITY: live Firestore IDOR", human.body)
        self.assertEqual(len(human._comments), 0)
        human.edit.assert_not_called()
        # A fresh fleet record was filed instead of mutating #1487.
        repo.create_issue.assert_called_once()
        self.assertEqual(len(created), 1)
        self.assertNotEqual(out.get("number"), 1487)


class FileDigestIssueSignatureBackwardCompatible(unittest.TestCase):
    """The public signature stays a backward-compatible superset of the original."""

    def test_original_positional_and_keyword_call_still_works(self):
        created = []
        client, repo = _make_client(created_holder=created)
        ops = go.GitHubOps(report_only=True, gh_client=client)
        with mock.patch("agent_toolkit.github_ops.GitHubOps", return_value=ops), \
             mock.patch("agent_toolkit.slack_tool.post_digest", return_value={"status": "posted"}):
            # The exact call shape every existing exec/ops graph uses today.
            out = ops_report.file_digest_issue(
                REPO, "CTO: tech posture", "all green",
                labels=["exec:cto"], report_only=_TRUE(), agent="cto",
                slack_title="CTO posture",
            )
        self.assertEqual(out["status"], "done")
        self.assertEqual(out["slack"], "posted")

    def test_no_agent_keeps_single_issue_path_and_no_slack(self):
        # Without an agent there is no provable ownership → keep the original non-deduped path
        # (no dedup marker latching) and NO Slack post (matches the original behaviour).
        created = []
        client, repo = _make_client(created_holder=created)
        ops = go.GitHubOps(report_only=True, gh_client=client)
        slack = mock.Mock(return_value={"status": "posted"})
        with mock.patch("agent_toolkit.github_ops.GitHubOps", return_value=ops), \
             mock.patch("agent_toolkit.slack_tool.post_digest", slack):
            out = ops_report.file_digest_issue(REPO, "anon digest", "body", labels=["x"],
                                               report_only=True)
        self.assertEqual(out["status"], "done")
        slack.assert_not_called()                      # no agent → no Slack (unchanged)
        self.assertEqual(created[0]._labels, ["x"])    # no attribution label injected
        self.assertNotIn("slack", out)


def _TRUE():
    return True


if __name__ == "__main__":
    unittest.main()
