"""Offline EVALUATION runner for the scheduler-qa agent fleet.

This is the formal OFFLINE-evals half that complements the online ``learning_loop.
judge_live_run``: run a TARGET (a graph, a prompt-under-test, or any
``callable(inputs) -> dict``) over a DATASET of examples, score each with the LLM-as-judge
(EVALUATORS), and produce **per-example scores + an aggregate** — an experiment.

It is the engine ``scripts/eval_gate.py`` calls to gate a redeploy: score a CANDIDATE,
compare to a BASELINE, and BLOCK if it regressed.

Two paths, same result shape (:class:`EvalReport`):
  * **offline loop** (default, the testable + creds-free path): iterate the dataset's
    examples locally, call ``target(inputs)``, then each evaluator ``(run_view, example)``,
    collect scores. Works with an injected/mock client OR a pure in-memory example list —
    NO network is required, which is what makes the gate runnable in CI and unit tests.
  * **upload** (opt-in ``upload=True``): delegate to ``client.evaluate(...)`` so the run
    ALSO lands as a LangSmith experiment (visible under Datasets & Experiments). Only used
    when explicitly asked and creds exist; never in tests.

Anthropic-terms posture (workspace AGENTS.md): this scores AGENT TASK OUTPUT quality
("did the agent produce a correct, useful verdict/digest?"). It does NOT train, fine-tune,
evaluate, or distill any ML model. Every evaluation routes the TARGET identifier AND the
judged content through ``assert_not_model_work`` and FAILS CLOSED (refuses to eval) on the
model-development denylist.

REPORT-ONLY: this module SCORES. It never deploys, never posts, never moves money, never
mutates an agent. The gate that wraps it only BLOCKS a redeploy — the redeploy itself is a
separate, human-gated step.

Design rules (match the rest of agent_toolkit):
  - Config from the ENVIRONMENT only — NEVER hardcode keys/ids/secrets.
  - FAIL-SAFE: a missing key, an offline backend, an SDK hiccup, or a target/judge failure
    must never crash the caller. Failures degrade to a structured result; secrets are never
    logged. Error strings are TYPE-ONLY (no message bodies that could carry a token).
  - The LangSmith client is INJECTABLE (``client=`` kwarg) so this is unit-testable with a
    mock and never touches the network in tests.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional

# The judged-score key the gate reads for its aggregate. The shared llm_judge emits a
# dict keyed "qa_verdict_quality" with an overall "score"; run_eval's judge re-keys to
# "usefulness". We accept BOTH and aggregate the "score" field, which both always carry.
DEFAULT_SCORE_KEY = "qa_verdict_quality"

# Minimum fraction of the dataset that MUST produce a numeric score for the aggregate to be
# trusted. This closes the partial-coverage masking hole: if a prompt/graph regression makes
# the candidate crash or emit un-judgeable output on a SUBSET of examples, those examples
# would otherwise be silently DROPPED from the mean (numerator AND denominator), so the few
# survivors could mask a catastrophic regression and ship GREEN. We instead require coverage:
# below the floor, the aggregate is SUPPRESSED (set to None) so the gate fails SAFE through
# the same path as a totally-unscored run (decide() -> EXIT_UNSCORED / report.ok == False).
#
# Default 1.0 = EVERY example given to the candidate must score (the strictest, most
# fail-safe choice — an unscored example is a real "broken on this input" signal, not noise).
# Operators may deliberately relax it via EVAL_MIN_COVERAGE (e.g. 0.8) when a flaky judge is
# expected; it is clamped to [0.0, 1.0]. A gate that degrades OPEN is worse than no gate.
DEFAULT_MIN_COVERAGE = 1.0


def _coverage_floor() -> float:
    raw = os.environ.get("EVAL_MIN_COVERAGE")
    if raw is None:
        return DEFAULT_MIN_COVERAGE
    try:
        return max(0.0, min(1.0, float(raw)))
    except (TypeError, ValueError):
        return DEFAULT_MIN_COVERAGE


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------
@dataclass
class ExampleScore:
    """One example's outcome: the target's output + the evaluator score(s)."""

    index: int
    inputs: dict
    reference: Optional[dict]
    output: dict
    score: Optional[float]
    key: str = DEFAULT_SCORE_KEY
    comment: str = ""
    error: Optional[str] = None  # target/judge error (type-only), if any

    def as_dict(self) -> dict:
        return {
            "index": self.index,
            "inputs": self.inputs,
            "score": self.score,
            "key": self.key,
            "comment": self.comment,
            "error": self.error,
        }


@dataclass
class EvalReport:
    """An offline experiment result: per-example scores + an aggregate."""

    target_name: str
    dataset_name: str
    scores: list[ExampleScore] = field(default_factory=list)
    aggregate: Optional[float] = None
    n_scored: int = 0
    n_total: int = 0
    refused: bool = False
    error: Optional[str] = None
    experiment_name: Optional[str] = None
    experiment_url: Optional[str] = None

    @property
    def ok(self) -> bool:
        """True when the evaluation produced an aggregate and was not refused/errored."""
        return self.aggregate is not None and not self.refused and self.error is None

    def as_dict(self) -> dict:
        return {
            "target_name": self.target_name,
            "dataset_name": self.dataset_name,
            "aggregate": self.aggregate,
            "n_scored": self.n_scored,
            "n_total": self.n_total,
            "refused": self.refused,
            "error": self.error,
            "experiment_name": self.experiment_name,
            "experiment_url": self.experiment_url,
            "scores": [s.as_dict() for s in self.scores],
        }


# ---------------------------------------------------------------------------
# A minimal run-like view the judge can read (matches learning_loop._RunView).
# ---------------------------------------------------------------------------
class _RunView:
    __slots__ = ("inputs", "outputs")

    def __init__(self, inputs: dict, outputs: dict) -> None:
        self.inputs = inputs
        self.outputs = outputs


class _ExampleView:
    """An example with ``.inputs`` / ``.outputs`` the judge reads the reference from."""

    __slots__ = ("inputs", "outputs", "metadata")

    def __init__(self, inputs: dict, outputs: Optional[dict], metadata: Optional[dict] = None) -> None:
        self.inputs = inputs or {}
        self.outputs = outputs or {}
        self.metadata = metadata or {}


# ---------------------------------------------------------------------------
# Anthropic-terms guard — fail CLOSED on the model-development denylist.
# ---------------------------------------------------------------------------
def _guard_or_none():
    try:
        from agent_toolkit.policy import assert_not_model_work, ModelWorkBlocked

        return assert_not_model_work, ModelWorkBlocked
    except Exception:
        return None, ()


def _guard_target(target_name: str) -> Optional[str]:
    """Return a refusal reason if the TARGET identifier trips the denylist, else None."""
    assert_not_model_work, ModelWorkBlocked = _guard_or_none()
    if assert_not_model_work is None:
        return None  # guard unavailable -> QA proceeds (mirrors llm_judge)
    try:
        assert_not_model_work(target_name)
    except ModelWorkBlocked as exc:  # type: ignore[misc]
        return type(exc).__name__
    except Exception:
        return None
    return None


def _guard_payload(*payloads: Optional[dict]) -> Optional[str]:
    """Return a refusal reason if any nested payload value trips the denylist, else None.

    Mirrors ``learning_loop._guard_strings``: recurse into dicts/lists and stringify
    scalars so model-dev content hidden one level down under a recognized key (exactly what
    the judge would ``str()``-ify and send to the paid LLM) is caught, not just top-level
    strings. The eval target's OUTPUT is attacker-influenced (a misbehaving/compromised
    prompt could emit 'fine-tune the gal-model classifier'), so guarding outputs matters.
    """
    assert_not_model_work, ModelWorkBlocked = _guard_or_none()
    if assert_not_model_work is None:
        return None
    try:
        for payload in payloads:
            for s in _iter_guard_text(payload):
                try:
                    assert_not_model_work(s)
                except ModelWorkBlocked as exc:  # type: ignore[misc]
                    return type(exc).__name__
    except Exception:
        return None
    return None


def _iter_guard_text(value: Any, _depth: int = 0):
    """Yield guardable text from ``value``, recursing dicts/lists (bounded depth)."""
    if _depth > 6:
        return
    try:
        if isinstance(value, str):
            if value:
                yield value
            return
        if isinstance(value, dict):
            yield str(value)
            for v in value.values():
                yield from _iter_guard_text(v, _depth + 1)
            return
        if isinstance(value, (list, tuple, set)):
            yield str(value)
            for v in value:
                yield from _iter_guard_text(v, _depth + 1)
            return
        if isinstance(value, (bool, int, float, bytes)):
            yield str(value)
    except Exception:
        return


# ---------------------------------------------------------------------------
# Default evaluator — the shared offline LLM-as-judge.
# ---------------------------------------------------------------------------
def default_evaluator() -> Optional[Callable[..., dict]]:
    """Return the shared LLM-as-judge (``langsmith_setup.llm_judge``), or None."""
    try:
        from agent_toolkit.langsmith_setup import llm_judge

        return llm_judge
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Dataset loading — local seed first (creds-free), client examples if available.
# ---------------------------------------------------------------------------
def load_local_examples() -> list[dict]:
    """Return the LOCAL seed examples (no creds needed)."""
    try:
        from agent_toolkit.eval_dataset import EVAL_EXAMPLES

        return list(EVAL_EXAMPLES)
    except Exception:
        return []


def _examples_from_client(client: Any, dataset_name: str) -> Optional[list[dict]]:
    """Best-effort pull of a dataset's examples via the client. None on any failure."""
    if client is None:
        return None
    try:
        raw = list(client.list_examples(dataset_name=dataset_name))
    except Exception:
        return None
    out: list[dict] = []
    for ex in raw:
        inputs = getattr(ex, "inputs", None)
        outputs = getattr(ex, "outputs", None)
        if isinstance(ex, dict):
            inputs = ex.get("inputs", inputs)
            outputs = ex.get("outputs", outputs)
        out.append({"inputs": inputs or {}, "outputs": outputs or {}})
    return out or None


def _resolve_examples(
    examples: Optional[Iterable[dict]],
    client: Any,
    dataset_name: str,
) -> list[dict]:
    """Resolve the example list: explicit > client-fetched > local seed."""
    if examples is not None:
        return list(examples)
    fetched = _examples_from_client(client, dataset_name)
    if fetched is not None:
        return fetched
    return load_local_examples()


# ---------------------------------------------------------------------------
# Score extraction helpers
# ---------------------------------------------------------------------------
def _coerce_score(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, f))


def _read_eval_result(result: Any) -> tuple[Optional[float], str, str]:
    """Pull (score, key, comment) from one evaluator result (dict or EvaluationResult)."""
    if isinstance(result, dict):
        score = _coerce_score(result.get("score"))
        if score is None:
            # run_eval's judge re-keys overall to "usefulness"; accept it as the score.
            score = _coerce_score(result.get("usefulness"))
        key = str(result.get("key") or DEFAULT_SCORE_KEY)
        comment = str(result.get("comment", ""))[:500]
        return score, key, comment
    # EvaluationResult-like object
    score = _coerce_score(getattr(result, "score", None))
    key = str(getattr(result, "key", None) or DEFAULT_SCORE_KEY)
    comment = str(getattr(result, "comment", "") or "")[:500]
    return score, key, comment


# ---------------------------------------------------------------------------
# THE OFFLINE EVALUATION LOOP
# ---------------------------------------------------------------------------
def run_evaluation(
    target: Callable[[dict], dict],
    *,
    dataset_name: str = "scheduler-qa-eval",
    target_name: Optional[str] = None,
    evaluators: Optional[list[Callable[..., dict]]] = None,
    examples: Optional[Iterable[dict]] = None,
    client: Optional[Any] = None,
    upload: bool = False,
    score_key: str = DEFAULT_SCORE_KEY,
    min_coverage: Optional[float] = None,
) -> EvalReport:
    """Run ``target`` over the dataset, score each example, aggregate. FAIL-SAFE.

    Args:
      target: ``callable(inputs: dict) -> dict`` — the graph/prompt under test. Its output
        dict is what the evaluators read (keys like report/summary/verdict/output).
      dataset_name: public dataset id (``scheduler-qa-eval``).
      target_name: identifier guarded against the model-dev denylist (defaults to
        ``dataset_name`` + the target repr). Pass the candidate's repo/prompt id here so a
        denylisted target is REFUSED.
      evaluators: list of ``(run_view, example) -> dict`` scorers. Defaults to the shared
        LLM-as-judge. The FIRST evaluator's score drives the aggregate.
      examples: explicit example list (testing); else fetched from ``client``; else the
        local seed (``eval_dataset.EVAL_EXAMPLES``).
      client: injectable LangSmith client (mock in tests; None => offline-only).
      upload: when True AND a client exists, ALSO run ``client.evaluate(...)`` so the run
        lands as a LangSmith experiment. Never required for the gate or tests.
      score_key: which evaluator key to aggregate when an evaluator returns multiple.
      min_coverage: minimum fraction of examples that must produce a numeric score for the
        aggregate to be trusted (defaults to ``EVAL_MIN_COVERAGE`` or 1.0). Below the floor
        the aggregate is SUPPRESSED to None (and ``error`` set) so a partial-coverage run —
        a regression that breaks the candidate on a SUBSET of inputs — fails SAFE instead of
        letting the surviving examples mask the broken ones.

    Returns an :class:`EvalReport`. On the model-dev denylist it returns
    ``refused=True`` (no target call, no judge call). Never raises.
    """
    target_name = target_name or f"{dataset_name}:{getattr(target, '__name__', repr(target))}"
    report = EvalReport(target_name=target_name, dataset_name=dataset_name)

    # 1) Anthropic-terms guard on the TARGET identifier — fail CLOSED.
    refusal = _guard_target(target_name)
    if refusal is not None:
        report.refused = True
        report.error = f"refused (model-dev denylist): {refusal}"
        return report

    # Distinguish "not provided" (None -> use the shared judge) from "provided empty"
    # ([] -> caller explicitly gave no evaluator, which is an honest error, NOT a silent
    # fall-through to the paid default judge).
    if evaluators is None:
        evaluators = _default_evaluators()
    if not evaluators:
        report.error = "no evaluator available"
        return report

    rows = _resolve_examples(examples, client, dataset_name)
    report.n_total = len(rows)
    if not rows:
        report.error = "no examples to evaluate"
        return report

    collected: list[float] = []
    for i, ex in enumerate(rows):
        inputs = (ex.get("inputs") if isinstance(ex, dict) else getattr(ex, "inputs", None)) or {}
        reference = ex.get("outputs") if isinstance(ex, dict) else getattr(ex, "outputs", None)

        # 1a) Guard the example INPUTS before running the target (an example could carry
        # model-dev content); skip-refuse that single example rather than running it.
        in_refusal = _guard_payload(inputs)
        if in_refusal is not None:
            report.scores.append(ExampleScore(
                index=i, inputs=inputs, reference=reference, output={},
                score=None, key=score_key, comment="", error=f"refused: {in_refusal}",
            ))
            continue

        # 2) Run the target (fail-safe — a target error becomes an example error, score None).
        try:
            output = target(dict(inputs)) or {}
            if not isinstance(output, dict):
                output = {"output": str(output)}
        except Exception as exc:
            report.scores.append(ExampleScore(
                index=i, inputs=inputs, reference=reference, output={},
                score=None, key=score_key, comment="", error=type(exc).__name__,
            ))
            continue

        # 2a) Guard the TARGET OUTPUT before it reaches the (paid) judge — fail CLOSED so a
        # compromised/misbehaving prompt that emits model-dev content is never judged.
        out_refusal = _guard_payload(output)
        if out_refusal is not None:
            report.scores.append(ExampleScore(
                index=i, inputs=inputs, reference=reference, output=output,
                score=None, key=score_key, comment="", error=f"refused: {out_refusal}",
            ))
            continue

        # 3) Score with the evaluator(s). The first evaluator drives the aggregate.
        run_view = _RunView(inputs=dict(inputs), outputs=output)
        example_view = _ExampleView(inputs=dict(inputs), outputs=reference)
        score, key, comment, err = _score_one(evaluators, run_view, example_view, score_key)
        es = ExampleScore(
            index=i, inputs=inputs, reference=reference, output=output,
            score=score, key=key, comment=comment, error=err,
        )
        report.scores.append(es)
        if score is not None:
            collected.append(score)

    report.n_scored = len(collected)
    report.aggregate = (sum(collected) / len(collected)) if collected else None

    # 3a) COVERAGE FLOOR — the partial-coverage masking guard.
    # `collected` holds ONLY examples that produced a numeric score; unscored ones (target
    # raised, output un-judgeable, judge declined) were DROPPED from both numerator and
    # denominator above, so they do NOT pull the mean down — they vanish. That lets a few
    # good survivors mask a candidate that is BROKEN on most of the dataset. If coverage is
    # below the floor, the run cannot be trusted: SUPPRESS the aggregate (-> None) so the gate
    # fails SAFE (decide() returns EXIT_UNSCORED / report.ok == False), exactly as it does for
    # a totally-unscored run. n_scored / n_total stay accurate for reporting. report.error is
    # only set when we actually had work to do (n_total > 0) and it is not already set.
    floor = _coverage_floor() if min_coverage is None else max(0.0, min(1.0, min_coverage))
    if report.n_total > 0:
        required = math.ceil(floor * report.n_total)
        if report.n_scored < required:
            report.aggregate = None
            if report.error is None:
                report.error = (
                    f"insufficient eval coverage: scored {report.n_scored}/{report.n_total} "
                    f"(< required {required}; floor {floor:.2f}) — BLOCKING fail-safe"
                )

    # 4) Optional: ALSO upload as a LangSmith experiment (never in tests / never required).
    if upload and client is not None:
        _maybe_upload(report, target, dataset_name, evaluators, client)

    return report


def _score_one(
    evaluators: list[Callable[..., dict]],
    run_view: _RunView,
    example_view: _ExampleView,
    score_key: str,
) -> tuple[Optional[float], str, str, Optional[str]]:
    """Run evaluators on one run; return (score, key, comment, error). Never raises.

    The aggregate is driven by the evaluator whose key matches ``score_key`` if present,
    else the first evaluator that returns a numeric score.
    """
    chosen: tuple[Optional[float], str, str] = (None, score_key, "")
    err: Optional[str] = None
    found_keyed = False
    for ev in evaluators:
        try:
            result = ev(run_view, example_view)
        except Exception as exc:  # an evaluator failure must not crash the loop
            err = err or type(exc).__name__
            continue
        score, key, comment = _read_eval_result(result)
        if key == score_key and score is not None and not found_keyed:
            chosen = (score, key, comment)
            found_keyed = True
        elif not found_keyed and chosen[0] is None and score is not None:
            chosen = (score, key, comment)
    # Surface the (type-only) evaluator error ONLY when nothing scored — a successful score
    # wins even if a later evaluator misbehaved.
    return chosen[0], chosen[1], chosen[2], (err if chosen[0] is None else None)


def _default_evaluators() -> list[Callable[..., dict]]:
    ev = default_evaluator()
    return [ev] if ev is not None else []


def _maybe_upload(
    report: EvalReport,
    target: Callable[[dict], dict],
    dataset_name: str,
    evaluators: list[Callable[..., dict]],
    client: Any,
) -> None:
    """Best-effort: ALSO record the run as a LangSmith experiment. Never raises."""
    try:
        results = client.evaluate(
            target,
            data=dataset_name,
            evaluators=evaluators,
            experiment_prefix=dataset_name,
            description=(
                "Offline eval of scheduler-qa agent output scored by an LLM-as-judge "
                "(usefulness/correctness). Evaluates AGENT task output, not any ML model."
            ),
            metadata={"suite": dataset_name},
            blocking=True,
        )
        report.experiment_name = getattr(results, "experiment_name", None) or dataset_name
        try:
            report.experiment_url = results.url
        except Exception:
            report.experiment_url = None
    except Exception as exc:
        report.error = report.error or f"upload skipped: {type(exc).__name__}"
