"""Safety tests for the cloud ceo executive agent.

The CEO CONSUMES the four exec officers' digests (CFO/CMO/COO/CTO) and synthesizes them into
company priorities + a consolidated PROPOSAL QUEUE — it does NOT re-do their work. The tests
prove the load-bearing invariants directly on the pure node cores (no checkpointer, no
network): (1) gather is FAIL-SAFE and tolerates missing exec digests; (2) analyze always
produces a deterministic proposal queue with escalate_to tags (org vs shay split preserved);
(3) compose always produces a non-empty summary via the deterministic fallback when the model
is unavailable; (4) deliver stays REPORT-ONLY (no GitHub write, no approval interrupt); (5)
the clock-in gate routes a clocked-out run straight to END without gathering; (6) the whole
graph runs unattended with no creds and never hangs. Run:
    .venv/bin/python -m unittest tests.test_ceo -v
"""
import os
import unittest
from unittest import mock

from graphs.exec import ceo as m


# --- gather: fail-safe, tolerates missing exec digests ----------------------------------
class GatherFailSafeTests(unittest.TestCase):
    def test_gather_reads_each_exec_digest(self):
        """gather reads one local digest per exec officer (CFO/CMO/COO/CTO)."""
        def fake_read(slug, **kwargs):
            return f"{slug.upper()} digest body"

        with mock.patch.object(m, "read_local_digest", side_effect=fake_read):
            out = m.gather({})

        self.assertEqual(set(out["digests"].keys()), set(m.EXEC_OFFICERS.keys()))
        self.assertEqual(out["digests"]["cfo"], "CFO digest body")

    def test_gather_tolerates_missing_digests(self):
        """A missing exec digest => '(no digest yet)' placeholder; gather never raises."""
        with mock.patch.object(m, "read_local_digest", return_value="(no digest yet)"):
            out = m.gather({})
        self.assertEqual(set(out["digests"].keys()), set(m.EXEC_OFFICERS.keys()))
        for officer in m.EXEC_OFFICERS:
            self.assertEqual(out["digests"][officer], "(no digest yet)")

    def test_gather_survives_a_raising_reader(self):
        """Even if a read raises, gather degrades that officer and never crashes."""
        with mock.patch.object(m, "read_local_digest",
                               side_effect=RuntimeError("fs error")):
            out = m.gather({})
        # Every officer present, each degraded to the placeholder — no crash.
        self.assertEqual(set(out["digests"].keys()), set(m.EXEC_OFFICERS.keys()))
        for officer in m.EXEC_OFFICERS:
            self.assertEqual(out["digests"][officer], "(no digest yet)")

    def test_gather_guards_every_officer_against_model_work(self):
        """assert_not_model_work is called on every exec officer name (Anthropic terms)."""
        seen = []

        def record(target):
            seen.append(target)

        with mock.patch.object(m, "assert_not_model_work", side_effect=record), \
                mock.patch.object(m, "read_local_digest", return_value="x"):
            m.gather({})

        for officer in m.EXEC_OFFICERS:
            self.assertIn(officer, seen)

    def test_gather_skips_a_denylisted_officer(self):
        """A denylisted officer is skipped entirely (not read, not in the digest map)."""
        def guard(target):
            if target == "cto":
                raise m.ModelWorkBlocked("denied")

        with mock.patch.object(m, "assert_not_model_work", side_effect=guard), \
                mock.patch.object(m, "read_local_digest", return_value="body"):
            out = m.gather({})

        self.assertNotIn("cto", out["digests"])
        self.assertIn("cfo", out["digests"])


# --- analyze: deterministic priorities + proposal queue with escalate_to tags -----------
class AnalyzeTests(unittest.TestCase):
    def test_queue_present_with_priorities(self):
        """analyze derives one priority + one queue entry per reporting officer."""
        digests = {
            "cfo": "# CFO\nToken burn within salary; propose a budget reallocation.",
            "cmo": "# CMO\nFunnel steady; propose an ASO copy refresh.",
            "coo": "# COO\nFleet healthy; maintainers green.",
            "cto": "# CTO\nCI green; IDOR rollout still held.",
        }
        out = m.analyze({"digests": digests})
        self.assertEqual(len(out["priorities"]), 4)
        self.assertEqual(len(out["queue"]), 4)
        for item in out["queue"]:
            self.assertIn(item["escalate_to"], ("org", "shay"))
            self.assertTrue(item["report_only"])

    def test_capital_item_escalates_to_shay(self):
        """A capital/funding line is tagged escalate_to=shay; an ordinary line stays org."""
        digests = {
            "cfo": "# CFO\nRunway tight — propose raising additional capital this quarter.",
            "cmo": "# CMO\nPropose a small ASO keyword tweak.",
        }
        out = m.analyze({"digests": digests})
        by_officer = {q["officer"]: q for q in out["queue"]}
        self.assertEqual(by_officer["cfo"]["escalate_to"], "shay")  # capital => Shay
        self.assertEqual(by_officer["cmo"]["escalate_to"], "org")   # ordinary => org

    def test_legal_item_escalates_to_shay(self):
        """A legal/contract concern is an ask for Shay."""
        digests = {"cto": "# CTO\nVendor contract renewal needs legal sign-off."}
        out = m.analyze({"digests": digests})
        self.assertEqual(out["queue"][0]["escalate_to"], "shay")

    def test_missing_digest_yields_priority_but_no_queue_entry(self):
        """An officer with no digest yet is shown as a coverage gap, not a proposal."""
        digests = {"cfo": "(no digest yet)", "cmo": "# CMO\nGrowth steady."}
        out = m.analyze({"digests": digests})
        officers = {p["officer"]: p for p in out["priorities"]}
        self.assertFalse(officers["cfo"]["reported"])
        self.assertTrue(officers["cmo"]["reported"])
        # Only the reporting officer contributes a queue entry.
        self.assertEqual([q["officer"] for q in out["queue"]], ["cmo"])

    def test_analyze_empty_digests_is_safe(self):
        """No digests at all => empty priorities + empty queue, no crash."""
        out = m.analyze({"digests": {}})
        self.assertEqual(out["priorities"], [])
        self.assertEqual(out["queue"], [])


# --- compose: deterministic fallback, queue always present ------------------------------
class ComposeFallbackTests(unittest.TestCase):
    def _state(self):
        digests = {"cfo": "# CFO\nBurn within salary.", "cmo": "# CMO\nFunnel steady."}
        analyzed = m.analyze({"digests": digests})
        return {"digests": digests, **analyzed}

    def test_compose_deterministic_when_model_raises(self):
        """budget_guard raising must NOT crash compose — summary is the deterministic memo."""
        with mock.patch.object(m, "budget_guard", side_effect=RuntimeError("no API key")):
            out = m.compose(self._state())
        summary = out["summary"]
        self.assertTrue(summary.strip())                       # never empty
        self.assertIn("Proposal queue", summary)               # queue is always present
        self.assertIn("RuntimeError", summary)                 # fallback labelled, not faked

    def test_compose_uses_model_output_when_available(self):
        """When the model works, its phrasing is used but clearly labelled ADVISORY.

        The deterministic queue (re-rendered verbatim in deliver) remains the source of truth,
        so the model prose is included under an explicit advisory heading rather than replacing
        the authoritative queue.
        """
        fake_model = mock.MagicMock()
        fake_model.invoke.return_value = mock.MagicMock(content="THE STRATEGY MEMO")
        with mock.patch.object(m, "budget_guard", return_value=fake_model):
            out = m.compose(self._state())
        self.assertIn("THE STRATEGY MEMO", out["summary"])
        self.assertIn("advisory", out["summary"].lower())

    def test_compose_falls_back_when_model_returns_empty(self):
        """An empty model response still yields a non-empty deterministic memo."""
        fake_model = mock.MagicMock()
        fake_model.invoke.return_value = mock.MagicMock(content="")
        with mock.patch.object(m, "budget_guard", return_value=fake_model):
            out = m.compose(self._state())
        self.assertTrue(out["summary"].strip())


# --- deliver: report-only ---------------------------------------------------------------
class DeliverReportOnlyTests(unittest.TestCase):
    def test_deliver_is_report_only_and_never_writes(self):
        """deliver must call file_digest_issue with report_only=True and the exec:ceo label."""
        captured = {}

        def fake_file_issue(repo, title, body, *, labels=None, report_only=None,
                            agent=None, slack_title=None, **kwargs):
            captured["repo"] = repo
            captured["title"] = title
            captured["labels"] = labels
            captured["report_only"] = report_only
            captured["body"] = body
            captured["agent"] = agent
            captured["slack_title"] = slack_title
            # report_only delivery MUST not enter the approval interrupt or call GitHub.
            assert report_only is True, "deliver must stay report-only on probation"
            return {"status": "report_only", "action": "open_issue", "repo": repo}

        queue = [
            {"officer": "cfo", "proposal": "raise capital", "escalate_to": "shay",
             "report_only": True},
            {"officer": "cmo", "proposal": "ASO tweak", "escalate_to": "org",
             "report_only": True},
        ]
        # OPS_REPORT_ONLY unset => report-only default True; local digest stubbed (no FS write).
        env = {k: v for k, v in os.environ.items() if k != "OPS_REPORT_ONLY"}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(m, "write_local_digest", return_value="/tmp/x/latest.md"), \
                mock.patch.object(m, "file_digest_issue", side_effect=fake_file_issue):
            out = m.deliver({"summary": "s", "digests": {"cfo": "x"},
                             "priorities": [{"officer": "cfo"}], "queue": queue})

        self.assertTrue(captured["report_only"])
        self.assertEqual(captured["repo"], m.DIGEST_REPO)
        self.assertEqual(captured["title"], "CEO: priorities + proposal queue")
        self.assertEqual(captured["labels"], ["exec:ceo"])
        # deliver routes the digest to the CEO's own Slack channel (fail-safe in the toolkit).
        self.assertEqual(captured["agent"], "ceo")
        self.assertTrue(captured["slack_title"])
        # The proposal queue (with escalate_to tags) is in the issue body for auditability.
        self.assertIn("escalate_to: shay", captured["body"])
        self.assertIn("escalate_to: org", captured["body"])
        # Provenance appendix is embedded so "what did the CEO see" is auditable.
        self.assertIn("Inputs consumed (provenance)", captured["body"])
        self.assertEqual(out["report"]["delivery"], "report_only")
        self.assertEqual(out["report"]["queue"], 2)
        self.assertEqual(out["report"]["shay_asks"], 1)
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
        # governance capture on the clocked-out path is report-only.
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
        queue = [{"officer": "cfo", "escalate_to": "shay"},
                 {"officer": "cmo", "escalate_to": "org"}]
        with mock.patch.object(m, "governance_capture") as gov:
            out = m.finalize({"priorities": [{"officer": "cfo"}, {"officer": "cmo"}],
                              "queue": queue,
                              "report": {"delivery": "report_only", "digest": "/tmp/d"}})
        self.assertTrue(out["report"]["report_only"])
        self.assertEqual(out["report"]["delivery"], "report_only")
        self.assertEqual(out["report"]["queue"], 2)
        self.assertEqual(out["report"]["shay_asks"], 1)
        gov.assert_called_once()
        self.assertTrue(gov.call_args[0][1]["report_only"])


# --- end-to-end graph: unattended, no creds, never hangs --------------------------------
class GraphInvokeTests(unittest.TestCase):
    def test_graph_compiles_without_checkpointer(self):
        self.assertIsNotNone(m.graph)

    def test_full_run_report_only_no_creds(self):
        """Unattended run with no creds: synthesizes the exec digests, stays report-only."""
        digests = {
            "cfo": "# CFO\nBurn within salary; propose raising capital next quarter.",
            "cmo": "# CMO\nFunnel steady; propose ASO refresh.",
            "coo": "(no digest yet)",
            "cto": "# CTO\nCI green.",
        }

        def fake_read(slug, **kwargs):
            return digests.get(slug, "(no digest yet)")

        env = {k: v for k, v in os.environ.items() if k != "OPS_REPORT_ONLY"}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(m, "check_clocked_in", return_value=True), \
                mock.patch.object(m, "read_local_digest", side_effect=fake_read), \
                mock.patch.object(m, "budget_guard", side_effect=RuntimeError("no model")), \
                mock.patch.object(m, "write_local_digest", return_value="/tmp/ceo/latest.md"), \
                mock.patch.object(m, "file_digest_issue",
                                  return_value={"status": "report_only"}) as fd:
            out = m.graph.invoke({})

        self.assertTrue(out["report"]["report_only"])
        self.assertEqual(out["report"]["delivery"], "report_only")
        # Three officers reported (coo had no digest) => 3 queue entries; cfo capital => 1 Shay ask.
        self.assertEqual(out["report"]["queue"], 3)
        self.assertEqual(out["report"]["shay_asks"], 1)
        self.assertEqual(out["report"]["priorities"], 4)        # all four officers shown
        self.assertTrue(fd.call_args.kwargs["report_only"])     # no GitHub call, no approval hang

    def test_clocked_out_graph_ends_without_work(self):
        with mock.patch.object(m, "check_clocked_in", return_value=False), \
                mock.patch.object(m, "read_local_digest") as rd, \
                mock.patch.object(m, "file_digest_issue") as fd:
            out = m.graph.invoke({})
        rd.assert_not_called()   # no digest reads on the clocked-out path
        fd.assert_not_called()   # no delivery on the clocked-out path
        self.assertEqual(out["report"]["status"], "skipped")


# --- freshness / provenance: stale digests flagged, inputs recorded ---------------------
class FreshnessProvenanceTests(unittest.TestCase):
    def test_gather_records_provenance_per_officer(self):
        """gather stats each digest and records presence + a content hash (fail-safe)."""
        def fake_read(slug, **kwargs):
            return f"# {slug.upper()}\npropose a thing"

        with mock.patch.object(m, "read_local_digest", side_effect=fake_read):
            out = m.gather({})

        prov = out["provenance"]
        self.assertEqual(set(prov.keys()), set(m.EXEC_OFFICERS.keys()))
        for officer in m.EXEC_OFFICERS:
            self.assertTrue(prov[officer]["present"])
            self.assertTrue(prov[officer]["sha8"])  # content hash recorded for audit

    def test_missing_digest_marked_not_present_and_stale(self):
        """A '(no digest yet)' placeholder is not present and counts as stale (no fresh output)."""
        with mock.patch.object(m, "read_local_digest", return_value="(no digest yet)"):
            out = m.gather({})
        for officer in m.EXEC_OFFICERS:
            self.assertFalse(out["provenance"][officer]["present"])
            self.assertTrue(out["provenance"][officer]["stale"])

    def test_analyze_flags_stale_officer_in_queue_and_priorities(self):
        """A stale digest still surfaces, but every entry is marked stale (missed schedule)."""
        digests = {"cfo": "# CFO\npropose a budget tweak."}
        provenance = {"cfo": {"present": True, "stale": True, "age_hours": 99.0, "sha8": "abc"}}
        out = m.analyze({"digests": digests, "provenance": provenance})
        self.assertTrue(out["priorities"][0]["stale"])
        self.assertTrue(all(q["stale"] for q in out["queue"]))

    def test_digest_provenance_is_fail_safe_for_missing_file(self):
        """_digest_provenance never raises on a missing file — degrades to unknown age."""
        prov = m._digest_provenance("definitely-not-a-real-slug-xyz", "(no digest yet)")
        self.assertFalse(prov["present"])
        self.assertTrue(prov["stale"])
        self.assertIsNone(prov["age_hours"])

    def test_provenance_appendix_renders_state(self):
        """The provenance appendix names each officer with its freshness + hash for audit."""
        provenance = {
            "cfo": {"present": True, "stale": False, "age_hours": 1.0, "sha8": "deadbeef"},
            "cmo": {"present": False, "stale": True, "age_hours": None, "sha8": ""},
        }
        text = m._provenance_appendix(provenance)
        self.assertIn("cfo", text)
        self.assertIn("deadbeef", text)
        self.assertIn("fresh", text)
        self.assertIn("missing/empty", text)  # cmo


# --- per-proposal parsing + line-scoped escalation --------------------------------------
class ProposalParsingTests(unittest.TestCase):
    def test_multiple_proposals_per_officer_are_kept(self):
        """A digest with several distinct asks yields several queue entries (not one headline)."""
        digests = {
            "cfo": (
                "# CFO\n"
                "- propose a budget reallocation toward growth\n"
                "- recommend pausing the unused vendor seat\n"
                "- request a small infra reserve"
            )
        }
        out = m.analyze({"digests": digests})
        cfo_items = [q for q in out["queue"] if q["officer"] == "cfo"]
        self.assertGreaterEqual(len(cfo_items), 3)  # all distinct asks survive

    def test_escalation_is_scoped_to_the_proposal_line_not_whole_body(self):
        """An incidental 'legal' mention elsewhere must NOT escalate an unrelated proposal."""
        digests = {
            "cfo": (
                "# CFO\n"
                "Context: our legal counsel reviewed the standard ToS last quarter.\n"
                "- propose an ASO keyword refresh\n"  # ordinary -> org
                "- recommend raising additional capital next quarter"  # capital -> shay
            )
        }
        out = m.analyze({"digests": digests})
        cfo_items = {q["proposal"]: q for q in out["queue"] if q["officer"] == "cfo"}
        aso = next(q for p, q in cfo_items.items() if "aso" in p.lower())
        cap = next(q for p, q in cfo_items.items() if "capital" in p.lower())
        self.assertEqual(aso["escalate_to"], "org")   # NOT escalated by the incidental 'legal'
        self.assertEqual(cap["escalate_to"], "shay")  # its own line is a capital ask

    def test_proposal_count_is_capped(self):
        """A flood of bullet lines is capped to _MAX_PROPOSALS_PER_OFFICER."""
        bullets = "\n".join(f"- propose item {i}" for i in range(20))
        out = m.analyze({"digests": {"cfo": "# CFO\n" + bullets}})
        cfo_items = [q for q in out["queue"] if q["officer"] == "cfo"]
        self.assertLessEqual(len(cfo_items), m._MAX_PROPOSALS_PER_OFFICER)

    def test_terse_digest_still_yields_one_proposal(self):
        """A one-line digest with no bullet/verb still contributes its headline as a proposal."""
        out = m.analyze({"digests": {"cmo": "Funnel steady this week."}})
        cmo_items = [q for q in out["queue"] if q["officer"] == "cmo"]
        self.assertEqual(len(cmo_items), 1)


# --- queue continuity: carry items across cycles via the CEO's own prior digest ---------
class QueueContinuityTests(unittest.TestCase):
    def test_carried_item_detected_from_prior_digest(self):
        """An item already in the CEO's prior digest is marked 'carried'; a new one is 'new'."""
        prior = (
            "# CEO\n"
            "- **[cfo]** raise capital  _(escalate_to: shay)_\n"
        )
        queue = [
            {"officer": "cfo", "proposal": "raise capital", "escalate_to": "shay"},
            {"officer": "cmo", "proposal": "ASO tweak", "escalate_to": "org"},
        ]
        with mock.patch.object(m, "read_local_digest", return_value=prior):
            marked = m._mark_queue_continuity(queue)
        by_officer = {q["officer"]: q for q in marked}
        self.assertEqual(by_officer["cfo"]["continuity"], "carried")
        self.assertEqual(by_officer["cmo"]["continuity"], "new")

    def test_continuity_is_fail_safe_when_no_prior_digest(self):
        """First-ever run (no prior digest) marks everything new and never raises."""
        with mock.patch.object(m, "read_local_digest", return_value="(no digest yet)"):
            marked = m._mark_queue_continuity(
                [{"officer": "cfo", "proposal": "x", "escalate_to": "org"}]
            )
        self.assertEqual(marked[0]["continuity"], "new")

    def test_compose_adds_continuity_tags(self):
        """compose annotates the queue with continuity before rendering."""
        prior = "# CEO\n- **[cfo]** burn within salary  _(escalate_to: org)_\n"
        digests = {"cfo": "# CFO\nburn within salary"}
        analyzed = m.analyze({"digests": digests})
        state = {"digests": digests, **analyzed}
        with mock.patch.object(m, "budget_guard", side_effect=RuntimeError("no model")), \
                mock.patch.object(m, "read_local_digest", return_value=prior):
            out = m.compose(state)
        self.assertTrue(any(q.get("continuity") for q in out["queue"]))


if __name__ == "__main__":
    unittest.main()
