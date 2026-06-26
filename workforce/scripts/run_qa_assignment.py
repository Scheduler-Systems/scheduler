"""Run the QA engineers' first REAL assignment: close the zero-e2e gap on the unmerged
schedule-creation branches (scheduler-api/web/ios/android).

QA = quality enablement (it unblocks shipping); it does not itself generate revenue.

SAFETY / PROBATION POSTURE:
- Default = REPORT-ONLY: each engineer runs in OBSERVE mode (read-only study of the branch's
  test setup + a draft of what e2e is missing). No CI dispatch, no outward writes, NO approval
  interrupt — safe to run unattended.
- QA_ASSIGNMENT_DISPATCH=1 (an ATTENDED activation step) runs the real path: the engineer
  dispatches its e2e CI workflow on the branch ref and drafts proposed actions. Proposed
  outward actions are collected REPORT-ONLY (printed / digested) and held at the engineers'
  human approval gate — never auto-approved, never merged (merges to prod repos are a human
  click, enforced by github_ops).

Usage:
    python scripts/run_qa_assignment.py            # report-only observe pass over all targets
    QA_ASSIGNMENT_DISPATCH=1 python scripts/run_qa_assignment.py   # attended: real e2e dispatch
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from importlib import import_module

from langgraph.checkpoint.memory import MemorySaver

from agent_toolkit import write_local_digest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MANIFEST = os.environ.get(
    "QA_ASSIGNMENT_MANIFEST", os.path.join(_REPO_ROOT, "docs", "qa", "first_assignment.json")
)


def _load_targets() -> list[dict]:
    try:
        with open(_MANIFEST, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return [t for t in (data.get("targets") or []) if isinstance(t, dict)]
    except Exception as exc:  # missing/corrupt manifest — degrade, don't crash
        print(f"[qa-assignment] could not read manifest {_MANIFEST}: {type(exc).__name__}")
        return []


def main() -> None:
    dispatch = os.environ.get("QA_ASSIGNMENT_DISPATCH", "").lower() in ("1", "true", "yes")
    mode_note = "REAL e2e dispatch (attended)" if dispatch else "report-only OBSERVE"
    targets = _load_targets()
    print(f"[qa-assignment] {mode_note} over {len(targets)} target(s)")

    lines = [f"QA first assignment — close the zero-e2e gap ({mode_note})", ""]
    for t in targets:
        engineer = t.get("engineer")
        repo = t.get("repo")
        branch = t.get("branch")
        if not engineer or not repo:
            continue
        entry = f"## {engineer} → {repo}@{branch}"
        try:
            mod = import_module(f"graphs.qa.{engineer}")
            graph = mod.builder.compile(checkpointer=MemorySaver())
            # report-only default = observe (no dispatch, no gate); dispatch flag = real path.
            state = {"target": repo, "ref": branch}
            if not dispatch:
                state["mode"] = "observe"
            cfg = {"configurable": {"thread_id": f"qa-assign-{engineer}"}}
            result = graph.invoke(state, cfg)
            # An approval gate (real path with proposed actions) surfaces as __interrupt__ —
            # collect it report-only; do NOT resume/approve here.
            pending = result.get("__interrupt__")
            report = result.get("report") or result.get("summary") or result.get("observations") or "(no report)"
            lines.append(entry)
            lines.append(f"- result: {str(report)[:600]}")
            if pending:
                lines.append(f"- ⏸️ AWAITING HUMAN APPROVAL (proposed actions): {str(pending)[:600]}")
            print(f"[qa-assignment] {engineer}: {'awaiting approval' if pending else 'done'}")
        except Exception as exc:  # one target failing must not kill the rest
            lines.append(entry)
            lines.append(f"- error: {type(exc).__name__}: {str(exc)[:200]}")
            print(f"[qa-assignment] {engineer} error: {type(exc).__name__}")
        lines.append("")

    path = write_local_digest("qa-first-assignment", "QA first assignment", "\n".join(lines))
    print(f"[qa-assignment] digest: {path}")


if __name__ == "__main__":
    main()
