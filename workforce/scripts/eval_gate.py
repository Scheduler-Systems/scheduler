"""eval_gate — pre-redeploy GATE: BLOCK a prompt/graph change that REGRESSES the agents.

The guard for "do not ship a prompt change that regresses the agents". The conversational
-CFO prompt + the governed-prompt-pull changes need a redeploy; this is what runs FIRST.

What it does:
  1. Runs the offline EVALUATION (``agent_toolkit.evaluations.run_evaluation``) on a
     CANDIDATE target (a graph or a prompt-under-test) over the ``scheduler-qa-eval``
     dataset, scored by the LLM-as-judge.
  2. Compares the candidate's AGGREGATE to a BASELINE score — a stored baseline file
     (``.eval/baseline.json``) OR a baseline target you run in the same pass (e.g. the
     currently deployed prompt). Prints a per-example + aggregate DIFF.
  3. EXITS NON-ZERO if the candidate regresses beyond ``--threshold`` (env
     ``REGRESSION_THRESHOLD``, default 0.05); exits 0 if it holds or improves.

It is **report-only / dry by default**: it SCORES and BLOCKS. It NEVER deploys, posts,
or moves money. ``--update-baseline`` only rewrites the local baseline file (a score
record) — it still does not deploy. The redeploy itself is a separate, human-gated step.

FAIL-SAFE semantics (the important ones for a gate):
  - A judge/target/network ERROR must NOT falsely PASS. If the candidate could not be
    scored (no aggregate), the gate BLOCKS (exit != 0) with a clear reason — a gate that
    degrades OPEN is worse than no gate.
  - The Anthropic-terms guard is enforced by the runner: a denylisted candidate is REFUSED
    and the gate BLOCKS.

Exit codes:
  0  candidate holds/improves vs baseline (within threshold)        -> redeploy may proceed
  1  candidate REGRESSED beyond threshold                            -> BLOCK redeploy
  2  candidate could not be scored (judge/target/creds error)        -> BLOCK (fail-safe)
  3  candidate REFUSED (model-dev denylist)                          -> BLOCK

Config from the ENVIRONMENT only — NEVER hardcode keys/ids/secrets:
  LANGSMITH_API_KEY, LANGSMITH_ENDPOINT, LANGSMITH_WORKSPACE_ID/TENANT_ID,
  REGRESSION_THRESHOLD.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Callable, Optional

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# Module-level so they are patchable in tests (no network at import — both are lazy).
from agent_toolkit.evaluations import run_evaluation  # noqa: E402
from agent_toolkit.langsmith_setup import get_client  # noqa: E402

DATASET_NAME = "scheduler-qa-eval"
BASELINE_PATH = os.path.join(_REPO_ROOT, ".eval", "baseline.json")
DEFAULT_THRESHOLD = 0.05

# Exit codes (see module docstring).
EXIT_PASS = 0
EXIT_REGRESSED = 1
EXIT_UNSCORED = 2
EXIT_REFUSED = 3


# ---------------------------------------------------------------------------
# Env bootstrap (fail-safe) — mirror run_eval so creds resolve identically.
# ---------------------------------------------------------------------------
def _load_env() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(os.path.join(_REPO_ROOT, ".env"))
    except Exception:
        pass
    ws = os.environ.get("LANGSMITH_WORKSPACE_ID") or os.environ.get("LANGSMITH_TENANT_ID")
    if ws:
        os.environ["LANGSMITH_WORKSPACE_ID"] = ws
    endpoint = os.environ.get("LANGSMITH_ENDPOINT")
    if endpoint:
        os.environ.setdefault("LANGCHAIN_ENDPOINT", endpoint)


def _threshold(cli_value: Optional[float]) -> float:
    if cli_value is not None:
        return cli_value
    raw = os.environ.get("REGRESSION_THRESHOLD")
    try:
        return float(raw) if raw is not None else DEFAULT_THRESHOLD
    except (TypeError, ValueError):
        return DEFAULT_THRESHOLD


# ---------------------------------------------------------------------------
# Baseline persistence (a local SCORE record — never a deploy).
# ---------------------------------------------------------------------------
def load_baseline(path: str = BASELINE_PATH) -> Optional[dict]:
    """Read the stored baseline record, or None if absent/unreadable. Never raises."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and data.get("aggregate") is not None:
            return data
    except Exception:
        return None
    return None


def save_baseline(report: Any, path: str = BASELINE_PATH) -> bool:
    """Write the candidate's aggregate (+ per-example scores) as the new baseline.

    Report-only: this only rewrites a LOCAL score record; it does NOT deploy. Never raises.
    """
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        record = {
            "aggregate": report.aggregate,
            "n_scored": report.n_scored,
            "n_total": report.n_total,
            "target_name": report.target_name,
            "dataset_name": report.dataset_name,
            "per_example": [
                {"index": s.index, "score": s.score, "key": s.key} for s in report.scores
            ],
        }
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(record, fh, indent=2, sort_keys=True)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Candidate / baseline target resolution
# ---------------------------------------------------------------------------
def _prompt_target(prompt_text: str) -> Callable[[dict], dict]:
    """Build a target that scores a PROMPT-UNDER-TEST against each example.

    For a prompt change we do not need to run the whole graph: we run the model with the
    candidate ``prompt_text`` as the system message and the example's question/inputs as
    the user turn, and let the judge score the answer vs the reference. This is what makes
    the gate able to compare a CANDIDATE prompt to the deployed one cheaply.

    Fail-safe: if no model is configured, the target returns an ``error`` output (which the
    runner records as an unscored example -> the gate fails safe, not open).
    """

    def target(inputs: dict) -> dict:
        try:
            from agent_toolkit.models import get_model, TIER_DEFAULT

            model = get_model(TIER_DEFAULT)
        except Exception as exc:
            return {"error": f"no model: {type(exc).__name__}"}
        user = _example_user_turn(inputs)
        try:
            resp = model.invoke([("system", prompt_text), ("user", user)])
            text = getattr(resp, "content", str(resp)) or ""
            return {"report": str(text), "summary": str(text)[:500]}
        except Exception as exc:
            return {"error": type(exc).__name__}

    return target


def _example_user_turn(inputs: dict) -> str:
    """Compose the user turn for a prompt-under-test from an example's inputs."""
    parts = []
    if inputs.get("question"):
        parts.append(str(inputs["question"]))
    if inputs.get("report"):
        parts.append(f"DATA:\n{inputs['report']}")
    if inputs.get("target"):
        parts.append(f"TARGET: {inputs['target']}")
    if inputs.get("mode"):
        parts.append(f"MODE: {inputs['mode']}")
    return "\n\n".join(parts) or json.dumps(inputs, default=str)[:2000]


def _graph_target(import_path: str) -> Callable[[dict], dict]:
    """Build a target that invokes a compiled graph by ``module:graph_attr`` path.

    e.g. ``graphs.qa.web_automation_engineer:builder`` (a StateGraph builder we compile) or
    ``graphs.exec.cfo_deepagents:graph`` (an already-compiled deep agent). Observe/read-only
    inputs are passed through. Fail-safe: import/compile/invoke errors become an ``error``
    output so the gate fails SAFE (the example is unscored), never open.
    """

    def target(inputs: dict) -> dict:
        try:
            graph = _resolve_graph(import_path)
        except Exception as exc:
            return {"error": f"graph import: {type(exc).__name__}"}
        try:
            payload = {"mode": "observe", **(inputs or {})}
            r = graph.invoke(payload) or {}
            if not isinstance(r, dict):
                return {"output": str(r)}
            return {
                "report": r.get("report"),
                "verdict": r.get("verdict"),
                "summary": (r.get("summary") or r.get("observations") or "")[:500],
            }
        except Exception as exc:
            return {"error": type(exc).__name__}

    return target


def _resolve_graph(import_path: str):
    """Import ``module:attr`` and return a compiled graph (compile a builder if needed)."""
    import importlib

    mod_name, _, attr = import_path.partition(":")
    attr = attr or "graph"
    module = importlib.import_module(mod_name)
    obj = getattr(module, attr)
    # A StateGraph builder needs compiling; a CompiledStateGraph already has .invoke.
    if hasattr(obj, "invoke"):
        return obj
    if hasattr(obj, "compile"):
        return obj.compile()
    raise TypeError(f"{import_path} is neither a compiled graph nor a builder")


# ---------------------------------------------------------------------------
# Diff printing
# ---------------------------------------------------------------------------
def _print_report(label: str, report: Any) -> None:
    print(f"  [{label}] target={report.target_name}")
    print(f"  [{label}] dataset={report.dataset_name} scored={report.n_scored}/{report.n_total}")
    for s in report.scores:
        score_str = f"{s.score:.3f}" if s.score is not None else "  n/a"
        note = f"  ({s.error})" if s.error else ""
        print(f"    ex#{s.index:<2} score={score_str}{note}  {s.comment[:80]}")
    agg = f"{report.aggregate:.3f}" if report.aggregate is not None else "n/a"
    print(f"  [{label}] AGGREGATE={agg}")


def _print_diff(candidate: Any, baseline_agg: Optional[float], baseline_per: Optional[list]) -> None:
    print("")
    print("PER-EXAMPLE DIFF (candidate vs baseline):")
    base_by_index = {}
    for b in (baseline_per or []):
        if isinstance(b, dict) and b.get("index") is not None:
            base_by_index[b["index"]] = b.get("score")
    for s in candidate.scores:
        c = s.score
        b = base_by_index.get(s.index)
        c_str = f"{c:.3f}" if c is not None else " n/a"
        b_str = f"{b:.3f}" if b is not None else " n/a"
        if c is not None and b is not None:
            d = c - b
            d_str = f"{d:+.3f}"
        else:
            d_str = "  n/a"
        print(f"    ex#{s.index:<2} candidate={c_str}  baseline={b_str}  delta={d_str}")


# ---------------------------------------------------------------------------
# The gate decision (pure, testable).
# ---------------------------------------------------------------------------
def decide(
    candidate_agg: Optional[float],
    baseline_agg: Optional[float],
    threshold: float,
) -> tuple[int, str]:
    """Return ``(exit_code, reason)`` for the gate.

    - candidate unscored (None aggregate)  -> EXIT_UNSCORED (fail-safe BLOCK).
    - no baseline                          -> PASS (nothing to regress against; first run).
    - candidate < baseline - threshold     -> EXIT_REGRESSED (BLOCK).
    - else                                 -> PASS.
    """
    if candidate_agg is None:
        return EXIT_UNSCORED, "candidate produced no aggregate score (judge/target/creds error) — BLOCKING fail-safe"
    if baseline_agg is None:
        return EXIT_PASS, f"no baseline to compare (candidate={candidate_agg:.3f}) — PASS (record a baseline with --update-baseline)"
    delta = candidate_agg - baseline_agg
    # A regression of EXACTLY the threshold is allowed (threshold is inclusive); a tiny
    # epsilon absorbs float error so e.g. 0.75 vs 0.80 at threshold 0.05 is treated as
    # the boundary (PASS), not a spurious block from 0.05000000000000004.
    if delta < -abs(threshold) - 1e-9:
        return EXIT_REGRESSED, (
            f"REGRESSION: candidate {candidate_agg:.3f} < baseline {baseline_agg:.3f} "
            f"(delta {delta:+.3f}, beyond -{abs(threshold):.3f}) — BLOCKING redeploy"
        )
    return EXIT_PASS, (
        f"candidate {candidate_agg:.3f} vs baseline {baseline_agg:.3f} "
        f"(delta {delta:+.3f}, within -{abs(threshold):.3f}) — PASS"
    )


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def _build_candidate_target(args) -> tuple[Optional[Callable[[dict], dict]], str, Optional[str]]:
    """Resolve the candidate target + its guard name. Returns (target, name, error)."""
    if args.candidate_graph:
        return _graph_target(args.candidate_graph), args.candidate_graph, None
    if args.candidate_prompt_file:
        try:
            with open(args.candidate_prompt_file, "r", encoding="utf-8") as fh:
                text = fh.read()
        except Exception as exc:
            return None, args.candidate_prompt_file, f"cannot read prompt file: {type(exc).__name__}"
        return _prompt_target(text), f"prompt:{os.path.basename(args.candidate_prompt_file)}", None
    return None, "", "no candidate given (--candidate-graph or --candidate-prompt-file required)"


def main(argv: Optional[list] = None) -> int:
    _load_env()
    parser = argparse.ArgumentParser(description="Pre-redeploy eval gate (report-only; blocks, never ships).")
    parser.add_argument("--candidate-graph", help="module:attr of the candidate graph (e.g. graphs.exec.cfo_deepagents:graph)")
    parser.add_argument("--candidate-prompt-file", help="path to a candidate system-prompt file to score")
    parser.add_argument("--baseline-graph", help="module:attr of a baseline graph to score in the same pass (else uses the stored baseline file)")
    parser.add_argument("--baseline-prompt-file", help="path to a baseline system-prompt file to score in the same pass")
    parser.add_argument("--threshold", type=float, default=None, help="max allowed regression (default REGRESSION_THRESHOLD or 0.05)")
    parser.add_argument("--update-baseline", action="store_true", help="rewrite the local baseline file with this candidate's scores (does NOT deploy)")
    parser.add_argument("--baseline-path", default=BASELINE_PATH)
    args = parser.parse_args(argv)

    threshold = _threshold(args.threshold)
    client = get_client()  # may be None -> offline local-seed eval

    print("eval_gate — pre-redeploy regression gate (report-only; blocks, never ships)")
    print(f"  dataset={DATASET_NAME}  threshold={threshold:.3f}  client={'yes' if client else 'none (offline seed)'}")

    target, target_name, terr = _build_candidate_target(args)
    if target is None:
        print(f"  ERROR: {terr}")
        return EXIT_UNSCORED

    candidate = run_evaluation(
        target, dataset_name=DATASET_NAME, target_name=target_name, client=client,
    )
    print("")
    _print_report("candidate", candidate)

    if candidate.refused:
        print(f"  REFUSED: {candidate.error}")
        return EXIT_REFUSED

    # Baseline: a same-pass baseline target wins; else the stored baseline file.
    baseline_agg: Optional[float] = None
    baseline_per: Optional[list] = None
    if args.baseline_graph or args.baseline_prompt_file:
        if args.baseline_graph:
            btarget, bname = _graph_target(args.baseline_graph), args.baseline_graph
        else:
            try:
                with open(args.baseline_prompt_file, "r", encoding="utf-8") as fh:
                    btarget, bname = _prompt_target(fh.read()), f"prompt:{os.path.basename(args.baseline_prompt_file)}"
            except Exception as exc:
                print(f"  baseline prompt unreadable ({type(exc).__name__}) — falling back to stored baseline")
                btarget = None
                bname = ""
        if btarget is not None:
            base_report = run_evaluation(btarget, dataset_name=DATASET_NAME, target_name=bname, client=client)
            print("")
            _print_report("baseline ", base_report)
            baseline_agg = base_report.aggregate
            baseline_per = [{"index": s.index, "score": s.score} for s in base_report.scores]
    if baseline_agg is None:
        stored = load_baseline(args.baseline_path)
        if stored is not None:
            baseline_agg = stored.get("aggregate")
            baseline_per = stored.get("per_example")
            print(f"\n  baseline (stored): aggregate={baseline_agg}  from {args.baseline_path}")

    _print_diff(candidate, baseline_agg, baseline_per)

    exit_code, reason = decide(candidate.aggregate, baseline_agg, threshold)
    # When the candidate could not be trusted (no aggregate), surface the runner's specific
    # reason — most importantly the COVERAGE-FLOOR block, where the candidate scored only a
    # subset of the dataset (a regression that breaks the agent on some inputs). decide()
    # only sees the aggregate (None) so it emits a generic message; the precise cause lives
    # on candidate.error. This does not change the exit code — it just makes the block legible.
    if exit_code == EXIT_UNSCORED and candidate.error:
        reason = f"{candidate.error} [scored {candidate.n_scored}/{candidate.n_total}]"
    print("")
    print(f"GATE: {reason}")

    if args.update_baseline:
        if candidate.aggregate is None:
            print("  --update-baseline IGNORED: candidate has no aggregate to record.")
        elif save_baseline(candidate, args.baseline_path):
            print(f"  baseline updated -> {args.baseline_path} (score record only; NOT a deploy).")
        else:
            print("  baseline update FAILED (could not write file).")

    print(f"  exit={exit_code} ({'PASS — redeploy may proceed' if exit_code == EXIT_PASS else 'BLOCK redeploy'})")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
