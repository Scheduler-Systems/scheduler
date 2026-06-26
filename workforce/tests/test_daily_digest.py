"""Safety tests for the once-a-day daily_digest fleet aggregator.

It rolls the WHOLE fleet into ONE report led by an AUTONOMY SCOREBOARD (revenue sections
first), so the tests prove the load-bearing invariants on the pure node cores (no
checkpointer, no network): (1) scoreboard math — staffed/total/active/probation/coverage —
is correct against a mocked roster + a temp catalog; (2) the day-over-day delta is read from
a seeded history jsonl; (3) pending-approvals is FAIL-SAFE (gh raising => 0/"unavailable",
no crash); (4) the composed body puts REVENUE before quality/ops; (5) persist appends a jsonl
line; (6) deliver stays REPORT-ONLY (report_only=True); (7) per-class grouping puts growth
first. stdlib unittest + unittest.mock, no network. Run:
    .venv/bin/python -m unittest tests.test_daily_digest -v
"""
import json
import os
import tempfile
import unittest
from unittest import mock

from graphs.ops import daily_digest as m


def _roster(statuses: dict) -> dict:
    """Build a minimal roster dict: {agent: status} -> the load_roster() shape."""
    agents = {
        name: {"role": f"role-{name}", "status": status, "salary_tokens_per_week": 1000,
               "scorecard": {}}
        for name, status in statuses.items()
    }
    return {"policy": {}, "org": {}, "agents": agents}


# --- scoreboard math --------------------------------------------------------------------
class ScoreboardMathTests(unittest.TestCase):
    def test_staffed_active_probation_coverage(self):
        """2 active + 1 probation, catalog total K=8 => staffed=3, active=2, coverage=2/8."""
        roster = _roster({"a": "active", "b": "active", "c": "probation"})
        with tempfile.TemporaryDirectory() as td:
            cat = os.path.join(td, "catalog.json")
            with open(cat, "w", encoding="utf-8") as fh:
                json.dump({"prioritized_agents": [{"agent_name": f"r{i}"} for i in range(8)]}, fh)
            with mock.patch.dict(os.environ, {"DAILY_DIGEST_CATALOG_PATH": cat,
                                              "WORKSPACE_ROOT": td}), \
                 mock.patch.object(m.payroll, "load_roster", return_value=roster), \
                 mock.patch.object(m.payroll, "reconcile_with_langsmith", return_value=None), \
                 mock.patch.object(m.work_board, "fetch_open_issues", return_value=[]):
                out = m.scoreboard({})

        sb = out["scoreboard"]
        self.assertEqual(sb["staffed"], 3)
        self.assertEqual(sb["total"], 8)
        self.assertEqual(sb["active"], 2)
        self.assertEqual(sb["probation"], 1)
        self.assertEqual(sb["coverage"], round(2 / 8, 4))         # active / total
        self.assertEqual(sb["staffed_pct"], round(3 / 8, 4))

    def test_zero_catalog_total_is_fail_safe(self):
        """Missing/empty catalog => total 0 and coverage 0.0 (no division-by-zero crash)."""
        roster = _roster({"a": "active"})
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.dict(os.environ,
                                 {"DAILY_DIGEST_CATALOG_PATH": os.path.join(td, "missing.json"),
                                  "WORKSPACE_ROOT": td}), \
                 mock.patch.object(m.payroll, "load_roster", return_value=roster), \
                 mock.patch.object(m.payroll, "reconcile_with_langsmith", return_value=None), \
                 mock.patch.object(m.work_board, "fetch_open_issues", return_value=[]):
                out = m.scoreboard({})
        sb = out["scoreboard"]
        self.assertEqual(sb["total"], 0)
        self.assertEqual(sb["coverage"], 0.0)


# --- day-over-day delta -----------------------------------------------------------------
class DeltaTests(unittest.TestCase):
    def test_delta_from_seeded_history(self):
        """A seeded prior scoreboard line drives the ▲/▼ delta vs today's run."""
        roster = _roster({"a": "active", "b": "active", "c": "active"})  # 3 active today
        with tempfile.TemporaryDirectory() as td:
            cat = os.path.join(td, "catalog.json")
            with open(cat, "w", encoding="utf-8") as fh:
                json.dump({"prioritized_agents": [{"agent_name": f"r{i}"} for i in range(10)]}, fh)
            # Seed the prior scoreboard: yesterday had 2 staffed / 1 active / coverage 0.1.
            hist_dir = os.path.join(td, ".tmp", "daily-digest")
            os.makedirs(hist_dir, exist_ok=True)
            with open(os.path.join(hist_dir, "scoreboard-history.jsonl"), "w", encoding="utf-8") as fh:
                fh.write(json.dumps({"staffed": 2, "active": 1, "coverage": 0.1,
                                     "date": "2026-06-04"}) + "\n")
            with mock.patch.dict(os.environ, {"DAILY_DIGEST_CATALOG_PATH": cat,
                                              "WORKSPACE_ROOT": td}), \
                 mock.patch.object(m.payroll, "load_roster", return_value=roster), \
                 mock.patch.object(m.payroll, "reconcile_with_langsmith", return_value=None), \
                 mock.patch.object(m.work_board, "fetch_open_issues", return_value=[]):
                out = m.scoreboard({})

        delta = out["scoreboard"]["delta"]
        self.assertTrue(delta["had_prior"])
        self.assertEqual(delta["staffed"], 3 - 2)                 # +1 staffed
        self.assertEqual(delta["active"], 3 - 1)                  # +2 active
        self.assertEqual(delta["coverage"], round((3 / 10) - 0.1, 4))

    def test_no_prior_history_means_no_delta(self):
        roster = _roster({"a": "active"})
        with tempfile.TemporaryDirectory() as td:
            cat = os.path.join(td, "catalog.json")
            with open(cat, "w", encoding="utf-8") as fh:
                json.dump({"prioritized_agents": [{"agent_name": "r0"}]}, fh)
            with mock.patch.dict(os.environ, {"DAILY_DIGEST_CATALOG_PATH": cat,
                                              "WORKSPACE_ROOT": td}), \
                 mock.patch.object(m.payroll, "load_roster", return_value=roster), \
                 mock.patch.object(m.payroll, "reconcile_with_langsmith", return_value=None), \
                 mock.patch.object(m.work_board, "fetch_open_issues", return_value=[]):
                out = m.scoreboard({})
        self.assertFalse(out["scoreboard"]["delta"]["had_prior"])


# --- pending approvals fail-safe --------------------------------------------------------
class PendingApprovalsTests(unittest.TestCase):
    def test_fetch_raises_degrades_to_unavailable(self):
        """gh absent / fetch raising => 0 + 'unavailable', no crash."""
        with mock.patch.object(m.work_board, "fetch_open_issues",
                               side_effect=RuntimeError("gh missing")):
            res = m._pending_approvals()
        self.assertEqual(res["count"], 0)
        self.assertEqual(res["note"], "unavailable")

    def test_counts_gate_human_required(self):
        """Only issues labelled gate:human-required are counted."""
        class _Item:
            def __init__(self, labels):
                self.labels = labels
        items = [
            _Item(("gate:human-required",)),
            _Item(("bug",)),
            _Item(("gate:human-required", "digest:daily")),
        ]
        with mock.patch.object(m.work_board, "fetch_open_issues", return_value=items):
            res = m._pending_approvals()
        self.assertEqual(res["count"], 2)
        self.assertIsNone(res["note"])

    def test_scoreboard_does_not_crash_when_gh_raises(self):
        """The whole scoreboard node survives a raising work_board (pending => unavailable)."""
        roster = _roster({"a": "active"})
        with tempfile.TemporaryDirectory() as td:
            cat = os.path.join(td, "catalog.json")
            with open(cat, "w", encoding="utf-8") as fh:
                json.dump({"prioritized_agents": [{"agent_name": "r0"}]}, fh)
            with mock.patch.dict(os.environ, {"DAILY_DIGEST_CATALOG_PATH": cat,
                                              "WORKSPACE_ROOT": td}), \
                 mock.patch.object(m.payroll, "load_roster", return_value=roster), \
                 mock.patch.object(m.payroll, "reconcile_with_langsmith", return_value=None), \
                 mock.patch.object(m.work_board, "fetch_open_issues",
                                   side_effect=RuntimeError("gh missing")):
                out = m.scoreboard({})  # must NOT raise
        self.assertEqual(out["scoreboard"]["pending_approvals"]["note"], "unavailable")


# --- per-class grouping: growth first ---------------------------------------------------
class PerClassTests(unittest.TestCase):
    def test_growth_class_listed_first(self):
        """Per-class output groups revenue/growth FIRST, then quality, then ops."""
        roster = _roster({
            "conversion_growth_analyst": "active",          # growth
            "qa_lead_aggregator": "active",                 # qa
            "revenue_reporter": "active",                   # ops (deployed employee)
        })
        with tempfile.TemporaryDirectory() as td:
            cat = os.path.join(td, "catalog.json")
            with open(cat, "w", encoding="utf-8") as fh:
                json.dump({"prioritized_agents": [{"agent_name": f"r{i}"} for i in range(3)]}, fh)
            with mock.patch.dict(os.environ, {"DAILY_DIGEST_CATALOG_PATH": cat,
                                              "WORKSPACE_ROOT": td}), \
                 mock.patch.object(m.payroll, "load_roster", return_value=roster), \
                 mock.patch.object(m.payroll, "reconcile_with_langsmith", return_value=None), \
                 mock.patch.object(m.work_board, "fetch_open_issues", return_value=[]):
                out = m.scoreboard({})

        per_class = out["scoreboard"]["per_class"]
        # growth precedes qa precedes ops in the rendered dict order.
        keys = list(per_class.keys())
        self.assertLess(keys.index("growth"), keys.index("qa"))
        self.assertLess(keys.index("qa"), keys.index("ops"))
        # growth has exactly the one staffed growth agent.
        self.assertEqual(per_class["growth"]["staffed"], 1)
        self.assertEqual(per_class["qa"]["staffed"], 1)
        self.assertEqual(per_class["ops"]["staffed"], 1)

    def test_per_class_sums_langsmith_runs_and_tokens(self):
        """Reconciled LangSmith runs/tokens are summed per class (fail-safe None => 0)."""
        roster = _roster({"conversion_growth_analyst": "active"})

        def fake_recon(agent):
            return {"run_count": 5, "total_tokens": 1200} if agent == "conversion_growth_analyst" else None

        with tempfile.TemporaryDirectory() as td:
            cat = os.path.join(td, "catalog.json")
            with open(cat, "w", encoding="utf-8") as fh:
                json.dump({"prioritized_agents": [{"agent_name": "r0"}]}, fh)
            with mock.patch.dict(os.environ, {"DAILY_DIGEST_CATALOG_PATH": cat,
                                              "WORKSPACE_ROOT": td}), \
                 mock.patch.object(m.payroll, "load_roster", return_value=roster), \
                 mock.patch.object(m.payroll, "reconcile_with_langsmith", side_effect=fake_recon), \
                 mock.patch.object(m.work_board, "fetch_open_issues", return_value=[]):
                out = m.scoreboard({})
        growth = out["scoreboard"]["per_class"]["growth"]
        self.assertEqual(growth["runs"], 5)
        self.assertEqual(growth["tokens"], 1200)


# --- compose: revenue before quality/ops ------------------------------------------------
class ComposeOrderingTests(unittest.TestCase):
    def _state(self):
        return {
            "scoreboard": {"staffed": 1, "total": 2, "active": 1, "probation": 0,
                           "coverage": 0.5, "staffed_pct": 0.5,
                           "pending_approvals": {"count": 0, "note": None},
                           "per_class": {c: {"roles": [], "staffed": 0, "runs": 0, "tokens": 0}
                                         for c in m.CLASS_ORDER},
                           "delta": {"had_prior": False}},
            "revenue": {"rc": {"ok": True, "metrics": {"mrr": 999}}, "digests": {}},
            "quality": {"digests": {}},
            "ops": {"digests": {}},
            "workforce": [],
        }

    def test_revenue_section_before_quality_and_ops(self):
        """REVENUE must appear BEFORE quality and ops in the composed body (revenue leads)."""
        with mock.patch.object(m, "budget_guard", side_effect=RuntimeError("no model")):
            out = m.compose(self._state())
        body = out["body"]
        i_rev = body.index("💰 REVENUE")
        i_qual = body.index("🧪 QUALITY")
        i_ops = body.index("🛠️ OPS")
        self.assertLess(i_rev, i_qual)
        self.assertLess(i_qual, i_ops)

    def test_board_leads_then_scoreboard_then_revenue(self):
        """Board investor-update leads the body; then the scoreboard precedes the revenue section.
        (Subordinate digests are isolated so their text can't collide with structural markers.)"""
        with mock.patch.object(m, "budget_guard", side_effect=RuntimeError("no model")), \
             mock.patch.object(m, "_read_local_digest", return_value="(no digest yet)"):
            out = m.compose(self._state())
        body = out["body"]
        self.assertTrue(body.lstrip().startswith("# 🏛️ BOARD → INVESTOR UPDATE"))
        self.assertLess(body.index("AUTONOMY SCOREBOARD"), body.index("💰 REVENUE"))

    def test_compose_never_empty_without_model(self):
        """budget_guard raising must NOT crash compose — body still built from facts."""
        with mock.patch.object(m, "budget_guard", side_effect=RuntimeError("no API key")):
            out = m.compose(self._state())
        self.assertTrue(out["body"].strip())
        self.assertIn("mrr", out["body"])                 # built from the gathered facts

    def test_compose_includes_model_narrative_when_available(self):
        """Narrative sits above the scoreboard (the board investor-update is now the very top)."""
        fake_model = mock.MagicMock()
        fake_model.invoke.return_value = mock.MagicMock(content="TODAY IN ONE LINE")
        with mock.patch.object(m, "budget_guard", return_value=fake_model), \
             mock.patch.object(m, "_read_local_digest", return_value="(no digest yet)"):
            out = m.compose(self._state())
        body = out["body"]
        self.assertIn("TODAY IN ONE LINE", body)
        self.assertTrue(body.lstrip().startswith("# 🏛️ BOARD → INVESTOR UPDATE"))
        self.assertLess(body.index("TODAY IN ONE LINE"), body.index("AUTONOMY SCOREBOARD"))


# --- persist: appends a jsonl line ------------------------------------------------------
class PersistTests(unittest.TestCase):
    def test_persist_appends_jsonl_line(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.dict(os.environ, {"WORKSPACE_ROOT": td}):
                out = m.persist({"scoreboard": {"staffed": 4, "active": 3, "coverage": 0.3}})
                path = out["report"]["history"]
                self.assertTrue(path)
                with open(path, "r", encoding="utf-8") as fh:
                    lines = [l for l in fh if l.strip()]
                self.assertEqual(len(lines), 1)
                rec = json.loads(lines[0])
                self.assertEqual(rec["staffed"], 4)
                self.assertIn("date", rec)               # stamped with today's date

    def test_persist_appends_a_second_line(self):
        """Persist APPENDS — a second run adds a new line, not overwrites."""
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.dict(os.environ, {"WORKSPACE_ROOT": td}):
                m.persist({"scoreboard": {"staffed": 1}})
                out = m.persist({"scoreboard": {"staffed": 2}})
                with open(out["report"]["history"], "r", encoding="utf-8") as fh:
                    lines = [l for l in fh if l.strip()]
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[-1])["staffed"], 2)

    def test_persist_is_fail_safe(self):
        """A persistence failure returns '' and never raises."""
        with mock.patch.object(m, "_append_scoreboard", return_value=""):
            out = m.persist({"scoreboard": {"staffed": 1}})
        self.assertEqual(out["report"]["history"], "")


# --- deliver: report-only ---------------------------------------------------------------
class DeliverReportOnlyTests(unittest.TestCase):
    def test_deliver_is_report_only_and_never_writes(self):
        """deliver must call file_digest_issue with report_only=True and the daily label."""
        captured = {}

        def fake_file(repo, title, body, *, labels=None, report_only=None, **kwargs):
            captured.update(repo=repo, title=title, labels=labels, report_only=report_only)
            assert report_only is True, "deliver must stay report-only on probation"
            return {"status": "report_only", "action": "open_issue", "repo": repo}

        env = {k: v for k, v in os.environ.items() if k != "OPS_REPORT_ONLY"}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(m, "write_local_digest", return_value="/tmp/d/latest.md") as wd, \
                mock.patch.object(m, "file_digest_issue", side_effect=fake_file):
            out = m.deliver({"body": "the digest", "report": {"history": "/tmp/h.jsonl"}})

        self.assertTrue(captured["report_only"])
        self.assertEqual(captured["repo"], m.DIGEST_REPO)
        self.assertEqual(captured["title"], "Daily fleet digest")
        self.assertEqual(captured["labels"], ["digest:daily"])
        self.assertEqual(out["report"]["delivery"], "report_only")
        self.assertTrue(out["report_only"])
        self.assertEqual(out["report"]["history"], "/tmp/h.jsonl")  # carried through from persist
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


# --- local digest reads -----------------------------------------------------------------
class LocalDigestTests(unittest.TestCase):
    def test_missing_file_returns_placeholder(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.dict(os.environ, {"WORKSPACE_ROOT": td}):
                self.assertEqual(m._read_local_digest("nope"), "(no digest yet)")

    def test_existing_file_is_read(self):
        with tempfile.TemporaryDirectory() as td:
            d = os.path.join(td, ".tmp", "store-health-checker")
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "latest.md"), "w", encoding="utf-8") as fh:
                fh.write("STORE OK")
            with mock.patch.dict(os.environ, {"WORKSPACE_ROOT": td}):
                self.assertEqual(m._read_local_digest("store-health-checker"), "STORE OK")


# --- budget gate / clock-in: never hangs, ends on clock-out -----------------------------
class BudgetGateTests(unittest.TestCase):
    def test_clocked_out_routes_to_end_and_reports(self):
        with mock.patch.object(m, "check_clocked_in", return_value=False), \
                mock.patch.object(m, "governance_capture") as gov:
            out = m.budget_gate({})
            self.assertTrue(out["report_only"])
            self.assertEqual(out["report"]["status"], "skipped")
            self.assertEqual(m._budget_route({}), "clocked_out")
        gov.assert_called_once()
        self.assertTrue(gov.call_args[0][1]["report_only"])

    def test_clocked_in_routes_to_scoreboard(self):
        with mock.patch.object(m, "check_clocked_in", return_value=True):
            self.assertEqual(m.budget_gate({}), {})
            self.assertEqual(m._budget_route({}), "scoreboard")


# --- finalize ----------------------------------------------------------------------------
class FinalizeTests(unittest.TestCase):
    def test_finalize_captures_report_only_governance(self):
        with mock.patch.object(m, "governance_capture") as gov:
            out = m.finalize({"scoreboard": {"staffed": 3, "total": 8, "active": 2,
                                             "coverage": 0.25},
                              "report": {"delivery": "report_only", "digest": "/tmp/d",
                                         "history": "/tmp/h"}})
        self.assertTrue(out["report"]["report_only"])
        self.assertEqual(out["report"]["delivery"], "report_only")
        self.assertEqual(out["report"]["coverage"], 0.25)
        gov.assert_called_once()
        self.assertTrue(gov.call_args[0][1]["report_only"])


# --- end-to-end graph: unattended, no creds, never hangs --------------------------------
class GraphInvokeTests(unittest.TestCase):
    def test_graph_compiles_without_checkpointer(self):
        self.assertIsNotNone(m.graph)

    def test_full_run_report_only_no_creds(self):
        roster = _roster({"a": "active", "b": "probation"})
        with tempfile.TemporaryDirectory() as td:
            cat = os.path.join(td, "catalog.json")
            with open(cat, "w", encoding="utf-8") as fh:
                json.dump({"prioritized_agents": [{"agent_name": f"r{i}"} for i in range(5)]}, fh)
            env = {k: v for k, v in os.environ.items() if k != "OPS_REPORT_ONLY"}
            env.update({"DAILY_DIGEST_CATALOG_PATH": cat, "WORKSPACE_ROOT": td})
            with mock.patch.dict(os.environ, env, clear=True), \
                 mock.patch.object(m, "check_clocked_in", return_value=True), \
                 mock.patch.object(m.payroll, "load_roster", return_value=roster), \
                 mock.patch.object(m.payroll, "reconcile_with_langsmith", return_value=None), \
                 mock.patch.object(m.work_board, "fetch_open_issues", return_value=[]), \
                 mock.patch.object(m.revenuecat, "metrics_overview",
                                   return_value={"ok": False, "metrics": {}, "raw": [], "error": "x"}), \
                 mock.patch.object(m, "budget_guard", side_effect=RuntimeError("no model")), \
                 mock.patch.object(m, "file_digest_issue",
                                   return_value={"status": "report_only"}) as fd:
                out = m.graph.invoke({})
                # The scoreboard history was appended during the run (assert while
                # WORKSPACE_ROOT still points at the temp dir).
                self.assertTrue(os.path.exists(m._history_path()))

        self.assertTrue(out["report"]["report_only"])
        self.assertEqual(out["report"]["staffed"], 2)
        self.assertEqual(out["report"]["total"], 5)
        self.assertEqual(out["report"]["delivery"], "report_only")
        self.assertTrue(fd.call_args.kwargs["report_only"])  # no GitHub call, no approval hang

    def test_clocked_out_graph_ends_without_work(self):
        with mock.patch.object(m, "check_clocked_in", return_value=False), \
                mock.patch.object(m.payroll, "load_roster") as lr, \
                mock.patch.object(m, "file_digest_issue") as fd:
            out = m.graph.invoke({})
        lr.assert_not_called()   # no roster read on the clocked-out path
        fd.assert_not_called()   # no delivery on the clocked-out path
        self.assertEqual(out["report"]["status"], "skipped")


if __name__ == "__main__":
    unittest.main()
