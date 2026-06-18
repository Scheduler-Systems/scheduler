"""web_qa_regression — the web QA agent's scheduled shift work: watch scheduler-web's
`main` for regressions and report.

Deployed-agent friendly: the observe path (read latest CI run + emit a verdict via
governance/OTel) is READ-ONLY and runs unattended with no human gate. Only the
issue-opening (write) passes the approval gate — so until the AUTO authority router lands
(epic #18), the write step is supervised; the read+verdict already works deployed.

State in: optional {target, branch}. State out: {conclusion, run_url, verdict, issue}.
"""
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END

from agent_toolkit import span, governance_capture, assert_not_model_work
from agent_toolkit.github_ops import GitHubOps

DEFAULT_TARGET = "Scheduler-Systems/scheduler-web"


class State(TypedDict, total=False):
    target: str
    branch: str
    conclusion: str
    run_url: str
    verdict: str
    issue: dict


def plan(state: State) -> dict:
    target = state.get("target", DEFAULT_TARGET)
    assert_not_model_work(target)  # Anthropic-terms guard
    return {"target": target, "branch": state.get("branch", "main")}


def check(state: State) -> dict:
    """Read-only recon — works unattended (no gate)."""
    with span("web_qa_regression.check", target=state["target"], branch=state["branch"]):
        try:
            info = GitHubOps().latest_run(state["target"], state["branch"])
            return {
                "conclusion": info.get("conclusion") or "",
                "run_url": info.get("html_url") or "",
            }
        except Exception as e:
            # Resilient: a deployed agent must complete + surface the cause, not crash.
            # Record only the exception TYPE — never str(e) — so no token/URL/secret that
            # might be in the message reaches the governance/observability sink.
            return {"conclusion": f"error: {type(e).__name__}", "run_url": ""}


def verdict(state: State) -> dict:
    c = state.get("conclusion") or ""
    if c.startswith("error:"):
        v = "error"  # recon failed — surface it, don't file a false regression
    elif c == "failure":
        v = "REGRESSION"
    else:
        v = "green"
    governance_capture(
        "web_qa_regression",
        {
            "target": state["target"],
            "branch": state["branch"],
            "conclusion": state.get("conclusion"),
            "verdict": v,
            "run_url": state.get("run_url"),
        },
    )
    return {"verdict": v}


def report(state: State) -> dict:
    """Write path — gated (supervised) until the AUTO authority router lands."""
    if state.get("verdict") != "REGRESSION":
        return {"issue": {"status": f"no-op ({state.get('verdict')})"}}
    body = (
        f"Regression detected on `{state['target']}@{state['branch']}`: the latest CI run "
        f"concluded **failure**.\n\nRun: {state.get('run_url')}\n\n"
        "Filed by the web QA agent on its scheduled shift."
    )
    res = GitHubOps().open_issue(
        state["target"], "QA: regression on main", body, labels=["gate:human-required"]
    )
    return {"issue": res}


builder = StateGraph(State)
builder.add_node("plan", plan)
builder.add_node("check", check)
builder.add_node("verdict", verdict)
builder.add_node("report", report)
builder.add_edge(START, "plan")
builder.add_edge("plan", "check")
builder.add_edge("check", "verdict")
builder.add_edge("verdict", "report")
builder.add_edge("report", END)

graph = builder.compile()  # NO checkpointer/store — injected by the platform
