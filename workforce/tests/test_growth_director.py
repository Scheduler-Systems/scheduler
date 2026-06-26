"""Safety tests for the BOARD growth_director officer.

It is a board officer that CONSUMES the CMO + CEO digests + the RevenueCat money number,
forms a revenue/funnel verdict against the ~0.4% conversion baseline, and PROPOSES growth
oversight notes — propose-only, everything resolved inside the org. The tests prove the
load-bearing invariants on the pure node cores (no checkpointer, no network):
  (1) gather is FAIL-SAFE with no RC / no subordinate digests (degrades to "(no digest yet)");
  (2) analyze is deterministic — flat/unknown revenue, conversion vs baseline, growth-shipping;
  (3) propose marks EVERY oversight note escalate_to="org" (no ask-for-Shay);
  (4) compose always produces a non-empty summary via the deterministic fallback w/o a model;
  (5) deliver stays REPORT-ONLY (no GitHub write, no approval interrupt) with the board label;
  (6) the clock-in gate routes a clocked-out run straight to END without gathering;
  (7) the graph compiles and runs unattended with no creds and never hangs.
stdlib unittest + unittest.mock, no network. Run:
    .venv/bin/python -m unittest tests.test_growth_director -v
"""
import os
import unittest
from unittest import mock

from graphs.board import growth_director as m


# --- gather: consume subordinate reports, fail-safe -------------------------------------
class GatherFailSafeTests(unittest.TestCase):
    def test_gather_survives_no_rc_and_no_digests(self):
        """No RC key + missing subordinate digests => structured dicts, never raises."""
        with mock.patch.object(
            m.revenuecat, "metrics_overview",
            return_value={"ok": False, "metrics": {}, "raw": [], "error": "key not set"},
        ), mock.patch.object(m, "read_local_digest", return_value="(no digest yet)"):
            out = m.gather({})

        self.assertFalse(out["rc"]["ok"])
        # Both subordinate digests present, degraded to the honest placeholder.
        self.assertEqual(set(out["digests"].keys()), set(m.SUBORDINATE_DIGESTS))
        for slug in m.SUBORDINATE_DIGESTS:
            self.assertEqual(out["digests"][slug], "(no digest yet)")

    def test_gather_reads_each_subordinate_digest(self):
        """gather reads the CMO and CEO digests by slug (officers consume reports)."""
        seen = []

        def fake_read(slug, *a, **k):
            seen.append(slug)
            return f"DIGEST::{slug}"

        with mock.patch.object(m, "read_local_digest", side_effect=fake_read), \
                mock.patch.object(m.revenuecat, "metrics_overview",
                                  return_value={"ok": True, "metrics": {}, "raw": []}):
            out = m.gather({})

        self.assertEqual(set(seen), {"cmo", "ceo"})
        self.assertEqual(out["digests"]["cmo"], "DIGEST::cmo")
        self.assertEqual(out["digests"]["ceo"], "DIGEST::ceo")

    def test_gather_guards_every_subordinate_against_model_work(self):
        """assert_not_model_work is called on every outward slug (Anthropic terms)."""
        seen = []
        with mock.patch.object(m, "assert_not_model_work", side_effect=seen.append), \
                mock.patch.object(m, "read_local_digest", return_value="x"), \
                mock.patch.object(m.revenuecat, "metrics_overview",
                                  return_value={"ok": False, "metrics": {}, "error": "x"}):
            m.gather({})
        for slug in m.SUBORDINATE_DIGESTS:
            self.assertIn(slug, seen)


# --- analyze: deterministic verdict -----------------------------------------------------
class AnalyzeTests(unittest.TestCase):
    def test_revenue_unknown_when_rc_unavailable(self):
        """RC unavailable => revenue 'unknown' (missing data is never an adverse verdict)."""
        out = m.analyze({"rc": {"ok": False, "error": "key not set"}, "digests": {}})
        a = out["analysis"]
        self.assertEqual(a["revenue_verdict"], "unknown")

    def test_revenue_flat_when_no_money(self):
        """RC ok but zero MRR/subs => 'flat'."""
        out = m.analyze({
            "rc": {"ok": True, "metrics": {"mrr": 0, "active_subscriptions": 0}},
            "digests": {"cmo": "shipped a draft", "ceo": "x"},
        })
        self.assertEqual(out["analysis"]["revenue_verdict"], "flat")

    def test_revenue_tracking_when_money_present(self):
        """RC ok with MRR/subs => 'tracking'."""
        out = m.analyze({
            "rc": {"ok": True, "metrics": {"mrr": 1234, "active_subscriptions": 42}},
            "digests": {},
        })
        self.assertEqual(out["analysis"]["revenue_verdict"], "tracking")

    def test_conversion_below_baseline_flagged(self):
        """A conversion metric clearly below the ~0.4% baseline => 'below_baseline'."""
        out = m.analyze({
            "rc": {"ok": True, "metrics": {"mrr": 10, "conversion": 0.001}},
            "digests": {},
        })
        self.assertEqual(out["analysis"]["conversion_verdict"], "below_baseline")

    def test_conversion_at_or_above_baseline(self):
        """Conversion at/above the baseline => 'at_or_above_baseline'."""
        out = m.analyze({
            "rc": {"ok": True, "metrics": {"mrr": 10, "conversion_rate": 0.01}},
            "digests": {},
        })
        self.assertEqual(out["analysis"]["conversion_verdict"], "at_or_above_baseline")

    def test_conversion_unknown_without_metric(self):
        """No conversion metric => 'unknown' (no false alarm)."""
        out = m.analyze({"rc": {"ok": True, "metrics": {"mrr": 10}}, "digests": {}})
        self.assertEqual(out["analysis"]["conversion_verdict"], "unknown")

    def test_growth_shipping_false_when_cmo_digest_empty(self):
        """An empty/'(no digest yet)' CMO digest => growth is NOT shipping."""
        out = m.analyze({
            "rc": {"ok": False, "error": "x"},
            "digests": {"cmo": "(no digest yet)", "ceo": "(no digest yet)"},
        })
        self.assertFalse(out["analysis"]["growth_shipping"])

    def test_growth_shipping_true_when_cmo_has_output(self):
        """A non-empty CMO digest => growth IS shipping."""
        out = m.analyze({
            "rc": {"ok": False, "error": "x"},
            "digests": {"cmo": "drafted 3 campaigns and 1 funnel experiment", "ceo": "x"},
        })
        self.assertTrue(out["analysis"]["growth_shipping"])


# --- propose: everything escalates to the org -------------------------------------------
class ProposeOrgEscalationTests(unittest.TestCase):
    def test_every_proposal_escalates_to_org(self):
        """No growth oversight note is ever an ask-for-Shay — all escalate_to='org'."""
        # Adverse on every axis => the most proposals.
        analysis = {
            "baseline": 0.004,
            "revenue_verdict": "flat", "revenue_note": "no MRR",
            "conversion_verdict": "below_baseline", "conversion_note": "0.10% < 0.40%",
            "growth_shipping": False, "shipping": {"cmo": False, "ceo": False},
            "metrics": {},
        }
        out = m.propose({"analysis": analysis})
        proposals = out["proposals"]
        self.assertTrue(proposals)  # adverse state => at least one note
        for p in proposals:
            self.assertEqual(p["escalate_to"], "org")
        # Never an ask for Shay.
        self.assertNotIn("shay", [p["escalate_to"] for p in proposals])

    def test_healthy_state_still_emits_an_oversight_note(self):
        """Even a healthy verdict yields a 'steady' oversight note (still escalate_to='org')."""
        analysis = {
            "baseline": 0.004,
            "revenue_verdict": "tracking", "revenue_note": "mrr=1234",
            "conversion_verdict": "at_or_above_baseline", "conversion_note": "ok",
            "growth_shipping": True, "shipping": {"cmo": True, "ceo": True},
            "metrics": {},
        }
        out = m.propose({"analysis": analysis})
        self.assertEqual(len(out["proposals"]), 1)
        self.assertEqual(out["proposals"][0]["area"], "steady")
        self.assertEqual(out["proposals"][0]["escalate_to"], "org")

    def test_not_shipping_produces_a_shipping_note(self):
        """When growth is not shipping, the board asks for the next cycle's output."""
        analysis = {
            "baseline": 0.004,
            "revenue_verdict": "tracking", "revenue_note": "mrr=1",
            "conversion_verdict": "unknown", "conversion_note": "n/a",
            "growth_shipping": False, "shipping": {"cmo": False},
            "metrics": {},
        }
        out = m.propose({"analysis": analysis})
        areas = [p["area"] for p in out["proposals"]]
        self.assertIn("shipping", areas)


# --- compose: deterministic fallback ----------------------------------------------------
class ComposeFallbackTests(unittest.TestCase):
    def _state(self):
        return {
            "rc": {"ok": True, "metrics": {"mrr": 1234, "active_subscriptions": 42}},
            "analysis": {"baseline": 0.004, "revenue_verdict": "tracking",
                         "revenue_note": "mrr=1234", "conversion_verdict": "unknown",
                         "conversion_note": "n/a", "growth_shipping": True},
            "proposals": [{"area": "steady", "note": "hold the bar", "escalate_to": "org"}],
        }

    def test_compose_deterministic_when_model_raises(self):
        """budget_guard raising must NOT crash compose — summary is the deterministic report."""
        with mock.patch.object(m, "budget_guard", side_effect=RuntimeError("no API key")):
            out = m.compose(self._state())
        summary = out["summary"]
        self.assertTrue(summary.strip())                 # never empty
        self.assertIn("mrr", summary)                    # built from gathered facts
        self.assertIn("RuntimeError", summary)           # fallback labelled, not faked

    def test_compose_uses_model_output_when_available(self):
        """When the model works, its phrasing is used (still fail-safe wrapped)."""
        fake_model = mock.MagicMock()
        fake_model.invoke.return_value = mock.MagicMock(content="THE BOARD OVERSIGHT NOTE")
        with mock.patch.object(m, "budget_guard", return_value=fake_model):
            out = m.compose(self._state())
        self.assertEqual(out["summary"], "THE BOARD OVERSIGHT NOTE")

    def test_compose_falls_back_when_model_returns_empty(self):
        """An empty model response still yields a non-empty deterministic digest."""
        fake_model = mock.MagicMock()
        fake_model.invoke.return_value = mock.MagicMock(content="")
        with mock.patch.object(m, "budget_guard", return_value=fake_model):
            out = m.compose(self._state())
        self.assertTrue(out["summary"].strip())


# --- deliver: report-only ----------------------------------------------------------------
class DeliverReportOnlyTests(unittest.TestCase):
    def test_deliver_is_report_only_and_never_writes(self):
        """deliver must call file_digest_issue with report_only=True and the board label."""
        captured = {}

        def fake_file_issue(repo, title, body, *, labels=None, report_only=None, **kwargs):
            captured.update(repo=repo, title=title, labels=labels, report_only=report_only)
            # report_only delivery MUST not enter the approval interrupt or call GitHub.
            assert report_only is True, "deliver must stay report-only on probation"
            return {"status": "report_only", "action": "open_issue", "repo": repo}

        env = {k: v for k, v in os.environ.items() if k != "OPS_REPORT_ONLY"}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(m, "write_local_digest", return_value="/tmp/x/latest.md") as wd, \
                mock.patch.object(m, "file_digest_issue", side_effect=fake_file_issue):
            out = m.deliver({"summary": "s", "rc": {"ok": True, "metrics": {}},
                             "analysis": {}, "proposals": []})

        self.assertTrue(captured["report_only"])
        self.assertEqual(captured["repo"], m.DIGEST_REPO)
        self.assertEqual(captured["title"], "Board — Growth (oversight)")
        self.assertEqual(captured["labels"], ["board:growth"])
        self.assertEqual(out["report"]["delivery"], "report_only")
        self.assertTrue(out["report_only"])
        wd.assert_called_once()


# --- _report_only env contract ----------------------------------------------------------
class ReportOnlyEnvTests(unittest.TestCase):
    def test_unset_defaults_true(self):
        env = {k: v for k, v in os.environ.items() if k != "OPS_REPORT_ONLY"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertTrue(m._report_only())

    def test_zero_and_false_are_false(self):
        with mock.patch.dict(os.environ, {"OPS_REPORT_ONLY": "0"}):
            self.assertFalse(m._report_only())
        with mock.patch.dict(os.environ, {"OPS_REPORT_ONLY": "false"}):
            self.assertFalse(m._report_only())

    def test_truthy_is_true(self):
        with mock.patch.dict(os.environ, {"OPS_REPORT_ONLY": "1"}):
            self.assertTrue(m._report_only())


# --- budget gate / clock-in -------------------------------------------------------------
class BudgetGateTests(unittest.TestCase):
    def test_clocked_out_ends_without_gather(self):
        """Clocked out: budget_gate reports + governance, the route goes to END (not gather)."""
        with mock.patch.object(m, "check_clocked_in", return_value=False), \
                mock.patch.object(m, "governance_capture") as gov, \
                mock.patch.object(m.revenuecat, "metrics_overview",
                                  side_effect=AssertionError("gather must not run")):
            out = m.budget_gate({})
            route = m._budget_route({})

        self.assertEqual(out["report"], {"clocked_in": False})
        self.assertEqual(route, "clocked_out")
        gov.assert_called_once()
        self.assertTrue(gov.call_args[0][1]["report_only"])

    def test_clocked_in_proceeds_to_gather(self):
        with mock.patch.object(m, "check_clocked_in", return_value=True):
            out = m.budget_gate({})
            route = m._budget_route({})
        self.assertEqual(out, {})
        self.assertEqual(route, "gather")


# --- finalize ----------------------------------------------------------------------------
class FinalizeTests(unittest.TestCase):
    def test_finalize_captures_report_only_governance(self):
        with mock.patch.object(m, "governance_capture") as gov:
            out = m.finalize({
                "analysis": {"revenue_verdict": "flat", "conversion_verdict": "unknown",
                             "growth_shipping": False},
                "proposals": [{"area": "revenue", "note": "x", "escalate_to": "org"}],
                "report": {"delivery": "report_only", "digest": "/tmp/d"},
            })
        self.assertTrue(out["report"]["report_only"])
        self.assertEqual(out["report"]["delivery"], "report_only")
        self.assertEqual(out["report"]["proposals"], 1)
        gov.assert_called_once()
        cap = gov.call_args[0][1]
        self.assertTrue(cap["report_only"])
        self.assertEqual(cap["escalations"], ["org"])  # only org escalations captured


# --- end-to-end graph: unattended, no creds, never hangs --------------------------------
class GraphInvokeTests(unittest.TestCase):
    def test_graph_compiles_without_checkpointer(self):
        self.assertIsNotNone(m.graph)

    def test_full_run_report_only_no_creds(self):
        """Unattended run with zero creds: completes, report-only, no GitHub call, no hang."""
        env = {k: v for k, v in os.environ.items() if k != "OPS_REPORT_ONLY"}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(m, "check_clocked_in", return_value=True), \
                mock.patch.object(m, "read_local_digest", return_value="(no digest yet)"), \
                mock.patch.object(m.revenuecat, "metrics_overview",
                                  return_value={"ok": False, "metrics": {}, "raw": [], "error": "x"}), \
                mock.patch.object(m, "budget_guard", side_effect=RuntimeError("no model")), \
                mock.patch.object(m, "write_local_digest", return_value="/tmp/d/latest.md"), \
                mock.patch.object(m, "file_digest_issue",
                                  return_value={"status": "report_only"}) as fd:
            out = m.graph.invoke({})

        self.assertTrue(out["report"]["report_only"])
        self.assertEqual(out["report"]["delivery"], "report_only")
        self.assertTrue(fd.call_args.kwargs["report_only"])  # no GitHub call, no approval hang

    def test_clocked_out_graph_ends_without_work(self):
        with mock.patch.object(m, "check_clocked_in", return_value=False), \
                mock.patch.object(m, "read_local_digest") as rd, \
                mock.patch.object(m, "file_digest_issue") as fd:
            out = m.graph.invoke({})
        rd.assert_not_called()   # no digest reads on the clocked-out path
        fd.assert_not_called()   # no delivery on the clocked-out path
        self.assertEqual(out["report"], {"clocked_in": False})


if __name__ == "__main__":
    unittest.main()
