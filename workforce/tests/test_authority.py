"""Unit tests for the delegation router (agent_toolkit/authority.py) + the real delegation.yaml.

The safety properties under test are the ones that keep the OWNER safe while taking him out of the
operational loop: owner-reserved decisions never delegate (by kind AND by flag), default-deny
escalates up, bet-the-company spend reaches the owner, and the mandate is inert until granted.
Loaded by path so it runs in the deps-free venv and CI.
"""
from __future__ import annotations

import copy
import importlib.util
import pathlib
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("authority", ROOT / "agent_toolkit" / "authority.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
route = _mod.route
reaches_owner = _mod.reaches_owner


def _mandate(granted: bool = False):
    # Hermetic: force the grant state regardless of the live file's current status, so the
    # proposed/granted tests don't depend on whether the owner has granted the real mandate.
    m = copy.deepcopy(yaml.safe_load((ROOT / "docs" / "governance" / "delegation.yaml").read_text()))
    if granted:
        m["status"], m["granted_by"] = "granted", "shay"  # the owner signs both together
    else:
        m["status"], m["granted_by"] = "proposed", ""
    return m


def _granted_with_caps(officer: int = 100, board: int = 1000):
    """A granted mandate with SYNTHETIC non-zero spend caps, for exercising spend-routing LOGIC
    independently of the owner's real-world caps (currently 0 — nothing delegated)."""
    m = _mandate(granted=True)
    m["mandate"] = dict(m["mandate"])
    m["mandate"]["max_officer_spend_usd"] = officer
    m["mandate"]["max_board_spend_usd"] = board
    return m


class RealMandate(unittest.TestCase):
    def test_loads_with_owner_and_authorities(self):
        # the live file (status is a live owner-set value: proposed before grant, granted after)
        m = yaml.safe_load((ROOT / "docs" / "governance" / "delegation.yaml").read_text())
        self.assertEqual(m["owner"], "shay")
        self.assertIn("spend", m["authorities"])
        self.assertIn(m["status"], ("proposed", "granted"))
        # if granted, it must be signed by the owner (the router enforces this too)
        if m["status"] == "granted":
            self.assertEqual(m["granted_by"], "shay")

    def test_every_lane_decider_and_escalation_present(self):
        for kind, lane in _mandate()["authorities"].items():
            self.assertTrue(lane.get("decider"), f"{kind} has no decider")
            self.assertTrue(lane.get("escalates_to"), f"{kind} has no escalation")

    def test_real_caps_delegate_no_spend(self):
        # owner set caps to ZERO 2026-06-06 — nothing delegated; EVERY positive spend → owner,
        # while non-spend lanes are still delegated to their officer.
        m = _mandate(granted=True)  # real caps (0/0), signed
        for amt in (1, 50, 1000):
            self.assertEqual(route({"kind": "spend", "amount_usd": amt}, m)["approver"], "owner")
        self.assertEqual(route({"kind": "hire_fire", "within_policy": True}, m)["approver"],
                         "hr_ops_manager")


class InertUntilGranted(unittest.TestCase):
    def test_proposed_mandate_routes_everything_to_owner(self):
        # a non-spend lane reaches the inert branch (under zero spend caps any spend is bet-the-company)
        v = route({"kind": "hire_fire", "within_policy": True}, _mandate(granted=False))
        self.assertEqual(v["approver"], "owner")
        self.assertFalse(v["active"])
        self.assertEqual(v["would_be"], "hr_ops_manager")  # records who WOULD decide once granted

    def test_granted_within_limit_goes_to_officer(self):
        # synthetic caps — exercises the within-limit→officer LOGIC (real caps are 0; see RealMandate)
        v = route({"kind": "spend", "amount_usd": 10}, _granted_with_caps())
        self.assertEqual(v["approver"], "cfo")
        self.assertEqual(v["tier"], "officer")
        self.assertTrue(v["active"])


class OwnerReservedNeverDelegates(unittest.TestCase):
    def setUp(self):
        self.granted = _mandate(granted=True)  # even fully granted, the bright line holds

    def test_owner_reserved_kind_always_owner(self):
        for kind in ("change_mandate", "live_billing_or_pricing", "security_rules_first_deploy",
                     "appoint_or_replace_board", "entity_or_captable"):
            v = route({"kind": kind}, self.granted)
            self.assertEqual(v["approver"], "owner", f"{kind} must reach the owner")

    def test_force_flag_beats_a_mislabeled_kind(self):
        # a billing change dressed up as a tiny "spend" must STILL reach the owner
        v = route({"kind": "spend", "amount_usd": 1, "touches_billing": True}, self.granted)
        self.assertEqual(v["approver"], "owner")
        self.assertIn("force-flagged", v["reason"])

    def test_paying_customer_flag_reaches_owner(self):
        v = route({"kind": "outward_message", "within_policy": True,
                   "touches_paying_customers": True}, self.granted)
        self.assertEqual(v["approver"], "owner")

    def test_bet_the_company_spend_reaches_owner(self):
        v = route({"kind": "spend", "amount_usd": 5000}, self.granted)  # > max_board_spend_usd
        self.assertEqual(v["approver"], "owner")
        self.assertIn("bet-the-company", v["reason"])


class DefaultDeny(unittest.TestCase):
    def test_unknown_kind_escalates_to_owner(self):
        v = route({"kind": "launch_nukes"}, _mandate(granted=True))
        self.assertEqual(v["approver"], "owner")
        self.assertFalse(v["within_limit"])

    def test_over_limit_spend_escalates_not_auto_approved(self):
        # synthetic caps (officer 100 / board 1000) to exercise the officer→board escalation logic
        v = route({"kind": "spend", "amount_usd": 500}, _granted_with_caps())  # > officer, <= board
        self.assertNotEqual(v["approver"], "cfo")
        self.assertEqual(v["approver"], "board")
        self.assertIn("escalates", v["reason"])

    def test_non_spend_without_within_policy_is_denied_up(self):
        # no within_policy assertion → can't prove within limit → escalate, never auto-approve
        v = route({"kind": "deploy_prod"}, _mandate(granted=True))
        self.assertNotEqual(v["tier"], "officer")

    def test_non_spend_with_within_policy_goes_to_officer(self):
        v = route({"kind": "deploy_prod", "within_policy": True}, _mandate(granted=True))
        self.assertEqual(v["approver"], "cto")
        self.assertEqual(v["tier"], "officer")


class RedTeamRegressions(unittest.TestCase):
    """One test per adversarial vector the red-team found (2026-06-06). Each MUST reach the owner."""

    def setUp(self):
        self.g = _mandate(granted=True)

    def test_nan_spend_reaches_owner(self):
        for amt in (float("nan"), "nan", "NaN"):
            v = route({"kind": "spend", "amount_usd": amt}, self.g)
            self.assertEqual(v["approver"], "owner", f"NaN spend {amt!r} must reach owner")

    def test_inf_spend_reaches_owner(self):
        for amt in (float("inf"), float("-inf"), "inf"):
            v = route({"kind": "spend", "amount_usd": amt}, self.g)
            self.assertEqual(v["approver"], "owner")

    def test_negative_spend_reaches_owner(self):
        # a refund/credit is real money out — owner-reserved, not an officer auto-approval
        v = route({"kind": "spend", "amount_usd": -5}, self.g)
        self.assertEqual(v["approver"], "owner")

    def test_bool_amount_is_not_a_valid_spend(self):
        v = route({"kind": "spend", "amount_usd": True}, self.g)
        self.assertEqual(v["approver"], "owner")

    def test_falsy_present_flag_still_reaches_owner(self):
        for val in (0, "", None):
            v = route({"kind": "spend", "amount_usd": 5, "touches_billing": val}, self.g)
            self.assertEqual(v["approver"], "owner", f"falsy-present flag {val!r} must still flag")

    def test_explicit_false_flag_does_not_force_owner(self):
        # an explicit `touches_billing: False` is an honest "not billing" → delegated normally
        # (synthetic caps so the $5 isn't bet-the-company under the real zero caps)
        v = route({"kind": "spend", "amount_usd": 5, "touches_billing": False}, _granted_with_caps())
        self.assertEqual(v["approver"], "cfo")

    def test_missing_caps_fail_closed(self):
        m = _mandate(granted=True)
        m["mandate"] = {}  # lost its limits → must not infer a 0-dollar ceiling and auto-approve
        v = route({"kind": "spend", "amount_usd": 5}, m)
        self.assertEqual(v["approver"], "owner")

    def test_granted_requires_owner_signature(self):
        # status flipped to granted but NOT signed by the owner → stays inert (owner decides)
        m = _mandate()
        m["status"] = "granted"  # no granted_by
        v = route({"kind": "spend", "amount_usd": 5}, m)
        self.assertEqual(v["approver"], "owner")
        self.assertFalse(v["active"])

    def test_granted_by_must_match_owner(self):
        m = _mandate()
        m["status"] = "granted"
        m["granted_by"] = "mallory"  # not the owner
        v = route({"kind": "spend", "amount_usd": 5}, m)
        self.assertEqual(v["approver"], "owner")

    def test_inert_mandate_is_active_false_on_every_path(self):
        m = _mandate()  # proposed
        for d in ({"kind": "live_billing_or_pricing"}, {"kind": "spend", "amount_usd": 5,
                  "touches_billing": True}, {"kind": "spend", "amount_usd": 9999},
                  {"kind": "unknown_thing"}, {"kind": "spend", "amount_usd": 5}):
            self.assertFalse(route(d, m)["active"], f"{d} must be inert (active=False) when proposed")


class ConstitutionProtection(unittest.TestCase):
    def test_canonical_bright_line_is_a_subset_of_owner_reserved(self):
        # removing any bright-line item from the mandate must fail the build
        canonical = {"change_mandate", "entity_or_captable", "bet_the_company_spend",
                     "live_billing_or_pricing", "security_rules_first_deploy", "appoint_or_replace_board"}
        self.assertTrue(canonical.issubset(set(_mandate()["owner_reserved"])),
                        "owner_reserved must always contain the full canonical bright-line set")

    def test_spend_ceilings_pinned_to_owner_baseline(self):
        # raising a cap self-grants authority; the pin makes that a CI-visible (owner) change.
        # Owner baseline 2026-06-06 = ZERO (nothing delegated). Any positive cap fails the build
        # until the owner bumps THIS pin too (an explicit, owner-signed change_mandate).
        caps = _mandate()["mandate"]
        self.assertLessEqual(caps["max_officer_spend_usd"], 0)
        self.assertLessEqual(caps["max_board_spend_usd"], 0)

    def test_editing_governance_dir_is_a_constitution_change(self):
        flagged = _mod.constitution_paths(
            ["docs/governance/delegation.yaml", "src/app.py", "README.md"])
        self.assertEqual(flagged, ["docs/governance/delegation.yaml"])

    def test_merge_lane_excludes_governance(self):
        # the merge_to_main lane must explicitly carve out docs/governance (not routine docs)
        self.assertIn("docs/governance", _mandate()["authorities"]["merge_to_main"]["limit"])


class MandateConsistency(unittest.TestCase):
    """The mandate must be internally safe: no owner-reserved item is also delegated, and every
    decider is a real officer (a roster agent or the board)."""

    def test_no_owner_reserved_item_is_also_a_delegated_lane(self):
        m = _mandate()
        overlap = set(m["owner_reserved"]) & set(m["authorities"])
        self.assertEqual(overlap, set(), f"owner-reserved items must NOT be delegable: {overlap}")

    def test_every_decider_is_a_real_officer(self):
        m = _mandate()
        roster = yaml.safe_load((ROOT / "roster.yaml").read_text())
        officers = set((roster.get("agents") or {}).keys()) | {"board", "owner"}
        for kind, lane in m["authorities"].items():
            self.assertIn(lane["decider"], officers, f"{kind} decider '{lane['decider']}' is not a real officer")


class Helpers(unittest.TestCase):
    def test_reaches_owner_true_for_reserved(self):
        self.assertTrue(reaches_owner({"kind": "live_billing_or_pricing"}, _mandate(granted=True)))

    def test_reaches_owner_false_for_delegated(self):
        # a non-spend delegated lane resolves to an officer (spend is 0-capped in the real mandate)
        self.assertFalse(reaches_owner({"kind": "hire_fire", "within_policy": True}, _mandate(granted=True)))


if __name__ == "__main__":
    unittest.main()
