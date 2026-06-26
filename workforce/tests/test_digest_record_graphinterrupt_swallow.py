"""Regression: the GitHub-record write must NOT swallow LangGraph's HITL pause signal.

Context (the Slack-additivity / fail-safe review of ``ops_report``):
Every exec/board/ops/marketing agent now delivers its digest through
``file_digest_issue(..., agent=...) -> file_digest_record(...)``. That seam wraps the
GitHub write in a broad ``except Exception`` so that a *real* GitHub failure (network /
not-configured / write-blocked) cannot abort the subsequent Slack post — the digest must
still reach Slack. That part is correct and desirable.

The bug: ``langgraph``'s ``interrupt()`` (used by ``approval.request_approval`` for the
human-in-the-loop gate) signals a pause by RAISING ``GraphInterrupt`` — and
``GraphInterrupt`` is a subclass of ``Exception``. So when a non-probation agent files a
RECORD that needs human approval, the GitHub block's ``except Exception`` CATCHES the
interrupt, turns it into ``{"status": "error", "error": "GraphInterrupt"}``, and then
posts to Slack and returns normally. Two consequences:

  1. The graph never pauses — the HITL approval gate is silently defeated.
  2. The agent posts to Slack as if everything was fine, even though no human approved and
     no record was written.

A control-flow signal like ``GraphInterrupt`` must propagate so the runtime can pause the
run; the broad catch must exclude it (catch ``Exception`` but re-raise ``GraphBubbleUp`` /
``GraphInterrupt``, or catch the concrete GitHub error types only).

Run: ../../.venv/bin/python -m unittest tests.test_digest_record_graphinterrupt_swallow -v
"""
import os
import unittest
from unittest import mock

from langgraph.errors import GraphInterrupt
from langgraph.types import Interrupt

from agent_toolkit import github_ops as go
from agent_toolkit import ops_report
from tests.test_github_records import _make_client


REPO = "Scheduler-Systems/qa-agent-platform"

# The seam consults the per-agent write gate whenever ``report_only`` is not an explicit True.
# These tests exercise the WRITE path (HITL gate / real error swallow), so cfo is write-enabled.
_WRITE_ENABLED_CFO = {"AGENTS_WRITE_ENABLED": "cfo", "OPS_REPORT_ONLY": "0"}


def _raise_interrupt(action, payload, *, risk="high"):
    """Stand in for ``request_approval`` inside a running graph: raise GraphInterrupt to pause."""
    raise GraphInterrupt((Interrupt(value={"action": action, "payload": payload}, id="x"),))


class GitHubRecordMustNotSwallowGraphInterrupt(unittest.TestCase):
    def test_approval_interrupt_propagates_through_file_digest_record(self):
        """A non-probation RECORD write hits the human gate; the resulting GraphInterrupt must
        bubble OUT of ``file_digest_record`` (so the graph pauses) — not be caught as a generic
        'github error' that then proceeds to post to Slack."""
        client, repo = _make_client(created_holder=[])
        # report_only=False  → record write goes through request_approval (the HITL gate).
        ops = go.GitHubOps(report_only=False, gh_client=client)

        slack_spy = mock.Mock(return_value={"status": "posted"})
        with mock.patch.dict(os.environ, _WRITE_ENABLED_CFO), \
             mock.patch("agent_toolkit.github_ops.GitHubOps", return_value=ops), \
             mock.patch.object(go, "request_approval", side_effect=_raise_interrupt), \
             mock.patch("agent_toolkit.slack_tool.post_digest", slack_spy):
            with self.assertRaises(GraphInterrupt):
                ops_report.file_digest_record(
                    REPO, "CFO: spend", "spend +4% this shift",
                    agent="cfo", record_kind="cfo-burn", report_only=False,
                )

        # The graph paused at the gate: no record write, and no Slack post happened on a run
        # that the human never approved.
        repo.create_issue.assert_not_called()
        slack_spy.assert_not_called()

    def test_real_github_error_still_does_not_abort_slack(self):
        """Guardrail for the fix: a genuine GitHub failure (NOT a control-flow signal) must
        STILL be swallowed so the Slack post remains additive. The fix must narrow the catch
        without re-breaking this."""
        boom = mock.Mock()
        boom.get_repo.side_effect = RuntimeError("GitHub 500 / network down")
        ops = go.GitHubOps(report_only=True, gh_client=boom)

        slack_spy = mock.Mock(return_value={"status": "posted"})
        with mock.patch.dict(os.environ, _WRITE_ENABLED_CFO), \
             mock.patch("agent_toolkit.github_ops.GitHubOps", return_value=ops), \
             mock.patch("agent_toolkit.slack_tool.post_digest", slack_spy):
            out = ops_report.file_digest_record(
                REPO, "CFO: spend", "spend ok", agent="cfo", record_kind="cfo-burn",
            )
        self.assertEqual(out["status"], "error")        # GitHub failed, captured, did not raise
        slack_spy.assert_called_once()                  # Slack post is additive — still happened
        self.assertEqual(out["slack"], "posted")


if __name__ == "__main__":
    unittest.main()
