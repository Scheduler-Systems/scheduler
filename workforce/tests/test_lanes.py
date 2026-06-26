"""Tests for the lane-discipline + escalation-framing seam (agent_toolkit/lanes.py).

The one-hour run-in surfaced SPAM (every exec re-flagged the same company-wide items) and
OVER-ESCALATION (almost everything addressed "Shay, act now"). These tests pin the policy that
fixes both:

  * each SYSTEMIC company-wide item has exactly ONE owner; a non-owner may NOT re-report it;
  * only a BRIGHT-LINE (escalate_to "shay") item is a founder ask — operational items stay org.

Pure unit tests, no network/model. Run: .venv/bin/python -m unittest tests.test_lanes -v
"""
import unittest

from agent_toolkit import lanes


class SystemicClassificationTests(unittest.TestCase):
    def test_each_runin_item_classifies_to_one_owner(self):
        """The four run-in systemic items each resolve to exactly ONE owner."""
        cases = {
            "We are over the 5.54M team token budget hard cap": ("team_budget_spend", "cfo"),
            "IDOR #1487 schedule_acl not deployed to production": ("security_idor_1487", "cto"),
            "RevenueCat funnel unavailable — missing rc keys": ("missing_revenuecat_keys", "cmo"),
            "0 active staff / 23 staffed": ("staffing_active_count", "board_chair"),
        }
        for text, (key, owner) in cases.items():
            self.assertEqual(lanes.systemic_item_for(text), key, text)
            self.assertEqual(lanes.SYSTEMIC_ITEMS[key]["owner"], owner, text)

    def test_own_lane_finding_is_not_systemic(self):
        """A plain own-lane finding is NOT a systemic item (returns None -> never lane-filtered)."""
        self.assertIsNone(lanes.systemic_item_for("Investigate red CI on scheduler-web"))
        self.assertIsNone(lanes.systemic_item_for(""))

    def test_each_systemic_item_has_exactly_one_owner(self):
        """Registry invariant: every systemic item declares a single owner string."""
        for key, spec in lanes.SYSTEMIC_ITEMS.items():
            self.assertIsInstance(spec.get("owner"), str, key)
            self.assertTrue(spec["owner"], key)


class OwnershipTests(unittest.TestCase):
    def test_only_owner_may_report_systemic_item(self):
        """A systemic item is reportable ONLY by its owner; a non-owner is blocked."""
        budget = "we are over the team token budget cap"
        self.assertTrue(lanes.may_report("cfo", budget))      # owner
        self.assertFalse(lanes.may_report("cto", budget))     # non-owner re-flag blocked
        self.assertFalse(lanes.may_report("audit_risk_director", budget))

    def test_idor_owned_by_cto_not_others(self):
        idor = "the Firestore IDOR #1487 is held"
        self.assertTrue(lanes.may_report("cto", idor))
        self.assertFalse(lanes.may_report("cfo", idor))

    def test_non_systemic_text_always_reportable(self):
        """Own-lane findings are always reportable, by any agent."""
        self.assertTrue(lanes.may_report("cto", "red CI on scheduler-web"))
        self.assertTrue(lanes.may_report("cmo", "commission a blog draft"))

    def test_filter_owned_drops_non_owner_systemic_keeps_own_lane(self):
        """A non-owner's list keeps own-lane items but drops systemic items it does not own."""
        cto_items = [
            "red CI on scheduler-web",               # own lane — keep
            "we are over the team budget cap",       # systemic, owned by cfo — drop for cto
            "IDOR #1487 deploy held",                # systemic, owned by cto — keep for cto
        ]
        kept = lanes.filter_owned("cto", cto_items)
        self.assertIn("red CI on scheduler-web", kept)
        self.assertIn("IDOR #1487 deploy held", kept)
        self.assertNotIn("we are over the team budget cap", kept)

    def test_see_owner_pointer_for_non_owner_only(self):
        """A non-owner gets a 'see <owner>' pointer; the owner (and non-systemic text) gets None."""
        self.assertEqual(
            lanes.see_owner_pointer("cto", "over the team budget cap"),
            "see cfo for team-budget spend vs cap",
        )
        self.assertIsNone(lanes.see_owner_pointer("cfo", "over the team budget cap"))  # owner
        self.assertIsNone(lanes.see_owner_pointer("cto", "red CI on scheduler-web"))   # non-systemic


class EscalationFramingTests(unittest.TestCase):
    def test_only_shay_is_bright_line(self):
        self.assertTrue(lanes.is_bright_line("shay"))
        self.assertTrue(lanes.is_bright_line(" SHAY "))
        self.assertFalse(lanes.is_bright_line("org"))
        self.assertFalse(lanes.is_bright_line(None))
        self.assertFalse(lanes.is_bright_line(""))

    def test_frame_escalation_audience(self):
        self.assertEqual(lanes.frame_escalation("shay"), "founder-ask")
        self.assertEqual(lanes.frame_escalation("org"), "org-internal")
        self.assertEqual(lanes.frame_escalation(None), "org-internal")

    def test_addressee_only_names_founder_for_bright_line(self):
        self.assertIn("Shay", lanes.addressee("shay"))
        self.assertNotIn("Shay", lanes.addressee("org"))

    def test_founder_ask_count_counts_only_bright_line(self):
        items = [{"escalate_to": "shay"}, {"escalate_to": "org"}, {"escalate_to": "shay"}]
        self.assertEqual(lanes.founder_ask_count(items), 2)
        self.assertEqual(lanes.founder_ask_count([]), 0)
        self.assertEqual(lanes.founder_ask_count([{"escalate_to": "org"}]), 0)

    def test_founder_ask_count_failsafe_on_bad_items(self):
        """A non-dict element contributes 0 rather than crashing."""
        self.assertEqual(lanes.founder_ask_count([None, "x", {"escalate_to": "shay"}]), 1)


class IdorDossierRelocationTests(unittest.TestCase):
    """The standing held IDOR dossier is owned by lanes (relocated from cto) — single source of truth."""

    def test_idor_dossier_is_the_security_idor_1487_content(self):
        item = lanes.idor_security_item()
        self.assertEqual(item["id"], "firestore-idor-entitlement-rollout")
        self.assertEqual(item["status"], "held")
        self.assertEqual(item["escalate_to"], "shay")
        self.assertEqual(item["systemic_key"], "security_idor_1487")
        self.assertIn("1487", item["detail"])

    def test_idor_dossier_returns_a_copy(self):
        """A caller mutating the returned dict must not corrupt the module constant."""
        item = lanes.idor_security_item()
        item["status"] = "MUTATED"
        self.assertEqual(lanes.IDOR_SECURITY_ITEM["status"], "held")

    def test_idor_is_open_tracks_status(self):
        self.assertTrue(lanes.idor_is_open())  # held => open/surfaced


class ReconcileFounderAsksRelocationTests(unittest.TestCase):
    """The founder-ask reconciliation is a SHARED lanes helper (relocated from board_chair)."""

    def test_systemic_ask_from_two_sources_reconciles_to_one(self):
        reports = {
            "audit-risk-director": "Open security risk: the IDOR #1487 is irreversible to deploy.",
            "cfo": "The IDOR #1487 deploy is irreversible — capital/legal sign-off needed.",
        }
        asks = lanes.reconcile_founder_asks(reports)
        idor = [a for a in asks if a.get("systemic") == "security_idor_1487"]
        self.assertEqual(len(idor), 1, "one reconciled IDOR ask, not one per mention")
        self.assertEqual(idor[0]["source"], "cto")  # attributed to the owning lane

    def test_no_shay_trigger_means_no_ask(self):
        reports = {"cfo": "all green", "ceo": "nothing to escalate"}
        self.assertEqual(lanes.reconcile_founder_asks(reports), [])
        self.assertEqual(lanes.reconciled_founder_ask_count(reports), 0)

    def test_non_systemic_capital_ask_is_counted(self):
        reports = {"cfo": "Need capital approval for new infra; escalate_to: shay"}
        self.assertEqual(lanes.reconciled_founder_ask_count(reports), 1)

    def test_reconcile_is_failsafe_on_bad_reports(self):
        self.assertEqual(lanes.reconcile_founder_asks(None), [])
        self.assertEqual(lanes.reconcile_founder_asks({"x": None}), [])


class StaffingViewRelocationTests(unittest.TestCase):
    """The staffing/headcount view is a SHARED lanes helper (relocated from board_chair)."""

    def test_counts_staffed_and_on_shift_active(self):
        roster = {"agents": {"a": {}, "b": {}, "c": {}}}
        head = lanes.staffing_view(roster, is_clocked_in=lambda n: n in ("a", "b"))
        self.assertEqual(head["staffed"], 3)
        self.assertEqual(head["active"], 2)

    def test_model_work_roles_are_not_counted(self):
        roster = {"agents": {"a": {}, "ml": {}}}
        head = lanes.staffing_view(roster, is_clocked_in=lambda n: True,
                                   is_model_work=lambda n: n == "ml")
        self.assertEqual(head["staffed"], 1)
        self.assertEqual(head["active"], 1)

    def test_no_clock_predicate_counts_all_active_failsafe(self):
        """Omitting is_clocked_in never under-reports a working fleet (all counted active)."""
        roster = {"agents": {"a": {}, "b": {}}}
        head = lanes.staffing_view(roster)
        self.assertEqual(head, {"staffed": 2, "active": 2})

    def test_failsafe_on_empty_or_bad_roster(self):
        self.assertEqual(lanes.staffing_view({}), {"staffed": 0, "active": 0})
        self.assertEqual(lanes.staffing_view({"agents": None}), {"staffed": 0, "active": 0})


if __name__ == "__main__":
    unittest.main()
