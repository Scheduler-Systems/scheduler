"""GitHub write surface — the keystone that turns the fleet from a narrator into a doer.

Every QA/SDLC graph today appends the string ``"would-write (approved)"`` and performs
ZERO GitHub writes. This module is the *only* place real branches/commits/PRs/merges are
created, and it makes every mutating call pass three guards, in order:

  1. ``assert_not_model_work`` (policy.py)  — Anthropic terms: never touch ML-model repos.
  2. ``assert_allowed_repo``                — default-DENY allow-list of repos the workforce
                                              may write to at all.
  3. ``request_approval`` / ``is_approved`` (approval.py) — the human gate; default-deny.

Safety properties (deliberate):
  * **Fail-closed, not theatre.** With no token configured a real write raises
    ``GitHubNotConfigured`` — it does NOT pretend to succeed. (Today GITHUB_* are empty,
    so the surface stays inert until a least-privilege GitHub App token is injected.)
  * **No agent merge to a production repo, ever.** ``merge_pr`` hard-raises for any repo in
    ``PROD_DEPLOY_REPOS`` regardless of approval — those merges must be a human click for
    the whole duty window (see .tmp/autonomy-roadmap/PLAN.md, authority matrix).
  * **Honest probation mode.** ``report_only=True`` returns the *intended* action as a plan
    dict without calling GitHub or the gate — useful for LEARN_MODE, and clearly labelled
    so it can never be mistaken for a completed write.

Token is read from the environment (``GITHUB_TOKEN`` then ``GITHUB_APP_TOKEN``) so the
credential never lives in code. pygithub is the client.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Optional

from .approval import is_approved, request_approval
from .policy import assert_not_model_work

# --- Allow-list (default DENY) --------------------------------------------------------
# Repos the workforce may write to at all. Curate deliberately; a repo not listed here is
# invisible to the write surface by construction (so a new/unlabelled financial/legal repo
# can never be touched). Start with the Scheduler product repos + the no-prod-deploy repos
# safe for the first close-the-loop proof.
ALLOWED_REPOS: frozenset[str] = frozenset(
    {
        # Product repos (writes allowed; merges still gated, and prod-merge hard-blocked below)
        "Scheduler-Systems/scheduler-web",
        "Scheduler-Systems/scheduler-api",
        "Scheduler-Systems/scheduler-ios",
        "Scheduler-Systems/scheduler-android",
        # No-prod-deploy repos — safe targets for the first proof + agent self-maintenance
        "gal-run/agent-workforce",
        "Scheduler-Systems/workspace-governance",
    }
)

# Of the allowed repos, the ones that deploy to production / paying users. An agent may
# OPEN PRs and DEV-deploy here, but MERGE is never an agent action — full stop, all duty.
PROD_DEPLOY_REPOS: frozenset[str] = frozenset(
    {
        "Scheduler-Systems/scheduler-web",
        "Scheduler-Systems/scheduler-api",
        "Scheduler-Systems/scheduler-ios",
        "Scheduler-Systems/scheduler-android",
    }
)

# Branches that must NEVER be deleted by an agent, in any repo, regardless of PR state
# or autonomy tier. (The repo's own default branch is also refused dynamically.)
_PROTECTED_BRANCHES: frozenset[str] = frozenset(
    {"main", "master", "develop", "phase-0-foundation", "release", "production", "gh-pages"}
)

_TOKEN_ENV_VARS = ("GITHUB_TOKEN", "GITHUB_APP_TOKEN", "GITHUB_DISPATCH_TOKEN")


class GitHubWriteBlocked(RuntimeError):
    """A guard (allow-list, prod-merge, or human rejection) refused the write."""


class GitHubNotConfigured(RuntimeError):
    """No token in the environment — a real write cannot proceed (fail-closed)."""


def _token() -> Optional[str]:
    for var in _TOKEN_ENV_VARS:
        val = os.environ.get(var)
        if val:
            return val
    return None


def assert_allowed_repo(repo: str) -> None:
    """Default-deny gate: raise unless ``repo`` is explicitly allow-listed (and not model work)."""
    assert_not_model_work(repo)
    if repo not in ALLOWED_REPOS:
        raise GitHubWriteBlocked(
            f"Blocked: '{repo}' is not in the write allow-list. Add it to ALLOWED_REPOS "
            "deliberately — the workforce can only act on curated repos."
        )


def _default_report_only() -> bool:
    return os.environ.get("GITHUB_OPS_REPORT_ONLY", "").lower() in ("1", "true", "yes")


def _app_private_key() -> Optional[str]:
    """GitHub App private key PEM. Sources, in order:
      GITHUB_APP_PRIVATE_KEY      — raw PEM content
      GITHUB_APP_PRIVATE_KEY_B64  — base64-encoded PEM (robust single-line env var for the
                                     LangGraph deployment env, since PEMs are multiline)
      GITHUB_APP_PRIVATE_KEY_PATH — a file path
    The value is never logged."""
    pem = os.environ.get("GITHUB_APP_PRIVATE_KEY")
    if pem:
        return pem
    b64 = os.environ.get("GITHUB_APP_PRIVATE_KEY_B64")
    if b64:
        import base64
        try:
            return base64.b64decode(b64).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return None
    gz = os.environ.get("GITHUB_APP_PRIVATE_KEY_GZ_B64")
    if gz:
        import base64
        import gzip
        try:
            return gzip.decompress(base64.b64decode(gz)).decode("utf-8")
        except (ValueError, UnicodeDecodeError, OSError):
            return None
    path = os.environ.get("GITHUB_APP_PRIVATE_KEY_PATH")
    if path:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return fh.read()
        except OSError:
            return None
    return None


@dataclass
class GitHubOps:
    """Mutating GitHub operations, each guarded. Construct once per graph node.

    ``report_only`` (None → env ``GITHUB_OPS_REPORT_ONLY``) returns a plan dict instead of
    writing — honest probation, never a fake success.
    """

    report_only: Optional[bool] = None

    def _is_report_only(self) -> bool:
        return self.report_only if self.report_only is not None else _default_report_only()

    def _client(self) -> Any:
        # Imported lazily so importing this module never requires pygithub/network.
        from github import Auth, Github, GithubIntegration

        # Preferred: authenticate as the least-privilege GitHub App and mint a
        # short-lived installation token (App ID + private key). Falls back to a
        # plain token, then fails closed.
        # NB: read FLEET_APP_ID first — the LangGraph deployment platform reserves/strips
        # GITHUB_APP_ID from the runtime env (its own GitHub-deploy App uses that name),
        # so the fleet's App id must travel under a non-reserved name.
        app_id = os.environ.get("FLEET_APP_ID") or os.environ.get("GITHUB_APP_ID")
        app_key = _app_private_key()
        if app_id and app_key:
            integ = GithubIntegration(auth=Auth.AppAuth(int(app_id), app_key))
            inst_id = os.environ.get("GITHUB_APP_INSTALLATION_ID")
            if inst_id:
                return integ.get_github_for_installation(int(inst_id))
            installs = list(integ.get_installations())
            if not installs:
                raise GitHubNotConfigured(
                    f"GitHub App {app_id} has no installations — install it on the target "
                    "repos (App → Install App), then retry."
                )
            return integ.get_github_for_installation(installs[0].id)

        tok = _token()
        if tok:
            return Github(auth=Auth.Token(tok))

        raise GitHubNotConfigured(
            "No GitHub credentials in env. Set GITHUB_APP_ID + "
            "GITHUB_APP_PRIVATE_KEY[_PATH] (preferred), or one of "
            f"{', '.join(_TOKEN_ENV_VARS)}. Use report_only=True for LEARN_MODE."
        )

    # Authority router — AUTO tier. Only these LOW-RISK report actions may proceed without a
    # human when AGENT_AUTONOMY=auto (e.g. scheduled overnight runs). Everything
    # consequential (PRs, merges, deploys, prod-flag changes) STILL gates / hard-blocks.
    _SAFE_AUTO_ACTIONS = frozenset({"open_issue", "comment_issue"})

    def _guard_and_run(self, *, action: str, repo: str, payload: dict, risk: str, run):
        """Shared path for every mutating op: allow-list → report-only? → AUTO-tier? → human gate → run."""
        assert_allowed_repo(repo)
        if self._is_report_only():
            return {"status": "report_only", "action": action, "repo": repo, "payload": payload}
        auto = os.environ.get("AGENT_AUTONOMY", "").lower() == "auto"
        if not (auto and action in self._SAFE_AUTO_ACTIONS):
            decision = request_approval(action, {"repo": repo, **payload}, risk=risk)
            if not is_approved(decision):
                raise GitHubWriteBlocked(
                    f"Human rejected '{action}' on {repo} (decision={decision!r})."
                )
        return run(self._client())

    # --- Operations ------------------------------------------------------------------

    def open_issue(self, repo: str, title: str, body: str, labels: Optional[list[str]] = None):
        return self._guard_and_run(
            action="open_issue",
            repo=repo,
            payload={"title": title, "labels": labels or []},
            risk="medium",
            run=lambda gh: _result(
                gh.get_repo(repo).create_issue(title=title, body=body, labels=labels or [])
            ),
        )

    def comment_issue(self, repo: str, number: int, body: str):
        return self._guard_and_run(
            action="comment_issue",
            repo=repo,
            payload={"number": number},
            risk="low",
            run=lambda gh: _result(gh.get_repo(repo).get_issue(number).create_comment(body)),
        )

    def create_branch(self, repo: str, new_branch: str, from_branch: str = "main"):
        def run(gh):
            r = gh.get_repo(repo)
            base = r.get_branch(from_branch)
            ref = r.create_git_ref(ref=f"refs/heads/{new_branch}", sha=base.commit.sha)
            return {"ref": ref.ref, "sha": base.commit.sha}

        return self._guard_and_run(
            action="create_branch",
            repo=repo,
            payload={"new_branch": new_branch, "from_branch": from_branch},
            risk="medium",
            run=run,
        )

    def put_file(self, repo: str, branch: str, path: str, content: str, message: str):
        """Create or update a single file on ``branch`` (agent branch only — never default)."""
        def run(gh):
            r = gh.get_repo(repo)
            try:
                existing = r.get_contents(path, ref=branch)
                res = r.update_file(path, message, content, existing.sha, branch=branch)
            except Exception:
                res = r.create_file(path, message, content, branch=branch)
            commit = res.get("commit") if isinstance(res, dict) else None
            return {"path": path, "branch": branch, "commit": getattr(commit, "sha", None)}

        return self._guard_and_run(
            action="put_file",
            repo=repo,
            payload={"path": path, "branch": branch, "message": message},
            risk="medium",
            run=run,
        )

    def open_pr(self, repo: str, head: str, base: str, title: str, body: str):
        return self._guard_and_run(
            action="open_pr",
            repo=repo,
            payload={"head": head, "base": base, "title": title},
            risk="medium",
            run=lambda gh: _result(
                gh.get_repo(repo).create_pull(title=title, body=body, head=head, base=base)
            ),
        )

    def merge_pr(self, repo: str, number: int, method: str = "squash"):
        """Merge a PR. HARD-BLOCKED for production repos: an agent never merges to prod."""
        if repo in PROD_DEPLOY_REPOS:
            raise GitHubWriteBlocked(
                f"Refusing to merge in production repo '{repo}'. Merges to prod-deploy repos "
                "are a human click for the entire duty window — open the PR and QUEUE it."
            )
        return self._guard_and_run(
            action="merge_pr",
            repo=repo,
            payload={"number": number, "method": method},
            risk="high",
            run=lambda gh: _result(
                gh.get_repo(repo).get_pull(number).merge(merge_method=method)
            ),
        )

    def delete_branch(self, repo: str, branch: str, reason: str = ""):
        """DESTRUCTIVE: delete a remote branch — the git-maintainer's prune op.

        Safety, in order:
          * never the default branch or a ``_PROTECTED_BRANCHES`` name (hard raise);
          * the head SHA is captured and returned BEFORE deletion (a deleted merged
            branch is recoverable from that SHA / the merge commit — reversible);
          * **auto-prune-safe path**: under ``AGENT_AUTONOMY=auto`` the delete proceeds
            WITHOUT a human gate ONLY when the branch has a MERGED PR (provably safe).
            Any non-merged branch falls through to the human approval gate, so an
            unattended run can never auto-delete unmerged work — it will raise and the
            caller should PROPOSE the prune instead.
        """
        if branch in _PROTECTED_BRANCHES:
            raise GitHubWriteBlocked(
                f"Refusing to delete protected branch '{branch}' in {repo}."
            )
        assert_allowed_repo(repo)
        if self._is_report_only():
            return {
                "status": "report_only",
                "action": "delete_branch",
                "repo": repo,
                "payload": {"branch": branch, "reason": reason},
            }

        gh = self._client()
        r = gh.get_repo(repo)
        if branch == r.default_branch:
            raise GitHubWriteBlocked(
                f"Refusing to delete the default branch '{branch}' in {repo}."
            )
        ref = r.get_git_ref(f"heads/{branch}")
        sha = ref.object.sha  # capture for recoverability BEFORE any delete
        owner = repo.split("/")[0]
        merged = any(
            p.merged_at is not None
            for p in r.get_pulls(state="all", head=f"{owner}:{branch}")
        )

        auto = os.environ.get("AGENT_AUTONOMY", "").lower() == "auto"
        safe_auto = auto and merged  # provably-safe: a merged PR is recoverable
        if not safe_auto:
            decision = request_approval(
                "delete_branch",
                {"repo": repo, "branch": branch, "sha": sha, "merged": merged, "reason": reason},
                risk="high",
            )
            if not is_approved(decision):
                raise GitHubWriteBlocked(
                    f"Refusing to auto-delete '{branch}' on {repo} (merged={merged}); "
                    "not provably-safe and no human approval. Propose it instead."
                )
        ref.delete()
        return {
            "status": "deleted",
            "repo": repo,
            "branch": branch,
            "deleted_sha": sha,
            "merged": merged,
            "auto": safe_auto,
            "reason": reason,
        }

    # --- Read-only recon (no gate — used by deployed agents to observe) ----------------

    def list_branches(self, repo: str) -> list[dict]:
        """All branches with head SHA, protected flag, and default flag. Read-only,
        allow-list scoped, no approval gate. Safe to run unattended."""
        assert_allowed_repo(repo)
        gh = self._client()
        r = gh.get_repo(repo)
        default = r.default_branch
        return [
            {
                "name": b.name,
                "sha": b.commit.sha,
                "protected": bool(getattr(b, "protected", False)),
                "is_default": b.name == default,
            }
            for b in r.get_branches()
        ]

    def branch_merged_pr(self, repo: str, branch: str) -> dict:
        """Whether ``branch`` is the head of a MERGED PR (and any open PRs). Read-only,
        allow-list scoped, no gate. Drives the auto-prune-safe decision."""
        assert_allowed_repo(repo)
        gh = self._client()
        r = gh.get_repo(repo)
        owner = repo.split("/")[0]
        pulls = list(r.get_pulls(state="all", head=f"{owner}:{branch}"))
        return {
            "has_pr": bool(pulls),
            "merged": any(p.merged_at is not None for p in pulls),
            "open": any(p.state == "open" for p in pulls),
            "numbers": [p.number for p in pulls],
        }

    def latest_run(self, repo: str, branch: str = "main") -> dict:
        """Latest GitHub Actions run on ``branch`` — read-only recon, no approval gate.
        Still allow-list scoped (and model-work guarded). Safe to run unattended."""
        assert_allowed_repo(repo)
        gh = self._client()
        runs = gh.get_repo(repo).get_workflow_runs(branch=branch)
        for run in runs:  # newest first
            return {
                "status": run.status,
                "conclusion": run.conclusion,
                "html_url": run.html_url,
                "name": run.name,
                "head_sha": run.head_sha,
            }
        return {"status": None, "conclusion": None, "html_url": None, "name": None}


def _result(obj: Any) -> dict:
    """Normalize a pygithub return into a small, log-safe dict."""
    return {
        "status": "done",
        "number": getattr(obj, "number", None),
        "html_url": getattr(obj, "html_url", None),
        "sha": getattr(obj, "sha", None),
        "merged": getattr(obj, "merged", None),
    }
