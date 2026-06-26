"""Records-vs-actions tests — the close-the-loop proof for the GitHub write surface.

The fleet captures <5% of its work in GitHub because every decision-grade digest is
report-only and Slack-only. The RECORD vs CODE boundary fixes this: a durable RECORD
(issue/comment) writes even under ``report_only=True`` (it is not an irreversible code
action), while CODE actions (open PR, merge, push) stay gated.

All tests inject a MOCKED GitHub client (``GitHubOps(gh_client=...)`` or ``file_digest_record``
with the github layer mocked) — NO real network, NO real writes.

Run: .venv/bin/python -m unittest tests.test_github_records -v
"""
import os
import unittest
from unittest import mock

from agent_toolkit import github_ops as go
from agent_toolkit import ops_report

# When a digest is filed via the seam WITHOUT an explicit ``report_only`` (None), the per-agent
# write gate decides. These seam tests exercise the WRITE path, so they run as a write-enabled
# agent: cfo on the allowlist with the global floor lifted (and the kill switch clocked-in).
_WRITE_ENABLED_CFO = {"AGENTS_WRITE_ENABLED": "cfo", "OPS_REPORT_ONLY": "0"}


class _Label:
    """A minimal stand-in for a pygithub Label (exposes ``.name``)."""
    def __init__(self, name):
        self.name = name


# --- Mock GitHub plumbing -------------------------------------------------------------
def _make_issue(number=1, body="", url="https://x/issues/1", labels=None, author="fleet[bot]"):
    """A mock pygithub Issue with body, comments list, author, and label tracking.

    ``labels`` seeds the issue's existing label names; ``author`` sets ``issue.user.login``
    (default a fleet-bot login) so the dedup find-or-update ownership check can recognize the
    issue as a fleet-owned record. ``_labels`` mirrors ``labels`` and ``add_to_labels`` keeps
    both in sync (so ``issue.labels`` reflects newly-added labels too).
    """
    issue = mock.Mock()
    issue.number = number
    issue.html_url = url
    issue.sha = None
    issue.merged = None
    issue.body = body
    issue._comments = []
    issue._labels = list(labels or [])
    issue.labels = [_Label(n) for n in issue._labels]
    issue.user = mock.Mock(); issue.user.login = author
    issue.create_comment.side_effect = lambda b: issue._comments.append(b) or mock.Mock(
        number=None, html_url=url + "#comment", sha=None, merged=None
    )

    def _edit(**kw):
        if "body" in kw:
            issue.body = kw["body"]
    issue.edit.side_effect = _edit

    def _add_label(lbl):
        issue._labels.append(lbl)
        issue.labels = [_Label(n) for n in issue._labels]
    issue.add_to_labels.side_effect = _add_label
    return issue


def _make_client(*, existing_issues=None, created_holder=None):
    """A mock ``Github`` client whose ``get_repo`` returns a repo backed by the given issues."""
    existing_issues = existing_issues or []
    client = mock.Mock()
    repo = mock.Mock()

    repo.get_issues.side_effect = lambda state="open": list(existing_issues)

    def _create_issue(title, body, labels):
        new = _make_issue(number=99, body=body, url="https://x/issues/99")
        new._labels = list(labels or [])
        if created_holder is not None:
            created_holder.append(new)
        return new
    repo.create_issue.side_effect = _create_issue

    def _get_issue(number):
        for i in existing_issues:
            if i.number == number:
                return i
        return _make_issue(number=number, url=f"https://x/issues/{number}")
    repo.get_issue.side_effect = _get_issue

    client.get_repo.return_value = repo
    return client, repo


REPO = "Scheduler-Systems/qa-agent-platform"


# --- 1. A RECORD writes even when report_only=True ------------------------------------
class RecordWritesUnderReportOnly(unittest.TestCase):
    def test_open_issue_record_writes_on_probation(self):
        created = []
        client, repo = _make_client(created_holder=created)
        ops = go.GitHubOps(report_only=True, gh_client=client)
        # Crucially: the human gate must NOT be entered for a record on probation.
        with mock.patch.object(go, "request_approval") as gate:
            out = ops.open_issue(REPO, "Daily CFO burn", "spend ok")
        gate.assert_not_called()                 # no approval interrupt
        repo.create_issue.assert_called_once()   # a REAL write happened
        self.assertEqual(out["status"], "done")  # not "report_only"
        self.assertEqual(len(created), 1)


# --- 2. A CODE action stays BLOCKED when report_only=True -----------------------------
class CodeActionBlockedUnderReportOnly(unittest.TestCase):
    def test_open_pr_is_report_only_no_write_no_gate(self):
        client, repo = _make_client()
        ops = go.GitHubOps(report_only=True, gh_client=client)
        with mock.patch.object(go, "request_approval") as gate:
            out = ops.open_pr(REPO, "feat/x", "main", "t", "b")
        gate.assert_not_called()
        repo.create_pull.assert_not_called()     # NO code write on probation
        self.assertEqual(out["status"], "report_only")
        self.assertEqual(out["action"], "open_pr")

    def test_put_file_is_report_only_on_probation(self):
        client, repo = _make_client()
        ops = go.GitHubOps(report_only=True, gh_client=client)
        out = ops.put_file(REPO, "feat/x", "a.txt", "data", "msg")
        self.assertEqual(out["status"], "report_only")
        repo.create_file.assert_not_called()
        repo.update_file.assert_not_called()


# --- 3. Dedup UPDATES the existing issue (one issue, +1 comment) ----------------------
class DedupFindOrUpdate(unittest.TestCase):
    def test_dedup_updates_existing_instead_of_creating(self):
        key = "record:cfo:burn"
        marker = go._record_marker(key)
        # A fleet-owned record carries BOTH the marker AND the agent attribution label.
        existing = _make_issue(
            number=7, body=f"old body\n{marker}", url="https://x/issues/7", labels=["agent:cfo"]
        )
        created = []
        client, repo = _make_client(existing_issues=[existing], created_holder=created)
        ops = go.GitHubOps(report_only=True, gh_client=client)

        out = ops.open_issue(REPO, "CFO burn", "new spend report", dedup_key=key, agent="cfo")

        # No second issue created; the existing one gets exactly one new comment (append-only).
        repo.create_issue.assert_not_called()
        self.assertEqual(len(created), 0)
        self.assertEqual(len(existing._comments), 1)
        # Append-only: the prior body is NEVER wholesale-overwritten on dedup.
        existing.edit.assert_not_called()
        self.assertIn("old body", existing.body)
        self.assertTrue(out["deduped"])
        self.assertEqual(out["number"], 7)

    def test_dedup_creates_when_no_existing_marker(self):
        key = "record:cfo:burn"
        # An open issue WITHOUT the marker must not be mistaken for the record.
        other = _make_issue(number=3, body="unrelated open issue")
        created = []
        client, repo = _make_client(existing_issues=[other], created_holder=created)
        ops = go.GitHubOps(report_only=True, gh_client=client)

        out = ops.open_issue(REPO, "CFO burn", "first report", dedup_key=key)

        repo.create_issue.assert_called_once()
        self.assertEqual(len(created), 1)
        self.assertFalse(out["deduped"])
        # The new issue body carries the hidden marker so the next shift will find it.
        self.assertIn(go._record_marker(key), created[0].body)


# --- 4. Per-agent label is applied ----------------------------------------------------
class PerAgentLabel(unittest.TestCase):
    def test_agent_label_added_on_create(self):
        created = []
        client, repo = _make_client(created_holder=created)
        ops = go.GitHubOps(report_only=True, gh_client=client)
        ops.open_issue(REPO, "t", "b", agent="cfo")
        _, kwargs = repo.create_issue.call_args
        self.assertIn("agent:cfo", kwargs["labels"])

    def test_agent_label_added_on_dedup_update(self):
        key = "record:cto:ci"
        # Owned via fleet-login authorship (no agent label yet) — the label must be added on update.
        existing = _make_issue(number=8, body=f"x\n{go._record_marker(key)}", author="fleet[bot]")
        client, repo = _make_client(existing_issues=[existing])
        ops = go.GitHubOps(report_only=True, gh_client=client)
        with mock.patch.dict("os.environ", {"GITHUB_FLEET_LOGINS": "fleet[bot]"}):
            ops.open_issue(REPO, "t", "b", dedup_key=key, agent="cto")
        self.assertIn("agent:cto", existing._labels)

    def test_agent_label_slug_sanitized(self):
        self.assertEqual(go.agent_label("audit_risk_director"), "agent:audit_risk_director")
        self.assertEqual(go.agent_label("CFO"), "agent:cfo")


# --- 5. Cross-link reference is rendered ----------------------------------------------
class CrossLinkRendering(unittest.TestCase):
    def test_related_refs_rendered_into_body(self):
        created = []
        client, repo = _make_client(created_holder=created)
        ops = go.GitHubOps(report_only=True, gh_client=client)
        ops.open_issue(REPO, "t", "body", related=[42, "#7", "Scheduler-Systems/scheduler-web#3"])
        body = created[0].body
        self.assertIn("Related:", body)
        self.assertIn("#42", body)
        self.assertIn("#7", body)
        self.assertIn("Scheduler-Systems/scheduler-web#3", body)

    def test_comment_on_pr_renders_related(self):
        existing = _make_issue(number=116)
        client, repo = _make_client(existing_issues=[existing])
        ops = go.GitHubOps(report_only=True, gh_client=client)
        ops.comment_on_pr(REPO, 116, "LGTM with a nit", related=[12])
        self.assertEqual(len(existing._comments), 1)
        self.assertIn("#12", existing._comments[0])


# --- 6. comment_on_pr posts -----------------------------------------------------------
class CommentOnPr(unittest.TestCase):
    def test_comment_on_pr_posts_under_report_only(self):
        existing = _make_issue(number=116, url="https://x/pull/116")
        client, repo = _make_client(existing_issues=[existing])
        ops = go.GitHubOps(report_only=True, gh_client=client)
        with mock.patch.object(go, "request_approval") as gate:
            out = ops.comment_on_pr(REPO, 116, "fleet review: passes")
        gate.assert_not_called()                       # record → no gate
        repo.get_issue.assert_called_once_with(116)    # PR conversation = issue timeline
        self.assertEqual(len(existing._comments), 1)
        self.assertEqual(out["status"], "done")


# --- 7. Fail-safe — a raising client never reaches the caller (file_digest_record) ----
class FailSafe(unittest.TestCase):
    def test_record_seam_swallows_client_exception(self):
        boom = mock.Mock()
        boom.get_repo.side_effect = RuntimeError("network down")
        ops = go.GitHubOps(report_only=True, gh_client=boom)
        # Patch the seam's GitHubOps to use our exploding client, and stub Slack. cfo is
        # write-enabled (None report_only ⇒ gate decides ⇒ real write attempt that then fails).
        with mock.patch.dict(os.environ, _WRITE_ENABLED_CFO), \
             mock.patch.object(ops_report, "post_digest", return_value={"status": "no_credentials"}, create=True), \
             mock.patch("agent_toolkit.github_ops.GitHubOps", return_value=ops):
            out = ops_report.file_digest_record(
                REPO, "t", "b", agent="cfo", record_kind="burn"
            )
        # No exception propagated; caller got a structured status dict.
        self.assertIn(out["status"], ("error", "blocked"))

    def test_record_seam_blocked_status_on_write_blocked(self):
        # An unlisted repo → GitHubWriteBlocked inside open_issue → seam returns blocked.
        out = ops_report.file_digest_record(
            "Scheduler-Systems/not-allow-listed", "t", "b",
            agent="cfo", record_kind="burn", report_only=True,
        )
        self.assertEqual(out["status"], "blocked")

    def test_record_seam_mirrors_to_slack(self):
        created = []
        client, repo = _make_client(created_holder=created)
        ops = go.GitHubOps(report_only=True, gh_client=client)
        with mock.patch.dict(os.environ, _WRITE_ENABLED_CFO), \
             mock.patch("agent_toolkit.github_ops.GitHubOps", return_value=ops), \
             mock.patch("agent_toolkit.slack_tool.post_digest", return_value={"status": "posted"}):
            out = ops_report.file_digest_record(
                REPO, "CFO burn", "spend ok", agent="cfo", record_kind="burn", related=[5],
            )
        self.assertEqual(out["status"], "done")
        self.assertEqual(out["slack"], "posted")
        self.assertTrue(out["deduped"] is False)       # first file → created, not deduped
        self.assertIn("agent:cfo", created[0]._labels)
        self.assertIn("#5", created[0].body)


# --- 8. HITL-line: the dedup RECORD lane must NEVER overwrite a FOREIGN issue ----------
class RecordBoundaryDoesNotOverwriteForeignIssue(unittest.TestCase):
    """Regression for the record-vs-action boundary bypass: a probation/report_only record
    must not latch onto and overwrite a human-authored issue that merely carries the (invisible,
    caller-controlled) dedup marker. No approval gate is entered for a record, so the ONLY thing
    protecting foreign durable state is the ownership check — assert it holds."""

    def test_dedup_does_not_touch_human_issue_with_same_marker(self):
        key = "cfo:burn"
        marker = go._record_marker(key)
        human_body = (
            "# SECURITY: live Firestore IDOR still open in prod\n"
            "Repro steps, customer impact, owner=shay …\n" + marker
        )
        # A HUMAN-authored issue: human login, no agent attribution label.
        human = _make_issue(number=1487, body=human_body, author="shay-human", labels=[])
        created = []
        client, repo = _make_client(existing_issues=[human], created_holder=created)
        ops = go.GitHubOps(report_only=True, gh_client=client)

        with mock.patch.object(go, "request_approval") as gate:
            out = ops.open_issue(
                REPO, "CFO daily burn", "spend ok this shift", dedup_key=key, agent="cfo"
            )

        gate.assert_not_called()  # record → no gate (so ownership is the only guard)
        # The human issue body is untouched and got no comment.
        self.assertIn("SECURITY: live Firestore IDOR", human.body)
        self.assertEqual(len(human._comments), 0)
        human.edit.assert_not_called()
        # A fresh fleet record was filed instead of mutating #1487.
        repo.create_issue.assert_called_once()
        self.assertEqual(len(created), 1)
        self.assertNotEqual(out.get("number"), 1487)

    def test_dedup_ignores_marker_without_agent_label_when_no_fleet_logins(self):
        # An issue carrying the marker but NOT the agent label (and no GITHUB_FLEET_LOGINS set)
        # is not provably fleet-owned → never edited; a new record is filed.
        key = "record:cfo:burn"
        unowned = _make_issue(number=5, body=f"quoted digest\n{go._record_marker(key)}", labels=[])
        created = []
        client, repo = _make_client(existing_issues=[unowned], created_holder=created)
        ops = go.GitHubOps(report_only=True, gh_client=client)
        out = ops.open_issue(REPO, "CFO burn", "report", dedup_key=key, agent="cfo")
        repo.create_issue.assert_called_once()
        self.assertEqual(len(unowned._comments), 0)
        self.assertFalse(out["deduped"])

    def test_fleet_login_authorship_authorizes_dedup_update(self):
        # With GITHUB_FLEET_LOGINS set, a fleet-authored issue IS the record → updated in place.
        key = "record:cfo:burn"
        owned = _make_issue(number=9, body=f"prior\n{go._record_marker(key)}", author="fleet[bot]")
        client, repo = _make_client(existing_issues=[owned])
        ops = go.GitHubOps(report_only=True, gh_client=client)
        with mock.patch.dict("os.environ", {"GITHUB_FLEET_LOGINS": "fleet[bot]"}):
            out = ops.open_issue(REPO, "CFO burn", "new report", dedup_key=key, agent="cfo")
        repo.create_issue.assert_not_called()
        self.assertTrue(out["deduped"])
        self.assertEqual(out["number"], 9)
        self.assertIn("prior", owned.body)  # append-only, body preserved


# --- 9. Comment-storm guard: no new comment when the record content is unchanged --------
class DedupCommentStormGuard(unittest.TestCase):
    def test_unchanged_content_does_not_append_a_comment(self):
        key = "record:git_maintainer:branch-review"
        body = "3 branches needing review"
        marker = go._record_marker(key)
        existing = _make_issue(
            number=11,
            body=f"{body}\n\n{marker}",  # body already contains the digest text
            labels=["agent:git_maintainer"],
        )
        client, repo = _make_client(existing_issues=[existing])
        ops = go.GitHubOps(report_only=True, gh_client=client)
        out = ops.open_issue(REPO, "git-maintainer", body, dedup_key=key, agent="git_maintainer")
        repo.create_issue.assert_not_called()
        self.assertTrue(out["deduped"])
        self.assertEqual(len(existing._comments), 0)  # no comment-storm on unchanged content

    def test_changed_content_does_append_a_comment(self):
        key = "record:git_maintainer:branch-review"
        marker = go._record_marker(key)
        existing = _make_issue(
            number=12, body=f"old: 1 branch\n\n{marker}", labels=["agent:git_maintainer"]
        )
        client, repo = _make_client(existing_issues=[existing])
        ops = go.GitHubOps(report_only=True, gh_client=client)
        ops.open_issue(REPO, "git-maintainer", "new: 5 branches", dedup_key=key, agent="git_maintainer")
        self.assertEqual(len(existing._comments), 1)


# --- 10. Attribution: file_digest_issue forwards the per-agent label to GitHub ----------
class FileDigestIssueAttribution(unittest.TestCase):
    def test_agent_label_applied_via_file_digest_issue(self):
        created = []
        client, repo = _make_client(created_holder=created)
        ops = go.GitHubOps(report_only=True, gh_client=client)
        with mock.patch("agent_toolkit.github_ops.GitHubOps", return_value=ops), \
             mock.patch("agent_toolkit.slack_tool.post_digest", return_value={"status": "posted"}):
            out = ops_report.file_digest_issue(
                REPO, "CFO daily burn", "spend ok", labels=["exec:cfo"],
                report_only=True, agent="cfo",
            )
        self.assertEqual(out["status"], "done")
        # The filed issue carries BOTH the hand-passed static label AND the attribution label.
        self.assertIn("exec:cfo", created[0]._labels)
        self.assertIn(go.agent_label("cfo"), created[0]._labels)  # "agent:cfo"

    def test_no_agent_means_no_attribution_label(self):
        created = []
        client, repo = _make_client(created_holder=created)
        ops = go.GitHubOps(report_only=True, gh_client=client)
        with mock.patch("agent_toolkit.github_ops.GitHubOps", return_value=ops):
            ops_report.file_digest_issue(REPO, "t", "b", labels=["x"], report_only=True)
        self.assertNotIn("agent:unknown", created[0]._labels)
        self.assertEqual(created[0]._labels, ["x"])


# --- 11. git_maintainer report() passes a dedup_key (Fix 2) -----------------------------
class GitMaintainerDedup(unittest.TestCase):
    def test_report_passes_dedup_key_and_agent(self):
        from graphs.qa import git_maintainer as gm
        fake = mock.Mock()
        fake.open_issue.return_value = {"status": "done", "number": 1, "html_url": "u"}
        state = {
            "repos": [REPO], "pruned": [], "errors": [],
            "proposals": [{"repo": REPO, "branch": "feat/orphan", "sha": "cccccccc",
                           "reason": "no PR for branch"}],
        }
        with mock.patch.object(gm, "GitHubOps", return_value=fake), \
             mock.patch.object(gm, "governance_capture"):
            gm.report(state)
        fake.open_issue.assert_called_once()
        _a, kwargs = fake.open_issue.call_args
        self.assertIsNotNone(kwargs.get("dedup_key"),
                             f"report() filed digest WITHOUT a dedup_key (#33/#35/#43). kwargs={kwargs}")
        self.assertEqual(kwargs.get("agent"), "git_maintainer")

    def test_two_shifts_do_not_create_two_issues(self):
        from graphs.qa import git_maintainer as gm
        store = {"issues": []}
        repo = mock.Mock()
        repo.get_issues.side_effect = lambda state="open": list(store["issues"])

        def _create_issue(title, body, labels):
            iss = _make_issue(number=len(store["issues"]) + 100, body=body,
                              labels=list(labels or []), author="fleet[bot]")
            store["issues"].append(iss)
            return iss
        repo.create_issue.side_effect = _create_issue
        client = mock.Mock(); client.get_repo.return_value = repo

        def _ops_factory(*a, **k):
            return go.GitHubOps(report_only=True, gh_client=client)

        state = {
            "repos": [REPO], "pruned": [], "errors": [],
            "proposals": [{"repo": REPO, "branch": "feat/orphan", "sha": "cccccccc",
                           "reason": "no PR for branch"}],
        }
        with mock.patch.object(gm, "GitHubOps", _ops_factory), \
             mock.patch.object(gm, "governance_capture"):
            gm.report(state)  # shift 1 → creates the one issue
            gm.report(state)  # shift 2 → must find-or-update, NOT create a second
        self.assertEqual(len(store["issues"]), 1,
                         f"filed {len(store['issues'])} issues across 2 shifts; expected 1 (find-or-update).")


if __name__ == "__main__":
    unittest.main()
