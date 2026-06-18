"""git_maintainer — the REMOTE git-hygiene agent's scheduled shift.

Across the allow-listed repos it: lists branches (read-only), classifies each, and
then on its own authority does ONLY the provably-safe, reversible prune —
**deletes branches whose PR is already merged** (recoverable from the merge commit).
Everything else (branches with no PR, or whose PR was closed-without-merge) is
PROPOSED in a single `gate:human-required` digest issue, never auto-deleted. The
default branch and protected names are refused by `github_ops` itself.

Deployed-agent friendly:
  * recon (list_branches / branch_merged_pr) is READ-ONLY, no gate, runs unattended;
  * the prune uses `github_ops.delete_branch`, which under AGENT_AUTONOMY=auto
    auto-proceeds ONLY for merged branches and gates everything else (so an
    unattended cron can never delete unmerged work — it raises and we propose it);
  * the digest issue uses `open_issue`, a SAFE_AUTO action.

State in: optional {repos}. State out: {pruned, proposals, errors, report}.
"""
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END

from agent_toolkit import span, governance_capture, assert_not_model_work
from agent_toolkit.github_ops import GitHubOps, ALLOWED_REPOS, _PROTECTED_BRANCHES

# The maintainer's own home — where the human-facing digest is filed.
DIGEST_REPO = "gal-run/agent-workforce"


class State(TypedDict, total=False):
    repos: list[str]
    prune_candidates: list[dict]
    proposals: list[dict]
    pruned: list[dict]
    errors: list[dict]
    report: dict


def plan(state: State) -> dict:
    repos = state.get("repos") or sorted(ALLOWED_REPOS)
    for r in repos:
        assert_not_model_work(r)  # Anthropic-terms guard, defense in depth
    return {"repos": repos}


def sweep(state: State) -> dict:
    """Read-only recon: classify every branch across the repos. No gate, no writes."""
    ops = GitHubOps()
    prune_candidates: list[dict] = []
    proposals: list[dict] = []
    errors: list[dict] = []
    with span("git_maintainer.sweep", repos=len(state["repos"])):
        for repo in state["repos"]:
            try:
                branches = ops.list_branches(repo)
            except Exception as e:
                # Surface the cause by TYPE only — never str(e) (may carry token/URL).
                errors.append({"repo": repo, "stage": "list_branches", "error": type(e).__name__})
                continue
            for b in branches:
                name = b["name"]
                if b["is_default"] or b["protected"] or name in _PROTECTED_BRANCHES:
                    continue
                try:
                    pr = ops.branch_merged_pr(repo, name)
                except Exception as e:
                    errors.append({"repo": repo, "branch": name, "stage": "pr", "error": type(e).__name__})
                    continue
                if pr.get("open"):
                    continue  # active PR — leave it alone
                if pr.get("merged"):
                    prune_candidates.append({"repo": repo, "branch": name, "sha": b["sha"]})
                else:
                    # no PR, or a PR closed without merging — NOT provably safe → propose
                    reason = "no PR for branch" if not pr.get("has_pr") else "PR closed unmerged"
                    proposals.append({"repo": repo, "branch": name, "sha": b["sha"], "reason": reason})
    return {"prune_candidates": prune_candidates, "proposals": proposals, "errors": errors}


def act(state: State) -> dict:
    """Auto-prune the provably-safe (merged) branches. Anything that can't be
    auto-deleted (blocked/not-configured) drops to the proposal list — never forced."""
    ops = GitHubOps()
    pruned: list[dict] = []
    proposals = list(state.get("proposals", []))
    errors = list(state.get("errors", []))
    with span("git_maintainer.act", candidates=len(state.get("prune_candidates", []))):
        for c in state.get("prune_candidates", []):
            try:
                res = ops.delete_branch(c["repo"], c["branch"], reason="merged-PR branch (auto-prune-safe)")
                if res.get("status") == "deleted":
                    pruned.append(res)
                else:  # report_only or unexpected — treat as a proposal, don't claim a delete
                    proposals.append({**c, "reason": f"not deleted ({res.get('status')})"})
            except Exception as e:
                # delete_branch fail-closed (e.g. gate refused, not configured) → propose it
                proposals.append({**c, "reason": f"auto-prune blocked ({type(e).__name__})"})
    return {"pruned": pruned, "proposals": proposals, "errors": errors}


def report(state: State) -> dict:
    pruned = state.get("pruned", [])
    proposals = state.get("proposals", [])
    errors = state.get("errors", [])
    governance_capture(
        "git_maintainer",
        {
            "repos": len(state.get("repos", [])),
            "pruned": len(pruned),
            "proposals": len(proposals),
            "errors": len(errors),
            "pruned_branches": [f"{p['repo']}#{p['branch']}" for p in pruned],
        },
    )
    if not proposals and not errors:
        return {"report": {"status": f"clean — auto-pruned {len(pruned)} merged branch(es), nothing to propose"}}

    def _lines(items, fmt):
        return "\n".join(fmt(i) for i in items) or "_none_"

    body = (
        "Automated git-maintainer shift.\n\n"
        f"### ✅ Auto-pruned ({len(pruned)}) — merged-PR branches (recoverable from the SHA)\n"
        + _lines(pruned, lambda p: f"- `{p['repo']}` `{p['branch']}` @ `{p['deleted_sha'][:9]}`")
        + f"\n\n### 🟡 Proposed for review ({len(proposals)}) — NOT auto-deleted\n"
        + _lines(proposals, lambda p: f"- `{p['repo']}` `{p['branch']}` @ `{p.get('sha','?')[:9]}` — {p['reason']}")
        + (f"\n\n### ⚠️ Recon errors ({len(errors)})\n"
           + _lines(errors, lambda e: f"- `{e['repo']}` {e.get('branch','')} — {e['stage']}: {e['error']}")
           if errors else "")
        + "\n\nReply on each proposed branch to approve/decline deletion."
    )
    res = GitHubOps().open_issue(
        DIGEST_REPO,
        "git-maintainer: branches needing review",
        body,
        labels=["gate:human-required"],
    )
    return {"report": {"issue": res, "pruned": len(pruned), "proposals": len(proposals)}}


builder = StateGraph(State)
builder.add_node("plan", plan)
builder.add_node("sweep", sweep)
builder.add_node("act", act)
builder.add_node("report", report)
builder.add_edge(START, "plan")
builder.add_edge("plan", "sweep")
builder.add_edge("sweep", "act")
builder.add_edge("act", "report")
builder.add_edge("report", END)

graph = builder.compile()  # NO checkpointer/store — injected by the platform
