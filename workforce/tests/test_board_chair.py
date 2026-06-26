"""Safety tests for the board_chair officer agent.

The chair CONSUMES the subordinate digests (ceo, audit-risk-director, growth-director,
daily-digest, cfo) and hands Shay ONE tight investor update: (a) KPIs, (b) decisions made
inside the org, (c) asks — ONLY capital/irreversible/legal items reach Shay; otherwise
"no asks". The tests prove the load-bearing invariants on the pure node cores (no
checkpointer, no network): (1) gather reads subordinate digests FAIL-SAFE (missing => "(no
digest yet)"); (2) the update has KPIs + an asks section, and empty asks renders "no asks";
(3) a Shay-level escalation in a subordinate digest surfaces as an escalate_to "shay" ask;
(4) compose always produces a non-empty deterministic update when the model is unavailable;
(5) deliver stays REPORT-ONLY (no GitHub write, no approval interrupt); (6) the clock-in gate
routes a clocked-out run straight to END. stdlib unittest + unittest.mock, no network. Run:
    .venv/bin/python -m unittest tests.test_board_chair -v
"""
import os
import tempfile
import unittest
from unittest import mock

from graphs.board import board_chair as m


def _roster(statuses: dict, salary: int = 1000) -> dict:
    """Minimal roster dict: {agent: status} -> the load_roster() shape."""
    agents = {
        name: {"role": f"role-{name}", "status": status,
               "salary_tokens_per_week": salary, "scorecard": {}}
        for name, status in statuses.items()
    }
    return {"policy": {}, "org": {}, "agents": agents}


# --- gather: consumes subordinate digests fail-safe -------------------------------------
class GatherTests(unittest.TestCase):
    def test_gather_reads_every_subordinate_digest_failsafe(self):
        """Missing digests degrade to '(no digest yet)'; gather never raises and KPIs assemble."""
        roster = _roster({"a": "active", "b": "probation"})
        with mock.patch.object(m, "read_local_digest", return_value="(no digest yet)") as rd, \
                mock.patch.object(m.payroll, "load_roster", return_value=roster), \
                mock.patch.object(m.payroll, "salary", return_value=1000), \
                mock.patch.object(m.payroll, "spent", return_value=200), \
                mock.patch.object(m.revenuecat, "metrics_overview",
                                  return_value={"ok": False, "metrics": {}, "error": "x"}):
            out = m.gather({})

        # Every subordinate slug was consumed (chair CONSUMES, never re-does).
        self.assertEqual(set(out["reports"].keys()), set(m.SUBORDINATE_DIGESTS))
        for slug in m.SUBORDINATE_DIGESTS:
            rd.assert_any_call(slug)
        # KPIs assembled off the roster despite zero digests.
        self.assertEqual(out["kpis"]["staffed"], 2)
        # active = operationally on-shift (clocked-in: not disabled/benched/over-budget). Both 'a'
        # and 'b' are clocked-in here, so both count — probation status no longer excludes an agent
        # that is actually working its shift (was the misleading "0 active" the founder flagged).
        self.assertEqual(out["kpis"]["active"], 2)

    def test_gather_survives_roster_and_rc_failure(self):
        """A raising roster + RC => KPIs degrade to safe defaults, no crash."""
        with mock.patch.object(m, "read_local_digest", return_value="(no digest yet)"), \
                mock.patch.object(m.payroll, "load_roster",
                                  side_effect=RuntimeError("no roster")), \
                mock.patch.object(m.revenuecat, "metrics_overview",
                                  side_effect=RuntimeError("no RC")):
            out = m.gather({})
        self.assertEqual(out["kpis"]["staffed"], 0)
        self.assertEqual(out["kpis"]["active"], 0)
        self.assertFalse(out["kpis"]["revenue"]["ok"])

    def test_kpis_compute_burn_and_revenue(self):
        """Burn = sum salary vs spent; revenue pulled from RC metrics."""
        roster = _roster({"a": "active", "b": "active"}, salary=1000)
        with mock.patch.object(m, "read_local_digest", return_value="(no digest yet)"), \
                mock.patch.object(m.payroll, "load_roster", return_value=roster), \
                mock.patch.object(m.payroll, "salary", return_value=1000), \
                mock.patch.object(m.payroll, "spent", return_value=600), \
                mock.patch.object(m.revenuecat, "metrics_overview",
                                  return_value={"ok": True,
                                                "metrics": {"mrr": 4200,
                                                            "active_subscriptions": 11}}):
            out = m.gather({})
        burn = out["kpis"]["burn"]
        self.assertEqual(burn["salary_tokens"], 2000)     # 2 x 1000
        self.assertEqual(burn["spent_tokens"], 1200)      # 2 x 600
        self.assertFalse(burn["over_budget"])
        self.assertTrue(out["kpis"]["revenue"]["ok"])
        self.assertEqual(out["kpis"]["revenue"]["mrr"], 4200)


# --- synthesize: decisions (org) + asks (shay only) -------------------------------------
class SynthesizeTests(unittest.TestCase):
    def test_no_shay_triggers_means_no_asks(self):
        """Routine subordinate reports => decisions escalate_to org, asks EMPTY."""
        reports = {slug: f"{slug} ran fine, nothing to escalate." for slug in m.SUBORDINATE_DIGESTS}
        out = m.synthesize({"reports": reports})
        # Decisions are all org-level, one per subordinate.
        self.assertEqual(len(out["decisions"]), len(m.SUBORDINATE_DIGESTS))
        for d in out["decisions"]:
            self.assertEqual(d["escalate_to"], "org")
        # No capital/irreversible/legal flag => no asks for Shay.
        self.assertEqual(out["asks"], [])

    def test_capital_item_surfaces_as_shay_ask(self):
        """A capital/legal escalation in a subordinate digest becomes an escalate_to 'shay' ask."""
        reports = {slug: "(no digest yet)" for slug in m.SUBORDINATE_DIGESTS}
        reports["cfo"] = "Need capital approval for new GPU spend; escalate_to: shay"
        out = m.synthesize({"reports": reports})
        self.assertEqual(len(out["asks"]), 1)
        ask = out["asks"][0]
        self.assertEqual(ask["escalate_to"], "shay")
        self.assertEqual(ask["source"], "cfo")

    def test_legal_keyword_triggers_ask(self):
        """A legal/contract mention also rises to a Shay-level ask (conservative trigger set)."""
        reports = {slug: "(no digest yet)" for slug in m.SUBORDINATE_DIGESTS}
        reports["audit-risk-director"] = "Open legal liability on the contract terms."
        out = m.synthesize({"reports": reports})
        self.assertEqual(len(out["asks"]), 1)
        self.assertEqual(out["asks"][0]["source"], "audit-risk-director")


# --- compose: tight update, KPIs + asks section, deterministic fallback -----------------
class ComposeTests(unittest.TestCase):
    def _state(self, asks=None):
        return {
            "kpis": {
                "staffed": 3, "active": 2,
                "burn": {"salary_tokens": 3000, "spent_tokens": 1000,
                         "remaining_tokens": 2000, "over_budget": False},
                "revenue": {"ok": True, "mrr": 4200, "revenue": 9000,
                            "active_subscriptions": 11, "active_trials": 3},
                "output": {"tests_landed": "reported", "drafts_produced": "(no digest yet)"},
            },
            "decisions": [{"decision": "ceo report reviewed", "source": "ceo",
                           "escalate_to": "org"}],
            "asks": asks if asks is not None else [],
        }

    def test_update_has_kpis_and_empty_asks_says_no_asks(self):
        """The deterministic update carries KPIs and, with no asks, reads 'no asks'."""
        with mock.patch.object(m, "budget_guard", side_effect=RuntimeError("no model")):
            out = m.compose(self._state(asks=[]))
        body = out["body"]
        self.assertTrue(body.strip())                     # never empty
        self.assertIn("## KPIs", body)
        self.assertIn("MRR=4200", body)                   # built from the assembled KPIs
        self.assertIn("no asks", body.lower())            # empty asks => 'no asks'
        self.assertIn("RuntimeError", body)               # fallback labelled, not faked

    def test_update_renders_shay_ask_when_present(self):
        """A Shay-level ask is rendered in the asks section with escalate_to shay."""
        asks = [{"ask": "capital approval needed", "source": "cfo", "escalate_to": "shay"}]
        with mock.patch.object(m, "budget_guard", side_effect=RuntimeError("no model")):
            out = m.compose(self._state(asks=asks))
        body = out["body"]
        self.assertIn("capital approval needed", body)
        self.assertIn("escalate_to: shay", body)
        self.assertNotIn("no asks", body.lower())

    def test_kpis_lead_then_decisions_then_asks(self):
        """Tight board order: KPIs, then decisions, then asks."""
        with mock.patch.object(m, "budget_guard", side_effect=RuntimeError("no model")):
            out = m.compose(self._state())
        body = out["body"]
        i_kpi = body.index("## KPIs")
        i_dec = body.index("Decisions made")
        i_ask = body.index("Asks for Shay")
        self.assertLess(i_kpi, i_dec)
        self.assertLess(i_dec, i_ask)

    def test_compose_prepends_model_note_when_available(self):
        fake_model = mock.MagicMock()
        fake_model.invoke.return_value = mock.MagicMock(content="THE HEADLINE")
        with mock.patch.object(m, "budget_guard", return_value=fake_model):
            out = m.compose(self._state())
        self.assertTrue(out["body"].startswith("THE HEADLINE"))

    def test_compose_falls_back_when_model_returns_empty(self):
        """An empty model response still yields a non-empty deterministic update."""
        fake_model = mock.MagicMock()
        fake_model.invoke.return_value = mock.MagicMock(content="")
        with mock.patch.object(m, "budget_guard", return_value=fake_model):
            out = m.compose(self._state())
        self.assertTrue(out["body"].strip())
        self.assertIn("## KPIs", out["body"])


# --- deliver: report-only ---------------------------------------------------------------
class DeliverReportOnlyTests(unittest.TestCase):
    def test_deliver_is_report_only_and_never_writes(self):
        """deliver must call file_digest_issue with report_only=True and the board label."""
        captured = {}

        def fake_file(repo, title, body, *, labels=None, report_only=None, **kwargs):
            captured.update(repo=repo, title=title, labels=labels, report_only=report_only)
            assert report_only is True, "deliver must stay report-only on probation"
            return {"status": "report_only", "action": "open_issue", "repo": repo}

        env = {k: v for k, v in os.environ.items() if k != "OPS_REPORT_ONLY"}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(m, "write_local_digest",
                                  return_value="/tmp/board-chair/latest.md") as wd, \
                mock.patch.object(m, "file_digest_issue", side_effect=fake_file):
            out = m.deliver({"body": "the investor update"})

        self.assertTrue(captured["report_only"])
        self.assertEqual(captured["repo"], m.DIGEST_REPO)
        self.assertEqual(captured["title"], "Board → Investor update")
        self.assertEqual(captured["labels"], ["board:investor-update"])
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


# --- budget gate / clock-in: never hangs, ends on clock-out -----------------------------
class BudgetGateTests(unittest.TestCase):
    def test_clocked_out_routes_to_end_and_reports(self):
        with mock.patch.object(m, "check_clocked_in", return_value=False), \
                mock.patch.object(m, "governance_capture") as gov, \
                mock.patch.object(m, "read_local_digest",
                                  side_effect=AssertionError("gather must not run")):
            out = m.budget_gate({})
            route = m._budget_route({})

        self.assertTrue(out["report_only"])
        self.assertEqual(out["report"]["status"], "skipped")
        self.assertEqual(route, "clocked_out")
        gov.assert_called_once()
        self.assertTrue(gov.call_args[0][1]["report_only"])

    def test_clocked_in_routes_to_gather(self):
        with mock.patch.object(m, "check_clocked_in", return_value=True):
            self.assertEqual(m.budget_gate({}), {})
            self.assertEqual(m._budget_route({}), "gather")


# --- finalize ----------------------------------------------------------------------------
class FinalizeTests(unittest.TestCase):
    def test_finalize_captures_report_only_governance(self):
        with mock.patch.object(m, "governance_capture") as gov:
            out = m.finalize({
                "kpis": {"staffed": 3, "active": 2},
                "decisions": [{"decision": "x"}],
                "asks": [],
                "report": {"delivery": "report_only", "digest": "/tmp/d"},
            })
        self.assertTrue(out["report"]["report_only"])
        self.assertEqual(out["report"]["delivery"], "report_only")
        self.assertEqual(out["report"]["asks"], 0)
        gov.assert_called_once()
        self.assertTrue(gov.call_args[0][1]["report_only"])


# --- end-to-end graph: unattended, no creds, never hangs --------------------------------
class GraphInvokeTests(unittest.TestCase):
    def test_graph_compiles_without_checkpointer(self):
        self.assertIsNotNone(m.graph)

    def test_full_run_report_only_no_creds(self):
        """Unattended run with zero creds: produces an investor update, report-only, no hang."""
        roster = _roster({"a": "active", "b": "probation"})
        env = {k: v for k, v in os.environ.items() if k != "OPS_REPORT_ONLY"}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(m, "check_clocked_in", return_value=True), \
                mock.patch.object(m, "read_local_digest", return_value="(no digest yet)"), \
                mock.patch.object(m.payroll, "load_roster", return_value=roster), \
                mock.patch.object(m.payroll, "salary", return_value=1000), \
                mock.patch.object(m.payroll, "spent", return_value=100), \
                mock.patch.object(m.revenuecat, "metrics_overview",
                                  return_value={"ok": False, "metrics": {}, "error": "x"}), \
                mock.patch.object(m, "budget_guard", side_effect=RuntimeError("no model")), \
                mock.patch.object(m, "file_digest_issue",
                                  return_value={"status": "report_only"}) as fd:
            out = m.graph.invoke({})

        self.assertTrue(out["report"]["report_only"])
        self.assertEqual(out["report"]["delivery"], "report_only")
        self.assertEqual(out["report"]["asks"], 0)        # no Shay-level asks => 'no asks'
        self.assertTrue(fd.call_args.kwargs["report_only"])  # no GitHub call, no approval hang

    def test_clocked_out_graph_ends_without_work(self):
        with mock.patch.object(m, "check_clocked_in", return_value=False), \
                mock.patch.object(m, "read_local_digest") as rd, \
                mock.patch.object(m, "file_digest_issue") as fd:
            out = m.graph.invoke({})
        rd.assert_not_called()   # no subordinate reads on the clocked-out path
        fd.assert_not_called()   # no delivery on the clocked-out path
        self.assertEqual(out["report"]["status"], "skipped")


if __name__ == "__main__":
    unittest.main()
