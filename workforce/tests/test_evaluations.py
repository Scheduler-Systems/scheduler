"""Tests for the offline EVALUATION runner (agent_toolkit/evaluations.py).

These prove the runner is a REAL evaluation, not a no-op:
  - it runs a target over the dataset and produces per-example scores + an aggregate;
  - the aggregate is the mean of the scored examples (so a worse target scores lower —
    this is what makes the gate able to detect a regression);
  - the Anthropic-terms guard REFUSES a denylisted target (no target/judge call) and a
    target whose OUTPUT carries model-dev content (fail CLOSED);
  - it is FAIL-SAFE: a target error / judge error degrades to an unscored example, never
    a crash and never a false high score.

NO real network and NO real model: the evaluator (judge) is always injected as a stub,
the target is a plain python callable, and examples are passed in-memory.
Run: .venv/bin/python -m unittest tests.test_evaluations -v
"""
import unittest
from unittest import mock

from agent_toolkit import evaluations as ev


# A judge stub: scores by the presence of an expected keyword in the target output, so a
# "good" target scores high and a "bad" target scores low (a real, discriminating signal).
def _keyword_judge(keyword: str, good=0.95, bad=0.10):
    def judge(run, example):
        text = ""
        out = getattr(run, "outputs", {}) or {}
        text = str(out.get("report") or out.get("summary") or out.get("output") or "")
        score = good if keyword.lower() in text.lower() else bad
        return {"key": "qa_verdict_quality", "score": score, "comment": f"kw={keyword}"}

    return judge


_EXAMPLES = [
    {"inputs": {"target": "scheduler-web", "mode": "observe"}, "outputs": {"expected": "grounded"}},
    {"inputs": {"agent": "cfo", "mode": "answer", "question": "spend?"}, "outputs": {"expected": "grounded"}},
    {"inputs": {"agent": "daily_digest", "mode": "observe"}, "outputs": {"expected": "grounded"}},
]


class RunEvaluationCoreTests(unittest.TestCase):
    def test_produces_per_example_scores_and_aggregate(self):
        def good_target(inputs):
            return {"report": "a grounded concrete observation"}

        rep = ev.run_evaluation(
            good_target, evaluators=[_keyword_judge("grounded")], examples=_EXAMPLES,
        )
        self.assertTrue(rep.ok)
        self.assertEqual(rep.n_total, 3)
        self.assertEqual(rep.n_scored, 3)
        self.assertEqual(len(rep.scores), 3)
        for s in rep.scores:
            self.assertAlmostEqual(s.score, 0.95)
        self.assertAlmostEqual(rep.aggregate, 0.95)

    def test_aggregate_is_mean_so_worse_target_scores_lower(self):
        # This is the property the gate depends on: a degraded target -> lower aggregate.
        def good_target(inputs):
            return {"report": "grounded and specific"}

        def bad_target(inputs):
            return {"report": "vague hand-wave with no specifics"}

        judge = _keyword_judge("grounded")
        good = ev.run_evaluation(good_target, evaluators=[judge], examples=_EXAMPLES)
        bad = ev.run_evaluation(bad_target, evaluators=[judge], examples=_EXAMPLES)
        self.assertGreater(good.aggregate, bad.aggregate)
        self.assertAlmostEqual(good.aggregate, 0.95)
        self.assertAlmostEqual(bad.aggregate, 0.10)

    def test_uses_local_seed_when_no_examples_and_no_client(self):
        from agent_toolkit.eval_dataset import example_count

        rep = ev.run_evaluation(
            lambda i: {"report": "grounded"}, evaluators=[_keyword_judge("grounded")],
        )
        # Defaults to the local seed dataset (no creds needed).
        self.assertEqual(rep.n_total, example_count())
        self.assertGreaterEqual(rep.n_total, 6)  # grew past the original 4 toy cases

    def test_pulls_examples_from_injected_client_when_no_explicit_examples(self):
        # A mock client supplies the dataset; no network.
        class _Ex:
            def __init__(self, inputs, outputs):
                self.inputs = inputs
                self.outputs = outputs

        client = mock.Mock()
        client.list_examples.return_value = [
            _Ex({"target": "scheduler-web"}, {"expected": "grounded"}),
            _Ex({"target": "scheduler-ios"}, {"expected": "grounded"}),
        ]
        rep = ev.run_evaluation(
            lambda i: {"report": "grounded"}, evaluators=[_keyword_judge("grounded")],
            client=client,
        )
        self.assertEqual(rep.n_total, 2)
        client.list_examples.assert_called_once()


class GuardTests(unittest.TestCase):
    def test_refuses_denylisted_target_name_no_calls(self):
        target = mock.Mock(side_effect=AssertionError("target must NOT run when refused"))
        judge = mock.Mock(side_effect=AssertionError("judge must NOT run when refused"))
        rep = ev.run_evaluation(
            target, target_name="gal-run/gal-model", evaluators=[judge], examples=_EXAMPLES,
        )
        self.assertTrue(rep.refused)
        self.assertIsNone(rep.aggregate)
        target.assert_not_called()
        judge.assert_not_called()

    def test_refuses_when_target_output_carries_model_dev_content(self):
        # A compromised/misbehaving prompt emits model-dev content in its OUTPUT; the judge
        # must NEVER see it (fail CLOSED) — the example is unscored, aggregate stays honest.
        def evil_target(inputs):
            return {"report": {"task": "fine-tune the gal-model classifier and distill it"}}

        judge = mock.Mock(side_effect=AssertionError("judge must NOT run on model-dev output"))
        rep = ev.run_evaluation(
            evil_target, target_name="scheduler-qa-eval:candidate",
            evaluators=[judge], examples=_EXAMPLES[:1],
        )
        judge.assert_not_called()
        self.assertEqual(rep.n_scored, 0)
        self.assertIsNone(rep.aggregate)
        self.assertIn("refused", (rep.scores[0].error or ""))

    def test_refuses_when_example_input_carries_model_dev_content(self):
        bad_examples = [{"inputs": {"target": "gal-model", "task": "distill"}, "outputs": {}}]
        judge = mock.Mock(side_effect=AssertionError("judge must NOT run"))
        target = mock.Mock(side_effect=AssertionError("target must NOT run on model-dev input"))
        rep = ev.run_evaluation(
            target, target_name="scheduler-qa-eval:candidate",
            evaluators=[judge], examples=bad_examples,
        )
        target.assert_not_called()
        judge.assert_not_called()
        self.assertEqual(rep.n_scored, 0)
        self.assertIn("refused", (rep.scores[0].error or ""))


class FailSafeTests(unittest.TestCase):
    def test_target_error_is_unscored_not_crash_not_false_pass(self):
        def boom_target(inputs):
            raise RuntimeError("target-token-leak")

        rep = ev.run_evaluation(
            boom_target, evaluators=[_keyword_judge("grounded")], examples=_EXAMPLES,
        )
        # All examples errored -> no aggregate (gate will fail SAFE), never a crash.
        self.assertEqual(rep.n_scored, 0)
        self.assertIsNone(rep.aggregate)
        self.assertFalse(rep.ok)
        for s in rep.scores:
            self.assertEqual(s.error, "RuntimeError")  # type-only, no secret
        self.assertNotIn("token-leak", str(rep.as_dict()))

    def test_judge_error_degrades_to_unscored_example(self):
        def good_target(inputs):
            return {"report": "grounded"}

        def boom_judge(run, example):
            raise ValueError("judge boom")

        rep = ev.run_evaluation(good_target, evaluators=[boom_judge], examples=_EXAMPLES)
        self.assertEqual(rep.n_scored, 0)
        self.assertIsNone(rep.aggregate)
        for s in rep.scores:
            self.assertEqual(s.error, "ValueError")

    def test_no_evaluator_available_is_error_not_crash(self):
        rep = ev.run_evaluation(
            lambda i: {"report": "x"}, evaluators=[], examples=_EXAMPLES,
        )
        self.assertIsNone(rep.aggregate)
        self.assertEqual(rep.error, "no evaluator available")

    def test_empty_dataset_is_error_not_crash(self):
        rep = ev.run_evaluation(
            lambda i: {"report": "x"}, evaluators=[_keyword_judge("grounded")], examples=[],
        )
        self.assertIsNone(rep.aggregate)
        self.assertEqual(rep.error, "no examples to evaluate")

    def test_accepts_run_eval_style_usefulness_keyed_result(self):
        # run_eval's judge re-keys overall to "usefulness"; the runner accepts it as score.
        def judge(run, example):
            return {"key": "usefulness", "usefulness": 0.7, "comment": "ok"}

        rep = ev.run_evaluation(
            lambda i: {"report": "x"}, evaluators=[judge], examples=_EXAMPLES,
            score_key="usefulness",
        )
        self.assertAlmostEqual(rep.aggregate, 0.7)


class ReportOnlyTests(unittest.TestCase):
    def test_runner_does_not_upload_by_default(self):
        client = mock.Mock()
        ev.run_evaluation(
            lambda i: {"report": "grounded"}, evaluators=[_keyword_judge("grounded")],
            examples=_EXAMPLES, client=client,
        )
        # upload defaults False -> client.evaluate is NEVER called (no experiment write).
        client.evaluate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
