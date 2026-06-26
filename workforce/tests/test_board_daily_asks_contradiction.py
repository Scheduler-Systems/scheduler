"""FAILING regression: the board_chair ↔ daily_digest founder-ask synthesis contradicts itself.

The architecture's promise (lanes.py / board_chair / daily_digest docstrings) is that there is
exactly ONE authoritative founder-ask count — the board chair renders
``asks: N (reconciled)`` and the daily digest DEFERS to it via
``daily_digest._reconciled_founder_asks(board_chair_text)`` so the company view can never say
"no asks" in one place and "Shay, N asks" in another.

THE BUG (lane-discipline / synthesis): ``_reconciled_founder_asks`` greps the board chair text
for the FIRST ``asks:\\s*(\\d+)`` match — but ``board_chair.compose`` PREPENDS an UNCONSTRAINED
model "chair's note" ABOVE the deterministic ``asks: N (reconciled)`` line and writes the whole
thing (narrative + update) to the ``board-chair`` digest that the daily digest reads. When the
model's free-text note contains ANY ``asks: <number>`` token (a routine compact status phrasing,
e.g. "decisions: 2, asks: 2 open items"), the greedy first-match regex grabs THAT number instead
of the authoritative reconciled count. Result: the board chair's own update says
``asks: 0 (reconciled)`` / "no asks", while the daily digest's single "FOUNDER ASKS (single
reconciled count)" line reports a different N — the exact contradiction the synthesis was built
to prevent.

This test drives the REAL ``board_chair.compose`` (model mocked to emit a plausible note) to
produce the persisted board-chair digest, then feeds that real text to the REAL
``daily_digest._reconciled_founder_asks`` and ``daily_digest.compose``. It asserts the two
counts agree. It FAILS on the current code (0 reconciled vs 2 parsed) and will pass once the
parser is anchored to the authoritative ``asks: N (reconciled)`` line (or the model note is kept
out of the machine-parsed region).

Run:
    ../../.venv/bin/python -m unittest tests.test_board_daily_asks_contradiction -v
"""
import re
import unittest
from unittest import mock

from graphs.board import board_chair as bc_m
from graphs.ops import daily_digest as dd_m
from agent_toolkit import lanes


def _authoritative_reconciled_count(board_chair_text: str) -> int:
    """The TRUE company-wide count = the board chair's own ``asks: N (reconciled)`` line."""
    m = re.search(r"asks:\s*(\d+)\s*\(reconciled\)", board_chair_text, re.IGNORECASE)
    return int(m.group(1)) if m else 0


class BoardDailyAsksContradictionTests(unittest.TestCase):
    def test_daily_digest_count_matches_board_chair_authoritative_count(self):
        """No founder asks this cadence => board chair renders 'asks: 0 (reconciled)' / 'no asks'.

        The daily digest's single reconciled founder-ask count MUST equal that 0. It currently
        does not: the model 'chair's note' prepended by compose carries an 'asks: 2' token that
        the greedy first-match regex picks up, so the daily digest contradicts the board chair.
        """
        # 1) No subordinate flags a Shay-level item -> the reconciled list is EMPTY.
        reports = {slug: f"{slug} ran fine; nothing to escalate." for slug in bc_m.SUBORDINATE_DIGESTS}
        synth = bc_m.synthesize({"reports": reports})
        self.assertEqual(lanes.founder_ask_count(synth["asks"]), 0)  # authoritative truth = 0

        # 2) Drive the REAL board_chair.compose. The model returns a routine compact status note
        #    that, like real LLM prose, contains an "asks: <n>" token referring to open items —
        #    NOT the reconciled founder-ask count.
        chair_note = "Status: staffing 3/5, burn within budget, decisions: 2, asks: 2 open items; MRR steady."
        fake_model = mock.MagicMock()
        fake_model.invoke.return_value = mock.MagicMock(content=chair_note)
        state = {
            "kpis": {
                "staffed": 5, "active": 3,
                "burn": {"salary_tokens": 5000, "spent_tokens": 1000,
                         "remaining_tokens": 4000, "over_budget": False},
                "revenue": {"ok": True, "mrr": 4200, "revenue": 9000,
                            "active_subscriptions": 11, "active_trials": 3},
                "output": {"tests_landed": "reported", "drafts_produced": "reported"},
            },
            "decisions": synth["decisions"],
            "asks": synth["asks"],  # EMPTY -> 'asks: 0 (reconciled)' / 'no asks'
        }
        with mock.patch.object(bc_m, "budget_guard", return_value=fake_model):
            board_chair_text = bc_m.compose(state)["body"]

        # The board chair's OWN authoritative line says zero asks / 'no asks'.
        self.assertEqual(_authoritative_reconciled_count(board_chair_text), 0)
        self.assertIn("no asks", board_chair_text.lower())

        # 3) Feed that REAL persisted board-chair text to the daily digest's deferring parser.
        parsed = dd_m._reconciled_founder_asks(board_chair_text)
        self.assertEqual(
            parsed,
            0,
            "daily_digest parsed a DIFFERENT founder-ask count than the board chair's "
            f"authoritative 'asks: 0 (reconciled)' line (got {parsed}) — the company view "
            "contradicts itself ('no asks' vs 'Shay, N asks').",
        )

    def test_daily_digest_body_does_not_contradict_board_no_asks(self):
        """End-to-end through daily_digest.compose: its FOUNDER ASKS line must agree with the
        board chair's 'no asks'. Today it can print 'FOUNDER ASKS ...: 2' next to the embedded
        board update that says 'no asks' — a self-contradicting single pane."""
        reports = {slug: f"{slug} ran fine." for slug in bc_m.SUBORDINATE_DIGESTS}
        synth = bc_m.synthesize({"reports": reports})
        chair_note = "Recap — decisions: 2, asks: 2 items reviewed; all green."
        fake_model = mock.MagicMock()
        fake_model.invoke.return_value = mock.MagicMock(content=chair_note)
        state = {
            "kpis": {"staffed": 5, "active": 3,
                     "burn": {"salary_tokens": 5000, "spent_tokens": 1000,
                              "remaining_tokens": 4000, "over_budget": False},
                     "revenue": {"ok": False, "note": "x"},
                     "output": {"tests_landed": "reported", "drafts_produced": "reported"}},
            "decisions": synth["decisions"],
            "asks": synth["asks"],
        }
        with mock.patch.object(bc_m, "budget_guard", return_value=fake_model):
            board_chair_text = bc_m.compose(state)["body"]

        def fake_read(slug):
            return board_chair_text if slug == "board-chair" else "(no digest yet)"

        with mock.patch.object(dd_m, "_read_local_digest", side_effect=fake_read), \
                mock.patch.object(dd_m, "budget_guard", side_effect=RuntimeError("no model")):
            body = dd_m.compose({"scoreboard": {"coverage": 0.5}, "revenue": {},
                                 "quality": {}, "ops": {}, "workforce": []})["body"]

        # The embedded board update says 'no asks'; the digest's single reconciled count line
        # must therefore read 0 — not a contradicting positive number.
        self.assertIn("no asks", body.lower())
        self.assertIn(
            "FOUNDER ASKS (single reconciled count): 0",
            body,
            "daily digest reports a non-zero founder-ask count while the embedded board update "
            "says 'no asks' — the single pane contradicts itself.",
        )


class DailyDigestSurvivesBoardChairOffboardTests(unittest.TestCase):
    """ACCEPTANCE (step-3 relocation): the daily digest produces the reconciled founder-ask count
    itself when the board chair's digest is ABSENT — the single pane no longer DEPENDS on the
    board chair agent (so it survives the board chair's eventual offboard).
    """

    def test_self_reconciles_when_board_chair_absent_zero(self):
        """No subordinate flags a Shay item + board-chair absent => self-reconciled count = 0."""
        def fake_read(slug):
            # Every digest is present-but-clean EXCEPT the board chair, which has NOT filed.
            if slug == "board-chair":
                return "(no digest yet)"
            return f"{slug} ran fine; nothing to escalate."

        with mock.patch.object(dd_m, "_read_local_digest", side_effect=fake_read), \
                mock.patch.object(dd_m, "budget_guard", side_effect=RuntimeError("no model")):
            body = dd_m.compose({"scoreboard": {"coverage": 0.5}, "revenue": {},
                                 "quality": {}, "ops": {}, "workforce": []})["body"]

        self.assertIn("FOUNDER ASKS (single reconciled count): 0", body)
        self.assertIn("board-chair digest absent", body.lower())

    def test_self_reconciles_when_board_chair_absent_nonzero(self):
        """A subordinate (cfo) escalates the systemic IDOR + board-chair absent => the daily digest
        STILL reports the single reconciled count (1), computed itself via the shared lanes algo —
        and it matches what the board chair WOULD have reconciled."""
        cfo_text = "The IDOR #1487 deploy is irreversible — capital/legal sign-off needed."

        def fake_read(slug):
            if slug == "board-chair":
                return "(no digest yet)"          # board chair has NOT filed
            if slug == "cfo":
                return cfo_text
            return "(no digest yet)"

        # The authoritative count the board chair WOULD have produced from the same reports.
        bc_reports = {slug: "(no digest yet)" for slug in bc_m.SUBORDINATE_DIGESTS}
        bc_reports["cfo"] = cfo_text
        expected = lanes.founder_ask_count(bc_m.synthesize({"reports": bc_reports})["asks"])
        self.assertEqual(expected, 1)

        with mock.patch.object(dd_m, "_read_local_digest", side_effect=fake_read), \
                mock.patch.object(dd_m, "budget_guard", side_effect=RuntimeError("no model")):
            body = dd_m.compose({"scoreboard": {"coverage": 0.5}, "revenue": {},
                                 "quality": {}, "ops": {}, "workforce": []})["body"]

        self.assertIn(
            f"FOUNDER ASKS (single reconciled count): {expected}", body,
            "with the board chair absent, the daily digest must self-reconcile the SAME count",
        )
        self.assertIn("board-chair digest absent", body.lower())
        self.assertEqual(body.count("FOUNDER ASKS (single reconciled count)"), 1)

    def test_still_defers_to_board_chair_when_present(self):
        """When the board chair HAS filed, the daily digest still DEFERS to its authoritative line
        (the relocation is a FALLBACK, it does not override a present board chair)."""
        bc_text = (
            "# Board → Investor update\n"
            "## Asks for Shay (capital / irreversible / legal only) — asks: 3 (reconciled)\n"
            "- **x** — _escalate_to: shay_"
        )

        def fake_read(slug):
            # Board chair present with 3; a subordinate ALSO escalates — must NOT change the count.
            if slug == "board-chair":
                return bc_text
            if slug == "cfo":
                return "Need capital approval; escalate_to: shay"
            return "(no digest yet)"

        with mock.patch.object(dd_m, "_read_local_digest", side_effect=fake_read), \
                mock.patch.object(dd_m, "budget_guard", side_effect=RuntimeError("no model")):
            body = dd_m.compose({"scoreboard": {"coverage": 0.5}, "revenue": {},
                                 "quality": {}, "ops": {}, "workforce": []})["body"]

        self.assertIn("FOUNDER ASKS (single reconciled count): 3", body)
        self.assertIn("owned by the board chair", body.lower())


class StaffingViewRelocationTests(unittest.TestCase):
    """ACCEPTANCE (step-3 relocation): the staffing/headcount view is a SHARED lanes helper, so the
    daily-digest survivor computes the SAME view the board chair does, without depending on it."""

    def test_staffing_view_shared_helper_counts_active_on_shift(self):
        roster = {"agents": {"a": {}, "b": {}, "ml": {}}}
        # 'a' clocked in, 'b' clocked out, 'ml' is a (skipped) model-dev role.
        head = lanes.staffing_view(
            roster,
            is_clocked_in=lambda n: n == "a",
            is_model_work=lambda n: n == "ml",
        )
        self.assertEqual(head["staffed"], 2)   # ml excluded
        self.assertEqual(head["active"], 1)    # only 'a' on-shift

    def test_board_chair_kpi_staffing_uses_shared_view(self):
        """board_chair._assemble_kpis must produce the same staffed/active the shared helper does."""
        roster = {
            "policy": {"team_token_budget": 1_000_000},
            "org": {},
            "agents": {"a": {"status": "active"}, "b": {"status": "probation"}},
        }
        with mock.patch.object(bc_m, "payroll") as pr, \
                mock.patch.object(bc_m, "check_clocked_in", return_value=True), \
                mock.patch.object(bc_m, "revenuecat") as rc:
            pr.load_roster.return_value = roster
            pr.salary.return_value = 0
            pr.spent.return_value = 0
            rc.metrics_overview.return_value = {"ok": False, "metrics": {}, "error": "x"}
            kpis = bc_m._assemble_kpis({})
        # Both agents are clocked in => both active; neither is a model-dev role => both staffed.
        self.assertEqual(kpis["staffed"], 2)
        self.assertEqual(kpis["active"], 2)


if __name__ == "__main__":
    unittest.main()
