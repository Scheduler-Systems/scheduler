"""Tests for the ACTIVE LangSmith learning loop (agent_toolkit/learning_loop.py).

These prove the loop is no longer inert and stays SAFE:
  - record_feedback WRITES a signal (the ledger that was empty) and is FAIL-SAFE
    (mock raising -> status dict, never an exception; no creds -> skipped).
  - get_prompt RETURNS the pulled Hub value, and the FALLBACK when the client raises /
    has no creds (so a graph that adopts the governed prompt NEVER breaks).
  - judge_live_run SCORES one production run and WRITES feedback; the Anthropic-terms
    guard still fails closed on the model-development denylist.
  - Everything is report-only: no agent behavior is mutated.

The LangSmith client is always INJECTED (a mock) or absent — NO real network.
Run: .venv/bin/python -m unittest tests.test_learning_loop -v
"""
import unittest
from unittest import mock

from agent_toolkit import learning_loop as ll


class _FakeFeedback:
    def __init__(self, fid="fb-123"):
        self.id = fid


def _ok_client():
    """A mock client whose create_feedback succeeds and records the call args."""
    c = mock.Mock()
    c.create_feedback.return_value = _FakeFeedback()
    return c


# ---------------------------------------------------------------------------
# 1) record_feedback — the signal ledger (was empty) + fail-safe
# ---------------------------------------------------------------------------
class RecordFeedbackTests(unittest.TestCase):
    def test_writes_feedback_and_returns_recorded_status(self):
        c = _ok_client()
        out = ll.record_feedback(
            "run-abc", "qa_verdict_quality", 0.9,
            comment="looks correct", source_agent="cfo", client=c,
        )
        self.assertTrue(out["ok"])
        self.assertEqual(out["status"], "recorded")
        self.assertEqual(out["feedback_id"], "fb-123")
        # The signal actually hit the (mock) ledger with the right key/score/provenance.
        c.create_feedback.assert_called_once()
        args, kwargs = c.create_feedback.call_args
        self.assertEqual(args[0], "run-abc")
        self.assertEqual(args[1], "qa_verdict_quality")
        self.assertEqual(kwargs["score"], 0.9)
        self.assertEqual(kwargs["comment"], "looks correct")
        self.assertEqual(kwargs["source_info"], {"source_agent": "cfo"})

    def test_fail_safe_when_client_raises(self):
        c = mock.Mock()
        c.create_feedback.side_effect = RuntimeError("boom-token-leak")
        out = ll.record_feedback("run-abc", "k", 1.0, client=c)
        # Never raises; returns an error status; the error string is TYPE-ONLY (no secret).
        self.assertFalse(out["ok"])
        self.assertEqual(out["status"], "error")
        self.assertEqual(out["error"], "RuntimeError")
        self.assertNotIn("boom-token-leak", str(out))

    def test_skipped_when_no_client_and_no_creds(self):
        # No injected client AND get_client() yields None (no creds) -> skipped, no raise.
        with mock.patch.object(ll, "_resolve_client", return_value=None):
            out = ll.record_feedback("run-abc", "k", 1.0)
        self.assertFalse(out["ok"])
        self.assertEqual(out["status"], "skipped")

    def test_skipped_when_no_run_id(self):
        c = _ok_client()
        out = ll.record_feedback(None, "k", 1.0, client=c)
        self.assertEqual(out["status"], "skipped")
        c.create_feedback.assert_not_called()

    def test_bool_and_unparseable_scores_are_coerced(self):
        c = _ok_client()
        ll.record_feedback("r", "k", True, client=c)
        self.assertIs(c.create_feedback.call_args.kwargs["score"], True)
        c.reset_mock()
        c.create_feedback.return_value = _FakeFeedback()
        ll.record_feedback("r", "k", "not-a-number", client=c)
        self.assertIsNone(c.create_feedback.call_args.kwargs["score"])


# ---------------------------------------------------------------------------
# 2) get_prompt — pull pinned Hub version; fall back so a graph never breaks
# ---------------------------------------------------------------------------
def _chat_prompt(system_text):
    from langchain_core.prompts import ChatPromptTemplate

    return ChatPromptTemplate([("system", system_text), ("user", "{input}")])


class GetPromptTests(unittest.TestCase):
    def test_returns_pulled_system_text(self):
        c = mock.Mock()
        c.pull_prompt.return_value = _chat_prompt("HUB GOVERNED PROMPT")
        out = ll.get_prompt("scheduler-qa-cfo", fallback="EMBEDDED", client=c)
        self.assertEqual(out, "HUB GOVERNED PROMPT")
        c.pull_prompt.assert_called_once_with("scheduler-qa-cfo")

    def test_returns_fallback_when_client_raises(self):
        c = mock.Mock()
        c.pull_prompt.side_effect = RuntimeError("not found")
        out = ll.get_prompt("scheduler-qa-cfo", fallback="EMBEDDED", client=c)
        self.assertEqual(out, "EMBEDDED")  # graph NEVER breaks

    def test_returns_fallback_when_no_creds(self):
        with mock.patch.object(ll, "_resolve_client", return_value=None):
            out = ll.get_prompt("scheduler-qa-cfo", fallback="EMBEDDED")
        self.assertEqual(out, "EMBEDDED")

    def test_returns_fallback_on_unparseable_object(self):
        c = mock.Mock()
        c.pull_prompt.return_value = object()  # no .messages / .template
        out = ll.get_prompt("x", fallback="EMBEDDED", client=c)
        self.assertEqual(out, "EMBEDDED")

    def test_accepts_raw_string_prompt(self):
        c = mock.Mock()
        c.pull_prompt.return_value = "RAW STRING PROMPT"
        out = ll.get_prompt("x", fallback="EMBEDDED", client=c)
        self.assertEqual(out, "RAW STRING PROMPT")

    def test_returns_fallback_when_pulled_prompt_has_no_system_message(self):
        """get_prompt must degrade to the embedded fallback UNCHANGED when the pulled Hub
        prompt has NO system role — adoption of the governed prompt must be safe + reversible.

        The Prompt Hub is a human-editable surface (the whole reason get_prompt exists is to
        adopt human-iterated versions). If the ``scheduler-qa-cfo`` version is ever pushed or
        edited as a user-only ChatPromptTemplate (no system message), ``_extract_system_text``
        currently returns the FIRST non-system template it finds (``'{input}'``) as a
        last-resort, so the CFO graph boots with ``'{input}'`` as its entire system prompt
        instead of falling back to the baked-in ``_SYSTEM``. The docstring promises the
        fallback is returned on ANY 'unexpected object shape' — a no-system ChatPromptTemplate
        is exactly that. This guards against a silent, non-reversible corrupted adoption.
        """
        from langchain_core.prompts import ChatPromptTemplate

        c = mock.Mock()
        # A ChatPromptTemplate with no system role at all (user-only).
        c.pull_prompt.return_value = ChatPromptTemplate(
            [("user", "{input}"), ("ai", "ok")]
        )
        out = ll.get_prompt("scheduler-qa-cfo", fallback="EMBEDDED", client=c)
        # Must be the embedded fallback — NOT the user-message template '{input}'.
        self.assertEqual(out, "EMBEDDED")

    def test_fallback_when_pulled_object_has_noniterable_messages(self):
        """get_prompt MUST NOT raise (its #1 contract). SDK/version drift can yield a pulled
        prompt whose ``.messages`` is truthy but not iterable; ``for msg in messages`` then
        raises TypeError. Because get_prompt runs at graph BUILD/IMPORT time, an escaping
        exception fails the whole deployment import — degrade to fallback instead.
        """
        class WeirdPrompt:
            messages = 7  # truthy but not iterable

        c = mock.Mock()
        c.pull_prompt.return_value = WeirdPrompt()
        out = ll.get_prompt("scheduler-qa-cfo", fallback="EMBEDDED", client=c)
        self.assertEqual(out, "EMBEDDED")  # MUST degrade, MUST NOT raise

    def test_fallback_when_extraction_raises_midway(self):
        """A pulled object whose ``.messages`` iteration has a side effect that raises
        (manifest-deserialization quirk under SDK drift) must still degrade to fallback,
        not propagate out of get_prompt.
        """
        class Exploder:
            @property
            def messages(self):
                return self

            def __iter__(self):
                raise RuntimeError("manifest deserialization side-effect")

        c = mock.Mock()
        c.pull_prompt.return_value = Exploder()
        out = ll.get_prompt("scheduler-qa-cfo", fallback="EMBEDDED", client=c)
        self.assertEqual(out, "EMBEDDED")


# ---------------------------------------------------------------------------
# 3) judge_live_run — score one production run, write feedback (online-eval code side)
# ---------------------------------------------------------------------------
class JudgeLiveRunTests(unittest.TestCase):
    def test_scores_run_and_writes_feedback(self):
        c = _ok_client()

        def fake_evaluator(run, example):
            # Sees the live run's outputs/inputs.
            self.assertEqual(run.outputs.get("report"), "all green")
            return {"key": "qa_verdict_quality", "score": 0.8, "comment": "useful"}

        out = ll.judge_live_run(
            "run-xyz",
            {"target": "Scheduler-Systems/scheduler-web"},
            {"report": "all green"},
            evaluator=fake_evaluator,
            client=c,
        )
        self.assertTrue(out["ok"])
        self.assertEqual(out["status"], "judged")
        self.assertEqual(out["judge"]["score"], 0.8)
        self.assertTrue(out["feedback"]["ok"])
        # The judge score was written back as feedback on the run.
        c.create_feedback.assert_called_once()
        args, kwargs = c.create_feedback.call_args
        self.assertEqual(args[0], "run-xyz")
        self.assertEqual(args[1], "qa_verdict_quality")
        self.assertEqual(kwargs["score"], 0.8)
        self.assertEqual(kwargs["source_info"], {"source_agent": "learning_loop:judge"})

    def test_refuses_model_dev_run_fail_closed(self):
        c = _ok_client()
        out = ll.judge_live_run(
            "run-xyz",
            {"target": "gal-run/gal-model"},  # trips the Anthropic-terms denylist
            {"report": "fine-tune the classifier"},
            evaluator=lambda r, e: {"key": "k", "score": 1.0},
            client=c,
        )
        self.assertFalse(out["ok"])
        self.assertEqual(out["status"], "refused")
        # Fail CLOSED: no judge call happened, no feedback written.
        c.create_feedback.assert_not_called()

    def test_refuses_model_dev_run_when_payload_is_nested(self):
        """The Anthropic-terms guard must fail CLOSED even when the model-dev text is a
        NESTED value (dict/list) under a recognized key — because that is EXACTLY what the
        default ``llm_judge`` extracts and sends to the paid LLM.

        judge_live_run's guard (``_guard_strings``) only inspects TOP-LEVEL string values,
        but the real evaluator (``langsmith_setup._extract_text``) reads ``outputs[key]``
        and ``str()``-ifies it whether or not it is a string. So a run whose ``report`` is a
        dict containing 'fine-tune'/'gal-model' slips past the guard yet still reaches the
        judge. This is both a compliance hole (model-dev content hits Claude despite the
        'fails CLOSED' docstring) AND a cost hole (the paid judge fires on a run that should
        have been refused with no LLM call).
        """
        from agent_toolkit.langsmith_setup import _extract_text

        c = _ok_client()
        seen = {}

        # An evaluator that mirrors the REAL llm_judge extraction, so we can observe what
        # text would actually be sent to the model.
        def judge_like_real(run, example):
            seen["verdict"] = _extract_text(run, "verdict", "report", "summary", "output")
            return {"key": "qa_verdict_quality", "score": 1.0}

        out = ll.judge_live_run(
            "run-xyz",
            {"target": "Scheduler-Systems/scheduler-web"},  # benign top-level string
            # Model-dev content hidden one level down under a recognized key.
            {"report": {"task": "fine-tune the gal-model classifier and distill it"}},
            evaluator=judge_like_real,
            client=c,
        )

        # The judge must NOT have seen model-development content...
        self.assertNotIn("fine-tune", seen.get("verdict", "").lower(),
                         "model-dev content reached the judge — guard bypassed")
        self.assertNotIn("gal-model", seen.get("verdict", "").lower(),
                         "model-dev content reached the judge — guard bypassed")
        # ...and the run must have been refused fail-closed: no judge, no feedback write.
        self.assertEqual(out["status"], "refused")
        self.assertFalse(out["ok"])
        c.create_feedback.assert_not_called()

    def test_evaluator_failure_is_fail_safe(self):
        c = _ok_client()
        out = ll.judge_live_run(
            "run-xyz", {"target": "ok"}, {"report": "ok"},
            evaluator=mock.Mock(side_effect=ValueError("judge boom")),
            client=c,
        )
        self.assertFalse(out["ok"])
        self.assertEqual(out["status"], "error")
        self.assertEqual(out["error"], "ValueError")
        c.create_feedback.assert_not_called()

    def test_uses_shared_offline_judge_by_default(self):
        # No evaluator injected -> it pulls the shared langsmith_setup.llm_judge.
        c = _ok_client()
        sentinel = mock.Mock(return_value={"key": "qa_verdict_quality", "score": 0.5})
        with mock.patch.object(ll, "_default_evaluator", return_value=sentinel):
            out = ll.judge_live_run("run-1", {"target": "ok"}, {"report": "ok"}, client=c)
        self.assertEqual(out["status"], "judged")
        sentinel.assert_called_once()


# ---------------------------------------------------------------------------
# Report-only / safety: the loop only ANNOTATES; it never mutates agent behavior.
# ---------------------------------------------------------------------------
class ReportOnlyTests(unittest.TestCase):
    def test_record_feedback_only_annotates_no_behavior_mutation(self):
        # The only side effect on the client is create_feedback — never an update/run/dispatch.
        c = _ok_client()
        ll.record_feedback("r", "k", 1.0, client=c)
        called = {name for name, *_ in c.mock_calls}
        self.assertEqual(called, {"create_feedback"})

    def test_judge_live_run_only_calls_create_feedback(self):
        c = _ok_client()
        ll.judge_live_run(
            "r", {"t": "ok"}, {"report": "ok"},
            evaluator=lambda run, ex: {"key": "k", "score": 1.0}, client=c,
        )
        called = {name for name, *_ in c.mock_calls}
        self.assertEqual(called, {"create_feedback"})


# ---------------------------------------------------------------------------
# Wiring proof: cfo_deepagents pulls its system prompt via get_prompt, falls back safe.
# ---------------------------------------------------------------------------
class CfoWiringTests(unittest.TestCase):
    def test_cfo_deepagents_build_uses_get_prompt_with_embedded_fallback(self):
        from graphs.exec import cfo_deepagents as cfo

        captured = {}

        def fake_create_deep_agent(model, tools, system_prompt):
            captured["system_prompt"] = system_prompt
            return mock.Mock()

        fake_deepagents = mock.Mock()
        fake_deepagents.create_deep_agent = fake_create_deep_agent
        # No client/creds -> get_prompt returns the embedded fallback (the existing _SYSTEM).
        with mock.patch.object(ll, "_resolve_client", return_value=None), \
             mock.patch.dict("sys.modules", {"deepagents": fake_deepagents}), \
             mock.patch.object(cfo, "get_model", return_value=mock.Mock()):
            cfo._build()
        self.assertEqual(captured["system_prompt"], cfo._SYSTEM)


if __name__ == "__main__":
    unittest.main()
