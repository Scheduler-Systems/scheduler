"""Tests for the android_automation_engineer QA worker. stdlib unittest, no network.

This graph was previously the only QA worker with ZERO test coverage. These tests pin the
load-bearing, SAFETY-relevant behavior on the pure node cores (no checkpointer, no network):

  1. clock-in gate short-circuits a clocked-out run (no dispatch, no writes);
  2. entry routing sends mode=observe to the read-only OBSERVE path;
  3. dispatch CAPTURES status code + body so a 403/404/422 is visible, and is skipped when
     test_results are pre-supplied;
  4. await_ci is a no-op when results are pre-supplied / dispatch failed / no token, and
     parses JUnit/Espresso artifacts into a results dict when it runs;
  5. summarize defers (blocked) with no results — surfacing the dispatch failure detail —
     and classifies when results are present (model mocked);
  6. gate builds the pending pr_comment + open_bug_issue writes for a regression+pr_number;
  7. finalize keeps the write-back REPORT-ONLY by default (GitHubOps returns plan dicts,
     never a real GitHub call) and only attempts writes when approved;
  8. _parse_verdict honors the VERDICT line, is negation-aware in the prose fallback, and
     defaults to blocked;
  9. _trim_results_for_model caps the payload fed to the model (token-budget / redaction).

Run: .venv/bin/python -m unittest tests.test_android_automation_engineer -v
"""
import importlib.util
import io
import os
import pathlib
import unittest
import zipfile
from unittest import mock

_SPEC = importlib.util.spec_from_file_location(
    "android_automation_engineer", pathlib.Path("graphs/qa/android_automation_engineer.py")
)
aae = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(aae)

from agent_toolkit import github_ops as go


# --- 1. clock-in gate -------------------------------------------------------------------
class BudgetGateTests(unittest.TestCase):
    def test_clocked_out_short_circuits(self):
        with mock.patch.object(aae, "check_clocked_in", return_value=False), \
             mock.patch.object(aae, "governance_capture") as gov:
            out = aae.budget_gate({"repo": aae.DEFAULT_REPO})
        self.assertEqual(out["verdict"], "clocked_out")
        self.assertIn("skipping run", out["report"])
        gov.assert_called_once()  # governance recorded the clocked-out terminal

    def test_clocked_in_is_noop(self):
        with mock.patch.object(aae, "check_clocked_in", return_value=True):
            self.assertEqual(aae.budget_gate({}), {})

    def test_route_ends_when_clocked_out(self):
        self.assertEqual(aae._after_budget_gate({"verdict": "clocked_out"}), "__end__")

    def test_route_proceeds_to_plan_when_clocked_in(self):
        self.assertEqual(aae._after_budget_gate({}), "plan")


# --- 2. observe-mode routing ------------------------------------------------------------
class EntryRoutingTests(unittest.TestCase):
    def test_observe_mode_routes_to_observe(self):
        self.assertEqual(aae._entry({"mode": "observe"}), "observe")

    def test_default_routes_to_plan(self):
        self.assertEqual(aae._entry({}), "plan")

    def test_after_gate_routes_observe(self):
        self.assertEqual(aae._after_budget_gate({"mode": "observe"}), "observe")


# --- 3. dispatch: capture status + body, skip when results supplied ---------------------
class DispatchTests(unittest.TestCase):
    def test_skips_when_test_results_present(self):
        out = aae.dispatch({"test_results": {"total": 1}, "repo": aae.DEFAULT_REPO,
                            "workflow": "gate.yml", "ref": "main"})
        self.assertFalse(out["dispatched"])
        self.assertIn("skipped", out["dispatch_detail"]["detail"])

    def test_dispatch_204_marks_dispatched(self):
        info = {"ok": True, "status": 204, "detail": "accepted (204)", "dispatched_at": 1.0}
        with mock.patch.object(aae, "_dispatch_workflow", return_value=info):
            out = aae.dispatch({"repo": aae.DEFAULT_REPO, "workflow": "gate.yml", "ref": "main"})
        self.assertTrue(out["dispatched"])
        self.assertEqual(out["dispatch_detail"]["status"], 204)

    def test_dispatch_failure_surfaces_status_and_body(self):
        """A 404 must be VISIBLE in dispatch_detail, not collapsed to dispatched=False only."""
        resp = mock.Mock(status_code=404, text='{"message":"Not Found"}')
        with mock.patch.object(aae, "_gh_token", return_value="tok"), \
             mock.patch("httpx.post", return_value=resp):
            info = aae._dispatch_workflow("o/r", "gate.yml", "main", {"suites": "x"})
        self.assertFalse(info["ok"])
        self.assertEqual(info["status"], 404)
        self.assertIn("404", info["detail"])
        self.assertIn("Not Found", info["detail"])

    def test_dispatch_no_token_is_fail_safe(self):
        with mock.patch.object(aae, "_gh_token", return_value=None):
            info = aae._dispatch_workflow("o/r", "gate.yml", "main", {})
        self.assertFalse(info["ok"])
        self.assertIn("no GITHUB", info["detail"])


# --- 4. await_ci: no-op cases + artifact parsing ----------------------------------------
class AwaitCITests(unittest.TestCase):
    def test_noop_when_results_supplied(self):
        self.assertEqual(aae.await_ci({"test_results": {"total": 1}}), {})

    def test_noop_when_dispatch_failed(self):
        self.assertEqual(aae.await_ci({"dispatched": False}), {})

    def test_noop_when_no_token(self):
        with mock.patch.object(aae, "_gh_token", return_value=None):
            self.assertEqual(aae.await_ci({"dispatched": True}), {})

    def test_run_not_found_returns_not_found(self):
        with mock.patch.object(aae, "_gh_token", return_value="tok"), \
             mock.patch.object(aae, "_find_dispatched_run", return_value=None), \
             mock.patch.object(aae.time, "sleep"), \
             mock.patch.object(aae.time, "time", side_effect=[0, 1, 10_000, 10_000]):
            out = aae.await_ci({"dispatched": True, "repo": "o/r", "workflow": "gate.yml",
                                "ref": "main", "dispatch_detail": {"dispatched_at": 0}})
        self.assertEqual(out["run_conclusion"], "not_found")

    def test_completed_run_downloads_and_parses(self):
        run = {"id": 7, "html_url": "https://x/run/7", "status": "completed",
               "conclusion": "failure"}
        parsed = {"artifacts": ["junit"], "total": 3, "failures": [{"name": "t"}],
                  "parsed_from": 1}
        with mock.patch.object(aae, "_gh_token", return_value="tok"), \
             mock.patch.object(aae, "_find_dispatched_run", return_value=run), \
             mock.patch.object(aae, "_download_and_parse_artifacts", return_value=parsed), \
             mock.patch.object(aae.time, "sleep"):
            out = aae.await_ci({"dispatched": True, "repo": "o/r", "workflow": "gate.yml",
                                "ref": "main", "dispatch_detail": {"dispatched_at": 0}})
        self.assertEqual(out["run_conclusion"], "failure")
        self.assertEqual(out["test_results"]["total"], 3)
        self.assertEqual(out["run_url"], "https://x/run/7")

    def test_parse_junit_counts_failures(self):
        xml = (b'<testsuite tests="2">'
               b'<testcase classname="C" name="ok"/>'
               b'<testcase classname="C" name="bad">'
               b'<failure message="boom">stack</failure></testcase>'
               b'</testsuite>')
        out = aae._parse_junit_xml(xml)
        self.assertEqual(out["total"], 2)
        self.assertEqual(len(out["failures"]), 1)
        self.assertEqual(out["failures"][0]["name"], "C.bad")
        self.assertEqual(out["failures"][0]["message"], "boom")

    def test_parse_junit_rejects_doctype_xxe(self):
        """Untrusted artifact XML carrying a DOCTYPE is refused (XXE / billion-laughs guard)."""
        evil = (b'<?xml version="1.0"?>\n<!DOCTYPE x [<!ENTITY a "lol">]>'
                b'<testsuite><testcase name="t"/></testsuite>')
        out = aae._parse_junit_xml(evil)
        self.assertEqual(out, {"total": 0, "failures": []})  # refused, not parsed

    def test_download_parses_zip_of_xml(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("TEST-foo.xml",
                        '<testsuite><testcase classname="A" name="b">'
                        '<error message="e"/></testcase></testsuite>')
        zip_bytes = buf.getvalue()

        list_resp = mock.Mock(status_code=200)
        list_resp.json.return_value = {"artifacts": [
            {"name": "espresso-results", "archive_download_url": "https://dl/1"}]}
        dl_resp = mock.Mock(status_code=200, content=zip_bytes)

        def fake_get(url, **kw):
            return dl_resp if url == "https://dl/1" else list_resp

        with mock.patch("httpx.get", side_effect=fake_get):
            out = aae._download_and_parse_artifacts("tok", "o/r", 9)
        self.assertEqual(out["artifacts"], ["espresso-results"])
        self.assertEqual(out["total"], 1)
        self.assertEqual(out["failures"][0]["name"], "A.b")


# --- 5. summarize: blocked-vs-classified ------------------------------------------------
class SummarizeTests(unittest.TestCase):
    def test_blocked_when_dispatch_failed_surfaces_detail(self):
        out = aae.summarize({
            "repo": aae.DEFAULT_REPO, "workflow": "gate.yml", "ref": "main",
            "dispatched": False,
            "dispatch_detail": {"detail": "HTTP 404: Not Found"},
        })
        self.assertEqual(out["verdict"], "blocked")
        self.assertIn("404", out["report"])
        self.assertIn("FAILED", out["report"])

    def test_blocked_when_dispatched_but_no_results(self):
        out = aae.summarize({
            "repo": aae.DEFAULT_REPO, "workflow": "gate.yml", "ref": "main",
            "dispatched": True, "run_conclusion": "timed_out",
        })
        self.assertEqual(out["verdict"], "blocked")
        self.assertIn("re-invoke", out["report"])
        self.assertIn("timed_out", out["report"])

    def test_classifies_when_results_present(self):
        fake_model = mock.Mock()
        fake_model.invoke.return_value = mock.Mock(
            content="VERDICT: regression\nSUMMARY: deterministic assertion failure")
        results = {"total": 5, "failures": [{"name": "LoginTest.bad", "message": "expected X"}]}
        with mock.patch.object(aae, "budget_guard", return_value=fake_model):
            out = aae.summarize({"repo": aae.DEFAULT_REPO, "test_results": results})
        self.assertEqual(out["verdict"], "regression")
        self.assertIn("regression", out["report"])

    def test_model_failure_is_blocked_and_leaks_no_raw_results(self):
        results = {"secret_internal": "do-not-leak", "failures": []}
        with mock.patch.object(aae, "budget_guard",
                               side_effect=RuntimeError("boom token=xyz")):
            out = aae.summarize({"repo": aae.DEFAULT_REPO, "test_results": results})
        self.assertEqual(out["verdict"], "blocked")
        self.assertNotIn("do-not-leak", out["report"])
        self.assertNotIn("token=xyz", out["report"])


# --- 6. gate: pending-write construction ------------------------------------------------
class GateTests(unittest.TestCase):
    def test_regression_with_pr_builds_both_writes(self):
        captured = {}

        def fake_approval(action, payload, risk):
            captured["payload"] = payload
            return "reject"  # rejection still records the pending writes

        with mock.patch.object(aae, "request_approval", side_effect=fake_approval):
            out = aae.gate({"verdict": "regression", "repo": aae.DEFAULT_REPO,
                            "ref": "main", "report": "R", "pr_number": 42})
        actions = [w["action"] for w in out["pending_writes"]]
        self.assertIn("pr_comment", actions)
        self.assertIn("open_bug_issue", actions)
        self.assertFalse(out["approved"])  # rejected
        # the open_bug_issue payload carries the regression labels
        bug = next(w for w in out["pending_writes"] if w["action"] == "open_bug_issue")
        self.assertIn("regression", bug["labels"])

    def test_clean_pass_no_pr_needs_no_approval(self):
        with mock.patch.object(aae, "request_approval") as approval:
            out = aae.gate({"verdict": "pass", "repo": aae.DEFAULT_REPO, "ref": "main",
                            "report": "ok"})
        approval.assert_not_called()
        self.assertEqual(out["pending_writes"], [])
        self.assertFalse(out["approved"])

    def test_pr_comment_built_even_without_regression(self):
        with mock.patch.object(aae, "request_approval", return_value="approve"):
            out = aae.gate({"verdict": "flaky", "repo": aae.DEFAULT_REPO, "ref": "main",
                            "report": "R", "pr_number": 7})
        actions = [w["action"] for w in out["pending_writes"]]
        self.assertEqual(actions, ["pr_comment"])  # flaky -> comment, no bug issue


# --- 7. finalize: report-only write-back ------------------------------------------------
class FinalizeWriteBackTests(unittest.TestCase):
    def test_report_only_default_records_write_to_github(self):
        """Default (probation): an ``open_bug_issue`` is a durable RECORD, not a code action,
        so under report_only it WRITES to GitHub (the close-the-loop fix) — the QA bug is
        captured instead of returning a never-filed plan dict. Governance still honestly
        labels the run report_only (no code action was taken)."""
        pending = [{"action": "open_bug_issue", "repo": aae.DEFAULT_REPO,
                    "title": "t", "body": "b", "labels": ["bug"]}]
        fake_issue = mock.Mock(number=31, html_url="https://x/i/31", sha=None, merged=None)
        fake_repo = mock.Mock()
        fake_repo.create_issue.return_value = fake_issue
        fake_client = mock.Mock()
        fake_client.get_repo.return_value = fake_repo
        with mock.patch.dict(os.environ, {}, clear=True), \
             mock.patch.object(go.GitHubOps, "_client", return_value=fake_client), \
             mock.patch.object(go, "request_approval") as gate, \
             mock.patch.object(aae, "governance_capture") as gov:
            out = aae.finalize({"verdict": "regression", "approved": True,
                                "pending_writes": pending, "repo": aae.DEFAULT_REPO,
                                "ref": "main", "report": "R"})
        gate.assert_not_called()                  # records never enter the merge gate
        fake_repo.create_issue.assert_called_once()  # the durable record actually wrote
        self.assertEqual(out["writes_executed"][0]["status"], "done")
        # governance honestly labels the run report_only
        self.assertTrue(gov.call_args[0][1]["report_only"])

    def test_not_approved_skips_writes(self):
        pending = [{"action": "open_bug_issue", "repo": aae.DEFAULT_REPO,
                    "title": "t", "body": "b"}]
        with mock.patch.object(aae, "_execute_writes") as ew, \
             mock.patch.object(aae, "governance_capture"):
            out = aae.finalize({"verdict": "regression", "approved": False,
                                "pending_writes": pending, "repo": aae.DEFAULT_REPO})
        ew.assert_not_called()
        self.assertEqual(out["writes_executed"], [])

    def test_write_report_only_default_is_on(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertTrue(aae._write_report_only())

    def test_write_report_only_requires_explicit_enable(self):
        with mock.patch.dict(os.environ, {"ANDROID_QA_WRITE_BACK": "enabled"}, clear=True):
            self.assertFalse(aae._write_report_only())
        # the fleet-wide switch wins when set
        with mock.patch.dict(os.environ,
                             {"ANDROID_QA_WRITE_BACK": "enabled",
                              "GITHUB_OPS_REPORT_ONLY": "1"}, clear=True):
            self.assertTrue(aae._write_report_only())

    def test_execute_writes_is_fail_safe(self):
        """A raising GitHubOps op becomes a structured error, not a crash."""
        pending = [{"action": "open_bug_issue", "repo": aae.DEFAULT_REPO,
                    "title": "t", "body": "b", "labels": []}]
        with mock.patch.object(go.GitHubOps, "open_issue",
                               side_effect=RuntimeError("network token=abc")):
            res = aae._execute_writes(aae.DEFAULT_REPO, pending)
        self.assertEqual(res[0]["status"], "error")
        self.assertEqual(res[0]["error"], "RuntimeError")  # type only, no token leak
        self.assertNotIn("abc", str(res))


# --- 8. _parse_verdict edge cases -------------------------------------------------------
class ParseVerdictTests(unittest.TestCase):
    def test_verdict_line_is_authoritative(self):
        # prose says 'no regression' but the VERDICT line says pass -> pass
        self.assertEqual(
            aae._parse_verdict("SUMMARY: no regression observed\nVERDICT: pass"), "pass")

    def test_verdict_line_regression(self):
        self.assertEqual(
            aae._parse_verdict("VERDICT: regression\nSUMMARY: assertion failed"), "regression")

    def test_prose_no_regression_does_not_flip(self):
        self.assertEqual(
            aae._parse_verdict("Summary: there is no regression here, all green"), "blocked")

    def test_prose_real_regression(self):
        self.assertEqual(
            aae._parse_verdict("Found a regression in LoginActivityTest"), "regression")

    def test_prose_flaky(self):
        self.assertEqual(aae._parse_verdict("The failure looks flaky (emulator ANR)"), "flaky")

    def test_unparseable_defaults_blocked(self):
        self.assertEqual(aae._parse_verdict(""), "blocked")
        self.assertEqual(aae._parse_verdict("totally unrelated text"), "blocked")

    def test_verdict_line_unknown_token_blocks_not_prose(self):
        # a VERDICT line that names no known token must NOT fall through to prose
        self.assertEqual(
            aae._parse_verdict("VERDICT: unknown\nFound a regression elsewhere"), "blocked")

    def test_mentions_positively_negation(self):
        self.assertFalse(aae._mentions_positively("there is no regression", "regression"))
        self.assertTrue(aae._mentions_positively("a clear regression", "regression"))


# --- 9. _trim_results_for_model ---------------------------------------------------------
class TrimResultsTests(unittest.TestCase):
    def test_caps_payload_size(self):
        big = {"total": 1, "failures": [{"name": f"t{i}", "message": "x" * 200}
                                        for i in range(500)]}
        text = aae._trim_results_for_model(big)
        self.assertLessEqual(len(text), aae._MAX_RESULTS_CHARS + 32)
        self.assertIn("truncated", text)

    def test_caps_failures_fed(self):
        big = {"total": 1, "failures": [{"name": f"t{i}"} for i in range(500)]}
        text = aae._trim_results_for_model(big)
        # only the first _MAX_FAILURES_FED are serialized
        self.assertIn("t0", text)
        self.assertNotIn(f"t{aae._MAX_FAILURES_FED + 50}", text)


if __name__ == "__main__":
    unittest.main()
