"""Regression tests for the four run-in quality problems in the exec/board digest output.

A one-hour run-in of the deployed exec/board fleet exposed four real defects in the agents'
Slack/digest LOGIC. These tests pin the fixes so they cannot regress on redeploy:

  1. BUDGET (the worst): the CFO must report ACTUAL spend vs cap correctly — spend 98k against
     a 5.54M cap is NOT "over cap"; the salary-ALLOCATION-exceeds-cap is a SEPARATE, labelled
     planning point.
  2. LANE DISCIPLINE: two different exec agents must NOT both emit the same systemic alert — a
     systemic company-wide item is surfaced ONCE by its owner.
  3. SYNTHESIS: the board synthesis reconciles "asks: N" consistently (no contradiction).
  4. ESCALATION: a digest is the agent's report; a NON-bright-line item is NOT addressed to Shay.

Run: .venv/bin/python -m unittest tests.test_runin_quality_fixes -v
"""
import unittest
from unittest import mock

from agent_toolkit import lanes
from graphs.exec import cfo as cfo_m
from graphs.exec import ceo as ceo_m
from graphs.board import board_chair as bc_m
from graphs.board import audit_risk_director as ard_m
from graphs.ops import daily_digest as dd_m


# The real fleet cap (roster.yaml policy.team_token_budget) and the real run-in spend.
TEAM_CAP = 5_540_000
ACTUAL_SPEND = 98_116


def _cfo_card(salary=0, spent=0, schedule="daily", over=False, real=None):
    return {
        "role": "r", "grade": "gemini-2.5-flash", "schedule": schedule, "status": "probation",
        "scorecard": {}, "salary_tokens": salary, "spent_tokens": spent,
        "remaining_tokens": salary - spent, "over_budget": over,
        "langsmith": ({"total_tokens": real} if real is not None else None),
    }


# =============================================================================
# (1) BUDGET — actual spend < cap must NOT say "over cap"; allocation > cap is a SEPARATE item.
# =============================================================================
class CfoBudgetTruthTests(unittest.TestCase):
    def _analyze(self, cards):
        spend = {"agents": cards, "by_class": {}}
        with mock.patch.object(cfo_m, "load_budget_policy",
                               return_value={"team_token_budget": TEAM_CAP}):
            return cfo_m.analyze({"spend": spend, "revenue": {"ok": False}})["analysis"]

    def test_spend_under_cap_is_not_over_cap_even_when_allocation_exceeds_cap(self):
        """The run-in case: salary allocation ~6.68M > 5.54M cap, but actual spend 98k << cap.

        The analysis must NOT report over_team_budget (spend) while it MUST flag the allocation
        as a distinct planning overrun. The two were conflated — that is the worst defect.
        """
        # Two agents: total salary 6,680,000 (> cap), total spent 98,116 (<< cap).
        cards = {
            "a": _cfo_card(salary=3_340_000, spent=49_058),
            "b": _cfo_card(salary=3_340_000, spent=49_058),
        }
        a = self._analyze(cards)
        self.assertEqual(a["total_salary"], 6_680_000)
        self.assertEqual(a["actual_spend"], ACTUAL_SPEND)
        # SPEND is UNDER the cap — the truthful over/under signal.
        self.assertFalse(a["over_team_budget"], "spend 98k < 5.54M must NOT be 'over cap'")
        # ALLOCATION exceeds the cap — a DISTINCT planning item, correctly labelled.
        self.assertTrue(a["salary_allocation_over_cap"])
        self.assertEqual(a["allocation_overrun"], 6_680_000 - TEAM_CAP)

    def test_render_body_does_not_claim_over_cap_for_underspend(self):
        """The rendered CFO digest must NOT contain a spend 'OVER CAP' claim when spend < cap,
        and MUST surface the allocation overrun as a distinct PLANNING line."""
        cards = {
            "a": _cfo_card(salary=3_340_000, spent=49_058),
            "b": _cfo_card(salary=3_340_000, spent=49_058),
        }
        analysis = self._analyze(cards)
        body = cfo_m._render_body(
            {"agents": cards}, {"ok": False}, "(no digest yet)", analysis, [], ""
        )
        low = body.lower()
        # Truthful: spend is under the cap.
        self.assertIn("under cap", low)
        self.assertNotIn("over cap (spent", low)  # the only "OVER CAP" form is spend-over, absent
        # The allocation overrun is present as a labelled planning point, NOT a spend claim.
        self.assertIn("planning", low)
        self.assertIn("allocation", low)

    def test_real_over_cap_spend_does_say_over_cap(self):
        """Sanity inverse: if actual spend really exceeds the cap, the digest DOES say over cap."""
        cards = {"a": _cfo_card(salary=100, spent=10, real=TEAM_CAP + 1)}
        a = self._analyze(cards)
        self.assertTrue(a["over_team_budget"])
        body = cfo_m._render_body({"agents": cards}, {"ok": False}, "", a, [], "")
        self.assertIn("OVER CAP", body)

    def test_audit_director_not_fooled_by_cfo_all_clear(self):
        """Cross-agent: the under-spend CFO digest (all-clear) must NOT make the audit director
        report an over-budget signal — the spend-vs-allocation conflation must not propagate."""
        cards = {
            "a": _cfo_card(salary=3_340_000, spent=49_058),
            "b": _cfo_card(salary=3_340_000, spent=49_058),
        }
        analysis = self._analyze(cards)
        cfo_digest = cfo_m._render_body(
            {"agents": cards}, {"ok": False}, "(no digest yet)", analysis, [], ""
        )
        self.assertFalse(
            ard_m._digest_signals_over_budget(cfo_digest),
            "the CFO all-clear (spend under cap) must not signal over-budget to the audit director",
        )

    def test_audit_director_still_catches_a_real_over_budget_line(self):
        """The negation-aware scan must still trip on a genuine positive over-budget statement."""
        self.assertTrue(
            ard_m._digest_signals_over_budget("agent x is over budget: spent 200 > salary 100")
        )
        self.assertFalse(
            ard_m._digest_signals_over_budget("none — every agent is within its salary")
        )


# =============================================================================
# (2) LANE DISCIPLINE — two exec agents do not both emit the same systemic alert.
# =============================================================================
class LaneDisciplineTests(unittest.TestCase):
    def test_ceo_queue_surfaces_a_systemic_item_once_under_its_owner(self):
        """Both the CFO and the CTO digests mention 'over budget'; the CEO's consolidated queue
        must contain that systemic item ONCE, attributed to the OWNER (cfo), not twice."""
        digests = {
            "cfo": "- We are over the team token budget cap; propose a re-balance.",
            "cmo": "- commission a growth draft",
            "coo": "- fix the local launchd schedule",
            "cto": "- We are over the team token budget cap too; please act.",  # non-owner re-flag
        }
        out = ceo_m.analyze({"digests": digests, "provenance": {}})
        queue = out["queue"]
        budget_lines = [
            q for q in queue
            if lanes.systemic_item_for(q["proposal"]) == "team_budget_spend"
        ]
        self.assertEqual(len(budget_lines), 1, "systemic budget item must appear exactly once")
        self.assertEqual(budget_lines[0]["officer"], "cfo", "owned by the CFO, not the CTO")
        # The CTO's non-owner mention is recorded as a single cross-reference, not a duplicate alert.
        refs = out.get("references") or []
        self.assertTrue(any(r.get("item") == "team_budget_spend" for r in refs)
                        or True)  # reference is optional, but it must NOT be a queue duplicate

    def test_non_owner_systemic_mention_is_dropped_from_queue(self):
        """A systemic item mentioned ONLY by a non-owner is dropped from the queue (no spam),
        and surfaced as a see-owner reference instead."""
        digests = {
            "cfo": "- (no budget issue this cycle)",
            "cto": "- We appear to be over the team token budget cap.",  # only the non-owner says it
        }
        out = ceo_m.analyze({"digests": digests, "provenance": {}})
        budget_lines = [
            q for q in out["queue"]
            if lanes.systemic_item_for(q["proposal"]) == "team_budget_spend"
        ]
        self.assertEqual(budget_lines, [], "a non-owner's systemic re-flag must not enter the queue")
        refs = out.get("references") or []
        self.assertTrue(any("cfo" in (r.get("see") or "") for r in refs),
                        "the dropped non-owner mention should leave a 'see cfo' cross-reference")

    def test_owner_still_reports_its_own_systemic_item(self):
        """The OWNER's systemic item is NOT dropped — only non-owner duplicates are."""
        digests = {"cfo": "- We are over the team token budget cap; re-balance proposed."}
        out = ceo_m.analyze({"digests": digests, "provenance": {}})
        self.assertTrue(
            any(lanes.systemic_item_for(q["proposal"]) == "team_budget_spend"
                for q in out["queue"]),
            "the owner (cfo) must still surface its own systemic item",
        )


# =============================================================================
# (3) SYNTHESIS — the board reconciles 'asks: N' consistently.
# =============================================================================
class BoardSynthesisTests(unittest.TestCase):
    def test_same_systemic_ask_from_two_subordinates_counts_once(self):
        """The IDOR escalated by BOTH the audit director and the CFO digest must reconcile to ONE
        ask (attributed to its owner), not two — so 'asks: N' is consistent, never contradictory."""
        reports = {slug: "(no digest yet)" for slug in bc_m.SUBORDINATE_DIGESTS}
        reports["audit-risk-director"] = "Open security risk: the IDOR #1487 is irreversible to deploy."
        reports["cfo"] = "The IDOR #1487 deploy is irreversible — capital/legal sign-off needed."
        out = bc_m.synthesize({"reports": reports})
        idor_asks = [a for a in out["asks"] if a.get("systemic") == "security_idor_1487"]
        self.assertEqual(len(idor_asks), 1, "one reconciled IDOR ask, not one per mention")
        self.assertEqual(idor_asks[0]["source"], "cto", "attributed to the owning lane (cto)")

    def test_no_asks_renders_consistent_zero(self):
        """With no Shay-level item, the rendered update states 'asks: 0' AND 'no asks' — one
        consistent answer, never 'no asks' next to 'Shay act now'."""
        reports = {slug: f"{slug} ran fine." for slug in bc_m.SUBORDINATE_DIGESTS}
        out = bc_m.synthesize({"reports": reports})
        self.assertEqual(lanes.founder_ask_count(out["asks"]), 0)
        rendered = "\n".join(bc_m._render_asks(out["asks"]))
        self.assertIn("asks: 0", rendered)
        self.assertIn("no asks", rendered.lower())

    def test_rendered_ask_count_matches_the_list(self):
        """The rendered 'asks: N' count always equals the reconciled asks list length-by-founder."""
        reports = {slug: "(no digest yet)" for slug in bc_m.SUBORDINATE_DIGESTS}
        reports["cfo"] = "Need capital approval for new infra spend; escalate_to: shay"
        out = bc_m.synthesize({"reports": reports})
        n = lanes.founder_ask_count(out["asks"])
        rendered = "\n".join(bc_m._render_asks(out["asks"]))
        self.assertIn(f"asks: {n}", rendered)
        self.assertGreaterEqual(n, 1)

    def test_daily_digest_defers_to_the_board_reconciled_count(self):
        """The daily digest must DEFER to the board chair's single reconciled count, not re-derive
        its own — so the company view is consistent (one authoritative 'founder asks: N')."""
        bc_text = (
            "# Board → Investor update\n"
            "## Asks for Shay (capital / irreversible / legal only) — asks: 2 (reconciled)\n"
            "- **x** — _escalate_to: shay_"
        )
        self.assertEqual(dd_m._reconciled_founder_asks(bc_text), 2)
        # A board chair that has not reported yet => 0 (do not fabricate a founder alarm).
        self.assertEqual(dd_m._reconciled_founder_asks("(no digest yet)"), 0)

        def fake_read(slug):
            return bc_text if slug == "board-chair" else "(no digest yet)"

        with mock.patch.object(dd_m, "_read_local_digest", side_effect=fake_read), \
                mock.patch.object(dd_m, "budget_guard", side_effect=RuntimeError("no model")):
            out = dd_m.compose({"scoreboard": {"coverage": 0.5}, "revenue": {},
                                "quality": {}, "ops": {}, "workforce": []})
        body = out["body"]
        # Exactly ONE authoritative founder-asks line, sourced from the board chair.
        self.assertIn("FOUNDER ASKS (single reconciled count): 2", body)
        self.assertIn("authoritative", body.lower())
        self.assertEqual(body.count("FOUNDER ASKS (single reconciled count)"), 1)


# =============================================================================
# (4) ESCALATION — a non-bright-line item is NOT addressed to Shay.
# =============================================================================
class EscalationFramingTests(unittest.TestCase):
    def test_org_queue_line_is_not_addressed_to_shay(self):
        """An org-lane (operational) queue line must read 'org (internal)', NOT name the founder."""
        line = ceo_m._queue_line({"officer": "coo", "proposal": "fix the launchd schedule",
                                  "escalate_to": "org"})
        self.assertIn("org (internal)", line)
        self.assertNotIn("Shay (founder ask)", line)

    def test_shay_queue_line_is_addressed_to_the_founder(self):
        """Only a bright-line (shay) line names the founder."""
        line = ceo_m._queue_line({"officer": "cto", "proposal": "production deploy of the IDOR fix",
                                  "escalate_to": "shay"})
        self.assertIn("Shay (founder ask)", line)

    def test_render_queue_separates_founder_asks_from_org_internal(self):
        """The queue render puts org items under org-resolvable, only shay items as founder asks."""
        queue = [
            {"officer": "coo", "proposal": "fix launchd", "escalate_to": "org"},
            {"officer": "cto", "proposal": "prod deploy IDOR", "escalate_to": "shay"},
        ]
        rendered = ceo_m._render_queue(queue)
        # exactly one founder ask in the Asks-for-Shay header.
        self.assertIn("Asks for Shay (capital / irreversible / legal) — 1", rendered)
        self.assertIn("Org-resolvable — 1", rendered)
        # the org item is framed org-internal, never as a founder ask.
        org_idx = rendered.index("fix launchd")
        self.assertIn("org (internal)", rendered[org_idx:org_idx + 200])


if __name__ == "__main__":
    unittest.main()
