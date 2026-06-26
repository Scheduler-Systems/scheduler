"""Safety tests for the cloud CMO (Chief Marketing Officer) officer agent.

The CMO is an EXECUTIVE: it CONSUMES the growth team's digests + the RevenueCat funnel and
PROPOSES growth priorities — it never re-does work, never executes, never moves money. The
tests prove the load-bearing invariants directly on the pure node cores (no checkpointer, no
network): (1) gather is FAIL-SAFE when no subordinate digest exists and RC is unavailable;
(2) analyze classifies which drafts exist + reads the funnel; (3) propose tags every item
escalate_to "org", and a paid/live push as "shay"; (4) compose always produces a non-empty
summary via the deterministic fallback when the model is unavailable; (5) deliver stays
REPORT-ONLY (no GitHub write, no approval interrupt); (6) the clock-in gate routes a
clocked-out run straight to END without gathering. Run:
    .venv/bin/python -m unittest tests.test_cmo -v
"""
import os
import unittest
from unittest import mock

from graphs.exec import cmo as m


# --- gather (fail-safe consumption) -----------------------------------------------------
class GatherFailSafeTests(unittest.TestCase):
    def test_gather_survives_no_digests_and_no_rc(self):
        """No subordinate digests + RC unavailable => gather returns dicts and never raises."""
        with mock.patch.object(m, "read_local_digest", return_value="(no digest yet)"), \
                mock.patch.object(
                    m.revenuecat, "metrics_overview",
                    return_value={"ok": False, "metrics": {}, "raw": [], "error": "key not set"},
                ):
            out = m.gather({})

        # Every growth slug was consumed (degraded to the honest placeholder).
        self.assertEqual(set(out["digests"].keys()), set(m.GROWTH_DIGESTS))
        for slug in m.GROWTH_DIGESTS:
            self.assertEqual(out["digests"][slug], "(no digest yet)")
        # Funnel degraded but structured.
        self.assertFalse(out["funnel"]["ok"])

    def test_gather_guards_every_slug_against_model_work(self):
        """assert_not_model_work is called on every outward subordinate slug (Anthropic terms)."""
        seen = []

        with mock.patch.object(m, "assert_not_model_work", side_effect=seen.append), \
                mock.patch.object(m, "read_local_digest", return_value="(no digest yet)"), \
                mock.patch.object(m.revenuecat, "metrics_overview",
                                  return_value={"ok": False, "metrics": {}, "error": "x"}):
            m.gather({})

        for slug in m.GROWTH_DIGESTS:
            self.assertIn(slug, seen)

    def test_gather_skips_denylisted_slug(self):
        """A slug that trips the model-work denylist is skipped, never read."""
        blocked = m.GROWTH_DIGESTS[0]

        def guard(target):
            if target == blocked:
                raise m.ModelWorkBlocked(target)

        with mock.patch.object(m, "assert_not_model_work", side_effect=guard), \
                mock.patch.object(m, "read_local_digest", return_value="present text"), \
                mock.patch.object(m.revenuecat, "metrics_overview",
                                  return_value={"ok": False, "metrics": {}, "error": "x"}):
            out = m.gather({})

        self.assertNotIn(blocked, out["digests"])
        # The remaining (non-blocked) slugs were still consumed.
        for slug in m.GROWTH_DIGESTS[1:]:
            self.assertIn(slug, out["digests"])


# --- analyze ----------------------------------------------------------------------------
class AnalyzeTests(unittest.TestCase):
    def test_analyze_flags_present_and_missing_drafts(self):
        digests = {
            m.GROWTH_DIGESTS[0]: "real conversion analysis",
            m.GROWTH_DIGESTS[1]: "(no digest yet)",
            m.GROWTH_DIGESTS[2]: "   ",  # whitespace-only counts as missing
        }
        funnel = {"ok": True, "metrics": {"mrr": 1234, "active_trials": 5,
                                          "active_subscriptions": 42, "revenue": 999}}
        out = m.analyze({"digests": digests, "funnel": funnel})
        analysis = out["analysis"]

        self.assertTrue(analysis["drafts"][m.GROWTH_DIGESTS[0]])
        self.assertFalse(analysis["drafts"][m.GROWTH_DIGESTS[1]])
        self.assertFalse(analysis["drafts"][m.GROWTH_DIGESTS[2]])
        self.assertEqual(analysis["drafts_present"], 1)
        self.assertIn(m.GROWTH_DIGESTS[1], analysis["drafts_missing"])
        # Funnel conversion read through.
        self.assertTrue(analysis["conversion"]["ok"])
        self.assertEqual(analysis["conversion"]["mrr"], 1234)

    def test_analyze_funnel_unavailable_is_failsafe(self):
        out = m.analyze({"digests": {}, "funnel": {"ok": False, "error": "key not set"}})
        conv = out["analysis"]["conversion"]
        self.assertFalse(conv["ok"])
        self.assertEqual(conv["mrr"], None)
        self.assertEqual(conv["error"], "key not set")


# --- propose (escalation tagging) -------------------------------------------------------
class ProposeTests(unittest.TestCase):
    def test_missing_drafts_and_dark_funnel_are_org(self):
        """Every gap-filling / instrumentation proposal is resolved inside the org."""
        analysis = {
            "drafts": {s: False for s in m.GROWTH_DIGESTS},
            "drafts_missing": list(m.GROWTH_DIGESTS),
            "conversion": {"ok": False, "error": "key not set"},
        }
        out = m.propose({"analysis": analysis})
        proposals = out["proposals"]

        self.assertTrue(proposals)
        # All of these are org-resolved — nothing escalated to Shay yet.
        for p in proposals:
            self.assertEqual(p["escalate_to"], "org")
        self.assertEqual(sum(1 for p in proposals if p["escalate_to"] == "shay"), 0)
        actions = {p["action"] for p in proposals}
        self.assertIn("commission_growth_draft", actions)
        self.assertIn("restore_funnel_instrumentation", actions)

    def test_all_drafts_ready_escalates_paid_push_to_shay(self):
        """When every growth draft exists, the paid/live push is an investor escalation (shay)."""
        analysis = {
            "drafts": {s: True for s in m.GROWTH_DIGESTS},
            "drafts_missing": [],
            "conversion": {"ok": True, "mrr": 1000, "active_trials": 3,
                           "active_subscriptions": 20, "revenue": 5000, "error": None},
        }
        out = m.propose({"analysis": analysis})
        proposals = out["proposals"]

        shay = [p for p in proposals if p["escalate_to"] == "shay"]
        self.assertEqual(len(shay), 1)
        self.assertEqual(shay[0]["action"], "approve_paid_growth_push")
        # The funnel-present review is org-resolved.
        self.assertTrue(any(p["action"] == "review_funnel_conversion" and p["escalate_to"] == "org"
                            for p in proposals))


# --- compose (deterministic fallback) ---------------------------------------------------
class ComposeFallbackTests(unittest.TestCase):
    def test_compose_deterministic_when_model_raises(self):
        """budget_guard raising must NOT crash compose — summary is the deterministic report."""
        analysis = {
            "drafts": {s: (i == 0) for i, s in enumerate(m.GROWTH_DIGESTS)},
            "conversion": {"ok": True, "mrr": 1234, "active_trials": 5,
                           "active_subscriptions": 42, "revenue": 999, "error": None},
        }
        proposals = [{"action": "review_funnel_conversion", "area": "funnel",
                      "why": "signal present", "escalate_to": "org"}]

        with mock.patch.object(m, "budget_guard", side_effect=RuntimeError("no API key")):
            out = m.compose({"analysis": analysis, "proposals": proposals})

        summary = out["summary"]
        self.assertTrue(summary.strip())                 # never empty
        self.assertIn("1234", summary)                   # built from the gathered facts
        self.assertIn("RuntimeError", summary)           # fallback labelled, not faked

    def test_compose_uses_model_output_when_available(self):
        fake_model = mock.MagicMock()
        fake_model.invoke.return_value = mock.MagicMock(content="THE CMO UPDATE")

        with mock.patch.object(m, "budget_guard", return_value=fake_model):
            out = m.compose({"analysis": {"conversion": {"ok": False}}, "proposals": []})

        self.assertEqual(out["summary"], "THE CMO UPDATE")

    def test_compose_falls_back_when_model_returns_empty(self):
        fake_model = mock.MagicMock()
        fake_model.invoke.return_value = mock.MagicMock(content="")

        with mock.patch.object(m, "budget_guard", return_value=fake_model):
            out = m.compose({"analysis": {"conversion": {"ok": False, "error": "x"}},
                             "proposals": []})

        self.assertTrue(out["summary"].strip())


# --- deliver (report-only) --------------------------------------------------------------
class DeliverReportOnlyTests(unittest.TestCase):
    def test_deliver_is_report_only_and_never_writes(self):
        """deliver must call file_digest_issue with report_only=True and write nothing live."""
        captured = {}

        def fake_file_issue(repo, title, body, *, labels=None, report_only=None, **kwargs):
            captured["repo"] = repo
            captured["title"] = title
            captured["labels"] = labels
            captured["report_only"] = report_only
            # report_only delivery MUST not enter the approval interrupt or call GitHub.
            assert report_only is True, "deliver must stay report-only on probation"
            return {"status": "report_only", "action": "open_issue", "repo": repo}

        # OPS_REPORT_ONLY unset => report-only default True; local digest stubbed (no FS write).
        env = {k: v for k, v in os.environ.items() if k != "OPS_REPORT_ONLY"}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(m, "write_local_digest", return_value="/tmp/x/latest.md"), \
                mock.patch.object(m, "file_digest_issue", side_effect=fake_file_issue):
            out = m.deliver({"summary": "s", "analysis": {"conversion": {"ok": True}},
                             "proposals": []})

        self.assertTrue(captured["report_only"])
        self.assertEqual(captured["repo"], m.DIGEST_REPO)
        self.assertEqual(captured["title"], "CMO: growth + funnel (proposal)")
        self.assertEqual(captured["labels"], ["exec:cmo"])
        self.assertEqual(out["report"]["delivery"], "report_only")
        self.assertTrue(out["report_only"])

    def test_report_only_env_can_be_disabled(self):
        """Only an explicit 0/false/no flips report-only off; everything else stays True."""
        with mock.patch.dict(os.environ, {"OPS_REPORT_ONLY": "0"}):
            self.assertFalse(m._report_only())
        with mock.patch.dict(os.environ, {"OPS_REPORT_ONLY": "false"}):
            self.assertFalse(m._report_only())
        with mock.patch.dict(os.environ, {"OPS_REPORT_ONLY": "1"}):
            self.assertTrue(m._report_only())
        env = {k: v for k, v in os.environ.items() if k != "OPS_REPORT_ONLY"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertTrue(m._report_only())  # unset => report-only


# --- budget gate / routing --------------------------------------------------------------
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
        # governance capture on the clocked-out path is report-only.
        self.assertTrue(gov.call_args[0][1]["report_only"])

    def test_clocked_in_proceeds_to_gather(self):
        with mock.patch.object(m, "check_clocked_in", return_value=True):
            out = m.budget_gate({})
            route = m._budget_route({})
        self.assertEqual(out, {})
        self.assertEqual(route, "gather")


# --- finalize ---------------------------------------------------------------------------
class FinalizeTests(unittest.TestCase):
    def test_finalize_captures_report_only_governance(self):
        proposals = [
            {"action": "review_funnel_conversion", "area": "funnel", "escalate_to": "org"},
            {"action": "approve_paid_growth_push", "area": "campaign", "escalate_to": "shay"},
        ]
        with mock.patch.object(m, "governance_capture") as gov:
            out = m.finalize({
                "analysis": {"conversion": {"ok": True}, "drafts_present": 3},
                "proposals": proposals,
                "report": {"delivery": "report_only", "digest": "/tmp/d"},
            })
        self.assertTrue(out["report"]["report_only"])
        self.assertEqual(out["report"]["delivery"], "report_only")
        self.assertEqual(out["report"]["proposals"], 2)
        self.assertEqual(out["report"]["asks_for_shay"], 1)
        gov.assert_called_once()
        self.assertTrue(gov.call_args[0][1]["report_only"])


# --- compile ----------------------------------------------------------------------------
class GraphCompileTests(unittest.TestCase):
    def test_graph_compiles_without_checkpointer(self):
        self.assertIsNotNone(m.graph)


if __name__ == "__main__":
    unittest.main()
