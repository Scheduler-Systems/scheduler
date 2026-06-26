"""Residual budget-correctness defect: the board chair's founder ask flattens the
CFO's spend-vs-allocation distinction back into a 'spend vs cap' claim.

Context (the run-in hardening): the CFO digest was fixed so that actual spend UNDER the cap
is NEVER reported as 'over cap'; the salary ALLOCATION exceeding the cap is surfaced as a
SEPARATE, clearly-labelled PLANNING re-balance (graphs/exec/cfo.py analyze/_render_body).
That distinction is the whole point — see tests/test_runin_quality_fixes.py.

But the board chair (graphs/board/board_chair.py + agent_toolkit/lanes.py) reconciles the
CFO's allocation re-balance into a founder ask labelled literally:

    "team-budget spend vs cap (owner: cfo)"

via lanes.systemic_item_for(), whose substring scan is NEGATION-UNAWARE and fires on the
"team token budget" string that always appears in the (truthful, spend-UNDER) CFO envelope.
The label says SPEND vs cap when the truth — carried in the very same CFO digest — is that
actual spend is UNDER the cap and only the allocation is over. The founder-facing ask thus
re-introduces the exact spend/allocation conflation the CFO digest was hardened to avoid.

This test pins the correct behaviour: when actual spend is UNDER the cap (only the allocation
is over), the founder ask the board hands Shay must NOT claim it as a 'spend' breach — it must
be framed as the allocation/planning re-balance it actually is.

Run: .venv/bin/python -m unittest tests.test_board_allocation_vs_spend_label -v
"""
import unittest
from unittest import mock

from graphs.exec import cfo as cfo_m
from graphs.board import board_chair as bc_m


TEAM_CAP = 5_540_000
# Live roster state: total salary allocation 6.68M (> cap), actual spend ~98k (<< cap).
ALLOC = 6_680_000
ACTUAL_SPEND = 98_000


def _cfo_card(salary=0, spent=0, real=None, schedule="daily"):
    return {
        "role": "r", "grade": "g", "schedule": schedule, "status": "probation",
        "scorecard": {}, "salary_tokens": salary, "spent_tokens": spent,
        "remaining_tokens": salary - spent, "over_budget": False,
        "langsmith": ({"total_tokens": real} if real is not None else None),
    }


def _live_cfo_digest():
    """The CFO digest for the real run-in state: allocation 6.68M over cap, spend 98k under cap.

    The allocation-over re-balance escalates a budget INCREASE to shay (capital), so the digest
    legitimately carries an escalate_to: shay trigger — which is what pulls it into the board's
    founder asks.
    """
    cards = {"a": _cfo_card(salary=ALLOC, real=ACTUAL_SPEND)}
    spend = {"agents": cards, "by_class": {}}
    with mock.patch.object(cfo_m, "load_budget_policy",
                           return_value={"team_token_budget": TEAM_CAP}):
        analysis = cfo_m.analyze({"spend": spend, "revenue": {"ok": False}})["analysis"]
    # Guard: the CFO itself is correct — actual spend is UNDER the cap, allocation is over.
    assert analysis["over_team_budget"] is False
    assert analysis["salary_allocation_over_cap"] is True
    proposals = [{
        "agent": "a", "action": "increase",
        "current_salary_tokens": ALLOC, "proposed_tokens": ALLOC, "grade": "g",
        "reason": "capital decision: roster allocation exceeds the cap — propose a re-balance",
        "escalate_to": "shay",
    }]
    return cfo_m._render_body(spend, {"ok": False}, "", analysis, proposals, "")


class BoardAllocationVsSpendLabelTests(unittest.TestCase):
    def test_founder_ask_does_not_claim_spend_over_cap_when_spend_is_under(self):
        """The board chair hands Shay ONE reconciled ask. When actual spend is UNDER the cap and
        only the salary ALLOCATION exceeds it, that ask must NOT be framed as a 'spend vs cap'
        breach — that is the spend/allocation conflation the CFO digest was hardened to avoid.
        """
        reports = {slug: "(no digest yet)" for slug in bc_m.SUBORDINATE_DIGESTS}
        reports["cfo"] = _live_cfo_digest()

        out = bc_m.synthesize({"reports": reports})
        rendered = "\n".join(bc_m._render_asks(out["asks"])).lower()

        # There IS a legitimate founder ask (the allocation re-balance is a capital decision).
        self.assertIn("escalate_to: shay", rendered)

        # FAILING ASSERTION (the residual defect): the ask is labelled "team-budget spend vs cap"
        # even though the underlying truth — in the very CFO digest being reconciled — is that
        # actual spend is UNDER the cap. A founder ask must not assert a SPEND breach that did not
        # happen. It should be framed as the allocation/planning re-balance it actually is.
        self.assertNotIn(
            "spend vs cap", rendered,
            "board founder ask claims a SPEND-vs-cap breach while actual spend is UNDER the cap "
            "(only the allocation is over) — re-introduces the spend/allocation conflation",
        )
        # The honest framing should name it as an allocation / re-balance item.
        self.assertTrue(
            "allocation" in rendered or "re-balance" in rendered or "rebalance" in rendered,
            "the allocation-over-cap founder ask should be framed as an allocation re-balance",
        )


if __name__ == "__main__":
    unittest.main()
