"""Tests for the pre-redeploy GATE (scripts/eval_gate.py).

These prove the gate actually BLOCKS a regression and is NOT a no-op:
  - decide(): the pure decision — PASS on hold/improve, BLOCK (exit 1) on regression beyond
    threshold, BLOCK (exit 2) fail-safe when the candidate could not be scored, PASS when no
    baseline exists.
  - end-to-end main(): a candidate that scores BELOW baseline-threshold exits NON-ZERO; a
    candidate that holds/improves exits 0 (proves it discriminates).
  - the Anthropic-terms guard: a denylisted candidate is REFUSED -> exit 3.
  - fail-safe: a judge/target error degrades the gate to BLOCK (exit 2), it does NOT falsely
    PASS (a gate that degrades OPEN is worse than no gate).

NO real network / NO real model: the candidate target is a stub via a patched
``run_evaluation``, or a real in-memory run with an injected judge stub and no client.
Run: .venv/bin/python -m unittest tests.test_eval_gate -v
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


def _report(aggregate, n=3, refused=False, error=None):
    scores = [ExampleScore(index=i, inputs={}, reference=None, output={}, score=(aggregate if aggregate is not None else None)) for i in range(n)]
    return EvalReport(
        target_name="candidate", dataset_name="scheduler-qa-eval", scores=scores,
        aggregate=aggregate, n_scored=(n if aggregate is not None else 0), n_total=n,
        refused=refused, error=error,
    )


# ---------------------------------------------------------------------------
# decide() — the pure gate decision
# ---------------------------------------------------------------------------
class DecideTests(unittest.TestCase):
    def test_pass_when_candidate_holds(self):
        code, _ = g.decide(0.78, 0.80, 0.05)
        self.assertEqual(code, g.EXIT_PASS)

    def test_pass_when_candidate_improves(self):
        code, _ = g.decide(0.92, 0.80, 0.05)
        self.assertEqual(code, g.EXIT_PASS)

    def test_block_when_candidate_regresses_beyond_threshold(self):
        code, reason = g.decide(0.70, 0.80, 0.05)
        self.assertEqual(code, g.EXIT_REGRESSED)
        self.assertIn("REGRESSION", reason)

    def test_threshold_is_inclusive_boundary(self):
        # A regression of EXACTLY the threshold is allowed (PASS), even with float error.
        code, _ = g.decide(0.75, 0.80, 0.05)
        self.assertEqual(code, g.EXIT_PASS)
        # Just beyond the threshold -> BLOCK.
        code2, _ = g.decide(0.749, 0.80, 0.05)
        self.assertEqual(code2, g.EXIT_REGRESSED)

    def test_block_failsafe_when_candidate_unscored(self):
        # No aggregate (judge/target/creds error) MUST block, not pass.
        code, reason = g.decide(None, 0.80, 0.05)
        self.assertEqual(code, g.EXIT_UNSCORED)
        self.assertIn("BLOCKING fail-safe", reason)

    def test_pass_when_no_baseline(self):
        code, reason = g.decide(0.60, None, 0.05)
        self.assertEqual(code, g.EXIT_PASS)
        self.assertIn("no baseline", reason)


# ---------------------------------------------------------------------------
# Baseline persistence (a local score record — never a deploy)
# ---------------------------------------------------------------------------
class BaselineIOTests(unittest.TestCase):
    def test_save_then_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "baseline.json")
            rep = _report(0.83)
            self.assertTrue(g.save_baseline(rep, path))
            loaded = g.load_baseline(path)
            self.assertIsNotNone(loaded)
            self.assertAlmostEqual(loaded["aggregate"], 0.83)

    def test_load_missing_returns_none(self):
        self.assertIsNone(g.load_baseline("/nonexistent/path/baseline.json"))


# ---------------------------------------------------------------------------
# main() end-to-end — proves the gate DISCRIMINATES (not a no-op)
# ---------------------------------------------------------------------------
class GateEndToEndTests(unittest.TestCase):
    def setUp(self):
        # Never resolve a real client in these tests.
        self._patches = [
            mock.patch.object(g, "get_client", return_value=None),
        ]
        for p in self._patches:
            p.start()
        self._tmp = tempfile.TemporaryDirectory()
        self.baseline_path = os.path.join(self._tmp.name, "baseline.json")

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._tmp.cleanup()

    def _write_baseline(self, aggregate):
        g.save_baseline(_report(aggregate), self.baseline_path)

    def _run_with_candidate_report(self, candidate_report, argv):
        # Patch the module-level run_evaluation the gate calls, to return our candidate
        # report whenever a candidate target is scored — no model, no network.
        with mock.patch.object(g, "run_evaluation", return_value=candidate_report):
            return g.main(argv)

    def test_blocks_on_regression_below_baseline_minus_threshold(self):
        self._write_baseline(0.85)
        # Candidate scores 0.60 -> regression of 0.25, well beyond 0.05 -> BLOCK (exit 1).
        candidate = _report(0.60)
        code = self._run_with_candidate_report(
            candidate,
            ["--candidate-graph", "graphs.exec.cfo_deepagents:graph",
             "--baseline-path", self.baseline_path, "--threshold", "0.05"],
        )
        self.assertEqual(code, g.EXIT_REGRESSED)

    def test_passes_when_candidate_holds_or_improves(self):
        self._write_baseline(0.85)
        # Candidate 0.88 -> improvement -> PASS (exit 0). Proves it is NOT always-block.
        candidate = _report(0.88)
        code = self._run_with_candidate_report(
            candidate,
            ["--candidate-graph", "graphs.exec.cfo_deepagents:graph",
             "--baseline-path", self.baseline_path, "--threshold", "0.05"],
        )
        self.assertEqual(code, g.EXIT_PASS)

    def test_passes_within_threshold(self):
        self._write_baseline(0.85)
        candidate = _report(0.82)  # -0.03, within 0.05 -> PASS
        code = self._run_with_candidate_report(
            candidate,
            ["--candidate-graph", "graphs.exec.cfo_deepagents:graph",
             "--baseline-path", self.baseline_path, "--threshold", "0.05"],
        )
        self.assertEqual(code, g.EXIT_PASS)

    def test_failsafe_blocks_when_candidate_unscored(self):
        self._write_baseline(0.85)
        # Judge/target error -> aggregate None -> gate BLOCKS (exit 2), NOT a false pass.
        candidate = _report(None)
        code = self._run_with_candidate_report(
            candidate,
            ["--candidate-graph", "graphs.exec.cfo_deepagents:graph",
             "--baseline-path", self.baseline_path],
        )
        self.assertEqual(code, g.EXIT_UNSCORED)

    def test_refused_candidate_blocks_with_exit_3(self):
        self._write_baseline(0.85)
        candidate = _report(None, refused=True, error="refused (model-dev denylist): ModelWorkBlocked")
        code = self._run_with_candidate_report(
            candidate,
            ["--candidate-graph", "gal-run/gal-model:graph",
             "--baseline-path", self.baseline_path],
        )
        self.assertEqual(code, g.EXIT_REFUSED)

    def test_no_candidate_given_blocks(self):
        code = g.main(["--baseline-path", self.baseline_path])
        self.assertEqual(code, g.EXIT_UNSCORED)

    def test_no_baseline_first_run_passes(self):
        # No baseline file written -> first run PASSES (nothing to regress against).
        candidate = _report(0.70)
        code = self._run_with_candidate_report(
            candidate,
            ["--candidate-graph", "graphs.exec.cfo_deepagents:graph",
             "--baseline-path", self.baseline_path],
        )
        self.assertEqual(code, g.EXIT_PASS)

    def test_update_baseline_writes_record_but_does_not_deploy(self):
        candidate = _report(0.77)
        code = self._run_with_candidate_report(
            candidate,
            ["--candidate-graph", "graphs.exec.cfo_deepagents:graph",
             "--baseline-path", self.baseline_path, "--update-baseline"],
        )
        self.assertEqual(code, g.EXIT_PASS)  # no prior baseline
        # The baseline file now exists with the candidate's score (a record only).
        loaded = g.load_baseline(self.baseline_path)
        self.assertIsNotNone(loaded)
        self.assertAlmostEqual(loaded["aggregate"], 0.77)


# ---------------------------------------------------------------------------
# End-to-end WITHOUT patching run_evaluation: a real offline eval with a judge stub,
# proving candidate-vs-baseline GRAPH targets discriminate through the real runner.
# ---------------------------------------------------------------------------
class GateRealRunnerTests(unittest.TestCase):
    def setUp(self):
        self._p = mock.patch.object(g, "get_client", return_value=None)
        self._p.start()
        self._tmp = tempfile.TemporaryDirectory()
        self.baseline_path = os.path.join(self._tmp.name, "baseline.json")

    def tearDown(self):
        self._p.stop()
        self._tmp.cleanup()

    def test_candidate_and_baseline_graphs_score_through_real_runner(self):
        # Two fake graph targets: a GOOD candidate (emits "grounded") and a BAD baseline.
        good_graph = mock.Mock()
        good_graph.invoke.return_value = {"report": "grounded specific observation"}
        bad_graph = mock.Mock()
        bad_graph.invoke.return_value = {"report": "vague"}

        def fake_resolve(path):
            return good_graph if "good" in path else bad_graph

        def judge(run, example):
            text = str((getattr(run, "outputs", {}) or {}).get("report", ""))
            return {"key": "qa_verdict_quality", "score": 0.95 if "grounded" in text else 0.10}

        # Force the real runner to use our judge + our local 2-example set, no network.
        examples = [
            {"inputs": {"target": "scheduler-web", "mode": "observe"}, "outputs": {}},
            {"inputs": {"target": "scheduler-ios", "mode": "observe"}, "outputs": {}},
        ]
        orig_run = g.run_evaluation

        def patched_run(target, **kw):
            kw.setdefault("evaluators", [judge])
            kw["examples"] = examples
            return orig_run(target, **kw)

        with mock.patch.object(g, "_resolve_graph", side_effect=fake_resolve), \
             mock.patch.object(g, "run_evaluation", side_effect=patched_run):
            # Candidate = the GOOD graph, baseline = the BAD graph -> candidate IMPROVES -> PASS.
            code = g.main([
                "--candidate-graph", "graphs.fake.good:graph",
                "--baseline-graph", "graphs.fake.bad:graph",
                "--baseline-path", self.baseline_path,
            ])
        self.assertEqual(code, g.EXIT_PASS)

    def test_candidate_worse_than_baseline_graph_blocks_through_real_runner(self):
        good_graph = mock.Mock()
        good_graph.invoke.return_value = {"report": "grounded specific observation"}
        bad_graph = mock.Mock()
        bad_graph.invoke.return_value = {"report": "vague"}

        def fake_resolve(path):
            return bad_graph if "bad" in path else good_graph

        def judge(run, example):
            text = str((getattr(run, "outputs", {}) or {}).get("report", ""))
            return {"key": "qa_verdict_quality", "score": 0.95 if "grounded" in text else 0.10}

        examples = [
            {"inputs": {"target": "scheduler-web", "mode": "observe"}, "outputs": {}},
            {"inputs": {"target": "scheduler-ios", "mode": "observe"}, "outputs": {}},
        ]
        orig_run = g.run_evaluation

        def patched_run(target, **kw):
            kw.setdefault("evaluators", [judge])
            kw["examples"] = examples
            return orig_run(target, **kw)

        with mock.patch.object(g, "_resolve_graph", side_effect=fake_resolve), \
             mock.patch.object(g, "run_evaluation", side_effect=patched_run):
            # Candidate = the BAD graph, baseline = the GOOD graph -> REGRESSION -> BLOCK.
            code = g.main([
                "--candidate-graph", "graphs.fake.bad:graph",
                "--baseline-graph", "graphs.fake.good:graph",
                "--baseline-path", self.baseline_path,
            ])
        self.assertEqual(code, g.EXIT_REGRESSED)


if __name__ == "__main__":
    unittest.main()
