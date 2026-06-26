"""FAILING test — the eval gate green-lights a redeploy on (almost) NO data.

Context (Anthropic-terms / fail-safe audit): the gate is supposed to degrade SAFELY —
"a judge error / missing creds / empty dataset must never green-light a deploy on no data;
it should refuse/block or report unavailable." The EMPTY dataset case is handled (aggregate
is None -> EXIT_UNSCORED). But the NEAR-EMPTY case is NOT: the aggregate is computed only
over the examples that actually produced a numeric score, with NO minimum-coverage floor.

So if the candidate target crashes (broken graph, flaky creds, network) on 9 of 10 examples
and the 1 that slips through scores well, the runner reports aggregate=0.95, n_scored=1,
n_total=10, ok=True — and ``decide(0.95, baseline=0.80)`` returns EXIT_PASS. The gate
green-lights a redeploy on effectively one data point. Same hole via the judge: if the judge
errors / returns no numeric score on all but one example, that one example sets the aggregate.

These tests assert the SAFE behavior (BLOCK / not-ok when coverage is too thin). They FAIL
today, pinning the hole. A fix: enforce a minimum scored-coverage in run_evaluation (refuse
when n_scored is too small a fraction of n_total) and/or have decide() treat a low-coverage
report as unscored (EXIT_UNSCORED), not PASS.

Run: .venv/bin/python -m unittest tests.test_eval_gate_coverage_floor -v
"""
import os
import sys
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPTS = os.path.join(_REPO_ROOT, "scripts")
for p in (_REPO_ROOT, _SCRIPTS):
    if p not in sys.path:
        sys.path.insert(0, p)

import eval_gate as g  # noqa: E402
from agent_toolkit.evaluations import run_evaluation  # noqa: E402


def _examples(n):
    return [{"inputs": {"target": f"t{i}", "mode": "observe"}, "outputs": {}} for i in range(n)]


class CoverageFloorTests(unittest.TestCase):
    def test_target_failing_on_9_of_10_must_not_pass(self):
        """Target crashes on 9/10 examples; the 1 survivor scores 0.95.

        Today: aggregate=0.95 over a SINGLE scored example, ok=True, gate -> PASS.
        Safe behavior: a report scored on ~10% of the dataset must NOT be treated as a
        valid pass — it green-lights a redeploy on essentially no data.
        """
        state = {"n": 0}

        def flaky_target(inputs):
            state["n"] += 1
            if state["n"] == 1:
                return {"report": "grounded specific finding"}
            raise RuntimeError("invoke failed (creds/network)")

        def judge(run, example):
            return {"key": "qa_verdict_quality", "score": 0.95}

        rep = run_evaluation(
            flaky_target, target_name="cand", evaluators=[judge], examples=_examples(10)
        )
        self.assertEqual(rep.n_total, 10)
        self.assertEqual(rep.n_scored, 1)

        # A gate that degrades safely must NOT report this run as ok / must NOT PASS the
        # candidate's lone-example aggregate against a healthy baseline.
        self.assertFalse(
            rep.ok,
            "FAIL-SAFE HOLE: report.ok is True with only 1/10 examples scored — a single "
            "data point is treated as a valid evaluation.",
        )
        code, reason = g.decide(rep.aggregate, 0.80, 0.05)
        self.assertNotEqual(
            code, g.EXIT_PASS,
            f"FAIL-SAFE HOLE: gate PASSED a redeploy on 1/10 scored examples "
            f"(aggregate={rep.aggregate}). reason={reason}",
        )

    def test_judge_failing_on_all_but_one_must_not_pass(self):
        """Judge returns a usable score on only 1 of 8 examples (rest: no numeric score).

        Mirrors a flaky/rate-limited judge or malformed judge output. Those examples are
        silently dropped from the denominator; the lone survivor sets the aggregate.
        """
        def good_target(inputs):
            return {"report": "grounded specific finding"}

        state = {"n": 0}

        def flaky_judge(run, example):
            state["n"] += 1
            if state["n"] == 1:
                return {"key": "qa_verdict_quality", "score": 0.97}
            return {"key": "qa_verdict_quality"}  # no score -> dropped from aggregate

        rep = run_evaluation(
            good_target, target_name="cand", evaluators=[flaky_judge], examples=_examples(8)
        )
        self.assertEqual(rep.n_total, 8)
        self.assertEqual(rep.n_scored, 1)
        self.assertFalse(
            rep.ok,
            "FAIL-SAFE HOLE: report.ok is True with only 1/8 examples scored (judge "
            "produced a usable score on a single example).",
        )
        code, _ = g.decide(rep.aggregate, 0.80, 0.05)
        self.assertNotEqual(
            code, g.EXIT_PASS,
            "FAIL-SAFE HOLE: gate PASSED a redeploy when the judge scored only 1/8 examples.",
        )


if __name__ == "__main__":
    unittest.main()
