"""Tests for the web_automation_engineer graph. stdlib unittest, no network, no model spend.

Pins the real behaviour added in the prod-harden pass:
  * triage classifies from the ACTUAL CI run conclusion (read back via github_ops.latest_run),
    NOT from the bare dispatch booleans;
  * dispatch correlates the run it triggered (run_url + head_sha captured by read_run);
  * finalize executes approved writes THROUGH github_ops (which keeps report-only/allow-list/
    second-gate guards) instead of recording a 'would-write' string;
  * NO GitHub write happens without approval;
  * the clocked-out kill-switch short-circuits before any dispatch/model/write;
  * CLASSIFICATION parsing is hardened + default-denies to indeterminate;
  * a missing model API key surfaces distinctly (model_available=False), not as a real verdict.

Run: .venv/bin/python -m unittest tests.test_web_automation_engineer -v
"""
import importlib.util
import pathlib
import unittest
from unittest import mock

_SPEC = importlib.util.spec_from_file_location(
    "web_automation_engineer", pathlib.Path("graphs/qa/web_automation_engineer.py")
)
wae = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(wae)

from agent_toolkit import github_ops as go


def _fake_model(content):
    """A stand-in chat model whose .invoke returns an object with `.content`."""
    m = mock.Mock()
    m.invoke.return_value = mock.Mock(content=content)
    return m


class ClassificationParseTests(unittest.TestCase):
    def test_clean_sentinel(self):
        self.assertEqual(wae._parse_classification("summary\nCLASSIFICATION: flaky"), "flaky")

    def test_markdown_wrapped_sentinel(self):
        self.assertEqual(
            wae._parse_classification("**CLASSIFICATION: regression**"), "regression"
        )

    def test_midline_sentinel(self):
        self.assertEqual(
            wae._parse_classification("verdict -> CLASSIFICATION: mixed because"), "mixed"
        )

    def test_unknown_value_default_denies(self):
        # An out-of-vocabulary verdict must NOT pass through — default-deny to indeterminate.
        self.assertEqual(wae._parse_classification("CLASSIFICATION: banana"), "indeterminate")

    def test_missing_sentinel_default_denies(self):
        self.assertEqual(wae._parse_classification("no sentinel at all"), "indeterminate")

    def test_last_valid_match_wins(self):
        self.assertEqual(
            wae._parse_classification("CLASSIFICATION: flaky\nCLASSIFICATION: regression"),
            "regression",
        )


class EntryRoutingTests(unittest.TestCase):
    def test_observe_mode_routes_to_observe(self):
        self.assertEqual(wae._entry({"mode": "observe"}), "observe")

    def test_default_routes_to_plan(self):
        self.assertEqual(wae._entry({}), "plan")


class ClockedOutTests(unittest.TestCase):
    def test_clocked_out_short_circuits_no_dispatch_no_model_no_write(self):
        with mock.patch.object(wae, "check_clocked_in", return_value=False), \
             mock.patch.object(wae, "dispatch_github_workflow") as disp, \
             mock.patch.object(wae, "budget_guard") as model, \
             mock.patch.object(wae, "GitHubOps") as ghops, \
             mock.patch.object(wae, "governance_capture"):
            out = wae.graph.invoke({"target": "Scheduler-Systems/scheduler-web"})
        self.assertIn("skipping run", out["report"])
        disp.assert_not_called()
        model.assert_not_called()
        ghops.assert_not_called()


class ReadRunTests(unittest.TestCase):
    def test_reads_back_real_conclusion_and_correlation_handles(self):
        info = {
            "status": "completed",
            "conclusion": "failure",
            "html_url": "https://gh/run/42",
            "head_sha": "deadbeef",
            "name": "gate",
        }
        with mock.patch.object(wae, "GitHubOps") as M:
            M.return_value.latest_run.return_value = info
            out = wae.read_run({"unit_dispatched": True, "e2e_dispatched": True})
        self.assertEqual(out["run_conclusion"], "failure")
        self.assertEqual(out["run_url"], "https://gh/run/42")
        self.assertEqual(out["run_sha"], "deadbeef")
        M.return_value.latest_run.assert_called_once()

    def test_not_dispatched_skips_recon(self):
        with mock.patch.object(wae, "GitHubOps") as M:
            out = wae.read_run({"unit_dispatched": False, "e2e_dispatched": False})
        self.assertEqual(out["run_recon_error"], "not-dispatched")
        M.return_value.latest_run.assert_not_called()

    def test_recon_error_records_type_only(self):
        with mock.patch.object(wae, "GitHubOps") as M:
            M.return_value.latest_run.side_effect = RuntimeError("token=ghp_secret leaked")
            out = wae.read_run({"unit_dispatched": True})
        # Only the exception TYPE, never the message (no secret leak into governance/OTel).
        self.assertEqual(out["run_recon_error"], "RuntimeError")
        self.assertNotIn("ghp_secret", str(out))


class TriageRealResultTests(unittest.TestCase):
    def test_real_failure_drives_regression_issue_draft(self):
        with mock.patch.object(
            wae, "budget_guard", return_value=_fake_model("red gate\nCLASSIFICATION: regression")
        ):
            out = wae.triage(
                {
                    "target": "Scheduler-Systems/scheduler-web",
                    "unit_dispatched": True,
                    "e2e_dispatched": True,
                    "run_conclusion": "failure",
                    "run_url": "https://gh/run/7",
                    "run_sha": "abc123",
                }
            )
        self.assertEqual(out["classification"], "regression")
        self.assertTrue(out["model_available"])
        kinds = [a["kind"] for a in out["proposed_actions"]]
        self.assertIn("open_issue", kinds)
        issue = next(a for a in out["proposed_actions"] if a["kind"] == "open_issue")
        self.assertIn("https://gh/run/7", issue["body"])  # cites the correlated run

    def test_green_run_files_nothing_even_if_model_says_regression(self):
        # The CI conclusion is the gate: a SUCCESS run must never produce a regression issue,
        # regardless of what the model emits. This kills the old blind-theater path.
        with mock.patch.object(
            wae, "budget_guard", return_value=_fake_model("CLASSIFICATION: regression")
        ):
            out = wae.triage(
                {
                    "target": "Scheduler-Systems/scheduler-web",
                    "unit_dispatched": True,
                    "e2e_dispatched": True,
                    "run_conclusion": "success",
                }
            )
        self.assertEqual(out["proposed_actions"], [])

    def test_pr_comment_drafted_when_pr_number_present(self):
        with mock.patch.object(
            wae, "budget_guard", return_value=_fake_model("green\nCLASSIFICATION: flaky")
        ):
            out = wae.triage(
                {
                    "target": "Scheduler-Systems/scheduler-web",
                    "unit_dispatched": True,
                    "run_conclusion": "success",
                    "pr_number": 12,
                }
            )
        kinds = [a["kind"] for a in out["proposed_actions"]]
        self.assertEqual(kinds, ["pr_comment"])

    def test_missing_model_key_surfaces_distinctly(self):
        # budget_guard re-raises get_model's 'No model API key configured' RuntimeError.
        with mock.patch.object(
            wae,
            "budget_guard",
            side_effect=RuntimeError("No model API key configured. Set ..."),
        ):
            out = wae.triage(
                {"target": "Scheduler-Systems/scheduler-web", "unit_dispatched": True,
                 "run_conclusion": "failure"}
            )
        self.assertFalse(out["model_available"])
        self.assertEqual(out["classification"], "indeterminate")
        self.assertEqual(out["proposed_actions"], [])  # no false regression on a key gap

    def test_other_config_error_is_not_swallowed(self):
        with mock.patch.object(
            wae, "budget_guard", side_effect=RuntimeError("some other boom")
        ):
            with self.assertRaises(RuntimeError):
                wae.triage({"target": "Scheduler-Systems/scheduler-web", "unit_dispatched": True})


class GateApprovalTests(unittest.TestCase):
    def test_no_actions_means_no_approval_request(self):
        with mock.patch.object(wae, "request_approval") as req:
            out = wae.gate({"proposed_actions": []})
        self.assertFalse(out["approved"])
        req.assert_not_called()

    def test_actions_route_through_human_gate(self):
        with mock.patch.object(wae, "request_approval", return_value="approve"), \
             mock.patch.object(wae, "is_approved", return_value=True):
            out = wae.gate({"proposed_actions": [{"kind": "open_issue"}]})
        self.assertTrue(out["approved"])


class FinalizeWriteGatingTests(unittest.TestCase):
    def test_unapproved_actions_are_not_written(self):
        with mock.patch.object(wae, "GitHubOps") as M, \
             mock.patch.object(wae, "governance_capture"):
            out = wae.finalize(
                {
                    "target": "Scheduler-Systems/scheduler-web",
                    "approved": False,
                    "proposed_actions": [{"kind": "open_issue", "repo": "Scheduler-Systems/scheduler-web"}],
                }
            )
        # GitHubOps must not even be constructed when nothing is approved.
        M.assert_not_called()
        self.assertIn("skipped (not approved)", str(out["report"]))

    def test_approved_open_issue_executes_through_github_ops(self):
        ops = mock.Mock()
        ops.open_issue.return_value = {"status": "report_only", "action": "open_issue"}
        with mock.patch.object(wae, "GitHubOps", return_value=ops), \
             mock.patch.object(wae, "governance_capture"):
            out = wae.finalize(
                {
                    "target": "Scheduler-Systems/scheduler-web",
                    "approved": True,
                    "classification": "regression",
                    "proposed_actions": [
                        {
                            "kind": "open_issue",
                            "repo": "Scheduler-Systems/scheduler-web",
                            "title": "t",
                            "body": "b",
                        }
                    ],
                }
            )
        ops.open_issue.assert_called_once()
        self.assertIn("report_only", str(out["report"]))

    def test_not_configured_is_reported_honestly_not_faked(self):
        ops = mock.Mock()
        ops.open_issue.side_effect = go.GitHubNotConfigured("no token")
        with mock.patch.object(wae, "GitHubOps", return_value=ops), \
             mock.patch.object(wae, "governance_capture"):
            out = wae.finalize(
                {
                    "approved": True,
                    "proposed_actions": [
                        {"kind": "open_issue", "repo": "Scheduler-Systems/scheduler-web"}
                    ],
                }
            )
        self.assertIn("not-configured", str(out["report"]))

    def test_blocked_write_is_reported_type_only(self):
        ops = mock.Mock()
        ops.comment_issue.side_effect = go.GitHubWriteBlocked("human rejected")
        with mock.patch.object(wae, "GitHubOps", return_value=ops), \
             mock.patch.object(wae, "governance_capture"):
            out = wae.finalize(
                {
                    "approved": True,
                    "proposed_actions": [
                        {"kind": "pr_comment", "repo": "Scheduler-Systems/scheduler-web",
                         "pr_number": 3, "body": "x"}
                    ],
                }
            )
        self.assertIn("blocked", str(out["report"]))


class FullGraphReportOnlyTests(unittest.TestCase):
    def test_failure_run_no_approval_writes_nothing(self):
        # End-to-end: dispatch fires, the run reads back as failure, the model says
        # regression — but with the human gate rejecting, NO GitHub write occurs.
        with mock.patch.object(wae, "check_clocked_in", return_value=True), \
             mock.patch.object(wae, "dispatch_github_workflow", return_value=True), \
             mock.patch.object(
                 wae, "budget_guard",
                 return_value=_fake_model("red\nCLASSIFICATION: regression")), \
             mock.patch.object(wae, "request_approval", return_value="reject"), \
             mock.patch.object(wae, "is_approved", return_value=False), \
             mock.patch.object(wae, "governance_capture"), \
             mock.patch.object(wae, "GitHubOps") as M:
            M.return_value.latest_run.return_value = {
                "status": "completed", "conclusion": "failure",
                "html_url": "https://gh/run/9", "head_sha": "sha9", "name": "gate",
            }
            out = wae.graph.invoke(
                {"target": "Scheduler-Systems/scheduler-web", "ref": "main"}
            )
        self.assertEqual(out["classification"], "regression")
        self.assertIn("skipped (not approved)", out["report"])
        M.return_value.open_issue.assert_not_called()
        M.return_value.comment_issue.assert_not_called()


if __name__ == "__main__":
    unittest.main()
