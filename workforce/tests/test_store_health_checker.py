"""Tests for store_health_checker — the revenue store/RC health watcher.

It must NOTICE (a) non-purchasable SKUs (the "could not check store status" family),
(b) baseline drift, (c) broken packages, and (d) a dead paywall — and deliver report-only
without ever hanging or writing. stdlib unittest + unittest.mock, no network. Run:
    .venv/bin/python -m unittest tests.test_store_health_checker -v
"""
import json
import os
import tempfile
import unittest
from unittest import mock

from graphs.ops import store_health_checker as m


# --- check_skus: non-purchasable + unverifiable + broken package + drift ----------------
class CheckSkusTests(unittest.TestCase):
    def test_non_purchasable_high_finding(self):
        with mock.patch.object(m.revenuecat, "is_configured", return_value=True), \
             mock.patch.object(m.revenuecat, "list_products",
                               return_value={"ok": True, "items": [{"id": "x", "store_identifier": ""}]}), \
             mock.patch.object(m.revenuecat, "list_offerings",
                               return_value={"ok": True, "items": []}):
            out = m.check_skus({})
        kinds = [f["kind"] for f in out["sku_findings"]]
        self.assertIn("non_purchasable", kinds)
        np = next(f for f in out["sku_findings"] if f["kind"] == "non_purchasable")
        self.assertEqual(np["severity"], "high")

    def test_rc_not_configured_emits_unverifiable_could_not_check(self):
        with mock.patch.object(m.revenuecat, "is_configured", return_value=False):
            out = m.check_skus({})
        self.assertEqual(len(out["sku_findings"]), 1)
        f = out["sku_findings"][0]
        self.assertEqual(f["kind"], "unverifiable")
        self.assertEqual(f["severity"], "warn")
        self.assertIn("could not check store status", f["detail"])

    def test_broken_package_high_finding(self):
        # A package references a product id that is NOT among the products list.
        offering = {"id": "off1", "packages": {"items": [{"id": "p1", "product_id": "ghost"}]}}
        with mock.patch.object(m.revenuecat, "is_configured", return_value=True), \
             mock.patch.object(m.revenuecat, "list_products",
                               return_value={"ok": True, "items": [{"id": "real", "store_identifier": "sku.real"}]}), \
             mock.patch.object(m.revenuecat, "list_offerings",
                               return_value={"ok": True, "items": [offering]}):
            out = m.check_skus({})
        bp = [f for f in out["sku_findings"] if f["kind"] == "broken_package"]
        self.assertEqual(len(bp), 1)
        self.assertEqual(bp[0]["severity"], "high")
        self.assertIn("ghost", bp[0]["detail"])

    def test_baseline_drift_missing_expected_product(self):
        # Baseline expects 'pro_monthly' + 'pro_yearly'; RC only returns 'pro_monthly'.
        with tempfile.TemporaryDirectory() as td:
            bpath = os.path.join(td, "rc_baseline.json")
            with open(bpath, "w", encoding="utf-8") as fh:
                json.dump({"products": ["pro_monthly", "pro_yearly"], "offerings": []}, fh)
            with mock.patch.dict(os.environ, {"RC_BASELINE_PATH": bpath}), \
                 mock.patch.object(m.revenuecat, "is_configured", return_value=True), \
                 mock.patch.object(m.revenuecat, "list_products",
                                   return_value={"ok": True,
                                                 "items": [{"id": "pro_monthly", "store_identifier": "sku.m"}]}), \
                 mock.patch.object(m.revenuecat, "list_offerings",
                                   return_value={"ok": True, "items": []}):
                out = m.check_skus({})
        drift = [f for f in out["sku_findings"] if f["kind"] == "drift"]
        self.assertTrue(any("pro_yearly" in f["detail"] and f["severity"] == "medium" for f in drift))

    def test_malformed_items_do_not_crash_check_skus(self):
        # FAIL-SAFE: SDK/contract drift could return a non-list 'items' (dict/str/None).
        # A dict 'items' previously crashed on the offerings[:cap] slice (KeyError). The
        # node must degrade to "no products/offerings", never raise.
        for bad in ({"oops": 1}, "not-a-list", None, 7):
            with mock.patch.object(m.revenuecat, "is_configured", return_value=True), \
                 mock.patch.object(m.revenuecat, "list_products",
                                   return_value={"ok": True, "items": bad}), \
                 mock.patch.object(m.revenuecat, "list_offerings",
                                   return_value={"ok": True, "items": bad}):
                out = m.check_skus({})  # must NOT raise for any shape
            self.assertEqual(out["products"], [])
            self.assertEqual(out["offerings"], [])

    def test_empty_baseline_skips_drift(self):
        # Baseline present but empty => "no baseline configured" => NO false drift alarms.
        with tempfile.TemporaryDirectory() as td:
            bpath = os.path.join(td, "rc_baseline.json")
            with open(bpath, "w", encoding="utf-8") as fh:
                json.dump({"products": [], "offerings": []}, fh)
            with mock.patch.dict(os.environ, {"RC_BASELINE_PATH": bpath}), \
                 mock.patch.object(m.revenuecat, "is_configured", return_value=True), \
                 mock.patch.object(m.revenuecat, "list_products",
                                   return_value={"ok": True,
                                                 "items": [{"id": "p", "store_identifier": "sku.p"}]}), \
                 mock.patch.object(m.revenuecat, "list_offerings",
                                   return_value={"ok": True, "items": []}):
                out = m.check_skus({})
        self.assertEqual([f for f in out["sku_findings"] if f["kind"] == "drift"], [])


# --- check_paywall: fail-safe high finding, never raises --------------------------------
class CheckPaywallTests(unittest.TestCase):
    def test_unreachable_url_is_high_finding_no_raise(self):
        def fake_probe(url, **kw):
            return {"url": url, "reachable": False, "ok": False, "status": None,
                    "error": "unreachable: ConnectError"}
        with mock.patch.dict(os.environ, {"REVENUE_PAYWALL_URLS": "https://paywall.example/"}), \
             mock.patch.object(m, "http_probe", side_effect=fake_probe):
            out = m.check_paywall({})
        self.assertEqual(len(out["paywall"]), 1)
        self.assertEqual(out["paywall"][0]["severity"], "high")
        self.assertEqual(out["paywall"][0]["kind"], "paywall_down")

    def test_probe_exception_does_not_crash_node(self):
        with mock.patch.dict(os.environ, {"REVENUE_PAYWALL_URLS": "https://x/"}), \
             mock.patch.object(m, "http_probe", side_effect=RuntimeError("boom")):
            out = m.check_paywall({})  # must not raise
        self.assertEqual(out["paywall"][0]["severity"], "high")


# --- triage: severity escalation --------------------------------------------------------
class TriageTests(unittest.TestCase):
    def test_high_finding_escalates_to_high(self):
        state = {"sku_findings": [{"severity": "high", "kind": "non_purchasable", "detail": "x"}],
                 "paywall": []}
        with mock.patch.object(m, "budget_guard", side_effect=RuntimeError("no model")):
            out = m.triage(state)
        self.assertEqual(out["severity"], "high")

    def test_paywall_down_escalates_to_high(self):
        state = {"sku_findings": [],
                 "paywall": [{"url": "u", "ok": False, "reachable": False}]}
        with mock.patch.object(m, "budget_guard", side_effect=RuntimeError("no model")):
            out = m.triage(state)
        self.assertEqual(out["severity"], "high")

    def test_only_medium_drift_is_medium(self):
        state = {"sku_findings": [{"severity": "medium", "kind": "drift", "detail": "x"}],
                 "paywall": [{"ok": True}]}
        with mock.patch.object(m, "budget_guard", side_effect=RuntimeError("no model")):
            out = m.triage(state)
        self.assertEqual(out["severity"], "medium")

    def test_clean_is_ok(self):
        with mock.patch.object(m, "budget_guard", side_effect=RuntimeError("no model")):
            out = m.triage({"sku_findings": [], "paywall": [{"ok": True}]})
        self.assertEqual(out["severity"], "ok")


# --- deliver: report-only, labels, no hang ----------------------------------------------
class DeliverTests(unittest.TestCase):
    def test_deliver_calls_file_digest_issue_report_only_true(self):
        captured = {}
        def fake_file(repo, title, body, *, labels=None, report_only=None, **kwargs):
            captured.update(repo=repo, title=title, labels=labels, report_only=report_only)
            return {"status": "report_only"}
        with mock.patch.dict(os.environ, {}, clear=False), \
             mock.patch.object(m, "_report_only", return_value=True), \
             mock.patch.object(m, "write_local_digest", return_value="/tmp/x.md") as wd, \
             mock.patch.object(m, "file_digest_issue", side_effect=fake_file):
            out = m.deliver({"severity": "high", "summary": "s", "sku_findings": [], "paywall": []})
        self.assertTrue(captured["report_only"])  # report-only => never hangs / never writes
        self.assertEqual(captured["repo"], m.DIGEST_REPO)
        self.assertIn("alert:store-health", captured["labels"])
        self.assertIn("gate:human-required", captured["labels"])  # high severity adds the gate label
        self.assertEqual(out["report"]["delivery"], "report_only")
        self.assertTrue(out["report_only"])
        wd.assert_called_once()

    def test_non_high_severity_omits_gate_label(self):
        captured = {}
        def fake_file(repo, title, body, *, labels=None, report_only=None, **kwargs):
            captured.update(labels=labels)
            return {"status": "report_only"}
        with mock.patch.object(m, "_report_only", return_value=True), \
             mock.patch.object(m, "write_local_digest", return_value=""), \
             mock.patch.object(m, "file_digest_issue", side_effect=fake_file):
            m.deliver({"severity": "medium", "summary": "s", "sku_findings": [], "paywall": []})
        self.assertIn("alert:store-health", captured["labels"])
        self.assertNotIn("gate:human-required", captured["labels"])


# --- _report_only env contract ----------------------------------------------------------
class ReportOnlyEnvTests(unittest.TestCase):
    def test_unset_defaults_true(self):
        env = dict(os.environ)
        env.pop("OPS_REPORT_ONLY", None)
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertTrue(m._report_only())

    def test_truthy_is_true(self):
        with mock.patch.dict(os.environ, {"OPS_REPORT_ONLY": "1"}):
            self.assertTrue(m._report_only())

    def test_zero_is_false(self):
        with mock.patch.dict(os.environ, {"OPS_REPORT_ONLY": "0"}):
            self.assertFalse(m._report_only())

    def test_false_is_false(self):
        with mock.patch.dict(os.environ, {"OPS_REPORT_ONLY": "false"}):
            self.assertFalse(m._report_only())


# --- budget gate / clock-in: never hangs, ends on clock-out -----------------------------
class BudgetGateTests(unittest.TestCase):
    def test_clocked_out_routes_to_end_and_reports(self):
        with mock.patch.object(m, "check_clocked_in", return_value=False):
            out = m.budget_gate({})
            self.assertTrue(out["report_only"])
            self.assertEqual(m._budget_route({}), "clocked_out")

    def test_clocked_in_routes_to_check_skus(self):
        with mock.patch.object(m, "check_clocked_in", return_value=True):
            self.assertEqual(m.budget_gate({}), {})
            self.assertEqual(m._budget_route({}), "check_skus")


# --- end-to-end graph: unattended, no creds, never hangs --------------------------------
class GraphInvokeTests(unittest.TestCase):
    def test_full_run_report_only_no_creds(self):
        def fake_probe(url, **kw):
            return {"url": url, "reachable": False, "ok": False, "status": None, "error": "x"}
        env = dict(os.environ)
        env.pop("OPS_REPORT_ONLY", None)
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch.object(m, "check_clocked_in", return_value=True), \
             mock.patch.object(m.revenuecat, "is_configured", return_value=False), \
             mock.patch.object(m, "http_probe", side_effect=fake_probe), \
             mock.patch.object(m, "budget_guard", side_effect=RuntimeError("no model")), \
             mock.patch.object(m, "write_local_digest", return_value=""), \
             mock.patch.object(m, "file_digest_issue",
                               return_value={"status": "report_only"}) as fd:
            out = m.graph.invoke({})
        # Unverifiable SKU + paywall down => high; delivered report-only; governance report set.
        self.assertEqual(out["report"]["severity"], "high")
        self.assertTrue(out["report"]["report_only"])
        # file_digest_issue called with report_only=True (no GitHub call, no approval hang).
        self.assertTrue(fd.call_args.kwargs["report_only"])

    def test_clocked_out_graph_ends_without_checks(self):
        with mock.patch.object(m, "check_clocked_in", return_value=False), \
             mock.patch.object(m.revenuecat, "list_products") as lp, \
             mock.patch.object(m, "file_digest_issue") as fd:
            out = m.graph.invoke({})
        lp.assert_not_called()   # no RC work on the clocked-out path
        fd.assert_not_called()   # no delivery on the clocked-out path
        self.assertEqual(out["report"]["severity"], "skipped")


if __name__ == "__main__":
    unittest.main()
