"""Safety tests for the cloud conversion_growth_analyst agent.

It watches the RevenueCat funnel + paywall and PROPOSES conversion experiments as drafts
(propose-only). The tests prove the load-bearing invariants directly on the pure node cores
(no checkpointer, no network):

  (1) gather is FAIL-SAFE — RC not configured falls back to the declared funnel_baseline and
      never raises;
  (2) analyze computes ~0.4% paid conversion from the declared baseline (252 / 1);
  (3) propose yields a NON-EMPTY deterministic experiment set when budget_guard raises;
  (4) deliver stays REPORT-ONLY (file_digest_issue called with report_only=True — no GitHub
      write, no approval interrupt);
  (5) the clock-in gate routes a clocked-out run straight to END without gathering.

stdlib unittest + unittest.mock, no network. Run:
    .venv/bin/python -m unittest tests.test_conversion_growth_analyst -v
"""
import json
import os
import tempfile
import unittest
from unittest import mock

from graphs.marketing import conversion_growth_analyst as m


# The declared baseline (mirrors docs/growth/scheduler_positioning.json) used across tests.
_BASELINE_POSITIONING = {
    "positioning_problem": "Mispositioned to-do listing; reposition to shift scheduling.",
    "revenue_levers": [
        "Reposition the store listing to shift scheduling (ASO copy + screenshots; no app release)",
        "Add an annual plan (none today)",
        "Configure the free trial (not configured in RevenueCat today)",
        "Revisit pricing vs competitors (currently underpriced)",
    ],
    "funnel_baseline": {
        "customers": 252,
        "paid_subscriptions": 1,
        "mrr_usd": 5,
        "active_trials": None,
    },
    "pricing": {
        "model": "per-user",
        "annual_plan_exists": False,
        "trial_configured": False,
    },
    "aso": {
        "in_flight_branches": [
            "Scheduler-Systems/scheduler-ios:aso/shift-scheduling-listing",
        ],
    },
    "paywall_urls": ["https://scheduler-web-next.web.app/"],
}


# --- gather: FAIL-SAFE with no RC creds, falls back to declared baseline -----------------
class GatherFailSafeTests(unittest.TestCase):
    def test_gather_survives_rc_not_configured(self):
        """RC not configured (degraded result) + a probe => gather returns dicts, never raises."""
        with tempfile.TemporaryDirectory() as td:
            ppath = os.path.join(td, "positioning.json")
            with open(ppath, "w", encoding="utf-8") as fh:
                json.dump(_BASELINE_POSITIONING, fh)
            with mock.patch.dict(os.environ, {"GROWTH_POSITIONING_PATH": ppath}), \
                 mock.patch.object(
                     m.revenuecat, "metrics_overview",
                     return_value={"ok": False, "metrics": {}, "raw": [], "error": "key not set"},
                 ), \
                 mock.patch.object(
                     m, "http_probe",
                     return_value={"url": "u", "reachable": True, "ok": True, "status": 200},
                 ):
                out = m.gather({})

        # Declared facts loaded; RC degraded but structured; one paywall probe captured.
        self.assertEqual(out["positioning"]["funnel_baseline"]["customers"], 252)
        self.assertFalse(out["rc"]["ok"])
        self.assertEqual(len(out["paywall"]), 1)

    def test_gather_missing_positioning_file_degrades(self):
        """A missing positioning file => positioning={} and gather still completes."""
        with mock.patch.dict(os.environ, {"GROWTH_POSITIONING_PATH": "/nonexistent/x.json"}), \
             mock.patch.object(m.revenuecat, "metrics_overview",
                               return_value={"ok": False, "metrics": {}, "error": "x"}):
            out = m.gather({})
        self.assertEqual(out["positioning"], {})
        # No declared paywall URLs => no probes, but the node still returns structured state.
        self.assertEqual(out["paywall"], [])

    def test_gather_probe_exception_does_not_crash(self):
        """A probe blowing up must NOT crash gather — it degrades to a structured result."""
        with tempfile.TemporaryDirectory() as td:
            ppath = os.path.join(td, "positioning.json")
            with open(ppath, "w", encoding="utf-8") as fh:
                json.dump({"paywall_urls": ["https://x/"]}, fh)
            with mock.patch.dict(os.environ, {"GROWTH_POSITIONING_PATH": ppath}), \
                 mock.patch.object(m.revenuecat, "metrics_overview",
                                   return_value={"ok": False, "metrics": {}, "error": "x"}), \
                 mock.patch.object(m, "http_probe", side_effect=RuntimeError("boom")):
                out = m.gather({})  # must not raise
        self.assertEqual(len(out["paywall"]), 1)
        self.assertFalse(out["paywall"][0]["ok"])


# --- analyze: computes ~0.4% conversion from the declared baseline -----------------------
class AnalyzeTests(unittest.TestCase):
    def test_paid_conversion_from_baseline_is_about_point_four_percent(self):
        """252 customers / 1 paid sub => ~0.4% paid conversion (declared-baseline source)."""
        out = m.analyze({"positioning": _BASELINE_POSITIONING, "rc": {"ok": False, "metrics": {}},
                         "paywall": []})
        findings = out["findings"]
        self.assertEqual(findings["customers"], 252)
        self.assertEqual(findings["paid_subscriptions"], 1)
        self.assertEqual(findings["source"], "declared_baseline")
        # 1/252 ≈ 0.003968 → ~0.40%.
        self.assertAlmostEqual(findings["paid_conversion"], 1 / 252, places=6)
        self.assertEqual(findings["paid_conversion_pct"], "~0.40%")
        # The conversion floor + the declared gaps are surfaced.
        self.assertIn("low_paid_conversion", findings["gaps"])
        self.assertIn("no_annual_plan", findings["gaps"])
        self.assertIn("trial_not_configured", findings["gaps"])
        self.assertIn("listing_mispositioned", findings["gaps"])

    def test_prefers_live_revenuecat_metrics_when_available(self):
        """When RC metrics succeed and expose numbers, analyze uses them over the baseline."""
        rc = {"ok": True, "metrics": {"customers": 1000, "active_subscriptions": 50}}
        out = m.analyze({"positioning": _BASELINE_POSITIONING, "rc": rc, "paywall": []})
        findings = out["findings"]
        self.assertEqual(findings["source"], "revenuecat")
        self.assertEqual(findings["customers"], 1000)
        self.assertEqual(findings["paid_subscriptions"], 50)
        self.assertAlmostEqual(findings["paid_conversion"], 0.05, places=6)

    def test_paywall_down_adds_gap(self):
        """An unreachable paywall surfaces a 'paywall_unreachable' gap."""
        out = m.analyze({"positioning": _BASELINE_POSITIONING, "rc": {"ok": False, "metrics": {}},
                         "paywall": [{"url": "u", "ok": False, "reachable": False}]})
        self.assertIn("paywall_unreachable", out["findings"]["gaps"])

    def test_no_data_does_not_crash_and_conversion_unknown(self):
        """Empty positioning + empty RC => no divide-by-zero; conversion is 'unknown'."""
        out = m.analyze({"positioning": {}, "rc": {"ok": False, "metrics": {}}, "paywall": []})
        self.assertIsNone(out["findings"]["paid_conversion"])
        self.assertEqual(out["findings"]["paid_conversion_pct"], "unknown")


# --- propose: deterministic fallback is non-empty when the model is unavailable ----------
class ProposeFallbackTests(unittest.TestCase):
    def _findings(self):
        return m.analyze({"positioning": _BASELINE_POSITIONING,
                          "rc": {"ok": False, "metrics": {}}, "paywall": []})["findings"]

    def test_deterministic_experiments_when_budget_guard_raises(self):
        """budget_guard raising must NOT crash propose — experiments come from the levers."""
        with mock.patch.object(m, "budget_guard", side_effect=RuntimeError("no API key")):
            out = m.propose({"positioning": _BASELINE_POSITIONING, "findings": self._findings()})
        experiments = out["experiments"]
        self.assertTrue(experiments)                              # NEVER empty
        self.assertGreaterEqual(len(experiments), m._MIN_EXPERIMENTS)
        self.assertLessEqual(len(experiments), m._MAX_EXPERIMENTS)
        # Every experiment has the canonical concrete shape.
        for exp in experiments:
            for key in ("hypothesis", "change", "metric_to_move", "effort", "expected_lift"):
                self.assertIn(key, exp)
        # The declared levers are concretely reflected (annual plan + trial experiments exist).
        blob = json.dumps(experiments).lower()
        self.assertIn("annual", blob)
        self.assertIn("trial", blob)

    def test_propose_uses_model_experiments_when_available(self):
        """When the model returns a valid JSON array, those experiments are used."""
        fake_model = mock.MagicMock()
        fake_model.invoke.return_value = mock.MagicMock(content=json.dumps([
            {"hypothesis": "H1", "change": "C1", "metric_to_move": "paid_conversion",
             "effort": "S", "expected_lift": "L1"},
            {"hypothesis": "H2", "change": "C2", "metric_to_move": "ARPU",
             "effort": "M", "expected_lift": "L2"},
        ]))
        with mock.patch.object(m, "budget_guard", return_value=fake_model):
            out = m.propose({"positioning": _BASELINE_POSITIONING, "findings": self._findings()})
        hyps = [e["hypothesis"] for e in out["experiments"]]
        self.assertIn("H1", hyps)
        self.assertIn("H2", hyps)

    def test_propose_falls_back_when_model_returns_garbage(self):
        """An unparseable model response falls back to the non-empty deterministic set."""
        fake_model = mock.MagicMock()
        fake_model.invoke.return_value = mock.MagicMock(content="not json at all")
        with mock.patch.object(m, "budget_guard", return_value=fake_model):
            out = m.propose({"positioning": _BASELINE_POSITIONING, "findings": self._findings()})
        self.assertTrue(out["experiments"])

    def test_propose_guards_outward_targets_against_model_work(self):
        """assert_not_model_work is applied to outward targets (digest repo + ASO repo)."""
        seen = []
        with mock.patch.object(m, "assert_not_model_work", side_effect=lambda t: seen.append(t)), \
             mock.patch.object(m, "budget_guard", side_effect=RuntimeError("no model")):
            m.propose({"positioning": _BASELINE_POSITIONING, "findings": self._findings()})
        self.assertIn(m.DIGEST_REPO, seen)
        self.assertIn("Scheduler-Systems/scheduler-ios", seen)

    def test_denylisted_target_is_skipped_not_fatal(self):
        """A denylisted outward target is skipped (ModelWorkBlocked) — propose still produces."""
        def guard(target):
            if "scheduler-ios" in target:
                raise m.ModelWorkBlocked("denied")
        with mock.patch.object(m, "assert_not_model_work", side_effect=guard), \
             mock.patch.object(m, "budget_guard", side_effect=RuntimeError("no model")):
            out = m.propose({"positioning": _BASELINE_POSITIONING, "findings": self._findings()})
        self.assertTrue(out["experiments"])


# --- compliance_scan: over-claims are flagged, never silently emitted -------------------
class ComplianceScanTests(unittest.TestCase):
    _PRODUCT = {"product": {"do_not_claim": ["time tracking", "AI scheduling",
                                             "clock-in/out", "offline"]}}

    def test_overclaim_in_model_draft_is_flagged(self):
        """A drafted experiment naming a do_not_claim feature must surface a compliance flag."""
        experiments = [
            {"hypothesis": "Add AI scheduling to auto-build rosters and lift paid conversion",
             "change": "Ship AI scheduling + time tracking", "metric_to_move": "paid_conversion",
             "effort": "L", "expected_lift": "big"},
            {"hypothesis": "h2", "change": "c2", "metric_to_move": "m",
             "effort": "S", "expected_lift": "l"},
        ]
        out = m.compliance_scan({"positioning": self._PRODUCT, "experiments": experiments})
        flags = out["compliance_flags"]
        self.assertTrue(flags)
        terms = {f["term"] for f in flags}
        self.assertIn("ai scheduling", terms)
        self.assertIn("time tracking", terms)
        # Flags point at the offending experiment + field (structured, reviewable).
        self.assertTrue(all({"index", "term", "field"} <= set(f) for f in flags))

    def test_clean_drafts_produce_no_flags(self):
        """Compliant drafts (only shipped features) produce zero flags."""
        experiments = [
            {"hypothesis": "Reposition the listing to shift scheduling",
             "change": "Rewrite ASO copy + screenshots (no app release)",
             "metric_to_move": "paid_conversion", "effort": "M", "expected_lift": "qualified installs"},
        ]
        out = m.compliance_scan({"positioning": self._PRODUCT, "experiments": experiments})
        self.assertEqual(out["compliance_flags"], [])

    def test_compliance_scan_failsafe_without_product_facts(self):
        """No product.do_not_claim list => no banned terms, no flags, never raises."""
        out = m.compliance_scan({"positioning": {}, "experiments": [{"change": "AI scheduling"}]})
        self.assertEqual(out["compliance_flags"], [])

    def test_overclaim_warning_rendered_into_delivered_body(self):
        """A non-empty compliance_flags set forces a prominent COMPLIANCE warning in the body."""
        body = m._render_body(
            {"source": "declared_baseline", "gaps": []},
            [{"hypothesis": "Add AI scheduling", "change": "ship it"}],
            [{"index": 1, "term": "ai scheduling", "field": "hypothesis"}],
        )
        self.assertIn("COMPLIANCE", body)
        self.assertIn("ai scheduling", body.lower())

    def test_clean_body_has_no_compliance_warning(self):
        """With no flags the body carries no COMPLIANCE warning (no false alarm)."""
        body = m._render_body({"source": "declared_baseline", "gaps": []},
                              [{"hypothesis": "h", "change": "c"}], [])
        self.assertNotIn("COMPLIANCE", body)

    def test_deliver_surfaces_overclaim_warning_end_to_end(self):
        """deliver renders the COMPLIANCE warning into the body it files (report-only)."""
        captured = {}

        def fake_file_issue(repo, title, body, *, labels=None, report_only=None, **kwargs):
            captured["body"] = body
            return {"status": "report_only"}

        env = {k: v for k, v in os.environ.items() if k != "OPS_REPORT_ONLY"}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(m, "write_local_digest", return_value="/tmp/x.md"), \
                mock.patch.object(m, "file_digest_issue", side_effect=fake_file_issue):
            out = m.deliver({
                "findings": {"source": "declared_baseline", "gaps": []},
                "experiments": [{"hypothesis": "Add AI scheduling", "change": "c"}],
                "compliance_flags": [{"index": 1, "term": "ai scheduling", "field": "hypothesis"}],
            })
        self.assertIn("COMPLIANCE", captured["body"])
        self.assertEqual(out["report"]["compliance_flags"], 1)


# --- deliver: report-only, labels, no hang ----------------------------------------------
class DeliverReportOnlyTests(unittest.TestCase):
    def test_deliver_is_report_only_and_never_writes(self):
        """deliver must call file_digest_issue with report_only=True and write nothing live."""
        captured = {}

        def fake_file_issue(repo, title, body, *, labels=None, report_only=None, **kwargs):
            captured["repo"] = repo
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
            out = m.deliver({
                "findings": {"paid_conversion_pct": "~0.40%", "gaps": ["low_paid_conversion"]},
                "experiments": [{"hypothesis": "h", "change": "c"}],
            })

        self.assertTrue(captured["report_only"])
        self.assertEqual(captured["repo"], m.DIGEST_REPO)
        self.assertEqual(captured["labels"], ["growth:experiment"])
        self.assertEqual(out["report"]["delivery"], "report_only")
        self.assertTrue(out["report_only"])
        self.assertEqual(out["report"]["experiments"], 1)

    def test_report_only_env_can_be_disabled(self):
        """Only an explicit 0/false/no flips report-only off; everything else stays True."""
        with mock.patch.dict(os.environ, {"OPS_REPORT_ONLY": "0"}):
            self.assertFalse(m._report_only())
        with mock.patch.dict(os.environ, {"OPS_REPORT_ONLY": "false"}):
            self.assertFalse(m._report_only())
        with mock.patch.dict(os.environ, {"OPS_REPORT_ONLY": "no"}):
            self.assertFalse(m._report_only())
        with mock.patch.dict(os.environ, {"OPS_REPORT_ONLY": "1"}):
            self.assertTrue(m._report_only())
        env = {k: v for k, v in os.environ.items() if k != "OPS_REPORT_ONLY"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertTrue(m._report_only())  # unset => report-only


# --- budget gate / clock-in: never hangs, ends on clock-out -----------------------------
class BudgetGateTests(unittest.TestCase):
    def test_clocked_out_ends_without_gather(self):
        """Clocked out: budget_gate reports + governance, the route goes to END (not gather)."""
        with mock.patch.object(m, "check_clocked_in", return_value=False), \
                mock.patch.object(m, "governance_capture") as gov, \
                mock.patch.object(m.revenuecat, "metrics_overview",
                                  side_effect=AssertionError("gather must not run")):
            out = m.budget_gate({})
            route = m._budget_route({})

        self.assertFalse(out["report"]["clocked_in"])
        self.assertTrue(out["report_only"])
        self.assertEqual(route, "clocked_out")
        gov.assert_called_once()
        self.assertTrue(gov.call_args[0][1]["report_only"])

    def test_clocked_in_proceeds_to_gather(self):
        with mock.patch.object(m, "check_clocked_in", return_value=True):
            out = m.budget_gate({})
            route = m._budget_route({})
        self.assertEqual(out, {})
        self.assertEqual(route, "gather")


# --- finalize: governance is report-only ------------------------------------------------
class FinalizeTests(unittest.TestCase):
    def test_finalize_captures_report_only_governance(self):
        with mock.patch.object(m, "governance_capture") as gov:
            out = m.finalize({
                "findings": {"paid_conversion_pct": "~0.40%", "gaps": ["low_paid_conversion"]},
                "experiments": [{"hypothesis": "h"}],
                "report": {"delivery": "report_only", "digest": "/tmp/d"},
            })
        self.assertTrue(out["report"]["report_only"])
        self.assertEqual(out["report"]["delivery"], "report_only")
        self.assertEqual(out["report"]["n_experiments"], 1)
        gov.assert_called_once()
        self.assertTrue(gov.call_args[0][1]["report_only"])


# --- end-to-end graph: unattended, no creds, never hangs --------------------------------
class GraphInvokeTests(unittest.TestCase):
    def test_full_run_report_only_no_creds(self):
        """Clocked in, no RC/model creds, report-only default => completes, never hangs."""
        env = dict(os.environ)
        env.pop("OPS_REPORT_ONLY", None)
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch.object(m, "check_clocked_in", return_value=True), \
             mock.patch.object(m.revenuecat, "metrics_overview",
                               return_value={"ok": False, "metrics": {}, "raw": [], "error": "x"}), \
             mock.patch.object(m, "http_probe",
                               return_value={"url": "u", "reachable": True, "ok": True, "status": 200}), \
             mock.patch.object(m, "budget_guard", side_effect=RuntimeError("no model")), \
             mock.patch.object(m, "write_local_digest", return_value=""), \
             mock.patch.object(m, "file_digest_issue",
                               return_value={"status": "report_only"}) as fd:
            out = m.graph.invoke({})
        # Non-empty experiments delivered report-only; governance report set.
        self.assertGreaterEqual(out["report"]["n_experiments"], m._MIN_EXPERIMENTS)
        self.assertTrue(out["report"]["report_only"])
        # file_digest_issue called with report_only=True (no GitHub call, no approval hang).
        self.assertTrue(fd.call_args.kwargs["report_only"])

    def test_clocked_out_graph_ends_without_work(self):
        with mock.patch.object(m, "check_clocked_in", return_value=False), \
             mock.patch.object(m.revenuecat, "metrics_overview") as mo, \
             mock.patch.object(m, "file_digest_issue") as fd:
            out = m.graph.invoke({})
        mo.assert_not_called()   # no RC work on the clocked-out path
        fd.assert_not_called()   # no delivery on the clocked-out path
        self.assertFalse(out["report"]["clocked_in"])


class GraphCompileTests(unittest.TestCase):
    def test_graph_compiles_without_checkpointer(self):
        self.assertIsNotNone(m.graph)


if __name__ == "__main__":
    unittest.main()
