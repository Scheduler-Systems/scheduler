"""run_eval — offline LangSmith EXPERIMENT proving the QA agents WORK and are EVALUATED.

What this does (and why it is allowed under the workspace Anthropic-terms posture):
  - Builds a small evaluation DATASET (``scheduler-qa-eval``) of observe-mode QA tasks
    for scheduler-web / -android / -ios + one cross-platform case.
  - Runs each example through a REAL QA worker graph (``web_automation_engineer``)
    compiled locally, in OBSERVE/read-only mode (no CI dispatch, no outward writes).
  - Scores each agent's task output with an LLM-as-judge (reused from
    ``agent_toolkit.langsmith_setup.llm_judge``) on usefulness/correctness.
  - Records the whole thing as a LangSmith EXPERIMENT (visible under Datasets &
    Experiments) with tracing on, then prints the experiment name, URL, and the
    aggregate usefulness score.

This evaluates the AGENT's QA task output ("did the QA agent produce a useful, correct
observation?") — it does NOT train, fine-tune, evaluate, or distill any ML MODEL. The
judge is ordinary orchestration (an LLM scoring a text verdict).

Design rules (match the rest of agent_toolkit):
  - Config is read from the ENVIRONMENT only — NEVER hardcode keys/ids/secrets:
      LANGSMITH_API_KEY, LANGSMITH_ENDPOINT, LANGSMITH_TENANT_ID / LANGSMITH_WORKSPACE_ID
  - Everything is FAIL-SAFE: a missing key, an offline backend, an SDK hiccup, or a
    worker/model failure must never crash the run. Failures degrade to a structured
    result + a non-zero exit code; secrets are never printed.
"""
from __future__ import annotations

import os
import sys
from typing import Any, Optional

# --- Make the repo importable whether run as `python scripts/run_eval.py`,
#     `python -m scripts.run_eval`, or from another cwd. -----------------------
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


# ---------------------------------------------------------------------------
# Env bootstrap (fail-safe). Load .env if python-dotenv is present, and normalise
# the tenant/workspace var so org-scoped LangSmith keys are scoped correctly.
# ---------------------------------------------------------------------------
def _load_env() -> None:
    """Best-effort load of the repo .env; never raises."""
    try:
        from dotenv import load_dotenv

        load_dotenv(os.path.join(_REPO_ROOT, ".env"))
    except Exception:
        pass  # dotenv optional — env may already be exported in the process
    # The SDK scopes org-keys via LANGSMITH_WORKSPACE_ID. Accept the TENANT alias too.
    ws = os.environ.get("LANGSMITH_WORKSPACE_ID") or os.environ.get("LANGSMITH_TENANT_ID")
    if ws:
        os.environ["LANGSMITH_WORKSPACE_ID"] = ws
    # Tracing on so the experiment + per-example runs are captured in LangSmith.
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
    os.environ.setdefault("LANGSMITH_TRACING", "true")
    endpoint = os.environ.get("LANGSMITH_ENDPOINT")
    if endpoint:
        os.environ.setdefault("LANGCHAIN_ENDPOINT", endpoint)


# Public identifiers (NOT secrets).
DATASET_NAME = "scheduler-qa-eval"
EXPERIMENT_PREFIX = "scheduler-qa-eval"

# The evaluation examples now live in the shared, single-source seed module so the
# provisioning script (here), the offline runner (agent_toolkit.evaluations), and the
# pre-redeploy gate (scripts/eval_gate.py) all agree on the SAME dataset. This grew the
# dataset past the original 4 toy QA cases to add the CFO conversational case + ops cases
# drawn from the agents' real digest shapes. Fail-safe import keeps run_eval working even
# if the seed module ever fails to import (degrades to an empty list -> nothing seeded).
try:
    from agent_toolkit.eval_dataset import EVAL_EXAMPLES
except Exception:  # pragma: no cover - defensive; seed module is in-repo
    EVAL_EXAMPLES = []


# ---------------------------------------------------------------------------
# Dataset seeding (idempotent)
# ---------------------------------------------------------------------------
def _seed_examples(client: Any, dataset_id: str) -> int:
    """Add the eval examples to the dataset IF it has none yet (idempotent).

    Returns the number of examples added (0 if it was already populated or on error).
    Never raises.
    """
    try:
        existing = list(client.list_examples(dataset_id=dataset_id, limit=1))
        if existing:
            return 0  # already seeded — keep it idempotent
    except Exception:
        # Couldn't confirm the dataset is empty (transient 503 / permission blip / SDK drift).
        # Degrade SAFELY: do NOT create. LangSmith does not dedupe by input, so blindly
        # creating here would re-insert all examples into a possibly-already-populated
        # dataset, producing DUPLICATES that double-weight those inputs and silently skew the
        # redeploy gate's aggregate. A no-op seed is safe; a duplicate seed corrupts the gate.
        return 0
    try:
        client.create_examples(dataset_id=dataset_id, examples=EVAL_EXAMPLES)
        return len(EVAL_EXAMPLES)
    except Exception:
        # Some SDKs reject batch create with these kwargs — try one-by-one.
        added = 0
        for ex in EVAL_EXAMPLES:
            try:
                client.create_example(
                    inputs=ex["inputs"],
                    outputs=ex.get("outputs"),
                    dataset_id=dataset_id,
                )
                added += 1
            except Exception:
                continue
        return added


# ---------------------------------------------------------------------------
# Target — invoke the REAL web_automation_engineer worker graph locally (observe mode)
# ---------------------------------------------------------------------------
def _build_worker():
    """Compile the web_automation_engineer graph locally via its builder. Never raises."""
    from graphs.qa import web_automation_engineer as wae

    return wae.builder.compile()  # no checkpointer/store — local one-shot invoke


def make_target(graph):
    """Return a ``target(inputs) -> dict`` that runs the worker in observe mode.

    Output keys (what the judge reads): report, classification, summary. On any failure
    returns ``{"error": str(e)}`` so the experiment still records the example.
    """

    def target(inputs: dict) -> dict:
        try:
            # OBSERVE/read-only: never dispatches CI, never proposes outward writes.
            payload = {"mode": "observe", **(inputs or {})}
            r = graph.invoke(payload) or {}
            return {
                "report": r.get("report"),
                "classification": r.get("classification"),
                # observe mode emits `observations`; dispatch path emits `summary`.
                "summary": (r.get("summary") or r.get("observations") or "")[:500],
            }
        except Exception as e:  # worker/model failure must not crash the experiment
            return {"error": str(e)}

    return target


# ---------------------------------------------------------------------------
# Evaluator — reuse the toolkit LLM-as-judge; adapt to {"key":"usefulness", ...}
# ---------------------------------------------------------------------------
def _get_judge():
    """Return an LLM-as-judge evaluator ``(run, example) -> dict`` scoring usefulness.

    Prefers the shared ``langsmith_setup.llm_judge`` (which already scores
    correctness + usefulness and is Anthropic-terms guarded), re-keyed to
    ``usefulness`` for the aggregate this script reports. Falls back to a local
    judge built on ``get_model(TIER_DEFAULT)`` if the shared one is unavailable.
    Never raises at build time.
    """
    shared = None
    try:
        from agent_toolkit.langsmith_setup import llm_judge as shared

        shared = shared
    except Exception:
        shared = None

    if shared is not None:

        def judge(run: Any, example: Any = None) -> dict:
            try:
                res = shared(run, example) or {}
            except Exception as exc:  # judge must never crash an eval run
                return {"key": "usefulness", "score": 0.0, "comment": f"judge error: {exc}"}
            # Prefer the dedicated usefulness axis; fall back to overall score.
            score = res.get("usefulness")
            if score is None:
                score = res.get("score", 0.0)
            return {
                "key": "usefulness",
                "score": _clamp(score),
                "comment": str(res.get("comment", ""))[:500],
            }

        return judge

    # --- Fallback: self-contained LLM-as-judge on the cost-first model router. ---
    _SYS = (
        "You are an impartial QA reviewer. You are given a QA agent's output about how a "
        "software platform's QA works, plus an optional reference of what a good answer "
        "looks like. Score ONLY the agent's output for usefulness and correctness: is it "
        "specific, accurate, actionable, and grounded (not invented)? Return STRICT JSON "
        "with keys: usefulness (0.0-1.0), comment (one short sentence). No other prose."
    )

    def judge(run: Any, example: Any = None) -> dict:
        failsafe = {"key": "usefulness", "score": 0.0, "comment": "judge unavailable"}
        agent_out = _run_text(run, "report", "summary", "observations", "output")
        reference = _example_text(example, "expected", "answer", "verdict", "output")
        context = _run_text(run, "target", "input") or _example_text(example, "target", "input")
        if not agent_out:
            return {**failsafe, "comment": "no agent output to judge"}
        try:
            from agent_toolkit.models import get_model, TIER_DEFAULT

            model = get_model(TIER_DEFAULT)
        except Exception as exc:
            return {**failsafe, "comment": f"no judge model configured: {exc}"}
        user = (
            f"CONTEXT (what was tested): {context or 'n/a'}\n\n"
            f"AGENT OUTPUT (judge this):\n{agent_out}\n\n"
            f"REFERENCE (may be empty):\n{reference or 'n/a'}\n\n"
            "Return the strict JSON described in the system message."
        )
        try:
            resp = model.invoke([("system", _SYS), ("user", user)])
            text = getattr(resp, "content", str(resp)) or ""
            parsed = _parse_json(text)
            return {
                "key": "usefulness",
                "score": _clamp(parsed.get("usefulness", parsed.get("score"))),
                "comment": str(parsed.get("comment", ""))[:500],
            }
        except Exception as exc:
            return {**failsafe, "comment": f"judge error: {exc}"}

    return judge


# ---------------------------------------------------------------------------
# Small helpers (text extraction / clamp / JSON parse) — all fail-safe.
# ---------------------------------------------------------------------------
def _run_text(run: Any, *keys: str) -> str:
    if run is None:
        return ""
    outputs = getattr(run, "outputs", None)
    inputs = getattr(run, "inputs", None)
    for holder in (outputs, inputs):
        if isinstance(holder, dict):
            for k in keys:
                v = holder.get(k)
                if v:
                    return str(v)
    return ""


def _example_text(example: Any, *keys: str) -> str:
    if example is None:
        return ""
    for attr in ("outputs", "inputs"):
        holder = getattr(example, attr, None)
        if isinstance(holder, dict):
            for k in keys:
                v = holder.get(k)
                if v:
                    return str(v)
    return ""


def _clamp(v: Any) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, f))


def _parse_json(text: str) -> dict:
    import json
    import re

    if not text:
        return {}
    for candidate in (text, *re.findall(r"\{.*?\}", text, flags=re.DOTALL)):
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj
        except Exception:
            continue
    return {}


# ---------------------------------------------------------------------------
# Aggregate usefulness from the experiment results (best-effort).
# ---------------------------------------------------------------------------
def _aggregate_usefulness(results: Any) -> Optional[float]:
    """Mean usefulness score across the experiment rows, or None if unavailable."""
    scores: list[float] = []
    try:
        for row in results:  # ExperimentResults is iterable over per-example results
            evals = []
            if isinstance(row, dict):
                er = row.get("evaluation_results") or {}
                evals = er.get("results") or []
            else:
                er = getattr(row, "evaluation_results", None)
                if isinstance(er, dict):
                    evals = er.get("results") or []
            for ev in evals:
                key = ev.get("key") if isinstance(ev, dict) else getattr(ev, "key", None)
                if key == "usefulness":
                    sc = ev.get("score") if isinstance(ev, dict) else getattr(ev, "score", None)
                    if sc is not None:
                        scores.append(float(sc))
    except Exception:
        return None
    if not scores:
        return None
    return sum(scores) / len(scores)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> int:
    _load_env()

    from agent_toolkit.langsmith_setup import ensure_dataset, get_client

    print(f"run_eval — scheduler-qa offline evaluation -> experiment '{EXPERIMENT_PREFIX}'")

    client = get_client()
    if client is None:
        print("  LANGSMITH_API_KEY not set — cannot create a LangSmith experiment. Aborting.")
        return 2

    # 1) Dataset (idempotent create-or-get) + seed the 4 eval examples once.
    ds = ensure_dataset(DATASET_NAME, client=client)
    if not ds.get("ok") or not ds.get("id"):
        print(f"  dataset error: could not ensure '{DATASET_NAME}': {ds.get('error')}")
        return 2
    added = _seed_examples(client, ds["id"])
    print(
        f"  dataset            : {ds['name']} id={ds['id']} "
        f"created={ds['created']} examples_added={added}"
    )

    # 2) Compile the real worker graph locally.
    try:
        graph = _build_worker()
    except Exception as exc:
        print(f"  worker error: could not compile web_automation_engineer: {exc}")
        return 2
    target = make_target(graph)

    # 3) Build the LLM-as-judge.
    judge = _get_judge()

    # 4) Run the experiment (tracing on via env). blocking=True so results are ready.
    try:
        results = client.evaluate(
            target,
            data=DATASET_NAME,
            evaluators=[judge],
            experiment_prefix=EXPERIMENT_PREFIX,
            description=(
                "Offline eval of scheduler-qa worker output (observe mode) scored by an "
                "LLM-as-judge for usefulness/correctness. Evaluates AGENT task output, "
                "not any ML model."
            ),
            metadata={"suite": "scheduler-qa-eval", "mode": "observe"},
            blocking=True,
        )
    except Exception as exc:
        print(f"  evaluate error: {exc}")
        return 1

    # 5) Report: experiment name, URL, aggregate usefulness.
    exp_name = getattr(results, "experiment_name", None) or EXPERIMENT_PREFIX
    try:
        exp_url = results.url  # property — may hit the network
    except Exception:
        exp_url = None
    agg = _aggregate_usefulness(results)

    print("")
    print("EXPERIMENT RECORDED (LangSmith -> Datasets & Experiments):")
    print(f"  experiment name    : {exp_name}")
    print(f"  experiment url     : {exp_url or '(open the dataset in LangSmith)'}")
    if agg is not None:
        print(f"  aggregate usefulness: {agg:.3f}  (mean over {len(EVAL_EXAMPLES)} examples)")
    else:
        print("  aggregate usefulness: n/a (no usefulness scores recorded)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
