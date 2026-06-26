"""git_sync_auditor — the LOCAL git-sync observability agent.

Runs ON the Mac (via launchd), NOT on LangGraph Platform: like git_local_maintainer
it needs the local multi-repo filesystem, which a cloud container can't see. It is
still a LangGraph graph, so running it with LANGSMITH_TRACING=true emits full traces
to the SAME LangSmith project as the deployed fleet — observability is met even
though execution is local.

MISSION — successor to git_local_maintainer's REPORTING half, nothing more. It is the
observability layer *over* the maintainer's destructive guard:

  - It is STRICTLY READ-ONLY. It reports local↔remote divergence across the whole
    workspace and NEVER pushes, removes worktrees, deletes branches, or (by default)
    fetches. Every git verb it runs is read-only recon.
  - It ALIGNS with the maintainer's recency/unpushed guard by *reusing* it: branches
    flagged ``protected`` are exactly the ones git_local_maintainer's
    ``_protected_activity`` refuses to auto-remove (recent commit OR unpushed work).
    The digest separates those "the maintainer will NOT auto-remove" items from the
    STALE items that are safe to clean — so a human can see, before any maintainer
    run, what is and isn't at risk.

It deliberately re-uses git_local_maintainer's primitives (``_git``,
``_protected_activity``, ``_default_branch``, ``_SKIP_SEGMENTS``, ``discover``) instead
of re-implementing them, so the auditor and the maintainer can never drift on what
counts as "alive" work or which repos are skipped (gal-model / .archive / .forks / …).

FAIL-SAFE: every git call is wrapped (``glm._git`` already returns a structured
(rc, text) on timeout/OSError) and every node completes even with no remotes, an
offline network, or an unreadable repo. A telemetry/network problem never crashes a node.

ANTHROPIC-TERMS / ML BOUNDARY: ``glm.discover`` already skips ``/gal-model`` (and the
rest of ``_SKIP_SEGMENTS``); we additionally drop any repo path containing 'gal-model'
as belt-and-braces, so the auditor never reads/reports an ML-model repo.
"""
from __future__ import annotations

import os
from typing_extensions import TypedDict

from langgraph.graph import StateGraph, START, END

from agent_toolkit import span, governance_capture, write_local_digest
from agent_toolkit.slack_tool import post_digest as _slack_post
from graphs.local import git_local_maintainer as glm

# Destructive/network verbs this auditor must NEVER run. Read-only is the whole point.
_FORBIDDEN_VERBS = frozenset(
    {"push", "fetch", "pull", "commit", "merge", "rebase", "reset", "checkout",
     "clean", "gc", "prune", "worktree", "stash"}  # 'stash list' handled via explicit allow below
)


def _fetch_enabled() -> bool:
    """OFF by default. The only network op the auditor may perform — and only a
    prune-trim of stale remote refs — is ``fetch --prune``, and only when explicitly
    env-gated. Default behavior touches the network for nothing."""
    return os.environ.get("GIT_SYNC_AUDITOR_FETCH", "").lower() in ("1", "true", "yes")


def _is_model_repo(path: str) -> bool:
    """Belt-and-braces ML-boundary skip (glm.discover already drops _SKIP_SEGMENTS)."""
    return "gal-model" in (path or "").lower()


class State(TypedDict, total=False):
    root: str
    repos: list
    findings: list
    summary: dict
    report: dict


def _track_counts(track: str) -> tuple[int, int, bool]:
    """Parse a ``%(upstream:track)`` string → (ahead, behind, upstream_gone).

    Forms: '' (in sync), '[gone]', '[ahead N]', '[behind M]', '[ahead N, behind M]'.
    """
    track = track or ""
    if "gone" in track:
        return 0, 0, True
    ahead = behind = 0
    for part in track.strip("[]").split(","):
        part = part.strip()
        if part.startswith("ahead "):
            ahead = int(part[6:]) if part[6:].isdigit() else 0
        elif part.startswith("behind "):
            behind = int(part[7:]) if part[7:].isdigit() else 0
    return ahead, behind, False


def _unpushed(repo: str, branch: str) -> int:
    """Commits on `branch` not on any remote (read-only; the maintainer's notion of unpushed)."""
    rc, out = glm._git(repo, "rev-list", "--count", branch, "--not", "--remotes")
    return int(out) if rc == 0 and out.isdigit() else 0


def _is_merged(repo: str, branch: str, default: str) -> bool:
    """READ-ONLY: is `branch` an ancestor of the default branch (locally or on origin)?

    Mirrors EXACTLY the maintainer's auto-prune precondition (git_local_maintainer.sweep:
    ``merge-base --is-ancestor name origin/<default>`` OR ``... name <default>``). The auditor
    must use the SAME test so its "safe for the maintainer to clean" claim cannot overstate
    what the maintainer will actually do. ``merge-base --is-ancestor`` mutates nothing.
    """
    if not branch:
        return False
    return (
        glm._git(repo, "merge-base", "--is-ancestor", branch, f"origin/{default}")[0] == 0
        or glm._git(repo, "merge-base", "--is-ancestor", branch, default)[0] == 0
    )


def discover(state: State) -> dict:
    """Enumerate workspace repos via the maintainer's own discovery (already skips
    /gal-model, /.archive, /.forks, node_modules, …). No model, no writes."""
    with span("git_sync_auditor.discover", root=state.get("root") or ""):
        out = glm.discover(state)
        # Belt-and-braces: drop any model-repo path even if a future glm change let one through.
        repos = [r for r in out.get("repos", []) if not _is_model_repo(r)]
        return {"root": out.get("root"), "repos": repos}


def audit(state: State) -> dict:
    """READ-ONLY per-repo sync audit. Builds one finding dict per repo.

    Uses ONLY read-only git (status --porcelain, for-each-ref, rev-list --count,
    symbolic-ref, remote get-url, stash list, rev-parse). NEVER fetches/pushes/removes/
    deletes anything — the optional ``fetch --prune`` is env-gated OFF by default.
    """
    root = state.get("root") or glm.DEFAULT_ROOT
    repos = state.get("repos", [])
    findings: list = []
    fetch = _fetch_enabled()
    with span("git_sync_auditor.audit", repos=len(repos), fetch=fetch):
        for repo in repos:
            if _is_model_repo(repo):
                continue  # ML boundary — never audit a model repo
            rel = repo.replace(root.rstrip("/") + "/", "")

            # Optional, env-gated, prune-only network refresh of remote-tracking refs.
            # Default OFF: with the env unset the auditor never touches the network.
            if fetch:
                glm._git(repo, "fetch", "--prune", "--quiet", timeout=90)

            # Dirty (tracked edits only — untracked '??' lines don't count as divergence).
            dirty = 0
            rc, porc = glm._git(repo, "status", "--porcelain")
            if rc == 0 and porc:
                dirty = sum(1 for ln in porc.splitlines() if not ln.startswith("??"))

            # Stashes.
            stashes = 0
            sc, stash = glm._git(repo, "stash", "list")
            if sc == 0 and stash:
                stashes = len(stash.splitlines())

            # Detached HEAD + current branch.
            cur_rc, current = glm._git(repo, "symbolic-ref", "--short", "HEAD")
            detached = cur_rc != 0 or not current
            if detached:
                current = ""

            # Remote presence.
            has_remote = glm._git(repo, "remote", "get-url", "origin")[0] == 0

            # Default branch (read-only) — needed to mirror the maintainer's merged-check.
            default = glm._default_branch(repo)

            # Per-branch divergence from for-each-ref upstream:track.
            branches: list = []
            any_unpushed = any_diverged = any_ahead = any_behind = False
            rc, refs = glm._git(
                repo, "for-each-ref",
                "--format=%(refname:short)|%(upstream:track)", "refs/heads/",
            )
            if rc == 0:
                for line in refs.splitlines():
                    parts = line.split("|")
                    if not parts or not parts[0]:
                        continue
                    name = parts[0]
                    track = parts[1] if len(parts) > 1 else ""
                    ahead, behind, gone = _track_counts(track)
                    unpushed = _unpushed(repo, name)
                    protected, preason = glm._protected_activity(repo, name)
                    # Only probe merged-status for gone-upstream branches (the only ones the
                    # maintainer would consider auto-deleting) to avoid extra git calls.
                    merged = _is_merged(repo, name, default) if gone else False
                    branches.append({
                        "name": name,
                        "ahead": ahead,
                        "behind": behind,
                        "unpushed": unpushed,
                        "upstream_gone": gone,
                        "merged": merged,
                        "protected": protected,
                        "protected_reason": preason,
                    })
                    if unpushed > 0:
                        any_unpushed = True
                    if ahead > 0 and behind > 0:
                        any_diverged = True
                    if ahead > 0:
                        any_ahead = True
                    if behind > 0:
                        any_behind = True

            # Repo classification — worst-of, most → least severe.
            if not has_remote and any_unpushed:
                classification = "orphan_no_remote"
            elif dirty:
                classification = "dirty"
            elif any_diverged:
                classification = "diverged"
            elif any_unpushed:
                classification = "unpushed"
            elif any_behind:
                classification = "behind"
            elif any_ahead:
                classification = "ahead"
            else:
                classification = "in_sync"

            findings.append({
                "repo": rel,
                "branch": current,
                "has_remote": has_remote,
                "dirty": dirty,
                "stashes": stashes,
                "detached": detached,
                "branches": branches,
                "classification": classification,
            })
    return {"findings": findings}


def report(state: State) -> dict:
    """Build the markdown digest, write it locally (fail-safe), and capture governance.

    The digest separates PROTECTED items — recent/unpushed work the maintainer will NOT
    auto-remove — from STALE items that are safe for the maintainer to clean, plus an
    orphan/no-remote section. STRICTLY READ-ONLY and report-only.
    """
    findings = state.get("findings", [])
    with span("git_sync_auditor.report", repos=len(findings)):
        # Counts by classification.
        counts: dict = {}
        for f in findings:
            counts[f["classification"]] = counts.get(f["classification"], 0) + 1

        in_sync = counts.get("in_sync", 0)
        diverged = counts.get("diverged", 0)
        unpushed = counts.get("unpushed", 0)
        dirty = counts.get("dirty", 0)
        orphan = counts.get("orphan_no_remote", 0)

        # Protected vs stale branch items (aligned EXACTLY with the maintainer's guard).
        # The maintainer auto-deletes a branch ONLY when it is gone-upstream AND merged AND
        # not protected (recent/unpushed). A gone-upstream branch that is NOT merged is
        # proposed for review by the maintainer (kind="gone-upstream-unmerged"), never
        # auto-cleaned — so the auditor must surface it the same way, not as "safe to clean".
        protected_items: list = []
        stale_items: list = []
        review_gone_unmerged: list = []
        orphan_items: list = []
        for f in findings:
            if f["classification"] == "orphan_no_remote":
                orphan_items.append(f)
            for b in f["branches"]:
                if b["protected"]:
                    protected_items.append((f["repo"], b))
                elif b["upstream_gone"]:
                    if b.get("merged"):
                        # gone + merged + not recent/unpushed → safe for the maintainer to clean.
                        stale_items.append((f["repo"], b))
                    else:
                        # gone but NOT merged → maintainer PROPOSES, never auto-cleans.
                        review_gone_unmerged.append((f["repo"], b))
        protected_count = len(protected_items)

        sec = lambda items: items or ["_none_"]
        lines = [
            f"scanned {len(findings)} repos\n",
            "## Sync classification",
            *sec([f"- **{k}**: {v}" for k, v in sorted(counts.items())]),
            f"\n## 🛡️ Protected ({protected_count}) — recent/unpushed; the maintainer will NOT auto-remove",
            *sec([
                f"- `{repo}` `{b['name']}` — {b['protected_reason']} "
                f"(ahead {b['ahead']}, behind {b['behind']}, unpushed {b['unpushed']})"
                for repo, b in protected_items
            ]),
            f"\n## 🧹 Stale ({len(stale_items)}) — upstream gone + merged, not recent/unpushed; safe for the maintainer to clean",
            *sec([
                f"- `{repo}` `{b['name']}` — upstream gone, merged (unpushed {b['unpushed']})"
                for repo, b in stale_items
            ]),
            f"\n## 🟡 Needs review ({len(review_gone_unmerged)}) — upstream gone but NOT merged; the maintainer will NOT auto-clean",
            *sec([
                f"- `{repo}` `{b['name']}` — upstream gone but not merged (unpushed {b['unpushed']})"
                for repo, b in review_gone_unmerged
            ]),
            f"\n## 🧭 Orphan / no remote ({len(orphan_items)}) — local commits with no origin",
            *sec([
                f"- `{f['repo']}` `{f['branch'] or '(detached)'}` — {f['dirty']} dirty, {f['stashes']} stash(es)"
                for f in orphan_items
            ]),
        ]
        body = "\n".join(lines)

        digest = write_local_digest("git-sync-auditor", "Git sync auditor", body)
        _slack_post("git_sync_auditor", "🔁 Git Sync Audit", body)

        governance_capture(
            "git_sync_auditor",
            {
                "repos": len(findings),
                "in_sync": in_sync,
                "diverged": diverged,
                "unpushed": unpushed,
                "dirty": dirty,
                "orphan": orphan,
                "protected_count": protected_count,
                "stale_count": len(stale_items),
                "gone_unmerged_count": len(review_gone_unmerged),
                "report_only": True,
            },
        )
        return {"report": {
            "repos": len(findings),
            "in_sync": in_sync,
            "diverged": diverged,
            "unpushed": unpushed,
            "dirty": dirty,
            "orphan": orphan,
            "protected_count": protected_count,
            "stale_count": len(stale_items),
            "gone_unmerged_count": len(review_gone_unmerged),
            "digest": digest,
        }}


builder = StateGraph(State)
builder.add_node("discover", discover)
builder.add_node("audit", audit)
builder.add_node("report", report)
builder.add_edge(START, "discover")
builder.add_edge("discover", "audit")
builder.add_edge("audit", "report")
builder.add_edge("report", END)

graph = builder.compile()  # NO checkpointer/store — injected by the platform
