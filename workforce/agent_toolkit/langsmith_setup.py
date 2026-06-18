"""Idempotent provisioning of the LangSmith LEARNING resources for scheduler-qa.

This sets up the *feedback loop* surface the QA agent fleet learns from:

  - a **dataset** (``scheduler-qa-learning``) — the growing corpus of QA examples
    (verdicts the team produced + human-corrected ground truth) used for regression
    and offline evaluation of the AGENTS' task output;
  - an **annotation queue** (``scheduler-qa-review``) — where a human reviews agent
    verdicts, supplying the ground truth that flows back into the dataset;
  - the agents' key **prompts** pushed to the LangSmith Prompt Hub as
    ``scheduler-qa-<agent>`` so prompts are versioned/diffable centrally;
  - an **LLM-as-judge** (:func:`llm_judge`) that scores an agent's verdict for
    correctness/usefulness.

Anthropic-terms posture (see workspace AGENTS.md): every function here evaluates the
**agent's task output (QA)** — "did this QA agent produce a correct, useful verdict?".
It does NOT train, fine-tune, evaluate, or distill any ML model. The judge call is
ordinary orchestration (an LLM scoring a text verdict), and its inputs are routed
through ``assert_not_model_work`` to keep that boundary explicit and enforced.

Design rules (match the rest of agent_toolkit):
  - Config is read from the ENVIRONMENT only — NEVER hardcode keys/ids/secrets:
      LANGSMITH_API_KEY, LANGSMITH_ENDPOINT, LANGSMITH_WORKSPACE_ID, LANGSMITH_PROJECT
  - Everything is idempotent (create-or-get) and FAIL-SAFE: a missing key, an offline
    backend, or an SDK hiccup must never crash the caller. Failures return a structured
    ``{"ok": False, "error": ...}`` (or a 0.0-scored judge dict) instead of raising.
  - ``main()`` prints a summary of names + ids only — NEVER secrets.
"""
from __future__ import annotations

import os
from typing import Any, Optional

# Resource names (the only "hardcoded" values — these are public identifiers, not secrets).
DATASET_NAME = "scheduler-qa-learning"
ANNOTATION_QUEUE_NAME = "scheduler-qa-review"
PROMPT_PREFIX = "scheduler-qa"
DEFAULT_ENDPOINT = "https://eu.api.smith.langchain.com"  # EU region


# ---------------------------------------------------------------------------
# Agent key-prompts — the load-bearing system instruction for each agent graph.
# Pushed to the Prompt Hub as ``scheduler-qa-<agent>`` so prompts are versioned and
# diffable centrally. These mirror the system instructions embedded in graphs/qa/*.py;
# the Prompt Hub becomes the single source the agents (and humans) review/iterate on.
# ---------------------------------------------------------------------------
AGENT_PROMPTS: dict[str, str] = {
    "qa_lead_aggregator": (
        "You are the QA lead for the Scheduler product (web, android, ios). "
        "You COORDINATE only: heavy suites run on CI/runners, never in this agent. "
        "Given each platform's verdict, write a 2-4 sentence shippability summary for "
        "the PR. Be concrete about what blocks shipping. Do NOT change the overall "
        "decision; pass/block is computed deterministically (anything not an explicit "
        "pass blocks). Report-only: any PR comment is gated by human approval."
    ),
    "web_automation_engineer": (
        "You are a web QA automation engineer for the scheduler-web Next.js app. "
        "Vitest unit + Playwright e2e suites are DISPATCHED to GitHub Actions (you never "
        "run them locally). Playwright runs in CI with 2 retries, so a test that fails "
        "then passes on retry is FLAKY, not a regression. Write a concise pass/fail "
        "summary, then on a final line output exactly:\n"
        "CLASSIFICATION: <flaky|regression|mixed|indeterminate>\n"
        "Use 'indeterminate' if the suites could not be dispatched. Report-only: any "
        "issue/PR-comment write is gated by human approval."
    ),
    "android_automation_engineer": (
        "You are an Android QA automation engineer for the scheduler-android app. "
        "JUnit unit + Espresso instrumented suites are DISPATCHED to CI (./gradlew "
        "testDebugUnitTest, ./gradlew connectedDebugAndroidTest); you never run an "
        "emulator in this agent. Summarize pass/fail, then on a final line output "
        "exactly:\nCLASSIFICATION: <flaky|regression|mixed|indeterminate>\n"
        "Report-only: any outward write is gated by human approval."
    ),
    "ios_automation_engineer": (
        "You are an iOS QA automation engineer for the scheduler-ios app. XCTest suites "
        "are DISPATCHED to CI (swift test); you never run a simulator in this agent. "
        "Summarize pass/fail, then on a final line output exactly:\n"
        "CLASSIFICATION: <flaky|regression|mixed|indeterminate>\n"
        "Report-only: any outward write is gated by human approval."
    ),
    "web_manual_tester": (
        "You are an exploratory QA tester for the scheduler-web app, driving a headless "
        "browser. Explore real user flows (auth, schedule build, chat, billing/paywall), "
        "look for broken UX, errors, and regressions versus expected behavior. Produce a "
        "concise verdict with concrete, reproducible findings. Report-only: any bug "
        "issue/comment is gated by human approval."
    ),
    "android_manual_tester": (
        "You are an exploratory QA tester for the scheduler-android app on an emulator "
        "(Stratus Mac node). Explore real user flows, look for broken UX, crashes, and "
        "regressions. Produce a concise verdict with concrete, reproducible findings. "
        "Report-only: any bug issue/comment is gated by human approval."
    ),
    "ios_manual_tester": (
        "You are an exploratory QA tester for the scheduler-ios app on a simulator "
        "(Stratus Mac node). Explore real user flows, look for broken UX, crashes, and "
        "regressions. Produce a concise verdict with concrete, reproducible findings. "
        "Report-only: any bug issue/comment is gated by human approval."
    ),
}

# LLM-as-judge instruction — scores an AGENT's QA verdict (task output), NOT a model.
_JUDGE_SYSTEM = (
    "You are an impartial QA reviewer. You are given a QA agent's verdict about a "
    "software change, plus (optionally) the reference/ground-truth verdict a human "
    "recorded. Judge ONLY the agent's task output on two axes:\n"
    "  - correctness: does the agent's verdict match the reference / the evidence?\n"
    "  - usefulness:  is it specific, actionable, and reproducible for an engineer?\n"
    "Return STRICT JSON with keys: correctness (0.0-1.0), usefulness (0.0-1.0), "
    "score (0.0-1.0 overall), comment (one short sentence). No prose outside the JSON."
)


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------
def _endpoint() -> str:
    return (os.environ.get("LANGSMITH_ENDPOINT") or DEFAULT_ENDPOINT).rstrip("/")


def get_client():
    """Build a LangSmith ``Client`` from the environment, or return None (fail-safe).

    Workspace selection for org-scoped keys is driven by ``LANGSMITH_WORKSPACE_ID``,
    which the SDK reads from the env — we ensure it's set in ``os.environ`` (if provided)
    before constructing the client so it is sent as the tenant header.
    """
    api_key = os.environ.get("LANGSMITH_API_KEY")
    if not api_key:
        return None
    # The SDK reads LANGSMITH_WORKSPACE_ID from the env to scope org-keys; make sure
    # it's present in the process env before we construct the client.
    ws = os.environ.get("LANGSMITH_WORKSPACE_ID")
    if ws:
        os.environ["LANGSMITH_WORKSPACE_ID"] = ws
    try:
        from langsmith import Client

        return Client(api_url=_endpoint(), api_key=api_key)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Dataset (create-or-get)
# ---------------------------------------------------------------------------
def ensure_dataset(name: str = DATASET_NAME, *, client: Optional[Any] = None) -> dict:
    """Idempotently create-or-get the QA learning dataset.

    Returns ``{"ok": bool, "name": str, "id": Optional[str], "created": bool, "error": ...}``.
    Never raises.
    """
    client = client or get_client()
    if client is None:
        return {"ok": False, "name": name, "id": None, "created": False,
                "error": "LANGSMITH_API_KEY not set"}
    description = (
        "Scheduler QA learning corpus: agent verdicts + human-corrected ground truth, "
        "used for offline evaluation of QA AGENT output (not model training)."
    )
    try:
        if client.has_dataset(dataset_name=name):
            ds = client.read_dataset(dataset_name=name)
            return {"ok": True, "name": name, "id": str(ds.id), "created": False, "error": None}
        ds = client.create_dataset(name, description=description)
        return {"ok": True, "name": name, "id": str(ds.id), "created": True, "error": None}
    except Exception as exc:  # offline / perms / SDK drift — degrade, don't crash
        return {"ok": False, "name": name, "id": None, "created": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Annotation queue (create-or-get)
# ---------------------------------------------------------------------------
def ensure_annotation_queue(name: str = ANNOTATION_QUEUE_NAME, *, client: Optional[Any] = None) -> dict:
    """Idempotently create-or-get the human-review annotation queue.

    Returns ``{"ok": bool, "name": str, "id": Optional[str], "created": bool, "error": ...}``.
    Never raises.
    """
    client = client or get_client()
    if client is None:
        return {"ok": False, "name": name, "id": None, "created": False,
                "error": "LANGSMITH_API_KEY not set"}
    try:
        # 1) Reuse an existing queue by name (idempotent).
        try:
            for q in client.list_annotation_queues():
                if getattr(q, "name", None) == name:
                    return {"ok": True, "name": name, "id": str(q.id), "created": False, "error": None}
        except Exception:
            pass  # listing failed — fall through to create (create-or-get is best-effort)

        # 2) Otherwise create it with a QA rubric (correctness + usefulness + notes).
        rubric_items = [
            {
                "feedback_key": "correctness",
                "description": "Does the agent's verdict match the evidence / ground truth?",
                "score_descriptions": {"0": "Wrong verdict", "1": "Correct verdict"},
                "is_required": True,
            },
            {
                "feedback_key": "usefulness",
                "description": "Is the finding specific, actionable, and reproducible?",
                "score_descriptions": {"0": "Not actionable", "1": "Clear and reproducible"},
                "is_required": True,
            },
            {
                "feedback_key": "notes",
                "description": "Reviewer notes / corrected ground truth",
                "is_required": False,
            },
        ]
        try:
            q = client.create_annotation_queue(
                name=name,
                description="Human review of scheduler-qa agent verdicts (feeds the learning dataset).",
                rubric_instructions=(
                    "Score each QA agent verdict for correctness and usefulness. Add the "
                    "corrected ground-truth verdict in notes so it can flow into the dataset."
                ),
                rubric_items=rubric_items,
            )
        except TypeError:
            # Older/newer SDKs may not accept rubric kwargs — fall back to a plain queue.
            q = client.create_annotation_queue(
                name=name,
                description="Human review of scheduler-qa agent verdicts.",
            )
        return {"ok": True, "name": name, "id": str(q.id), "created": True, "error": None}
    except Exception as exc:
        return {"ok": False, "name": name, "id": None, "created": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Prompt Hub push
# ---------------------------------------------------------------------------
def _build_chat_prompt(system_text: str):
    """Build a ChatPromptTemplate (system + user{question}) or None if langchain is absent."""
    try:
        from langchain_core.prompts import ChatPromptTemplate

        return ChatPromptTemplate(
            [("system", system_text), ("user", "{input}")]
        )
    except Exception:
        return None


def push_agent_prompts(*, client: Optional[Any] = None, prompts: Optional[dict] = None) -> dict:
    """Push each agent's key prompt to the Prompt Hub as ``scheduler-qa-<agent>``.

    Idempotent: ``push_prompt`` creates the prompt or commits a new version. Fail-safe:
    a failure on one prompt does not stop the others.

    Returns ``{"ok": bool, "pushed": {<identifier>: <url|None>}, "errors": {<id>: <msg>}}``.
    Never raises.
    """
    client = client or get_client()
    prompts = prompts or AGENT_PROMPTS
    out: dict[str, Any] = {"ok": False, "pushed": {}, "errors": {}}
    if client is None:
        out["errors"]["*"] = "LANGSMITH_API_KEY not set"
        return out

    for agent, system_text in prompts.items():
        identifier = f"{PROMPT_PREFIX}-{agent}"
        try:
            obj = _build_chat_prompt(system_text)
            if obj is None:
                out["errors"][identifier] = "langchain_core not available to build prompt object"
                continue
            url = client.push_prompt(identifier, object=obj)
            out["pushed"][identifier] = url
        except Exception as exc:  # per-prompt isolation
            out["errors"][identifier] = str(exc)

    out["ok"] = bool(out["pushed"]) and not out["errors"]
    return out


# ---------------------------------------------------------------------------
# LLM-as-judge (scores the AGENT's QA verdict — NOT a model)
# ---------------------------------------------------------------------------
def _extract_text(obj: Any, *keys: str) -> str:
    """Best-effort pull of a text field from a LangSmith run/example or a plain dict."""
    if obj is None:
        return ""
    holder = None
    for attr in ("outputs", "inputs"):
        holder = getattr(obj, attr, None) if not isinstance(obj, dict) else obj.get(attr)
        if isinstance(holder, dict):
            for k in keys:
                if k in holder and holder[k] is not None:
                    return str(holder[k])
    if isinstance(obj, dict):
        for k in keys:
            if k in obj and obj[k] is not None:
                return str(obj[k])
    return ""


def llm_judge(run: Any, example: Any = None) -> dict:
    """LLM-as-judge: score a QA agent's verdict for correctness + usefulness.

    Evaluator signature compatible with ``client.evaluate`` (``(run, example) -> dict``).
    This scores the AGENT's task output (a QA verdict) — it is NOT model training,
    fine-tuning, evaluation, or distillation. The judged content is routed through the
    Anthropic-terms guard to keep that boundary explicit and enforced.

    Returns a feedback dict: ``{"key": "qa_verdict_quality", "score": float,
    "correctness": float, "usefulness": float, "comment": str}``. Never raises; on any
    failure returns a 0.0 score with an explanatory comment.
    """
    # Pull the agent's verdict (run output) and the reference verdict (example output).
    agent_verdict = _extract_text(run, "verdict", "report", "summary", "output")
    reference = _extract_text(example, "verdict", "report", "answer", "expected", "output") if example else ""
    context = _extract_text(run, "target", "input", "question") or _extract_text(example, "input", "question")

    failsafe = {
        "key": "qa_verdict_quality",
        "score": 0.0,
        "correctness": 0.0,
        "usefulness": 0.0,
        "comment": "judge unavailable",
    }

    # Anthropic-terms guard: this is QA of agent output, not model work. Make it explicit
    # and FAIL-CLOSED — if any judged input string trips the model-development denylist,
    # refuse to judge (score 0). If the guard module is simply unavailable, QA is still
    # permitted, so proceed.
    try:
        from agent_toolkit.policy import assert_not_model_work, ModelWorkBlocked
    except Exception:
        assert_not_model_work = None  # guard unavailable -> QA proceeds
        ModelWorkBlocked = ()
    if assert_not_model_work is not None:
        try:
            for s in (context, reference, agent_verdict):
                assert_not_model_work(s)
        except ModelWorkBlocked as exc:
            return {**failsafe, "comment": f"refused (model-dev denylist): {exc}"}

    if not agent_verdict:
        return {**failsafe, "comment": "no agent verdict to judge"}

    # Use the project's cost-first model router (orchestration config; not model dev).
    try:
        from agent_toolkit.models import get_model, TIER_DEFAULT

        model = get_model(TIER_DEFAULT)
    except Exception as exc:
        return {**failsafe, "comment": f"no judge model configured: {exc}"}

    user = (
        f"CONTEXT (what was tested): {context or 'n/a'}\n\n"
        f"AGENT VERDICT (judge this):\n{agent_verdict}\n\n"
        f"REFERENCE VERDICT (ground truth, may be empty):\n{reference or 'n/a'}\n\n"
        "Return the strict JSON described in the system message."
    )
    try:
        resp = model.invoke([("system", _JUDGE_SYSTEM), ("user", user)])
        text = getattr(resp, "content", str(resp)) or ""
        parsed = _parse_judge_json(text)
        return {
            "key": "qa_verdict_quality",
            "score": _clamp(parsed.get("score")),
            "correctness": _clamp(parsed.get("correctness")),
            "usefulness": _clamp(parsed.get("usefulness")),
            "comment": str(parsed.get("comment", ""))[:500],
        }
    except Exception as exc:  # model/network failure must not crash an eval run
        return {**failsafe, "comment": f"judge error: {exc}"}


def _clamp(v: Any) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, f))


def _parse_judge_json(text: str) -> dict:
    """Tolerantly parse the judge's JSON (handles ```json fences / surrounding prose)."""
    import json
    import re

    if not text:
        return {}
    # Try the whole string, then the first {...} block.
    for candidate in (text, *re.findall(r"\{.*?\}", text, flags=re.DOTALL)):
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj
        except Exception:
            continue
    return {}


# ---------------------------------------------------------------------------
# main — provision everything and print a summary (names + ids only; NO secrets)
# ---------------------------------------------------------------------------
def main() -> dict:
    """Provision dataset + annotation queue + prompts; print a no-secrets summary."""
    client = get_client()

    summary: dict[str, Any] = {
        "endpoint": _endpoint(),
        "workspace_id_set": bool(os.environ.get("LANGSMITH_WORKSPACE_ID")),
        "project": os.environ.get("LANGSMITH_PROJECT", "scheduler-qa"),
        "api_key_present": bool(os.environ.get("LANGSMITH_API_KEY")),
    }

    dataset = ensure_dataset(client=client)
    queue = ensure_annotation_queue(client=client)
    prompts = push_agent_prompts(client=client)

    summary["dataset"] = {"name": dataset["name"], "id": dataset["id"],
                          "created": dataset["created"], "ok": dataset["ok"],
                          "error": dataset["error"]}
    summary["annotation_queue"] = {"name": queue["name"], "id": queue["id"],
                                   "created": queue["created"], "ok": queue["ok"],
                                   "error": queue["error"]}
    summary["prompts"] = {
        "ok": prompts["ok"],
        "pushed": sorted(prompts["pushed"].keys()),
        "errors": prompts["errors"],
    }

    # --- Human-readable summary (no secrets) ---
    print("LangSmith setup — scheduler-qa")
    print(f"  endpoint           : {summary['endpoint']}")
    print(f"  project            : {summary['project']}")
    print(f"  api key present    : {summary['api_key_present']}")
    print(f"  workspace id set   : {summary['workspace_id_set']}")
    if not summary["api_key_present"]:
        print("  (LANGSMITH_API_KEY not set — nothing provisioned; this is a dry summary.)")
    print(
        f"  dataset            : {dataset['name']} "
        f"id={dataset['id']} created={dataset['created']} ok={dataset['ok']}"
        + (f" error={dataset['error']}" if dataset["error"] else "")
    )
    print(
        f"  annotation queue   : {queue['name']} "
        f"id={queue['id']} created={queue['created']} ok={queue['ok']}"
        + (f" error={queue['error']}" if queue["error"] else "")
    )
    print(f"  prompts pushed     : {summary['prompts']['pushed'] or 'none'}")
    if summary["prompts"]["errors"]:
        print(f"  prompt errors      : {summary['prompts']['errors']}")

    return summary


if __name__ == "__main__":
    main()
