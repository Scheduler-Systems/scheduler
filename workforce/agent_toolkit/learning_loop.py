"""The ACTIVE side of the LangSmith learning loop for the agent fleet.

``scripts/langsmith_setup.py`` *provisions* the learning surface (a dataset, an
annotation queue, the Prompt Hub versions, an offline LLM-as-judge) and ``scripts/
run_eval.py`` runs an *offline* experiment against it. That half is real but INERT:
nothing in production ever **writes** a feedback signal, no graph ever **pulls** the
governed Hub prompt (each embeds its own copy), and the judge only runs offline. This
module closes that loop with three small, fail-safe seams the live graphs can call:

  1. :func:`record_feedback` — the first-class signal ledger. Wraps
     ``client.create_feedback`` so a run can be scored (by a human, a rule, or the
     judge). Feedback on runs is what fills the annotation queue and, once a human
     corrects it, what flows into the dataset.
  2. :func:`get_prompt` — pull the PINNED Prompt Hub version pushed by
     ``langsmith_setup.push_agent_prompts``, falling back to the embedded text on ANY
     failure, so a graph can adopt the centrally-governed/iterated prompt without ever
     becoming fragile (no creds / not found / offline => the graph just uses its
     baked-in text). This is what makes the push-but-never-pull provisioning live.
  3. :func:`judge_live_run` — run the existing offline judge (or an injected
     evaluator) on ONE *production* run and write the score back via
     :func:`record_feedback`. This is the code side of "online evals"; the
     *sampling/scheduling* of which live runs to judge is LangSmith **automation-rule**
     config (set in the LangSmith UI), NOT faked here.

The closed loop:  live run -> feedback (record_feedback / judge_live_run) ->
annotation queue (human review) -> dataset (corrected ground truth) -> Prompt Hub
(iterated prompt) -> get_prompt (graph adopts it).  Every hop already had a half; this
module supplies the missing writes/reads.

REPORT-ONLY: nothing here mutates an agent's behavior or moves money. ``record_feedback``
only annotates an *observation* of a run; ``get_prompt`` only swaps in governed prompt
TEXT (and always degrades to the existing baked-in text); ``judge_live_run`` only writes
a score. No outward action, no roster/ledger edit.

Anthropic-terms posture (workspace AGENTS.md): this is QA of the AGENT's task output —
"did this agent produce a correct, useful verdict?" — NOT model training/eval/distill.
:func:`judge_live_run` routes the judged strings through ``assert_not_model_work`` and
fails CLOSED if they trip the model-development denylist.

Design rules (match the rest of agent_toolkit):
  - Config is read from the ENVIRONMENT only — NEVER hardcode keys/ids/secrets.
  - Everything is FAIL-SAFE: a missing key, an offline backend, or an SDK hiccup must
    never crash the caller. Functions return a structured status dict (or the fallback)
    instead of raising. Secrets are never logged.
  - The LangSmith client is INJECTABLE (``client=`` kwarg) so this is unit-testable with
    a mock and never touches the network in tests.
"""
from __future__ import annotations

from typing import Any, Callable, Optional


# ---------------------------------------------------------------------------
# Client resolution — reuse the provisioning module's fail-safe builder so client
# construction (endpoint / workspace / key handling) stays in ONE place.
# ---------------------------------------------------------------------------
def _resolve_client(client: Optional[Any]):
    """Return the injected client, else build one from the env (fail-safe -> None)."""
    if client is not None:
        return client
    try:
        from agent_toolkit.langsmith_setup import get_client

        return get_client()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 1) record_feedback — the first-class signal ledger (currently empty in prod).
# ---------------------------------------------------------------------------
def record_feedback(
    run_id: Any,
    key: str,
    score: Any,
    *,
    comment: Optional[str] = None,
    source_agent: Optional[str] = None,
    client: Optional[Any] = None,
) -> dict:
    """Write ONE feedback signal on a LangSmith run (wraps ``client.create_feedback``).

    This is the loop's missing write: a score/annotation on a run is what populates the
    annotation queue and (after human correction) the learning dataset.

    FAIL-SAFE: never raises. Returns a status dict:
      - ``{"ok": True,  "status": "recorded",  "run_id", "key", "score", "feedback_id"}``
      - ``{"ok": False, "status": "skipped",   ...}``  when there are no creds (no client)
        or no ``run_id`` (nothing to attach the signal to)
      - ``{"ok": False, "status": "error", "error": <type-only msg>, ...}``  on SDK/network
        failure.

    ``source_agent`` is recorded as feedback ``source_info`` (provenance: which agent/rule
    produced the signal). Secrets are never included or logged.
    """
    base = {"ok": False, "status": "skipped", "run_id": _str_or_none(run_id), "key": key,
            "score": _coerce_score(score)}

    if not run_id:
        return {**base, "reason": "no run_id"}

    resolved = _resolve_client(client)
    if resolved is None:
        return {**base, "reason": "no LangSmith client (LANGSMITH_API_KEY not set)"}

    source_info = {"source_agent": source_agent} if source_agent else None
    try:
        fb = resolved.create_feedback(
            run_id,
            key,
            score=_coerce_score(score),
            comment=(str(comment)[:2000] if comment is not None else None),
            source_info=source_info,
        )
        return {
            "ok": True,
            "status": "recorded",
            "run_id": _str_or_none(run_id),
            "key": key,
            "score": _coerce_score(score),
            "feedback_id": _str_or_none(getattr(fb, "id", None)),
        }
    except Exception as exc:  # offline / perms / SDK drift — degrade, don't crash
        return {**base, "status": "error", "error": _safe_err(exc)}


# ---------------------------------------------------------------------------
# 2) get_prompt — pull the pinned Prompt Hub version, fall back to embedded text.
# ---------------------------------------------------------------------------
def get_prompt(name: str, *, fallback: str, client: Optional[Any] = None) -> str:
    """Return the governed system-prompt TEXT for ``name`` from the Prompt Hub.

    Closes the push-but-never-pull half of the loop: ``langsmith_setup.push_agent_prompts``
    pushes ``scheduler-qa-<agent>`` prompts, but no graph ever pulled them. A graph calls
    this with its existing embedded text as ``fallback`` so it adopts the centrally
    iterated version WITHOUT ever becoming fragile.

    On ANY failure — no client/creds, prompt not found, offline, SDK drift, or an
    unexpected object shape — return ``fallback`` unchanged so the graph NEVER breaks.
    Never raises.
    """
    resolved = _resolve_client(client)
    if resolved is None:
        return fallback
    try:
        obj = resolved.pull_prompt(name)
        # Extraction must ALSO be inside the guard: a pulled object's exact shape comes
        # from the resolved langsmith/langchain-core versions and can drift (a truthy-but-
        # non-iterable .messages, an attribute access with a side effect, etc.). If that
        # raises out of get_prompt the whole graph fails to IMPORT — the worst version of
        # the failure this function's #1 contract forbids ("Never raises").
        text = _extract_system_text(obj)
    except Exception:
        return fallback
    return text if text else fallback


# ---------------------------------------------------------------------------
# 3) judge_live_run — run the existing judge on ONE production run, write the score.
# ---------------------------------------------------------------------------
def judge_live_run(
    run_id: Any,
    inputs: Optional[dict],
    outputs: Optional[dict],
    *,
    evaluator: Optional[Callable[..., dict]] = None,
    client: Optional[Any] = None,
) -> dict:
    """Score ONE live production run with the LLM-as-judge and write feedback.

    The code side of LangSmith "online evals": take a single real run (its ``inputs`` /
    ``outputs``), score it with the EXISTING offline judge
    (``langsmith_setup.llm_judge``) — or an injected ``evaluator`` for tests / alternate
    rubrics — and persist the score on that run via :func:`record_feedback`.

    NOTE (honest): WHICH live runs get judged and HOW OFTEN is **sampling/scheduling**
    that lives in LangSmith automation-rule config (the run-rules UI), not here. This
    function is only the per-run scoring+write primitive that such a rule would invoke.

    ANTHROPIC-TERMS GUARD: the judged strings are routed through ``assert_not_model_work``
    and this FAILS CLOSED (``status="refused"``, no judge call, no write) if they trip the
    model-development denylist. QA of agent output is permitted; model train/eval/distill
    is not.

    FAIL-SAFE: never raises. Returns a status dict embedding the judge result and the
    feedback-write status:
      - ``{"ok": True,  "status": "judged",  "judge": {...}, "feedback": {...}}``
      - ``{"ok": False, "status": "refused", ...}``       (denylist tripped)
      - ``{"ok": False, "status": "error",   ...}``       (evaluator failed)
    """
    base = {"ok": False, "run_id": _str_or_none(run_id)}

    # Anthropic-terms guard — fail CLOSED on the model-development denylist. If the guard
    # module is unavailable, QA is still permitted, so proceed (mirrors llm_judge).
    try:
        from agent_toolkit.policy import assert_not_model_work, ModelWorkBlocked
    except Exception:
        assert_not_model_work = None  # guard unavailable -> QA proceeds
        ModelWorkBlocked = ()  # type: ignore[assignment]
    if assert_not_model_work is not None:
        try:
            for s in _guard_strings(inputs, outputs):
                assert_not_model_work(s)
        except ModelWorkBlocked as exc:  # type: ignore[misc]
            return {**base, "status": "refused", "error": _safe_err(exc)}

    # Resolve the evaluator: injected wins; otherwise the shared offline judge.
    evaluator = evaluator or _default_evaluator()
    if evaluator is None:
        return {**base, "status": "error", "error": "no evaluator available"}

    # Build a minimal run/example view the judge can read (it pulls text off .outputs /
    # .inputs). A plain dict-shaped object is enough and avoids importing run schemas.
    run_view = _RunView(inputs=inputs or {}, outputs=outputs or {})
    try:
        result = evaluator(run_view, None)
    except Exception as exc:  # evaluator must never crash the caller
        return {**base, "status": "error", "error": _safe_err(exc)}
    if not isinstance(result, dict):
        return {**base, "status": "error", "error": "evaluator returned non-dict"}

    key = str(result.get("key") or "qa_verdict_quality")
    score = result.get("score")
    comment = result.get("comment")
    feedback = record_feedback(
        run_id, key, score, comment=comment, source_agent="learning_loop:judge", client=client
    )
    return {**base, "ok": bool(feedback.get("ok")), "status": "judged",
            "judge": result, "feedback": feedback}


# ---------------------------------------------------------------------------
# Helpers — all fail-safe, no network.
# ---------------------------------------------------------------------------
class _RunView:
    """Minimal run-like view (``.inputs`` / ``.outputs`` dicts) for an evaluator.

    The shared ``llm_judge`` reads text off ``run.outputs`` / ``run.inputs``; this gives
    a live run that exact shape without importing LangSmith run schemas.
    """

    __slots__ = ("inputs", "outputs")

    def __init__(self, inputs: dict, outputs: dict) -> None:
        self.inputs = inputs
        self.outputs = outputs


def _default_evaluator() -> Optional[Callable[..., dict]]:
    """Return the shared offline LLM-as-judge, or None if it can't be imported."""
    try:
        from agent_toolkit.langsmith_setup import llm_judge

        return llm_judge
    except Exception:
        return None


def _extract_system_text(obj: Any) -> str:
    """Best-effort pull of the SYSTEM prompt text from a pulled Prompt Hub object.

    Handles a ChatPromptTemplate (the shape ``push_agent_prompts`` pushes), a plain
    PromptTemplate, or a raw string. Returns "" if no SYSTEM text could be extracted.

    Defensive by contract: the caller (:func:`get_prompt`) promises to NEVER raise, but
    it also wraps this call in a guard. Even so, this iterates ``.messages`` inside its
    own try/except so a pulled object whose ``.messages`` is truthy-but-non-iterable (or
    whose iteration has a side effect under SDK drift) yields "" -> fallback rather than
    propagating.

    Only a SYSTEM-role message's template is returned. A no-system ChatPromptTemplate
    (e.g. a human mis-edit on the Hub that pushes a user-only prompt) returns "" so the
    caller degrades to its baked-in fallback — NEVER adopting an arbitrary user/ai
    template (such as '{input}') as a graph's entire system prompt.
    """
    if obj is None:
        return ""
    if isinstance(obj, str):
        return obj
    # ChatPromptTemplate -> .messages; find the SYSTEM message's template text only.
    messages = getattr(obj, "messages", None)
    if messages:
        try:
            for msg in messages:
                if "system" not in type(msg).__name__.lower():
                    continue
                prompt = getattr(msg, "prompt", None)
                template = getattr(prompt, "template", None)
                if isinstance(template, str) and template:
                    return template
        except Exception:
            # Non-iterable / side-effecting .messages under SDK drift -> degrade to "".
            return ""
    # Plain PromptTemplate (or anything carrying a .template string).
    template = getattr(obj, "template", None)
    if isinstance(template, str) and template:
        return template
    return ""


def _guard_strings(inputs: Optional[dict], outputs: Optional[dict]):
    """Yield the text the Anthropic-terms guard should check from a live run.

    GUARD == EXTRACTOR PARITY: the default judge (``langsmith_setup.llm_judge``) reads
    content via ``_extract_text``, which does ``str(holder[key])`` for ANY type under a
    recognized key — so a nested dict/list value (e.g.
    ``outputs={"report": {"task": "fine-tune the gal-model classifier"}}``) becomes a
    string the PAID LLM judge sees. If this guard only inspected TOP-LEVEL ``str`` values
    it would miss exactly that, letting model-development content slip past a guard whose
    docstring promises it "FAILS CLOSED". So recurse into nested dicts/lists and stringify
    non-str scalars, covering the same surface the extractor stringifies.
    """
    for holder in (inputs, outputs):
        yield from _iter_guard_text(holder)


def _iter_guard_text(value: Any, _depth: int = 0):
    """Yield guardable text from ``value``, recursing dicts/lists (bounded depth).

    Mirrors what ``_extract_text`` can turn into a judged string: str values directly,
    other scalars via ``str()``, and the contents of nested dicts/lists (including the
    ``str(dict)``/``str(list)`` form the extractor itself would produce). Bounded depth
    keeps a pathological/cyclic payload from spinning; fail-safe (never raises)."""
    if _depth > 6:
        return
    try:
        if isinstance(value, str):
            if value:
                yield value
            return
        if isinstance(value, dict):
            # The extractor does str(holder[key]) on a dict value -> guard that form too.
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
        # A value whose __str__/__iter__ misbehaves must not break the guard sweep.
        return


def _coerce_score(v: Any) -> Any:
    """Pass through bool/int/float (what create_feedback accepts); else best-effort float.

    Returns None if the value can't be turned into a number (create_feedback accepts a
    None score — an annotation-only signal).
    """
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, (int, float)):
        return v
    try:
        return float(v)
    except Exception:
        # Broad on purpose: this is also called when building the pre-try ``base`` dict,
        # so a value whose __float__ raises something other than TypeError/ValueError must
        # still degrade to None rather than escape the caller.
        return None


def _str_or_none(v: Any) -> Optional[str]:
    """Stringify ``v`` (or None). Fail-safe: a pathological ``__str__`` must not escape
    into a caller that builds its status/``base`` dict before entering any try block."""
    if v is None:
        return None
    try:
        return str(v)
    except Exception:
        return None


def _safe_err(exc: Exception) -> str:
    """Type-only error string — never include a message that could carry a secret."""
    return type(exc).__name__
