"""Safety tests for the BOARD audit_risk_director officer.

It is OVERSIGHT, not work: it CONSUMES the CFO + CTO digests + the roster budget caps and
PROPOSES risk flags + controls along three axes (spend-vs-budget, safety-gate compliance,
security posture). The tests prove the load-bearing invariants on the pure node cores (no
checkpointer, no network):
  (1) over-budget is detected from a mocked CFO digest signal AND from a mocked roster scan,
      and surfaces as an escalate_to="shay" (material) proposal;
  (2) a clean fleet (within budget, report-only in force, no CTO risk) raises NO material asks;
  (3) compose always yields a non-empty body via the deterministic fallback when the model is
      unavailable; (4) deliver stays REPORT-ONLY (no GitHub write, no approval interrupt);
  (5) every read is FAIL-SAFE (missing digests / unreadable roster never crash);
  (6) the clock-in gate routes a clocked-out run straight to END without gathering. Run:
    .venv/bin/python -m unittest tests.test_audit_risk_director -v
"""
import os
import unittest
from unittest import mock

from graphs.board import audit_risk_director as m
from agent_toolkit import lanes


def _roster(agents: dict, *, team_cap: int = 4800000) -> dict:
    """Build a load_roster()-shaped dict from {agent: {salary, ...}}."""
    return {
        "policy": {"team_token_budget": team_cap},
        "org": {},
        "agents": {
            name: {
                "role": f"role-{name}",
                "status": rec.get("status", "active"),
                "salary_tokens_per_week": rec.get("salary", 1000),
                "scorecard": {},
            }
            for name, rec in agents.items()
        },
    }


# --- gather: fail-safe digest + budget reads --------------------------------------------
class GatherFailSafeTests(unittest.TestCase):
    def test_gather_survives_missing_digests_and_roster(self):
        """No CFO/CTO digests + an unreadable roster => structured dicts, never raises."""
        with mock.patch.object(m, "read_local_digest", return_value="(no digest yet)"), \
                mock.patch.object(m.payroll, "load_roster",
                                  side_effect=RuntimeError("no roster")):
            out = m.gather({})

        self.assertEqual(out["cfo"], "(no digest yet)")
        self.assertEqual(out["cto"], "(no digest yet)")
        # roster unavailable degrades to a structured (not crashing) budget result.
        self.assertEqual(out["budget"]["over_budget_agents"], [])
        self.assertEqual(out["budget"]["note"], "roster unavailable")

    def test_gather_reads_the_cfo_and_cto_slugs(self):
        """gather consumes the cfo + cto digests (officers read reports, don't re-do work)."""
        def fake_read(slug, **kw):
            return {"cfo": "CFO SAYS HI", "cto": "CTO SAYS HI"}.get(slug, "(no digest yet)")

        with mock.patch.object(m, "read_local_digest", side_effect=fake_read), \
                mock.patch.object(m.payroll, "load_roster", return_value=_roster({})):
            out = m.gather({})
        self.assertEqual(out["cfo"], "CFO SAYS HI")
        self.assertEqual(out["cto"], "CTO SAYS HI")

    def test_read_officer_guards_model_work_slug(self):
        """A denylisted subordinate slug is skipped (Anthropic terms), not read."""
        with mock.patch.object(m, "read_local_digest") as rd:
            self.assertEqual(m._read_officer("gal-model"), "(no digest yet)")
        rd.assert_not_called()  # never even attempted to read a model-dev slug


# --- budget analysis: over-budget detection from the roster scan ------------------------
class BudgetAnalysisTests(unittest.TestCase):
    def test_detects_over_budget_agent_from_roster_scan(self):
        """An agent whose ledger spend exceeds its salary is flagged over budget."""
        roster = _roster({"spender": {"salary": 1000}, "ok": {"salary": 1000}})

        def fake_spent(agent, **kw):
            return 5000 if agent == "spender" else 100

        with mock.patch.object(m.payroll, "load_roster", return_value=roster), \
                mock.patch.object(m.payroll, "spent", side_effect=fake_spent):
            budget = m._budget_analysis()

        over = {a["agent"] for a in budget["over_budget_agents"]}
        self.assertIn("spender", over)
        self.assertNotIn("ok", over)

    def test_flags_fleet_over_team_cap(self):
        """Fleet spend exceeding the team cap is flagged independently of per-agent status."""
        roster = _roster({"a": {"salary": 10_000_000}}, team_cap=100)  # huge salary => not over

        with mock.patch.object(m.payroll, "load_roster", return_value=roster), \
                mock.patch.object(m.payroll, "spent", return_value=500):  # > cap of 100
            budget = m._budget_analysis()

        self.assertTrue(budget["fleet_over_cap"])
        self.assertEqual(budget["over_budget_agents"], [])  # agent itself within its salary


# --- analyze + propose: material risk => escalate_to shay -------------------------------
class AnalyzeProposeTests(unittest.TestCase):
    def test_over_budget_is_operational_and_routes_org_not_shay(self):
        """An over-budget agent => a budget finding routed ORG-internal, NOT a founder ask.

        Running over a weekly token salary is an OPERATIONAL burn condition the CFO/board cap,
        bench, or re-grade inside the org (delegation mandate: ``set_budget`` is the board's;
        only a spend ABOVE ``max_board_spend_usd`` is owner-reserved). It must NOT be escalated
        to an unreachable founder — matching the CFO graph, which routes the same condition to
        "org" and reserves "shay" only for a budget INCREASE (capital).
        """
        budget = {
            "team_cap": 1000, "fleet_spent": 5000, "fleet_over_cap": False,
            "over_budget_agents": [{"agent": "spender", "spent_tokens": 5000,
                                    "salary_tokens": 1000}],
            "note": None,
        }
        findings = m.analyze({"cfo": "(no digest yet)", "cto": "(no digest yet)",
                              "budget": budget})["findings"]
        self.assertEqual(len(findings["budget"]), 1)

        with mock.patch.dict(os.environ, {"OPS_REPORT_ONLY": "1"}):  # report-only in force
            proposals = m.propose({"findings": findings})["proposals"]
        budget_props = [p for p in proposals if p["axis"] == "budget"]
        self.assertEqual(len(budget_props), 1)
        self.assertEqual(budget_props[0]["escalate_to"], "org")  # operational, not a founder ask

    def test_cfo_digest_over_budget_signal_is_detected(self):
        """A CFO digest that SAYS 'over budget' trips a finding even with an empty ledger scan."""
        clean_budget = {"team_cap": 1000, "fleet_spent": 0, "fleet_over_cap": False,
                        "over_budget_agents": [], "note": None}
        findings = m.analyze({"cfo": "Two agents are OVER BUDGET this week.",
                              "cto": "(no digest yet)", "budget": clean_budget})["findings"]
        flags = {f["flag"] for f in findings["budget"]}
        self.assertIn("cfo_reports_over_budget", flags)

    def test_security_risk_from_cto_digest_is_material(self):
        """A CTO digest reporting an IDOR => a material security proposal escalated to Shay."""
        findings = m.analyze({"cfo": "(no digest yet)",
                              "cto": "Open IDOR in scheduler Firestore rules.",
                              "budget": {"over_budget_agents": []}})["findings"]
        self.assertEqual(len(findings["security"]), 1)

        with mock.patch.dict(os.environ, {"OPS_REPORT_ONLY": "1"}):
            proposals = m.propose({"findings": findings})["proposals"]
        sec = [p for p in proposals if p["axis"] == "security"]
        self.assertEqual(sec[0]["escalate_to"], "shay")

    def test_report_only_disabled_is_a_material_safety_finding(self):
        """OPS_REPORT_ONLY off while on probation => a material safety-gate finding."""
        with mock.patch.dict(os.environ, {"OPS_REPORT_ONLY": "0"}):
            findings = m.analyze({"cfo": "(no digest yet)", "cto": "(no digest yet)",
                                  "budget": {"over_budget_agents": []}})["findings"]
            proposals = m.propose({"findings": findings})["proposals"]
        self.assertEqual(len(findings["safety"]), 1)
        safety = [p for p in proposals if p["axis"] == "safety"]
        self.assertEqual(safety[0]["escalate_to"], "shay")

    def test_clean_fleet_raises_no_budget_or_safety_asks(self):
        """Within budget + report-only in force => the BUDGET and SAFETY axes raise zero asks.

        NOTE (step-3 relocation): the standing held IDOR is now owned by the lane registry and is
        ALWAYS surfaced as a material security finding (it survives the CTO's offboard), so the
        SECURITY axis is no longer empty on a "clean" cycle — that is asserted in
        ``StandingIdorRelocationTests``. Here we prove the budget/safety axes stay clean (no
        operational over-escalation): a within-budget, report-only fleet contributes no
        budget/safety founder ask of its own.
        """
        clean_budget = {"team_cap": 1000, "fleet_spent": 10, "fleet_over_cap": False,
                        "over_budget_agents": [], "note": None}
        with mock.patch.dict(os.environ, {"OPS_REPORT_ONLY": "1"}):
            findings = m.analyze({"cfo": "All green, well within budget.",
                                  "cto": "No new security issues found.",
                                  "budget": clean_budget})["findings"]
            proposals = m.propose({"findings": findings})["proposals"]
        self.assertEqual(findings["budget"], [])
        self.assertEqual(findings["safety"], [])
        non_security = [p for p in proposals if p["axis"] != "security"]
        self.assertEqual(non_security, [])
        self.assertEqual(sum(1 for p in non_security if p["escalate_to"] == "shay"), 0)


# --- step-3 relocation: IDOR ownership moved to lanes (survives the CTO offboard) --------
class StandingIdorRelocationTests(unittest.TestCase):
    """ACCEPTANCE: the standing held IDOR is surfaced from the lane registry, NOT the CTO digest.

    The relocation moves the IDOR dossier ownership into ``agent_toolkit.lanes`` so the Board's
    risk oversight keeps surfacing the live #1487 IDOR even after the CTO agent is offboarded —
    i.e. even when the CTO digest is ABSENT ("(no digest yet)").
    """

    def test_idor_surfaced_even_when_cto_digest_absent(self):
        """With cto == '(no digest yet)', the standing IDOR is STILL a material security finding."""
        sec = m._security_findings("(no digest yet)")
        self.assertTrue(sec, "the standing held IDOR must be surfaced even with no CTO digest")
        self.assertTrue(all(f["material"] for f in sec))
        self.assertTrue(
            any(f.get("systemic") == "security_idor_1487" for f in sec),
            "the relocated IDOR (lanes) must be one of the surfaced security findings",
        )
        # And it carries the lanes dossier facts (single source of truth), 1487 in the detail.
        self.assertIn("1487", " ".join(f["detail"] for f in sec))

    def test_idor_security_finding_reads_from_lanes_source(self):
        """The finding's facts come from ``lanes.idor_security_item()`` — the relocated SoT."""
        sec = m._security_findings("")  # empty CTO digest, same as absent
        idor = next(f for f in sec if f.get("systemic") == "security_idor_1487")
        self.assertIn(lanes.idor_security_item()["title"], idor["detail"])

    def test_idor_absent_cto_digest_escalates_to_shay_end_to_end(self):
        """End-to-end: with no CTO digest, the IDOR still produces a shay-escalated security ask."""
        clean_budget = {"team_cap": 4_800_000, "fleet_spent": 1, "fleet_over_cap": False,
                        "over_budget_agents": [], "note": None}
        with mock.patch.dict(os.environ, {"OPS_REPORT_ONLY": "1"}):
            findings = m.analyze({"cfo": "(no digest yet)", "cto": "(no digest yet)",
                                  "budget": clean_budget})["findings"]
            proposals = m.propose({"findings": findings})["proposals"]
        sec = [p for p in proposals if p["axis"] == "security"]
        self.assertTrue(sec, "the standing IDOR must surface as a security proposal")
        self.assertEqual(sec[0]["escalate_to"], "shay")
        self.assertGreaterEqual(lanes.founder_ask_count(proposals), 1)

    def test_cto_prose_idor_is_not_double_counted(self):
        """A CTO digest that ALSO mentions the IDOR must not produce TWO IDOR findings."""
        sec = m._security_findings("Open IDOR #1487 still un-remediated in production.")
        self.assertEqual(len(sec), 1, "the standing + CTO-prose IDOR must reconcile to ONE finding")

    def test_additional_cto_risk_still_surfaced_alongside_idor(self):
        """A NEW, distinct CTO-reported risk (beyond the IDOR) is surfaced in ADDITION to it."""
        sec = m._security_findings("New CVE-2026-9999 exploit found in a dependency.")
        flags = [f["detail"] for f in sec]
        self.assertEqual(len(sec), 2, "standing IDOR + the new distinct CTO risk = two findings")
        self.assertTrue(any("1487" in d for d in flags))
        self.assertTrue(any("additional" in d for d in flags))


# --- compose: deterministic fallback ----------------------------------------------------
class ComposeFallbackTests(unittest.TestCase):
    def _state(self):
        return {
            "findings": {
                "budget": [{"flag": "agent_over_budget", "detail": "spender spent>salary"}],
                "safety": [],
                "security": [],
            },
            "proposals": [{"axis": "budget", "flag": "agent_over_budget",
                           "detail": "spender spent>salary",
                           "control": "freeze", "escalate_to": "shay"}],
            "budget": {"team_cap": 1000, "fleet_spent": 5000},
        }

    def test_compose_deterministic_when_model_raises(self):
        """budget_guard raising must NOT crash compose — body built from the findings."""
        with mock.patch.object(m, "budget_guard", side_effect=RuntimeError("no API key")):
            out = m.compose(self._state())
        self.assertTrue(out["summary"].strip())             # never empty
        self.assertIn("Audit & Risk", out["body"])          # built from the facts
        self.assertIn("escalate_to: **shay**", out["body"])  # the material ask is rendered
        self.assertIn("RuntimeError", out["summary"])       # fallback labelled, not faked

    def test_compose_prepends_model_narrative_when_available(self):
        fake_model = mock.MagicMock()
        fake_model.invoke.return_value = mock.MagicMock(content="BOARD RISK READ")
        with mock.patch.object(m, "budget_guard", return_value=fake_model):
            out = m.compose(self._state())
        self.assertTrue(out["summary"].startswith("BOARD RISK READ"))


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
                mock.patch.object(m, "write_local_digest", return_value="/tmp/d/latest.md") as wd, \
                mock.patch.object(m, "file_digest_issue", side_effect=fake_file):
            out = m.deliver({"summary": "the risk digest"})

        self.assertTrue(captured["report_only"])
        self.assertEqual(captured["repo"], m.DIGEST_REPO)
        self.assertEqual(captured["title"], "Board — Audit & Risk (oversight)")
        self.assertEqual(captured["labels"], ["board:audit-risk"])
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
        self.assertTrue(gov.call_args[0][1]["report_only"])  # report-only governance

    def test_clocked_in_routes_to_gather(self):
        with mock.patch.object(m, "check_clocked_in", return_value=True):
            self.assertEqual(m.budget_gate({}), {})
            self.assertEqual(m._budget_route({}), "gather")


# --- finalize ----------------------------------------------------------------------------
class FinalizeTests(unittest.TestCase):
    def test_finalize_captures_report_only_governance_and_counts_asks(self):
        proposals = [
            {"axis": "budget", "escalate_to": "shay"},
            {"axis": "safety", "escalate_to": "org"},
        ]
        findings = {"budget": [{}], "safety": [], "security": [{}]}
        with mock.patch.object(m, "governance_capture") as gov:
            out = m.finalize({"findings": findings, "proposals": proposals,
                              "report": {"delivery": "report_only", "digest": "/tmp/d"}})
        self.assertTrue(out["report"]["report_only"])
        self.assertEqual(out["report"]["delivery"], "report_only")
        self.assertEqual(out["report"]["asks_for_shay"], 1)
        self.assertEqual(out["report"]["proposals"], 2)
        gov.assert_called_once()
        self.assertTrue(gov.call_args[0][1]["report_only"])
        self.assertEqual(gov.call_args[0][1]["asks_for_shay"], 1)


# --- end-to-end graph: unattended, no creds, never hangs --------------------------------
class GraphInvokeTests(unittest.TestCase):
    def test_graph_compiles_without_checkpointer(self):
        self.assertIsNotNone(m.graph)

    def test_full_run_report_only_no_creds(self):
        """A clocked-in run with no creds completes report-only, never hangs/writes."""
        env = {k: v for k, v in os.environ.items() if k != "OPS_REPORT_ONLY"}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(m, "check_clocked_in", return_value=True), \
                mock.patch.object(m, "read_local_digest", return_value="(no digest yet)"), \
                mock.patch.object(m.payroll, "load_roster", return_value=_roster({"a": {}})), \
                mock.patch.object(m.payroll, "spent", return_value=0), \
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
        self.assertEqual(out["report"]["status"], "skipped")


if __name__ == "__main__":
    unittest.main()
