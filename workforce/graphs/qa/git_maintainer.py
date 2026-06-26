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

SAFETY GUARD (2026-06-06, prod-harden): "PR merged" alone is NOT a license to auto-
delete. The LOCAL maintainer (graphs/local/git_local_maintainer.py) refuses to remove
a worktree/branch that is recently active, has unpushed commits, or matches a protected
name — but that agent has the filesystem to see it. The REMOTE maintainer (this graph)
runs in a cloud container with only the GitHub API, yet the same hazards exist on the
*remote* side: a branch can be the head of a squash-merged PR (so it reads "merged") while
its worktree is still actively checked out locally, or while it is a long-lived integration
branch (``feat/ops-fleet*``) or a HELD security branch (``fix/firestore-idor-acl-1487``).
Auto-deleting those remotely yanks the upstream out from under live local work and erases
a gate-held branch. So before EVER classifying a merged branch as auto-prune-safe we apply
``_prune_guard`` — an API-only equivalent of the local activity/protected guard — and route
ANY guarded branch to propose-for-human-review instead of auto-delete. Borderline → propose.

State in: optional {repos}. State out: {pruned, proposals, errors, report}.
"""
import os
import re
from datetime import datetime, timezone

from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END

from agent_toolkit import span, governance_capture, assert_not_model_work
from agent_toolkit.github_ops import GitHubOps, ALLOWED_REPOS, _PROTECTED_BRANCHES
from agent_toolkit.write_gate import write_enabled

# The maintainer's own home — where the human-facing digest is filed.
DIGEST_REPO = "Scheduler-Systems/qa-agent-platform"

# This graph's own slug — the identity the per-agent write floor is keyed on. git_maintainer is a
# TIER-2 agent: it is NOT on the default ``AGENTS_WRITE_ENABLED`` allowlist, so until a human
# graduates it the floor keeps it PROPOSE-ONLY (it never auto-deletes).
AGENT = "git_maintainer"

# --- Prune guard (remote equivalent of the LOCAL maintainer's activity guard) ----------
# How many days of inactivity a merged branch must have before it is even *considered* for
# auto-prune. A merge whose head still received a commit inside this window is treated as
# live (its worktree may still be open locally) and is PROPOSED, never auto-deleted.
PRUNE_MIN_IDLE_DAYS = int(os.environ.get("GIT_MAINTAINER_MIN_IDLE_DAYS", "7"))

# Protected branch-NAME patterns that must never be auto-deleted even when their PR is
# merged (a squash/rebase merge leaves the head branch behind reading "merged"). These map
# the prompt's protected set onto signals the remote agent CAN see (the branch name + the
# repo default), and they cover both named hazards exactly: ``feat/ops-fleet-prod-harden``
# (feat/*) and ``fix/firestore-idor-acl-1487`` (fix/* AND, via its issue, a held item).
#   * feat/*  release/*  fix/*  → long-lived integration / fix branches, often still checked
#                                  out in a local worktree whose upstream this would delete;
#   * *security* / *hotfix*     → sensitive branches (e.g. an IDOR/ACL fix) — always review;
#   * *held* / gate:* markers   → an explicit "do not touch" marker carried in the name.
# Anything matching is PROPOSED for human review, never auto-pruned.
_PROTECTED_PREFIXES = ("feat/", "feature/", "fix/", "hotfix/", "release/", "hold/", "wip/")
_PROTECTED_SUBSTRINGS = ("security", "hotfix", "held", "hold", "gate:", "do-not-delete", "keep")
_HELD_LABELS = frozenset({"gate:human-required", "gate:held", "hold", "held", "do-not-delete",
                          "security", "do-not-merge"})


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def _matches_protected_pattern(branch: str) -> str:
    """Return a human reason if ``branch`` matches a protected NAME pattern, else ""."""
    b = _norm(branch)
    if not b:
        return "empty/unknown branch name"
    for pre in _PROTECTED_PREFIXES:
        if b.startswith(pre):
            return f"protected prefix '{pre}*'"
    for sub in _PROTECTED_SUBSTRINGS:
        if sub in b:
            return f"protected marker '{sub}' in name"
    return ""


def _parse_iso(ts) -> "datetime | None":
    """Parse a GitHub ISO-8601 timestamp (e.g. '2026-06-01T00:00:00Z') → aware datetime."""
    if not ts:
        return None
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    s = str(ts).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _recently_active(last_activity_iso, *, days: int = PRUNE_MIN_IDLE_DAYS) -> bool:
    """True if the branch head's last commit/PR activity is within ``days`` (so: live).
    Unknown/unparseable timestamp → treated as recent (conservative, work-preserving)."""
    dt = _parse_iso(last_activity_iso)
    if dt is None:
        return True  # can't prove it's idle → assume live, propose not prune
    age_days = (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0
    return age_days < days


def _prune_guard(branch: str, pr: dict, *, default_branch: str = "") -> str:
    """The remote equivalent of the local maintainer's protected-activity guard.

    Given a branch the recon already classified as MERGED, decide whether it is still
    unsafe to auto-delete. Returns a human-readable reason to PROPOSE-instead-of-prune,
    or "" if it is genuinely a stale, mergeable, unprotected branch that may be pruned.

    Checks (all API-only — no filesystem needed):
      1. default branch / classic protected names (belt-and-braces; github_ops also refuses);
      2. protected NAME pattern (feat/* fix/* release/* *security* held/gate markers …) —
         covers branches still checked out by a local worktree and HELD security branches;
      3. a HELD/gate label on the (merged) PR — an explicit do-not-touch marker;
      4. recent activity — a commit/PR event inside PRUNE_MIN_IDLE_DAYS means the branch may
         still be live work locally; an unknown timestamp is treated as recent.
    """
    b = _norm(branch)
    if b in _PROTECTED_BRANCHES or (default_branch and b == _norm(default_branch)):
        return "default/protected branch name"
    pat = _matches_protected_pattern(branch)
    if pat:
        return pat
    labels = {_norm(l) for l in (pr.get("labels") or [])}
    held = labels & {_norm(x) for x in _HELD_LABELS}
    if held:
        return f"held/gate label: {', '.join(sorted(held))}"
    if _recently_active(pr.get("last_activity")):
        return f"recent activity (<{PRUNE_MIN_IDLE_DAYS}d) — may be live locally"
    return ""


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
    """Read-only recon: classify every branch across the repos. No gate, no writes.

    A merged branch is only added to ``prune_candidates`` (the auto-delete set) if it ALSO
    clears ``_prune_guard`` — the API-only protected/activity guard. A merged-but-guarded
    branch (protected name pattern, held/gate label, or recent activity) drops to
    ``proposals`` for human review, so the agent can never yank the upstream out from under
    a live local worktree (e.g. ``feat/ops-fleet-prod-harden``) or auto-erase a HELD security
    branch (e.g. ``fix/firestore-idor-acl-1487``) just because a squash-merge left it behind.
    """
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
            default = next((b["name"] for b in branches if b.get("is_default")), "")
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
                    # MERGED is necessary but NOT sufficient for auto-prune. Apply the remote
                    # protected/activity guard; anything it flags is proposed, never deleted.
                    guard = _prune_guard(name, pr, default_branch=default)
                    if guard:
                        proposals.append({"repo": repo, "branch": name, "sha": b["sha"],
                                          "reason": f"merged but held back: {guard}"})
                    else:
                        prune_candidates.append({"repo": repo, "branch": name, "sha": b["sha"]})
                else:
                    # no PR, or a PR closed without merging — NOT provably safe → propose
                    reason = "no PR for branch" if not pr.get("has_pr") else "PR closed unmerged"
                    proposals.append({"repo": repo, "branch": name, "sha": b["sha"], "reason": reason})
    return {"prune_candidates": prune_candidates, "proposals": proposals, "errors": errors}


def act(state: State) -> dict:
    """Auto-prune the provably-safe (merged) branches. Anything that can't be
    auto-deleted (blocked/not-configured) drops to the proposal list — never forced.

    THE FLOOR (2026-06-07, prod-harden): a branch delete is a DESTRUCTIVE/irreversible CODE
    action, so before deleting ANYTHING this node consults the company-wide per-agent write
    floor — ``write_enabled("git_maintainer")`` — which composes THREE independent stops:
      * the master report-only floor (``OPS_REPORT_ONLY`` unset/truthy ⇒ propose, never prune);
      * the per-agent allowlist (``AGENTS_WRITE_ENABLED``; git_maintainer is TIER-2, OFF the
        default allowlist ⇒ propose until a human graduates it); and
      * the kill switch / over-budget (``check_clocked_in`` False ⇒ propose).
    If the floor is NOT lifted for this agent, EVERY prune candidate is routed to ``proposals``
    and ``delete_branch`` is never called — closing the prior fail-open where the destructive
    prune only consulted ``GITHUB_OPS_REPORT_ONLY`` + ``AGENT_AUTONOMY`` and ignored the floor.

    Defense in depth: even when the floor IS lifted, re-apply the NAME-pattern guard here (pure,
    no PR data needed) before every delete. So if a guarded branch ever reaches
    ``prune_candidates`` — a future caller, a sweep regression, or hand-injected state — the
    auto-delete is STILL refused and the branch is proposed."""
    pruned: list[dict] = []
    proposals = list(state.get("proposals", []))
    errors = list(state.get("errors", []))
    candidates = state.get("prune_candidates", [])

    # MASTER FLOOR: until git_maintainer is explicitly write-enabled (master floor lifted +
    # named on the allowlist + clocked-in), it stays PROPOSE-ONLY. Route every candidate to the
    # human-review list and never touch the destructive delete path.
    if candidates and not write_enabled(AGENT):
        with span("git_maintainer.act", candidates=len(candidates), write_enabled=False):
            for c in candidates:
                proposals.append({**c, "reason": "report-only floor: git_maintainer not write-enabled"})
        return {"pruned": pruned, "proposals": proposals, "errors": errors}

    ops = GitHubOps()
    with span("git_maintainer.act", candidates=len(candidates), write_enabled=True):
        for c in candidates:
            pat = _matches_protected_pattern(c["branch"]) or (
                "default/protected branch name" if _norm(c["branch"]) in _PROTECTED_BRANCHES else "")
            if pat:
                # Second-layer block: a protected-pattern branch must never be auto-deleted,
                # regardless of how it landed in the candidate list. Propose it instead.
                proposals.append({**c, "reason": f"guard re-blocked (protected pattern): {pat}"})
                continue
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
        dedup_key="git-maintainer:branches-needing-review",
        agent="git_maintainer",
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
