"""Safety tests for the cloud aso_store_listing_agent — the ASO repositioning drafter.

It repositions the mispositioned "to-do" store listing to B2B shift scheduling and DRAFTS
ASO copy per store, so the tests prove the load-bearing invariants on the pure node cores
(no checkpointer, no network):
  1. DO-NOT-CLAIM enforcement: a draft containing a banned term ("time tracking") is flagged
     by compliance_scan, compliance_flags is non-empty, and the ⚠️ COMPLIANCE warning lands
     in the delivered body — an over-claim is NEVER silently emitted.
  2. DETERMINISTIC fallback: when the model raises, draft_listing still produces a non-empty
     draft per store built only from the declared facts (and never over-claims).
  3. FAIL-SAFE positioning read: a missing positioning file still yields a draft from minimal
     defaults, no raise.
  4. REPORT-ONLY delivery: deliver calls file_digest_issue with report_only=True (no GitHub
     write, no approval interrupt) and the clock-in gate routes a clocked-out run to END.
Run: .venv/bin/python -m unittest tests.test_aso_store_listing_agent -v
"""
import json
import os
import tempfile
import unittest
from unittest import mock

from graphs.marketing import aso_store_listing_agent as m


# --- do_not_claim enforcement (load-bearing) --------------------------------------------
class ComplianceScanTests(unittest.TestCase):
    def test_injected_overclaim_term_is_flagged(self):
        """A draft containing 'time tracking' => compliance_scan flags it, flags non-empty."""
        facts = {"do_not_claim": ["time tracking", "AI scheduling"]}
        drafts = {
            "App Store": {
                "title": "Scheduler — Shifts",
                "subtitle": "Now with Time Tracking built in",  # banned (case-insensitive)
                "keywords": "shifts, roster",
                "short_desc": "Plan shifts fast.",
                "long_desc": "Build rosters for your team.",
            }
        }
        out = m.compliance_scan({"facts": facts, "drafts": drafts})
        flags = out["compliance_flags"]
        self.assertTrue(flags, "an over-claim must produce a non-empty compliance_flags")
        self.assertTrue(any(f["term"] == "time tracking" for f in flags))
        flagged = next(f for f in flags if f["term"] == "time tracking")
        self.assertEqual(flagged["store"], "App Store")
        self.assertEqual(flagged["field"], "subtitle")

    def test_clean_draft_has_no_flags(self):
        """A draft using only shipped features yields zero compliance flags."""
        facts = {"do_not_claim": ["time tracking", "AI scheduling", "clock-in/out"]}
        drafts = {
            "Google Play": {
                "title": "Scheduler — Shift Scheduling",
                "subtitle": "Rosters in one click",
                "keywords": "shift scheduling, roster, team chat",
                "short_desc": "Build staff shifts and export to CSV.",
                "long_desc": "B2B shift scheduling for small teams.",
            }
        }
        out = m.compliance_scan({"facts": facts, "drafts": drafts})
        self.assertEqual(out["compliance_flags"], [])

    def test_overclaim_warning_appears_in_delivered_body(self):
        """When flags exist, the ⚠️ COMPLIANCE warning + the banned term land in the body."""
        captured = {}

        def fake_file(repo, title, body, *, labels=None, report_only=None, **_kw):
            captured.update(body=body, labels=labels, report_only=report_only)
            return {"status": "report_only"}

        state = {
            "facts": {"do_not_claim": ["time tracking"], "ships": ["team chat"]},
            "drafts": {"App Store": {"title": "Now with time tracking", "subtitle": "",
                                     "keywords": "", "short_desc": "", "long_desc": ""}},
            "compliance_flags": [{"store": "App Store", "term": "time tracking", "field": "title"}],
        }
        with mock.patch.object(m, "_report_only", return_value=True), \
                mock.patch.object(m, "write_local_digest", return_value="/tmp/x.md"), \
                mock.patch.object(m, "file_digest_issue", side_effect=fake_file):
            out = m.deliver(state)

        self.assertIn("⚠️ COMPLIANCE", captured["body"])
        self.assertIn("time tracking", captured["body"])
        # A compliance flag escalates to the human-review gate label.
        self.assertIn("gate:human-required", captured["labels"])
        self.assertEqual(out["report"]["compliance_flags"], 1)

    def test_scan_survives_non_dict_draft_block(self):
        """FAIL-SAFE: a non-dict draft block must not crash the scan."""
        facts = {"do_not_claim": ["time tracking"]}
        drafts = {"App Store": "not-a-dict", "Google Play": None}
        out = m.compliance_scan({"facts": facts, "drafts": drafts})
        self.assertEqual(out["compliance_flags"], [])


# --- draft_listing: deterministic fallback + uses model when present ---------------------
class DraftListingTests(unittest.TestCase):
    def test_deterministic_draft_when_model_raises(self):
        """budget_guard raising must NOT crash draft_listing — drafts come from the facts."""
        facts = {
            "what_it_is": "B2B shift scheduling for small teams",
            "ships": ["per-user pricing", "team chat", "CSV export"],
            "do_not_claim": ["time tracking", "AI scheduling"],
            "stores": ["App Store", "Google Play"],
        }
        with mock.patch.object(m, "budget_guard", side_effect=RuntimeError("no API key")):
            out = m.draft_listing({"facts": facts})

        drafts = out["drafts"]
        self.assertEqual(set(drafts.keys()), {"App Store", "Google Play"})
        for store, draft in drafts.items():
            # Every required field present and non-empty (never an empty draft).
            for field in ("title", "subtitle", "keywords", "short_desc", "long_desc"):
                self.assertTrue(str(draft.get(field, "")).strip(), f"{store}.{field} empty")
        # Deterministic fallback must never over-claim a do_not_claim feature.
        blob = json.dumps(drafts).lower()
        self.assertNotIn("time tracking", blob)
        self.assertNotIn("ai scheduling", blob)

    def test_model_draft_used_when_available(self):
        """When the model returns a usable per-store JSON block, it overrides the baseline."""
        facts = {"ships": ["team chat"], "do_not_claim": [], "stores": ["App Store"]}
        model_json = json.dumps({
            "App Store": {
                "title": "MODEL TITLE",
                "subtitle": "MODEL SUB",
                "keywords": ["shifts", "roster"],
                "short_desc": "MODEL SHORT",
                "long_desc": "MODEL LONG",
            }
        })
        fake_model = mock.MagicMock()
        fake_model.invoke.return_value = mock.MagicMock(content=model_json)
        with mock.patch.object(m, "budget_guard", return_value=fake_model):
            out = m.draft_listing({"facts": facts})
        draft = out["drafts"]["App Store"]
        self.assertEqual(draft["title"], "MODEL TITLE")
        self.assertEqual(draft["keywords"], "shifts, roster")  # list coerced to comma string

    def test_partial_model_block_keeps_deterministic_fields(self):
        """A partial model block (only a title) must NOT blank out the other fields.

        The model override is merged per-field onto the complete deterministic baseline, so
        every required field stays non-empty (FAIL-SAFE) while the model's field still wins.
        """
        facts = {
            "what_it_is": "B2B shift scheduling for small teams",
            "ships": ["team chat", "CSV export"],
            "do_not_claim": [],
            "stores": ["App Store"],
        }
        fake_model = mock.MagicMock()
        fake_model.invoke.return_value = mock.MagicMock(
            content=json.dumps({"App Store": {"title": "MODEL TITLE ONLY"}})
        )
        with mock.patch.object(m, "budget_guard", return_value=fake_model):
            out = m.draft_listing({"facts": facts})
        draft = out["drafts"]["App Store"]
        # Model field wins.
        self.assertEqual(draft["title"], "MODEL TITLE ONLY")
        # Every OTHER required field is still present and non-empty (from the baseline).
        for field in ("subtitle", "keywords", "short_desc", "long_desc"):
            self.assertTrue(str(draft.get(field, "")).strip(),
                            f"{field} blanked out by partial model block")

    def test_bad_model_output_keeps_deterministic_draft(self):
        """Unparseable model output falls back to the deterministic draft (never empty)."""
        fake_model = mock.MagicMock()
        fake_model.invoke.return_value = mock.MagicMock(content="not json at all")
        facts = {"ships": ["team chat"], "do_not_claim": [], "stores": ["App Store"]}
        with mock.patch.object(m, "budget_guard", return_value=fake_model):
            out = m.draft_listing({"facts": facts})
        draft = out["drafts"]["App Store"]
        self.assertTrue(str(draft.get("title", "")).strip())


# --- positioning load: fail-safe (missing file still drafts) ----------------------------
class LoadPositioningTests(unittest.TestCase):
    def test_missing_file_returns_defaults_no_raise(self):
        """A missing positioning file must NOT raise — minimal defaults are returned."""
        with mock.patch.dict(os.environ,
                             {"SCHEDULER_POSITIONING_PATH": "/no/such/path/positioning.json"}):
            facts = m._load_positioning()
        self.assertTrue(facts["ships"])
        self.assertTrue(facts["do_not_claim"])
        self.assertTrue(facts["stores"])

    def test_gather_with_missing_file_still_produces_a_draft(self):
        """End-to-end: missing positioning file -> gather -> draft_listing yields a draft."""
        with mock.patch.dict(os.environ,
                             {"SCHEDULER_POSITIONING_PATH": "/no/such/path/positioning.json"}):
            g = m.gather({})
            with mock.patch.object(m, "budget_guard", side_effect=RuntimeError("no model")):
                out = m.draft_listing(g)
        self.assertTrue(out["drafts"])  # non-empty even with no file and no model
        for draft in out["drafts"].values():
            self.assertTrue(str(draft.get("title", "")).strip())

    def test_real_positioning_file_is_read(self):
        """A real positioning JSON file is parsed into normalized facts."""
        data = {
            "product": {
                "what_it_is": "Shift scheduling",
                "ships": ["per-user pricing", "CSV export"],
                "do_not_claim": ["time tracking", "AI scheduling"],
            },
            "positioning_problem": "Mispositioned as a to-do app.",
            "aso": {"stores": ["App Store"]},
        }
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "positioning.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh)
            with mock.patch.dict(os.environ, {"SCHEDULER_POSITIONING_PATH": path}):
                facts = m._load_positioning()
        self.assertEqual(facts["what_it_is"], "Shift scheduling")
        self.assertEqual(facts["ships"], ["per-user pricing", "CSV export"])
        self.assertEqual(facts["do_not_claim"], ["time tracking", "AI scheduling"])
        self.assertEqual(facts["stores"], ["App Store"])

    def test_non_json_file_degrades_to_defaults(self):
        """A non-JSON positioning file degrades to defaults without raising."""
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "positioning.json")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("this is not json {")
            with mock.patch.dict(os.environ, {"SCHEDULER_POSITIONING_PATH": path}):
                facts = m._load_positioning()
        self.assertTrue(facts["ships"])
        self.assertTrue(facts["do_not_claim"])


# --- deliver: report-only, never writes / never hangs -----------------------------------
class DeliverReportOnlyTests(unittest.TestCase):
    def test_deliver_is_report_only_and_never_writes(self):
        """deliver must call file_digest_issue with report_only=True and write nothing live."""
        captured = {}

        def fake_file(repo, title, body, *, labels=None, report_only=None, **_kw):
            captured.update(repo=repo, labels=labels, report_only=report_only)
            assert report_only is True, "deliver must stay report-only on probation"
            return {"status": "report_only", "action": "open_issue", "repo": repo}

        env = {k: v for k, v in os.environ.items() if k != "OPS_REPORT_ONLY"}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(m, "write_local_digest", return_value="/tmp/x/latest.md") as wd, \
                mock.patch.object(m, "file_digest_issue", side_effect=fake_file):
            out = m.deliver({
                "facts": {"ships": ["team chat"], "do_not_claim": []},
                "drafts": {"App Store": {"title": "t", "subtitle": "s",
                                         "keywords": "k", "short_desc": "d", "long_desc": "l"}},
                "compliance_flags": [],
            })

        self.assertTrue(captured["report_only"])
        self.assertEqual(captured["repo"], m.DIGEST_REPO)
        self.assertIn("growth:aso", captured["labels"])
        self.assertNotIn("gate:human-required", captured["labels"])  # no flags => no gate label
        self.assertEqual(out["report"]["delivery"], "report_only")
        self.assertTrue(out["report_only"])
        wd.assert_called_once()

    def test_report_only_env_contract(self):
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
    def test_clocked_out_routes_to_end_and_reports(self):
        with mock.patch.object(m, "check_clocked_in", return_value=False), \
                mock.patch.object(m, "governance_capture") as gov:
            out = m.budget_gate({})
            route = m._budget_route({})
        self.assertTrue(out["report_only"])
        self.assertEqual(out["report"]["delivery"], "skipped")
        self.assertEqual(route, "clocked_out")
        gov.assert_called_once()
        self.assertTrue(gov.call_args[0][1]["report_only"])

    def test_clocked_in_routes_to_gather(self):
        with mock.patch.object(m, "check_clocked_in", return_value=True):
            self.assertEqual(m.budget_gate({}), {})
            self.assertEqual(m._budget_route({}), "gather")


# --- finalize ---------------------------------------------------------------------------
class FinalizeTests(unittest.TestCase):
    def test_finalize_captures_report_only_governance(self):
        with mock.patch.object(m, "governance_capture") as gov:
            out = m.finalize({
                "drafts": {"App Store": {}, "Google Play": {}},
                "compliance_flags": [{"store": "App Store", "term": "x", "field": "title"}],
                "report": {"delivery": "report_only"},
            })
        self.assertTrue(out["report"]["report_only"])
        self.assertEqual(out["report"]["stores"], 2)
        self.assertEqual(out["report"]["compliance_flags"], 1)
        self.assertEqual(out["report"]["delivery"], "report_only")
        gov.assert_called_once()
        self.assertTrue(gov.call_args[0][1]["report_only"])


# --- end-to-end graph: unattended, no creds, never hangs --------------------------------
class GraphInvokeTests(unittest.TestCase):
    def test_full_run_report_only_no_creds(self):
        """Unattended run with no model + missing file still drafts and delivers report-only."""
        env = {k: v for k, v in os.environ.items() if k != "OPS_REPORT_ONLY"}
        env["SCHEDULER_POSITIONING_PATH"] = "/no/such/path/positioning.json"
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(m, "check_clocked_in", return_value=True), \
                mock.patch.object(m, "budget_guard", side_effect=RuntimeError("no model")), \
                mock.patch.object(m, "write_local_digest", return_value=""), \
                mock.patch.object(m, "file_digest_issue",
                                  return_value={"status": "report_only"}) as fd:
            out = m.graph.invoke({})
        self.assertTrue(out["report"]["report_only"])
        self.assertGreaterEqual(out["report"]["stores"], 1)
        self.assertTrue(fd.call_args.kwargs["report_only"])  # no GitHub call, no approval hang

    def test_overclaim_model_draft_is_flagged_end_to_end(self):
        """A model that over-claims 'time tracking' is caught by compliance_scan end-to-end."""
        data = {
            "product": {
                "what_it_is": "Shift scheduling",
                "ships": ["team chat"],
                "do_not_claim": ["time tracking"],
            },
            "aso": {"stores": ["App Store"]},
        }
        model_json = json.dumps({
            "App Store": {
                "title": "Scheduler with Time Tracking",  # over-claim
                "subtitle": "Shifts",
                "keywords": "shifts",
                "short_desc": "Plan shifts.",
                "long_desc": "Built for teams.",
            }
        })
        fake_model = mock.MagicMock()
        fake_model.invoke.return_value = mock.MagicMock(content=model_json)

        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "positioning.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh)
            env = {k: v for k, v in os.environ.items() if k != "OPS_REPORT_ONLY"}
            env["SCHEDULER_POSITIONING_PATH"] = path
            captured = {}

            def fake_file(repo, title, body, *, labels=None, report_only=None, **_kw):
                captured.update(body=body, labels=labels)
                return {"status": "report_only"}

            with mock.patch.dict(os.environ, env, clear=True), \
                    mock.patch.object(m, "check_clocked_in", return_value=True), \
                    mock.patch.object(m, "budget_guard", return_value=fake_model), \
                    mock.patch.object(m, "write_local_digest", return_value=""), \
                    mock.patch.object(m, "file_digest_issue", side_effect=fake_file):
                out = m.graph.invoke({})

        self.assertEqual(out["report"]["compliance_flags"], 1)
        self.assertIn("⚠️ COMPLIANCE", captured["body"])
        self.assertIn("gate:human-required", captured["labels"])

    def test_clocked_out_graph_ends_without_drafting(self):
        with mock.patch.object(m, "check_clocked_in", return_value=False), \
                mock.patch.object(m, "budget_guard") as bg, \
                mock.patch.object(m, "file_digest_issue") as fd:
            out = m.graph.invoke({})
        bg.assert_not_called()   # no model spend on the clocked-out path
        fd.assert_not_called()   # no delivery on the clocked-out path
        self.assertEqual(out["report"]["delivery"], "skipped")


if __name__ == "__main__":
    unittest.main()
