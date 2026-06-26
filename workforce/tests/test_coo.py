"""Safety tests for the executive coo (Chief Operating Officer) agent.

The COO is an OFFICER: it CONSUMES the ops subordinates' latest local digests (it does not
re-do their work), judges fleet health, and lands ops fixes as PROPOSALS in a report-only
digest. The tests prove the load-bearing invariants on the pure node cores (no checkpointer,
no network): (1) STALE-digest detection — "(no digest yet)" / empty => stale, and a stale
LOCAL-scheduled agent surfaces the launchd/substrate (schedule-not-firing) risk; (2) gather is
FAIL-SAFE with no digests + an unreadable roster; (3) compose always produces a non-empty
summary via the deterministic fallback when the model is unavailable; (4) deliver stays
REPORT-ONLY (no GitHub write, no approval interrupt) with the exec:coo label; (5) proposals are
tagged escalate_to org vs shay (infra spend => shay); (6) the clock-in gate routes a clocked-out
run straight to END without gathering. stdlib unittest + unittest.mock, no network. Run:
    .venv/bin/python -m unittest tests.test_coo -v
"""
import os
import unittest
from unittest import mock

from graphs.exec import coo as m


def _roster(ops, statuses=None):
    """Build a minimal load_roster() shape with an ``org.ops`` group + agent statuses."""
    statuses = statuses or {}
    agents = {
        name: {"role": f"role-{name}", "status": statuses.get(name, "probation")}
        for name in ops
    }
    return {"policy": {}, "org": {"ops": list(ops)}, "agents": agents}


# --- stale-digest detection -------------------------------------------------------------
class StaleDetectionTests(unittest.TestCase):
    def test_is_stale_for_placeholder_and_empty(self):
        self.assertTrue(m._is_stale("(no digest yet)"))
        self.assertTrue(m._is_stale(""))
        self.assertTrue(m._is_stale("   \n  "))

    def test_is_fresh_for_real_content(self):
        self.assertFalse(m._is_stale("STORE OK — all SKUs purchasable"))

    def test_analyze_splits_fresh_vs_stale(self):
        """Real digests => fresh; missing/placeholder => stale."""
        digests = {
            "git-sync-auditor": "in sync across 12 repos",      # fresh
            "memory-sync": "(no digest yet)",                   # stale (local schedule)
            "store-health-checker": "all offerings purchasable",  # fresh
            "daily-digest": "",                                 # stale (cloud)
        }
        out = m.analyze({"digests": digests})
        a = out["analysis"]
        self.assertIn("git-sync-auditor", a["fresh"])
        self.assertIn("store-health-checker", a["fresh"])
        self.assertIn("memory-sync", a["stale"])
        self.assertIn("daily-digest", a["stale"])
        self.assertFalse(a["all_fresh"])

    def test_local_stale_surfaces_schedule_not_firing_risk(self):
        """A STALE LOCAL-scheduled agent surfaces the launchd/substrate (schedule-not-firing) risk."""
        digests = {
            "git-sync-auditor": "(no digest yet)",   # LOCAL launchd — stale
            "memory-sync": "synced",                 # fresh
            "store-health-checker": "ok",
            "daily-digest": "ok",
        }
        out = m.analyze({"digests": digests})
        risks = out["analysis"]["risks"]
        kinds = {(r["risk"], r["agent"]) for r in risks}
        self.assertIn(("schedule_not_firing", "git-sync-auditor"), kinds)

    def test_stale_cloud_agent_is_plain_stale_risk(self):
        """A stale CLOUD agent (not in LOCAL_SCHEDULED) is a plain stale_digest risk, not launchd."""
        digests = {
            "git-sync-auditor": "ok",
            "memory-sync": "ok",
            "store-health-checker": "ok",
            "daily-digest": "(no digest yet)",       # cloud — stale
        }
        out = m.analyze({"digests": digests})
        risks = {(r["risk"], r["agent"]) for r in out["analysis"]["risks"]}
        self.assertIn(("stale_digest", "daily-digest"), risks)
        self.assertNotIn(("schedule_not_firing", "daily-digest"), risks)

    def test_all_fresh_has_no_risks(self):
        digests = {s: f"{s} report" for s in m.OPS_SUBORDINATES}
        out = m.analyze({"digests": digests})
        self.assertTrue(out["analysis"]["all_fresh"])
        self.assertEqual(out["analysis"]["risks"], [])


# --- gather: fail-safe + consumes digests -----------------------------------------------
class GatherFailSafeTests(unittest.TestCase):
    def test_gather_reads_every_subordinate_digest(self):
        """gather calls read_local_digest for each ops subordinate and keys results by slug."""
        seen = []

        def fake_read(slug, **kw):
            seen.append(slug)
            return f"{slug} digest"

        with mock.patch.object(m, "read_local_digest", side_effect=fake_read), \
                mock.patch.object(m.payroll, "load_roster",
                                  return_value=_roster(m.OPS_SUBORDINATES)):
            out = m.gather({})

        self.assertEqual(set(out["digests"].keys()), set(m.OPS_SUBORDINATES))
        for slug in m.OPS_SUBORDINATES:
            self.assertIn(slug, seen)

    def test_gather_survives_unreadable_roster_and_missing_digests(self):
        """No digests (all placeholder) + a roster that raises => gather degrades, never raises."""
        with mock.patch.object(m, "read_local_digest", return_value="(no digest yet)"), \
                mock.patch.object(m.payroll, "load_roster",
                                  side_effect=RuntimeError("roster missing")):
            out = m.gather({})

        # All subordinate slots present (placeholder), roster degraded to empty ops class.
        self.assertEqual(set(out["digests"].keys()), set(m.OPS_SUBORDINATES))
        self.assertEqual(out["ops_roster"], {"members": [], "count": 0})

    def test_gather_guards_every_subordinate_against_model_work(self):
        """assert_not_model_work is called on every outward agent string (Anthropic terms)."""
        seen = []

        with mock.patch.object(m, "assert_not_model_work", side_effect=lambda t: seen.append(t)), \
                mock.patch.object(m, "read_local_digest", return_value="ok"), \
                mock.patch.object(m.payroll, "load_roster",
                                  return_value=_roster(m.OPS_SUBORDINATES)):
            m.gather({})

        for slug in m.OPS_SUBORDINATES:
            self.assertIn(slug, seen)

    def test_gather_reads_roster_ops_members(self):
        """The roster ops class members + statuses are surfaced."""
        roster = _roster(m.OPS_SUBORDINATES, statuses={"memory-sync": "active"})
        with mock.patch.object(m, "read_local_digest", return_value="ok"), \
                mock.patch.object(m.payroll, "load_roster", return_value=roster):
            out = m.gather({})
        members = {mem["agent"]: mem["status"] for mem in out["ops_roster"]["members"]}
        self.assertEqual(out["ops_roster"]["count"], len(m.OPS_SUBORDINATES))
        self.assertEqual(members["memory-sync"], "active")


# --- propose: escalation routing --------------------------------------------------------
class ProposeEscalationTests(unittest.TestCase):
    def test_single_local_failure_escalates_to_org(self):
        """One stale LOCAL schedule => an org-internal re-provision fix (no spend, escalate org)."""
        analysis = {
            "fresh": ["memory-sync"],
            "stale": ["git-sync-auditor"],
            "risks": [{"risk": "schedule_not_firing", "agent": "git-sync-auditor",
                       "detail": "did not fire"}],
            "all_fresh": False,
        }
        out = m.propose({"analysis": analysis})
        props = out["proposals"]
        self.assertEqual(len(props), 1)
        self.assertEqual(props[0]["action"], "fix_local_schedule")
        self.assertEqual(props[0]["escalate_to"], "org")
        # A SINGLE local failure does NOT yet trigger the paid-infra (shay) migration.
        self.assertFalse(any(p["escalate_to"] == "shay" for p in props))

    def test_all_local_schedules_stale_escalates_infra_spend_to_shay(self):
        """When ALL local schedules are stale, the durable paid-infra fix escalates to Shay."""
        analysis = {
            "fresh": [],
            "stale": list(m.LOCAL_SCHEDULED),
            "risks": [{"risk": "schedule_not_firing", "agent": a, "detail": "did not fire"}
                      for a in m.LOCAL_SCHEDULED],
            "all_fresh": False,
        }
        out = m.propose({"analysis": analysis})
        props = out["proposals"]
        shay = [p for p in props if p["escalate_to"] == "shay"]
        self.assertEqual(len(shay), 1)
        self.assertEqual(shay[0]["action"], "migrate_local_schedules_to_paid_infra")
        # The per-agent org fixes are still present alongside the one shay ask.
        self.assertTrue(any(p["escalate_to"] == "org" for p in props))

    def test_no_risks_means_no_proposals(self):
        out = m.propose({"analysis": {"risks": [], "all_fresh": True}})
        self.assertEqual(out["proposals"], [])


# --- compose: deterministic fallback ----------------------------------------------------
class ComposeFallbackTests(unittest.TestCase):
    def _state(self):
        return {
            "analysis": {
                "fresh": ["store-health-checker"],
                "stale": ["git-sync-auditor"],
                "risks": [{"risk": "schedule_not_firing", "agent": "git-sync-auditor",
                           "detail": "launchd did not fire"}],
                "all_fresh": False,
            },
            "proposals": [{"action": "fix_local_schedule", "agent": "git-sync-auditor",
                           "escalate_to": "org", "remedy": "reload launchd"}],
            "ops_roster": {"members": [{"agent": "git-sync-auditor", "status": "probation",
                                        "role": "auditor"}], "count": 1},
        }

    def test_compose_deterministic_when_model_raises(self):
        """budget_guard raising must NOT crash compose — summary is the deterministic report."""
        with mock.patch.object(m, "budget_guard", side_effect=RuntimeError("no API key")):
            out = m.compose(self._state())
        summary = out["summary"]
        self.assertTrue(summary.strip())                  # never empty
        self.assertIn("git-sync-auditor", summary)        # built from the gathered facts
        self.assertIn("RuntimeError", summary)            # fallback labelled, not faked

    def test_compose_uses_model_output_when_available(self):
        """When the model works, its phrasing is used (still fail-safe wrapped)."""
        fake_model = mock.MagicMock()
        fake_model.invoke.return_value = mock.MagicMock(content="THE COO REPORT")
        with mock.patch.object(m, "budget_guard", return_value=fake_model):
            out = m.compose(self._state())
        self.assertEqual(out["summary"], "THE COO REPORT")

    def test_compose_falls_back_when_model_returns_empty(self):
        """An empty model response still yields a non-empty deterministic digest."""
        fake_model = mock.MagicMock()
        fake_model.invoke.return_value = mock.MagicMock(content="")
        with mock.patch.object(m, "budget_guard", return_value=fake_model):
            out = m.compose(self._state())
        self.assertTrue(out["summary"].strip())


# --- deliver: report-only ---------------------------------------------------------------
class DeliverReportOnlyTests(unittest.TestCase):
    def test_deliver_is_report_only_and_never_writes(self):
        """deliver must call file_digest_issue with report_only=True and the exec:coo label."""
        captured = {}

        def fake_file(repo, title, body, *, labels=None, report_only=None, **kwargs):
            captured.update(repo=repo, title=title, labels=labels, report_only=report_only)
            # report_only delivery MUST not enter the approval interrupt or call GitHub.
            assert report_only is True, "deliver must stay report-only on probation"
            return {"status": "report_only", "action": "open_issue", "repo": repo}

        env = {k: v for k, v in os.environ.items() if k != "OPS_REPORT_ONLY"}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(m, "write_local_digest", return_value="/tmp/coo/latest.md") as wd, \
                mock.patch.object(m, "file_digest_issue", side_effect=fake_file):
            out = m.deliver({"summary": "s", "analysis": {}, "proposals": [], "ops_roster": {}})

        self.assertTrue(captured["report_only"])
        self.assertEqual(captured["repo"], m.DIGEST_REPO)
        self.assertEqual(captured["title"], "COO: ops fleet health (proposal)")
        self.assertEqual(captured["labels"], ["exec:coo"])
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
    def test_clocked_out_ends_without_gather(self):
        """Clocked out: budget_gate reports + governance, the route goes to END (not gather)."""
        with mock.patch.object(m, "check_clocked_in", return_value=False), \
                mock.patch.object(m, "governance_capture") as gov, \
                mock.patch.object(m, "read_local_digest",
                                  side_effect=AssertionError("gather must not run")):
            out = m.budget_gate({})
            route = m._budget_route({})

        self.assertEqual(out["report"]["status"], "skipped")
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


# --- finalize ----------------------------------------------------------------------------
class FinalizeTests(unittest.TestCase):
    def test_finalize_captures_report_only_governance(self):
        with mock.patch.object(m, "governance_capture") as gov:
            out = m.finalize({
                "analysis": {"fresh": ["a"], "stale": ["b"], "risks": [{"r": 1}]},
                "proposals": [{"action": "x"}],
                "report": {"delivery": "report_only", "digest": "/tmp/d"},
            })
        self.assertTrue(out["report"]["report_only"])
        self.assertEqual(out["report"]["delivery"], "report_only")
        self.assertEqual(out["report"]["fresh"], 1)
        self.assertEqual(out["report"]["stale"], 1)
        self.assertEqual(out["report"]["proposals"], 1)
        gov.assert_called_once()
        self.assertTrue(gov.call_args[0][1]["report_only"])


# --- end-to-end graph: unattended, no creds, never hangs --------------------------------
class GraphInvokeTests(unittest.TestCase):
    def test_graph_compiles_without_checkpointer(self):
        self.assertIsNotNone(m.graph)

    def test_full_run_report_only_no_creds(self):
        """Unattended run, no creds: all digests stale, model down => report-only, no hang."""
        env = {k: v for k, v in os.environ.items() if k != "OPS_REPORT_ONLY"}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(m, "check_clocked_in", return_value=True), \
                mock.patch.object(m, "read_local_digest", return_value="(no digest yet)"), \
                mock.patch.object(m.payroll, "load_roster",
                                  return_value=_roster(m.OPS_SUBORDINATES)), \
                mock.patch.object(m, "budget_guard", side_effect=RuntimeError("no model")), \
                mock.patch.object(m, "write_local_digest", return_value="/tmp/coo/latest.md"), \
                mock.patch.object(m, "file_digest_issue",
                                  return_value={"status": "report_only"}) as fd:
            out = m.graph.invoke({})

        self.assertTrue(out["report"]["report_only"])
        self.assertEqual(out["report"]["delivery"], "report_only")
        # Both LOCAL schedules stale => their schedule-not-firing risks + the paid-infra ask.
        self.assertGreaterEqual(out["report"]["proposals"], len(m.LOCAL_SCHEDULED))
        self.assertTrue(fd.call_args.kwargs["report_only"])  # no GitHub call, no approval hang

    def test_clocked_out_graph_ends_without_work(self):
        with mock.patch.object(m, "check_clocked_in", return_value=False), \
                mock.patch.object(m, "read_local_digest") as rd, \
                mock.patch.object(m.payroll, "load_roster") as lr, \
                mock.patch.object(m, "file_digest_issue") as fd:
            out = m.graph.invoke({})
        rd.assert_not_called()    # no digest reads on the clocked-out path
        lr.assert_not_called()    # no roster read on the clocked-out path
        fd.assert_not_called()    # no delivery on the clocked-out path
        self.assertEqual(out["report"]["status"], "skipped")


if __name__ == "__main__":
    unittest.main()
