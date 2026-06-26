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
        "Scheduler-Systems/qa-agent-platform",
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


# --- RECORD vs CODE boundary (Shay's HITL line) ---------------------------------------
# An issue/comment is a durable RECORD of work, not an irreversible ACTION on the codebase
# — so it does NOT violate the no-auto-merge rule and MAY write even on probation
# (report_only=True). A CODE action mutates the repo's source / git state / merge state and
# stays gated: under report_only it returns an honest plan dict and never touches GitHub.
#
# RECORD actions: open_issue, comment_issue, comment_on_pr  (durable narration / cross-link).
# CODE actions:   create_branch, put_file, open_pr, merge_pr, delete_branch (source/git/merge).
_RECORD_ACTIONS: frozenset[str] = frozenset(
    {"open_issue", "comment_issue", "comment_on_pr"}
)


# --- Record markers, per-agent labels, cross-links ------------------------------------
# A hidden HTML comment embedded in an issue body lets the next shift find-or-update the
# SAME issue (kills the #33/#35/#43 duplicate-issue spam) without a sidecar store. GitHub
# renders HTML comments invisibly, so it never clutters the human view.
def _record_marker(dedup_key: str) -> str:
    """The invisible find-or-update marker for ``dedup_key`` (an HTML comment)."""
    return f"<!-- agent-record:{dedup_key} -->"


def agent_label(agent: str) -> str:
    """Per-agent attribution label, e.g. ``agent:cfo`` (the missing 'who did this')."""
    slug = "".join(c if (c.isalnum() or c in "-_") else "-" for c in (agent or "")).strip("-").lower()
    return f"agent:{slug}" if slug else "agent:unknown"


def _fleet_logins() -> frozenset[str]:
    """Optional allow-list of GitHub logins the fleet writes as (its bot/App identities).

    Sourced from ``GITHUB_FLEET_LOGINS`` (comma-separated, case-insensitive). When set, the
    dedup find-or-update path will ONLY latch onto an issue authored by one of these logins
    (a non-matching OR unknown author is foreign) — so a record can never overwrite/edit a
    human-authored issue even if that issue happens to carry the (invisible, caller-controlled)
    record marker. When unset, the find-or-update path requires BOTH the per-agent attribution
    label AND a recognizable bot author (see ``_is_fleet_owned_record``), so the human-appliable
    label alone can never authorize mutating a human-authored issue."""
    raw = os.environ.get("GITHUB_FLEET_LOGINS", "")
    return frozenset(p.strip().lower() for p in raw.split(",") if p.strip())


def _issue_labels(issue: Any) -> set[str]:
    """Return an issue's label names as a lowercased set (fail-soft for mock/real objects)."""
    names: set[str] = set()
    try:
        for lbl in getattr(issue, "labels", None) or []:
            name = getattr(lbl, "name", lbl)
            if isinstance(name, str):
                names.add(name.lower())
    except Exception:
        pass
    return names


def _issue_author_login(issue: Any) -> Optional[str]:
    """The issue author's login, lowercased, or None if unavailable (fail-soft)."""
    try:
        login = getattr(getattr(issue, "user", None), "login", None)
        return login.lower() if isinstance(login, str) else None
    except Exception:
        return None


def _looks_like_bot_login(login: Optional[str]) -> bool:
    """Heuristic: does ``login`` look like an automation/App identity (never a human)?

    Used ONLY as a corroborating signal for find-or-update when no ``GITHUB_FLEET_LOGINS``
    allow-list is configured. A GitHub App always authors as ``<app-slug>[bot]``; CI bots use
    the ``github-actions[bot]`` family. A real human login (e.g. ``shay-human``) never matches,
    so this can never let a record latch onto a human-authored issue. An unknown author (None)
    is NOT bot-like — an unverifiable author must not be treated as the fleet."""
    if not isinstance(login, str) or not login:
        return False
    lo = login.lower()
    return lo.endswith("[bot]") or lo in {"github-actions", "github-actions[bot]"}


def _record_unchanged(issue: Any, body: str) -> bool:
    """Whether ``body`` already appears in the issue body or its most-recent comment.

    Comment-storm guard for a frequently-scheduled record: when the new digest text is identical
    to what is already on file, skip appending yet another comment. Fail-soft (any error → False,
    i.e. err toward posting so a real update is never silently dropped)."""
    text = (body or "").strip()
    if not text:
        return True  # nothing to add
    try:
        if text in (getattr(issue, "body", "") or ""):
            return True
        comments = list(getattr(issue, "_comments", None) or [])
        if comments and isinstance(comments[-1], str) and text in comments[-1]:
            return True
        # Real pygithub issue: inspect the latest comment body.
        get_comments = getattr(issue, "get_comments", None)
        if callable(get_comments):
            last = None
            for c in get_comments():
                last = c
            if last is not None and text in (getattr(last, "body", "") or ""):
                return True
    except Exception:
        return False
    return False


def _is_fleet_owned_record(issue: Any, *, agent_lbl: Optional[str]) -> bool:
    """Whether ``issue`` is a record the fleet itself owns and may safely find-or-UPDATE.

    This guards the dedup find-or-update lane, which MUTATES a pre-existing issue (appends a
    comment, adds labels) with NO human gate under ``report_only``. So the bar is deliberately
    HIGH: the only thing standing between a probation digest and a foreign-issue write is this
    check. The marker alone is never sufficient (it is invisible in GitHub's rendered view and
    the dedup_key is caller/LLM-controlled, so a human quoting an agent digest can carry it),
    and the per-agent label alone is never sufficient EITHER (a human routinely applies an
    ``agent:<slug>`` label when triaging a fleet digest into their own thread). Authorizing a
    mutation therefore requires PROOF the fleet authored the issue:

      * if ``GITHUB_FLEET_LOGINS`` is set → the issue author MUST be one of those logins. A
        non-matching author is foreign, and an UNKNOWN author (None — ghost/deleted user or a
        minimal API payload) is foreign too: an unverifiable author can never satisfy an
        authoritative allow-list (no fall-through to the weaker label path); else
      * if no allow-list is configured → we corroborate label-attribution with bot-authorship:
        the issue must BOTH carry the per-agent ``agent:<slug>`` label (applied only by this
        write surface) AND be authored by a recognizable automation/App identity
        (``…[bot]``/``github-actions``). A human author (or unknown author) fails this, so a
        human-triaged issue carrying the label is left untouched.

    When ownership cannot be proven the caller must NOT mutate the issue; it files its OWN
    fresh fleet record instead (the label-only signal may seed a new record but NEVER authorizes
    editing a pre-existing one)."""
    author = _issue_author_login(issue)
    fleet = _fleet_logins()
    if fleet:
        # An explicit fleet-login allow-list is AUTHORITATIVE: only a matching, known author is
        # fleet-owned. Non-matching OR unknown (None) author → foreign (no label fall-through).
        return author is not None and author in fleet
    # No allow-list configured: corroborate label-attribution with bot-authorship so the label
    # alone (human-appliable) can never authorize mutating a human-authored issue.
    if agent_lbl and agent_lbl.lower() in _issue_labels(issue):
        return _looks_like_bot_login(author)
    return False


def _normalize_ref(ref: Any) -> Optional[str]:
    """Render one cross-link reference into a GitHub-recognized token.

    Accepts an int (→ ``#123``), a ``#123`` string, an ``owner/repo#123`` string, or a full
    issue/PR URL. Returns ``None`` for anything unusable (fail-soft — never raises)."""
    if ref is None:
        return None
    if isinstance(ref, int):
        return f"#{ref}" if ref > 0 else None
    s = str(ref).strip()
    if not s:
        return None
    return s


def _render_related(related: Optional[list]) -> str:
    """Render a ``related=[...]`` list into a GitHub cross-link footer (or "")."""
    if not related:
        return ""
    refs = [r for r in (_normalize_ref(x) for x in related) if r]
    if not refs:
        return ""
    return "\n\nRelated: " + ", ".join(refs)


def _compose_record_body(
    body: str,
    *,
    dedup_key: Optional[str] = None,
    related: Optional[list] = None,
) -> str:
    """Assemble a record body: original text + cross-link footer + hidden dedup marker."""
    parts = [body or ""]
    footer = _render_related(related)
    if footer:
        parts.append(footer)
    if dedup_key:
        parts.append("\n" + _record_marker(dedup_key))
    return "".join(parts)


@dataclass
class GitHubOps:
    """Mutating GitHub operations, each guarded. Construct once per graph node.

    ``report_only`` (None → env ``GITHUB_OPS_REPORT_ONLY``) governs probation behaviour, but
    its effect now depends on whether the op is a RECORD or a CODE action (see
    ``_RECORD_ACTIONS``):

      * **CODE actions** (open_pr, merge_pr, create_branch, put_file, delete_branch): under
        report_only the call returns an honest ``{"status": "report_only", ...}`` plan dict
        WITHOUT contacting GitHub or the gate — exactly as before. Probation = no code writes.
      * **RECORD actions** (open_issue, comment_issue, comment_on_pr): a durable record of work
        (an issue/comment) is NOT an irreversible code action, so it MAY write even under
        report_only. This is the whole point — capture the fleet's decision-grade work in
        GitHub instead of letting it scroll away in Slack. RECORD writes are still allow-list
        scoped and model-work guarded; they simply do not require the human merge gate.

    ``gh_client`` (optional): an injected GitHub client. When set, ``_client()`` returns it
    instead of authenticating — the seam tests use to mock GitHub with NO network/writes.
    """

    report_only: Optional[bool] = None
    gh_client: Optional[Any] = None

    def _is_report_only(self) -> bool:
        return self.report_only if self.report_only is not None else _default_report_only()

    def _client(self) -> Any:
        if self.gh_client is not None:
            return self.gh_client
        return self._authenticated_client()

    def _authenticated_client(self) -> Any:
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
        """Shared path for every mutating op: allow-list → (report-only? / record?) → AUTO-tier? → human gate → run.

        The report_only behaviour now forks on RECORD vs CODE (see ``_RECORD_ACTIONS``):

          * CODE action + report_only  → return the plan dict, no GitHub, no gate (probation).
          * RECORD action + report_only → SKIP the human merge gate but STILL WRITE the record
            (a durable issue/comment is not an irreversible code action). Allow-list + model
            guard still apply.
          * Not report_only → the existing AUTO-tier / human-gate path runs for every action.
        """
        assert_allowed_repo(repo)
        is_record = action in _RECORD_ACTIONS
        if self._is_report_only():
            if not is_record:
                # CODE action on probation: honest plan, never a write.
                return {"status": "report_only", "action": action, "repo": repo, "payload": payload}
            # RECORD action on probation: write the durable record without the merge gate.
            return run(self._client())
        auto = os.environ.get("AGENT_AUTONOMY", "").lower() == "auto"
        # Records and the explicitly-safe AUTO actions skip the gate when autonomy is on.
        gate_free = auto and (is_record or action in self._SAFE_AUTO_ACTIONS)
        if not gate_free:
            decision = request_approval(action, {"repo": repo, **payload}, risk=risk)
            if not is_approved(decision):
                raise GitHubWriteBlocked(
                    f"Human rejected '{action}' on {repo} (decision={decision!r})."
                )
        return run(self._client())

    # --- Operations ------------------------------------------------------------------

    def open_issue(
        self,
        repo: str,
        title: str,
        body: str,
        labels: Optional[list[str]] = None,
        *,
        dedup_key: Optional[str] = None,
        agent: Optional[str] = None,
        related: Optional[list] = None,
    ):
        """Open (or, with ``dedup_key``, find-or-update) a durable record issue.

        * ``dedup_key`` — when set, search the repo's OPEN issues for the hidden
          ``<!-- agent-record:{dedup_key} -->`` marker AND for proof the issue is a
          fleet-owned record (see ``_is_fleet_owned_record``: fleet-login authorship and/or
          the agent's own ``agent:<slug>`` label). If a fleet-owned match is found, APPEND an
          update comment (one issue, +1 comment) instead of filing a duplicate; otherwise open
          a fresh issue carrying the marker. The marker alone never authorizes an edit — a
          human-authored issue that merely quotes the (invisible, caller-controlled) marker is
          NOT treated as the record, so the dedup lane can never overwrite foreign state.
          This is the find-or-update that ends the #33/#35/#43 duplicate-issue spam.
        * ``agent`` — adds a per-agent attribution label ``agent:<slug>`` (the missing "who").
        * ``related`` — a list of issue/PR refs (ints, ``#n``, ``owner/repo#n``, or URLs);
          rendered into a GitHub cross-link footer so records link to the work they touch.

        A RECORD action: writes even under ``report_only=True`` (see ``_guard_and_run``).
        """
        all_labels = list(labels or [])
        agent_lbl = agent_label(agent) if agent else None
        if agent_lbl and agent_lbl not in all_labels:
            all_labels.append(agent_lbl)
        composed = _compose_record_body(body, dedup_key=dedup_key, related=related)

        def run(gh):
            r = gh.get_repo(repo)
            if dedup_key:
                marker = _record_marker(dedup_key)
                existing = None
                for issue in r.get_issues(state="open"):
                    if marker not in (getattr(issue, "body", "") or ""):
                        continue
                    # The marker is necessary but NOT sufficient: only find-or-update an issue
                    # the fleet itself owns, so a record can never overwrite/edit a foreign
                    # (e.g. human-authored) issue that merely quotes the invisible marker.
                    if not _is_fleet_owned_record(issue, agent_lbl=agent_lbl):
                        continue
                    existing = issue
                    break
                if existing is not None:
                    # Find-or-update on a FLEET-OWNED record: APPEND an update comment (never
                    # wholesale-replace the body — prior content is preserved by construction)
                    # and ensure the agent label. Comment-storm guard: skip the comment when the
                    # new content already appears in the issue body or its most recent comment.
                    update = _compose_record_body(body, related=related)
                    if not _record_unchanged(existing, body):
                        existing.create_comment(update)
                    for lbl in all_labels:
                        if lbl.lower() in _issue_labels(existing):
                            continue
                        try:
                            existing.add_to_labels(lbl)
                        except Exception:
                            pass
                    return {**_result(existing), "deduped": True, "dedup_key": dedup_key}
            issue = r.create_issue(title=title, body=composed, labels=all_labels)
            res = _result(issue)
            if dedup_key:
                res = {**res, "deduped": False, "dedup_key": dedup_key}
            return res

        return self._guard_and_run(
            action="open_issue",
            repo=repo,
            payload={"title": title, "labels": all_labels, "dedup_key": dedup_key},
            risk="medium",
            run=run,
        )

    def comment_issue(self, repo: str, number: int, body: str, *, related: Optional[list] = None):
        composed = _compose_record_body(body, related=related)
        return self._guard_and_run(
            action="comment_issue",
            repo=repo,
            payload={"number": number},
            risk="low",
            run=lambda gh: _result(gh.get_repo(repo).get_issue(number).create_comment(composed)),
        )

    def comment_on_pr(self, repo: str, pr_number: int, body: str, *, related: Optional[list] = None):
        """Post a record comment on a PR (an issue-style comment on the PR conversation).

        A RECORD action: durable narration of the fleet's review of a human PR — writes even
        under ``report_only=True``. (In GitHub a PR is an issue, so the comment lands on the
        PR's conversation timeline via ``get_issue(pr_number).create_comment``.)
        """
        composed = _compose_record_body(body, related=related)
        return self._guard_and_run(
            action="comment_on_pr",
            repo=repo,
            payload={"pr_number": pr_number},
            risk="low",
            run=lambda gh: _result(
                gh.get_repo(repo).get_issue(pr_number).create_comment(composed)
            ),
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
        allow-list scoped, no gate. Drives the auto-prune-safe decision.

        Also surfaces two signals the prune guard needs so a merged-but-still-live or
        gate-held branch is never auto-deleted:
          * ``labels``        — union of label names across the branch's PRs (so a
                                ``gate:human-required`` / ``hold`` / ``security`` marker is visible);
          * ``last_activity`` — the most recent updated/merged/created timestamp across those
                                PRs (ISO-8601), a coarse "is this branch still live?" proxy.
        Both are best-effort and fail-soft (a missing attribute never raises)."""
        assert_allowed_repo(repo)
        gh = self._client()
        r = gh.get_repo(repo)
        owner = repo.split("/")[0]
        pulls = list(r.get_pulls(state="all", head=f"{owner}:{branch}"))

        labels: set[str] = set()
        stamps: list[str] = []
        for p in pulls:
            for lbl in (getattr(p, "labels", None) or []):
                nm = getattr(lbl, "name", lbl)
                if isinstance(nm, str) and nm:
                    labels.add(nm)
            for attr in ("updated_at", "merged_at", "created_at"):
                v = getattr(p, attr, None)
                if v is not None:
                    stamps.append(v.isoformat() if hasattr(v, "isoformat") else str(v))

        return {
            "has_pr": bool(pulls),
            "merged": any(p.merged_at is not None for p in pulls),
            "open": any(p.state == "open" for p in pulls),
            "numbers": [p.number for p in pulls],
            "labels": sorted(labels),
            "last_activity": max(stamps) if stamps else None,
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
