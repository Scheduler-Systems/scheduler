"""Regression: the per-agent attribution label must reach GitHub on the file_digest_issue path.

Every C-suite / board graph delivers through ``ops_report.file_digest_issue(..., agent="cfo")``
(see graphs/exec/*.py, graphs/board/*.py). The whole point of ``github_ops.agent_label`` is the
"missing who" — so an issue filed by the CFO can be told apart from one filed by the CTO via the
``agent:<slug>`` label.

``file_digest_record`` forwards ``agent=`` into ``open_issue`` (and test_github_records covers it),
but ``file_digest_issue`` accepts ``agent=`` and uses it ONLY for Slack routing — it never passes
it to ``open_issue``. Result: on the path every exec/board agent actually uses, the GitHub issue
carries NO per-agent attribution label, and CFO is indistinguishable from CTO at the label level.

This test injects a mocked GitHub client (no network, no real writes) and asserts the label lands.

Run: ../../.venv/bin/python -m unittest tests.test_attribution_file_digest_issue -v
"""
import unittest
from unittest import mock

from agent_toolkit import github_ops as go
from agent_toolkit import ops_report


REPO = "Scheduler-Systems/qa-agent-platform"


def _make_client(created_holder):
    """Mock Github client: get_repo().create_issue() records the created issue's labels."""
    client = mock.Mock()
    repo = mock.Mock()
    repo.get_issues.side_effect = lambda state="open": []

    def _create_issue(title, body, labels):
        issue = mock.Mock()
        issue.number = 99
        issue.html_url = "https://x/issues/99"
        issue.sha = None
        issue.merged = None
        issue.body = body
        issue._labels = list(labels or [])
        created_holder.append(issue)
        return issue

    repo.create_issue.side_effect = _create_issue
    client.get_repo.return_value = repo
    return client


class FileDigestIssueAppliesAgentLabel(unittest.TestCase):
    def test_agent_label_reaches_github_on_file_digest_issue_path(self):
        """A CFO digest filed via file_digest_issue(agent='cfo') must carry the agent:cfo label."""
        created = []
        client = _make_client(created)
        ops = go.GitHubOps(report_only=True, gh_client=client)

        # Route the seam's GitHubOps to our injected mock client; stub Slack so it is a no-op.
        with mock.patch("agent_toolkit.github_ops.GitHubOps", return_value=ops), \
             mock.patch("agent_toolkit.slack_tool.post_digest", return_value={"status": "posted"}):
            out = ops_report.file_digest_issue(
                REPO,
                "CFO: spend + budget allocation (proposal)",
                "spend ok",
                labels=["exec:cfo"],
                report_only=True,
                agent="cfo",
            )

        # A real (mocked) write happened — this is the close-the-loop, not a report-only plan.
        self.assertEqual(out.get("status"), "done")
        self.assertEqual(len(created), 1, "expected exactly one issue created")

        labels = created[0]._labels
        # The whole point of agent attribution: CFO is distinguishable from CTO via this label.
        self.assertIn(
            go.agent_label("cfo"), labels,
            f"per-agent attribution label missing from the filed issue; labels={labels!r}. "
            "file_digest_issue accepts agent= but never forwards it to open_issue, so the "
            "agent:<slug> 'who did this' label is dropped on the exec/board delivery path.",
        )


if __name__ == "__main__":
    unittest.main()
