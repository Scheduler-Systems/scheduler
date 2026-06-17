"""git_local_maintainer — the LOCAL git-hygiene agent.

Runs ON the Mac (via launchd), NOT on LangGraph Platform: it needs the local
filesystem to see the multi-repo workspace, which a cloud container can't. It is
still a LangGraph graph so running it locally with LANGSMITH_TRACING=true emits
full traces to the SAME LangSmith project as the deployed fleet — observability
is met even though execution is local.

Working principle it ENFORCES: **GitHub is the source of truth; local is
ephemeral working space.** A worktree should live only while you are actively
working in it; once its PR is merged/closed the work is on GitHub and the local
copy is rot. So this agent:

  1. ensure-on-github  — pushes any unpushed commits to a `refs/backup/auto/<branch>`
     ref (additive, no CI, never touches real branches) so nothing accumulates
     un-backed-up locally;
  2. worktree-cleanup  — auto-removes worktrees that are CLEAN *and* whose branch
     is merged/closed (`git worktree remove` refuses a dirty tree — built-in
     safety); proposes dirty/active ones, never force-removes;
  3. branch-prune      — deletes local branches that are merged + upstream-gone
     (`git branch -d` refuses unmerged — built-in safety);
  4. propose the rest  — dirty trees, local-only work, unmerged gone branches,
     stashes → digest for human review, never auto-touched.

It composes with the deployed remote `git_maintainer` (which deletes merged
branches on GitHub): that makes locals show "upstream gone", which this one then
cleans. GIT_MAINTAINER_DRY_RUN=1 makes every step report-only (no push/remove/delete).
"""
from __future__ import annotations

import json
import os
import subprocess
from typing_extensions import TypedDict

from langgraph.graph import StateGraph, START, END

from agent_toolkit import span, governance_capture

DEFAULT_ROOT = "/Users/scheduler-systems/Documents/scheduler-systems-ltd"

# Buckets never touched: dependency checkouts, archived/fork material, and — hard
# rule — the ML-model repo. (Matches the workspace's own hygiene conventions.)
_SKIP_SEGMENTS = ("/node_modules/", "/.build/", "/vendor/", "/.gal-test/",
                  "/.archive/", "/.forks/", "/gal-model")
_PROTECTED_BRANCHES = frozenset(
    {"main", "master", "develop", "phase-0-foundation", "release", "production", "gh-pages"}
)


class State(TypedDict, total=False):
    root: str
    repos: list[str]
    prune_candidates: list[dict]
    backed_up: list[dict]
    worktrees_removed: list[dict]
    deleted_local: list[dict]
    proposals: list[dict]
    errors: list[dict]
    report: dict


def _git(repo: str, *args: str, timeout: int = 60) -> tuple[int, str]:
    """Run a git command in `repo`; return (returncode, stdout+stderr stripped)."""
    try:
        p = subprocess.run(
            ["git", "-C", repo, *args],
            capture_output=True, text=True, timeout=timeout,
        )
        return p.returncode, (p.stdout + p.stderr).strip()
    except (subprocess.TimeoutExpired, OSError) as e:
        return 1, type(e).__name__


def _protected_activity(repo: str, branch: str, days: int = 3) -> tuple[bool, str]:
    """SAFETY GUARD (incident 2026-06-05): a clean worktree holding unpushed
    security commits was auto-removed because its branch looked 'done'. Never
    auto-remove a worktree or delete a branch that is still alive — i.e. has a
    commit in the last `days`, OR has commits not on any remote (unpushed). Such
    items are proposed for human review instead. `--not --remotes` treats commits
    that exist only locally (or only under a backup ref) as unpushed, which is the
    conservative, work-preserving choice."""
    if not branch:
        return True, "detached/unknown branch"
    recent = _git(repo, "log", "-1", f"--since={days}.days.ago", "--format=%H", branch)[1]
    if recent:
        return True, f"commit in last {days}d"
    cnt = _git(repo, "rev-list", "--count", branch, "--not", "--remotes")[1]
    n = int(cnt) if cnt.isdigit() else 0
    if n > 0:
        return True, f"{n} unpushed commit(s)"
    return False, ""


def _dry_run() -> bool:
    return os.environ.get("GIT_MAINTAINER_DRY_RUN", "").lower() in ("1", "true", "yes")


def _gh_pr_state(repo: str, branch: str) -> str:
    """'MERGED' | 'CLOSED' | 'OPEN' | '' (unknown), via gh — catches squash-merges
    that aren't a literal ancestor of the default branch."""
    try:
        p = subprocess.run(
            ["gh", "pr", "list", "--head", branch, "--state", "all",
             "--json", "state,mergedAt", "--limit", "1"],
            cwd=repo, capture_output=True, text=True, timeout=30,
        )
        if p.returncode != 0:
            return ""
        arr = json.loads(p.stdout or "[]")
        if not arr:
            return ""
        return "MERGED" if arr[0].get("mergedAt") else arr[0].get("state", "")
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return ""


def _default_branch(repo: str) -> str:
    rc, out = _git(repo, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if rc == 0 and out:
        return out.split("/", 1)[-1]
    return "main"


def discover(state: State) -> dict:
    root = state.get("root") or os.environ.get("WORKSPACE_ROOT") or DEFAULT_ROOT
    repos: list[str] = []
    seen: set[str] = set()
    for dirpath, dirnames, _ in os.walk(root):
        if ".git" in dirnames:
            dirnames[:] = [d for d in dirnames if d not in ("node_modules", ".build", "vendor")]
        if os.path.exists(os.path.join(dirpath, ".git")):
            seg = dirpath + "/"
            if any(s in seg for s in _SKIP_SEGMENTS):
                continue
            rc, common = _git(dirpath, "rev-parse", "--git-common-dir")
            if rc != 0:
                continue
            key = common if common.startswith("/") else os.path.join(dirpath, common)
            if key in seen:
                continue
            seen.add(key)
            repos.append(dirpath)
    return {"root": root, "repos": sorted(repos)}


def sweep(state: State) -> dict:
    """Classify local branches: dirty / unpushed / safe-prune / propose. Read-only."""
    proposals: list[dict] = []
    errors: list[dict] = []
    candidates: list[dict] = []
    with span("git_local_maintainer.sweep", repos=len(state["repos"])):
        for repo in state["repos"]:
            rel = repo.replace(state["root"].rstrip("/") + "/", "")
            rc, porc = _git(repo, "status", "--porcelain")
            if rc == 0 and porc:
                tracked = sum(1 for ln in porc.splitlines() if not ln.startswith("??"))
                if tracked:
                    proposals.append({"repo": rel, "kind": "uncommitted", "detail": f"{tracked} tracked edits"})
            rc, _ = _git(repo, "remote", "get-url", "origin")
            if rc == 0:
                fc, fout = _git(repo, "fetch", "--prune", "--quiet", timeout=90)
                if fc != 0:
                    errors.append({"repo": rel, "stage": "fetch", "error": fout[:40]})
            rc, refs = _git(
                repo, "for-each-ref",
                "--format=%(refname:short)|%(upstream:track)|%(objectname)", "refs/heads/",
            )
            if rc != 0:
                errors.append({"repo": rel, "stage": "for-each-ref", "error": refs[:40]})
                continue
            default = _default_branch(repo)
            current = _git(repo, "symbolic-ref", "--short", "HEAD")[1]
            for line in refs.splitlines():
                parts = line.split("|")
                if len(parts) < 3:
                    continue
                name, track, sha = parts[0], parts[1], parts[2]
                if name in _PROTECTED_BRANCHES or name == default or name == current:
                    continue
                gone = "gone" in track
                if not gone:
                    if track == "":
                        ac, ahead = _git(repo, "rev-list", "--count", name, "--not", "--remotes")
                        if ac == 0 and ahead.isdigit() and int(ahead) > 0:
                            proposals.append({"repo": rel, "kind": "local-only-branch",
                                              "branch": name, "sha": sha, "detail": f"{ahead} commits, no remote"})
                    continue
                merged = _git(repo, "merge-base", "--is-ancestor", name, f"origin/{default}")[0] == 0 \
                    or _git(repo, "merge-base", "--is-ancestor", name, default)[0] == 0
                if merged:
                    candidates.append({"repo_dir": repo, "rel": rel, "branch": name, "sha": sha})
                else:
                    proposals.append({"repo": rel, "kind": "gone-upstream-unmerged",
                                      "branch": name, "sha": sha, "detail": "upstream deleted but NOT merged"})
            sc, stash = _git(repo, "stash", "list")
            if sc == 0 and stash:
                proposals.append({"repo": rel, "kind": "stashes", "detail": f"{len(stash.splitlines())} stash(es)"})
    return {"prune_candidates": candidates, "proposals": proposals, "errors": errors}


def backup(state: State) -> dict:
    """Ensure local work is on GitHub: push any unpushed commits to
    refs/backup/auto/<branch> (force-with-lease; additive, no CI, never a real
    branch). Guarantees nothing accumulates un-backed-up locally."""
    backed = list(state.get("backed_up", []))
    errors = list(state.get("errors", []))
    dry = _dry_run()
    with span("git_local_maintainer.backup", repos=len(state["repos"]), dry_run=dry):
        for repo in state["repos"]:
            rel = repo.replace(state["root"].rstrip("/") + "/", "")
            if _git(repo, "remote", "get-url", "origin")[0] != 0:
                continue  # no remote → can't back up to GitHub (bundle is the manual fallback)
            rc, refs = _git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads/")
            if rc != 0:
                continue
            for name in refs.splitlines():
                ac, ahead = _git(repo, "rev-list", "--count", name, "--not", "--remotes")
                if not (ac == 0 and ahead.isdigit() and int(ahead) > 0):
                    continue
                if dry:
                    backed.append({"repo": rel, "branch": name, "commits": int(ahead), "dry_run": True})
                    continue
                pc, pout = _git(repo, "push", "--force-with-lease", "origin",
                                f"{name}:refs/backup/auto/{name}", timeout=120)
                if pc == 0:
                    backed.append({"repo": rel, "branch": name, "commits": int(ahead)})
                else:
                    errors.append({"repo": rel, "branch": name, "stage": "backup-push", "error": pout[:50]})
    return {"backed_up": backed, "errors": errors}


def _list_worktrees(repo: str) -> list[dict]:
    rc, out = _git(repo, "worktree", "list", "--porcelain")
    if rc != 0:
        return []
    wts: list[dict] = []
    cur: dict = {}
    for line in out.splitlines() + [""]:
        if line.startswith("worktree "):
            cur = {"path": line[9:], "branch": None, "detached": False, "bare": False}
        elif line.startswith("branch "):
            cur["branch"] = line[7:].replace("refs/heads/", "")
        elif line == "detached":
            cur["detached"] = True
        elif line == "bare":
            cur["bare"] = True
        elif line == "" and cur:
            wts.append(cur)
            cur = {}
    return wts


def worktrees(state: State) -> dict:
    """Auto-remove worktrees that are CLEAN and whose branch is merged/closed; the
    work is on GitHub so the local copy is rot. Propose dirty/active ones. Never the
    main checkout, never a dirty tree (git worktree remove refuses that anyway)."""
    removed = list(state.get("worktrees_removed", []))
    proposals = list(state.get("proposals", []))
    dry = _dry_run()
    here = os.path.realpath(os.getcwd())
    with span("git_local_maintainer.worktrees", repos=len(state["repos"]), dry_run=dry):
        for repo in state["repos"]:
            rel = repo.replace(state["root"].rstrip("/") + "/", "")
            wts = _list_worktrees(repo)
            for i, wt in enumerate(wts):
                if i == 0 or wt["bare"]:
                    continue  # main checkout / bare repo — never remove
                wpath, wbranch = wt["path"], wt["branch"]
                if os.path.realpath(wpath) == here:
                    continue  # never remove the worktree we're running from
                default = _default_branch(repo)
                if wbranch and (wbranch in _PROTECTED_BRANCHES or wbranch == default):
                    continue  # a default/protected-branch worktree is infra — never remove
                # SAFETY GUARD: never auto-remove a worktree with recent activity or
                # unpushed commits, even if its branch looks merged/closed. Propose it.
                protected, preason = _protected_activity(repo, wbranch)
                if protected:
                    proposals.append({"repo": rel, "kind": "worktree-protected",
                                      "branch": wbranch or "(detached)",
                                      "detail": f"{wpath.split('/')[-1]} — {preason}; not auto-removed"})
                    continue
                clean = not _git(wpath, "status", "--porcelain")[1]
                done, why = False, ""
                if wbranch:
                    default = _default_branch(repo)
                    if _git(repo, "merge-base", "--is-ancestor", wbranch, f"origin/{default}")[0] == 0:
                        done, why = True, "merged into default"
                    else:
                        pr = _gh_pr_state(repo, wbranch)
                        if pr in ("MERGED", "CLOSED"):
                            done, why = True, f"PR {pr.lower()}"
                if clean and done:
                    if dry:
                        removed.append({"repo": rel, "path": wpath, "branch": wbranch, "why": why, "dry_run": True})
                        continue
                    rc, out = _git(repo, "worktree", "remove", wpath)
                    if rc == 0:
                        _git(repo, "worktree", "prune")
                        removed.append({"repo": rel, "path": wpath, "branch": wbranch, "why": why})
                    else:
                        proposals.append({"repo": rel, "kind": "worktree-remove-refused",
                                          "branch": wbranch, "detail": out[:60]})
                else:
                    reason = "dirty (uncommitted/untracked)" if not clean else "branch not merged/closed"
                    proposals.append({"repo": rel, "kind": "worktree-stale" if done else "worktree-active",
                                      "branch": wbranch or "(detached)", "detail": f"{wpath.split('/')[-1]} — {reason}"})
    return {"worktrees_removed": removed, "proposals": proposals}


def act(state: State) -> dict:
    """Prune the provably-safe local branches (merged + upstream gone).
    GIT_MAINTAINER_DRY_RUN=1 reports what WOULD be deleted without touching anything."""
    deleted = list(state.get("deleted_local", []))
    proposals = list(state.get("proposals", []))
    dry = _dry_run()
    with span("git_local_maintainer.act", candidates=len(state.get("prune_candidates", [])), dry_run=dry):
        for c in state.get("prune_candidates", []):
            if dry:
                deleted.append({"repo": c["rel"], "branch": c["branch"], "sha": c["sha"], "dry_run": True})
                continue
            # SAFETY GUARD: never delete a branch with recent activity or unpushed
            # commits, even if merged + upstream-gone. Propose it for review instead.
            protected, preason = _protected_activity(c["repo_dir"], c["branch"])
            if protected:
                proposals.append({"repo": c["rel"], "kind": "prune-protected",
                                  "branch": c["branch"], "sha": c["sha"], "detail": preason})
                continue
            rc, out = _git(c["repo_dir"], "branch", "-d", c["branch"])  # -d refuses unmerged
            if rc == 0:
                deleted.append({"repo": c["rel"], "branch": c["branch"], "sha": c["sha"]})
            else:
                proposals.append({"repo": c["rel"], "kind": "prune-refused",
                                  "branch": c["branch"], "sha": c["sha"], "detail": out[:60]})
    return {"deleted_local": deleted, "proposals": proposals}


def report(state: State) -> dict:
    deleted = state.get("deleted_local", [])
    backed = state.get("backed_up", [])
    wt_removed = state.get("worktrees_removed", [])
    proposals = state.get("proposals", [])
    errors = state.get("errors", [])
    governance_capture(
        "git_local_maintainer",
        {
            "repos": len(state.get("repos", [])),
            "backed_up": len(backed),
            "worktrees_removed": len(wt_removed),
            "deleted_local": len(deleted),
            "proposals": len(proposals),
            "errors": len(errors),
        },
    )
    root = state.get("root", DEFAULT_ROOT)
    digest_dir = os.path.join(root, ".tmp", "git-local-maintainer")
    digest_path = ""
    try:
        os.makedirs(digest_dir, exist_ok=True)
        digest_path = os.path.join(digest_dir, "latest.md")
        sec = lambda items, fmt: [fmt(i) for i in items] or ["_none_"]
        lines = [
            "# Local git-maintainer digest",
            f"\nscanned {len(state.get('repos', []))} repos",
            f"\n## ⬆️ Backed up to GitHub ({len(backed)}) — unpushed work → refs/backup/auto/*",
            *sec(backed, lambda b: f"- `{b['repo']}` `{b['branch']}` ({b['commits']} commits)"),
            f"\n## 🧹 Worktrees removed ({len(wt_removed)}) — clean + merged/closed",
            *sec(wt_removed, lambda w: f"- `{w['repo']}` `{w.get('branch')}` — {w['why']}"),
            f"\n## ✂️ Local branches pruned ({len(deleted)}) — merged + upstream gone",
            *sec(deleted, lambda d: f"- `{d['repo']}` `{d['branch']}` @ `{d['sha'][:9]}`"),
            f"\n## 🟡 Needs review ({len(proposals)}) — NOT auto-touched",
            *sec(proposals, lambda p: f"- `{p['repo']}` **{p['kind']}** {p.get('branch','')} — {p.get('detail','')}"),
        ]
        if errors:
            lines.append(f"\n## ⚠️ Errors ({len(errors)})")
            lines += [f"- `{e['repo']}` {e.get('stage')}: {e.get('error')}" for e in errors]
        with open(digest_path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    except OSError:
        digest_path = ""
    return {"report": {"backed_up": len(backed), "worktrees_removed": len(wt_removed),
                       "deleted": len(deleted), "proposals": len(proposals),
                       "errors": len(errors), "digest": digest_path}}


builder = StateGraph(State)
builder.add_node("discover", discover)
builder.add_node("sweep", sweep)
builder.add_node("backup", backup)
builder.add_node("worktrees", worktrees)
builder.add_node("act", act)
builder.add_node("report", report)
builder.add_edge(START, "discover")
builder.add_edge("discover", "sweep")
builder.add_edge("sweep", "backup")
builder.add_edge("backup", "worktrees")
builder.add_edge("worktrees", "act")
builder.add_edge("act", "report")
builder.add_edge("report", END)

graph = builder.compile()
