"""FALSE-PASS proof for the pre-redeploy GATE (scripts/eval_gate.py).

These tests demonstrate a path where a CATASTROPHIC regression ships GREEN, because the
aggregate is an average over ONLY the examples that produced a numeric score
(``agent_toolkit.evaluations.run_evaluation`` -> ``sum(collected)/len(collected)`` with
unscored examples DROPPED from both numerator and denominator).

A redeploy that breaks the agent on most of the dataset (target raises, or the judge
cannot score the broken/empty output -> score None) has those examples silently dropped.
The aggregate becomes the average of the FEW survivors, which can be >= baseline -> PASS.
``decide()`` only fails safe when the aggregate is None (i.e. ZERO examples scored); a
single surviving example is enough to defeat the fail-safe.

There is NO minimum-coverage guard: ``decide()`` never sees ``n_scored``/``n_total`` and
never checks that the candidate scored the SAME examples the baseline did.

Run: .venv/bin/python -m unittest tests.test_eval_gate_masking -v

These tests are EXPECTED TO FAIL against the current code — each asserts the gate SHOULD
block the regression. They will pass once the gate requires score coverage (e.g. block
when n_scored < n_total, or require the candidate to cover the baseline's examples).
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPTS = os.path.join(_REPO_ROOT, "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import eval_gate as g  # noqa: E402
from agent_toolkit.evaluations import EvalReport, ExampleScore  # noqa: E402


def _baseline_report(aggregate, n=5):
    scores = [ExampleScore(index=i, inputs={}, reference=None, output={}, score=aggregate) for i in range(n)]
    return EvalReport(
        target_name="deployed", dataset_name="scheduler-qa-eval", scores=scores,
        aggregate=aggregate, n_scored=n, n_total=n,
    )


# A 5-example local set; only the "lucky" input survives the regression.
_EXAMPLES = [
    {"inputs": {"target": "scheduler-web", "mode": "observe"}, "outputs": {}},
    {"inputs": {"target": "scheduler-ios", "mode": "observe"}, "outputs": {}},
    {"inputs": {"target": "scheduler-android", "mode": "observe"}, "outputs": {}},
    {"inputs": {"target": "scheduler-api", "mode": "observe"}, "outputs": {}},
    {"inputs": {"target": "scheduler-lucky", "mode": "observe"}, "outputs": {}},
]


def _grounded_judge(run, example):
    """Numeric score only for real content; None for empty/un-judgeable output."""
    text = str((getattr(run, "outputs", {}) or {}).get("report", "")).strip()
    if not text:
        return {"key": "qa_verdict_quality", "score": None, "comment": "could not judge: empty output"}
    return {"key": "qa_verdict_quality", "score": 0.95 if "grounded" in text else 0.10}


class MaskingFalsePassTests(unittest.TestCase):
    def setUp(self):
        self._patches = [mock.patch.object(g, "get_client", return_value=None)]
        for p in self._patches:
            p.start()
        self._tmp = tempfile.TemporaryDirectory()
        self.baseline_path = os.path.join(self._tmp.name, "baseline.json")
        # Deployed agent scored 0.85 across all 5 examples.
        g.save_baseline(_baseline_report(0.85), self.baseline_path)

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._tmp.cleanup()

    def _run_against_broken_graph(self, broken_invoke):
        broken_graph = mock.Mock()
        broken_graph.invoke.side_effect = broken_invoke
        orig_run = g.run_evaluation

        def patched_run(target, **kw):
            kw.setdefault("evaluators", [_grounded_judge])
            kw["examples"] = _EXAMPLES
            return orig_run(target, **kw)

        with mock.patch.object(g, "_resolve_graph", side_effect=lambda p: broken_graph), \
             mock.patch.object(g, "run_evaluation", side_effect=patched_run):
            return g.main([
                "--candidate-graph", "graphs.exec.broken_redeploy:graph",
                "--baseline-path", self.baseline_path,
                "--threshold", "0.05",
            ])

    def test_empty_output_on_most_examples_must_not_pass(self):
        """Candidate emits empty (un-judgeable) output on 4/5 inputs -> those drop to None,
        aggregate is the average of the 1 survivor (0.95) > baseline 0.85 -> currently PASS.
        A real gate MUST block: the agent is broken on 80% of the dataset."""
        def broken_invoke(payload):
            if "lucky" in str(payload):
                return {"report": "grounded specific observation"}
            return {"report": ""}  # broken-prompt output: empty / un-judgeable
        code = self._run_against_broken_graph(broken_invoke)
        self.assertNotEqual(
            code, g.EXIT_PASS,
            "FALSE PASS: candidate broke on 4/5 examples (scored 1/5) yet the gate let the "
            "redeploy proceed — the aggregate averaged only the surviving example.",
        )

    def test_target_crashes_on_most_examples_must_not_pass(self):
        """Candidate graph RAISES on 4/5 inputs (caught in _graph_target -> error output ->
        but here we surface as score None via the judge). The crashed examples are dropped;
        the 1 survivor (0.95) > baseline -> currently PASS. A real gate MUST block."""
        def broken_invoke(payload):
            if "lucky" in str(payload):
                return {"report": "grounded specific observation"}
            raise RuntimeError("KABOOM: prompt regression broke the agent on this input")
        # _graph_target converts the raise to {"error": ...}; that output has no "report",
        # so the judge returns score None for it -> dropped. Same masking, crash flavour.
        def crash_judge(run, example):
            out = getattr(run, "outputs", {}) or {}
            text = str(out.get("report") or "").strip()
            if not text:  # error output (or empty) -> un-judgeable -> None
                return {"key": "qa_verdict_quality", "score": None, "comment": "could not judge"}
            return {"key": "qa_verdict_quality", "score": 0.95 if "grounded" in text else 0.10}
        broken_graph = mock.Mock()
        broken_graph.invoke.side_effect = broken_invoke
        orig_run = g.run_evaluation

        def patched_run(target, **kw):
            kw.setdefault("evaluators", [crash_judge])
            kw["examples"] = _EXAMPLES
            return orig_run(target, **kw)

        with mock.patch.object(g, "_resolve_graph", side_effect=lambda p: broken_graph), \
             mock.patch.object(g, "run_evaluation", side_effect=patched_run):
            code = g.main([
                "--candidate-graph", "graphs.exec.broken_redeploy:graph",
                "--baseline-path", self.baseline_path,
                "--threshold", "0.05",
            ])
        self.assertNotEqual(
            code, g.EXIT_PASS,
            "FALSE PASS: candidate crashed on 4/5 examples yet the gate let the redeploy "
            "proceed — crashed examples were dropped from the aggregate.",
        )


if __name__ == "__main__":
    unittest.main()
