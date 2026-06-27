"""pr_eval — DETERMINISTIC pull-request evaluation + safe-to-automerge classification.

This is the brain behind the board's "agents decide on PRs" step: given a PR it gathers the
facts (PR metadata, diff, CI checks) via the ``gh`` CLI, classifies the blast radius / HARD
GATEs, and returns a structured verdict — without ever merging anything. The *deciding* lives
here (pure, deterministic, testable); the *acting* lives in the board ``pr_review`` graph,
which calls this and posts a report-only review (and would merge only the provably-safe class,
off probation, via ``github_ops``).

Why LangGraph-free (deliberate):
  * This module must import with nothing but the stdlib + ``github_ops`` (no langgraph /
    langchain / model SDK). It is the deterministic core that a test can exercise with no
    network and no LLM, and that any caller (the graph, a CLI, a webhook) can reuse.
  * v1 makes NO model call. The verdict is derived from CI state + mergeability + a
    substring scan of the changed paths, so it is reproducible and never "vibes". A future
    version may add a model-written narrative ON TOP, exactly like the board graphs do —
    but the gate decision must always stand on the deterministic facts.

The gate rules INHERIT the workspace ``pr-eval`` skill + ``github_ops``:
  * A HARD GATE (``safe_to_automerge=False`` + a ``gate_reason``) fires if ANY of:
      - the PR merges to the default/main branch of a PRODUCTION repo (``PROD_DEPLOY_REPOS``)
        — it deploys an app/API/infra, is customer-facing, or is a billing/security baseline;
      - the repo is not on the write allow-list (``assert_allowed_repo`` raises);
      - the diff itself is gate-relevant (security / auth / access-control / governance /
        billing / secrets / deploy / infra paths);
      - merging would require ``--admin`` (a failing/blocked merge-state the agent must not
        force);
      - irreversible / capital / legal markers appear in the PR.
  * ``safe_to_automerge=True`` ONLY when ALL hold: a clean review verdict (no blocker), CI
    checks pass, ``mergeable == MERGEABLE`` & ``mergeStateStatus == CLEAN``, AND the blast
    radius is LOW (docs / tooling / tests / gated-off config) in a NON-production OR
    no-deploy + no-secret + reversible change.

Gather seam (testability): every ``gh`` subprocess call goes through an injectable ``runner``
(``_gather(repo, number, runner=...)``). The default runner shells out to ``gh``; tests pass a
fake runner so they need NO network and NO ``gh`` install.
"""
from __future__ import annotations

import json
import subprocess
from typing import Any, Callable, Optional

from .github_ops import (
    PROD_DEPLOY_REPOS,
    GitHubWriteBlocked,
    assert_allowed_repo,
)

# A runner takes the ``gh`` argv (without the leading "gh") and returns (returncode, stdout).
# stderr is folded into stdout being irrelevant — we only need the payload or a failure signal.
Runner = Callable[[list[str]], "tuple[int, str]"]

# Verdicts (review lens). APPROVE / APPROVE_WITH_NITS carry no blocker; the others do.
VERDICT_APPROVE = "APPROVE"
VERDICT_APPROVE_WITH_NITS = "APPROVE_WITH_NITS"
VERDICT_REQUEST_CHANGES = "REQUEST_CHANGES"
VERDICT_BLOCKED = "BLOCKED"
VERDICT_UNKNOWN = "UNKNOWN"

_NON_BLOCKING_VERDICTS = frozenset({VERDICT_APPROVE, VERDICT_APPROVE_WITH_NITS})

# Blast-radius buckets.
BLAST_LOW = "low"          # docs / tooling / tests / gated-off config — reversible, no deploy
BLAST_MEDIUM = "medium"    # ordinary app/source change, no gate marker
BLAST_HIGH = "high"        # gate-relevant: security/auth/access-control/governance/billing/deploy

# Path substrings whose presence in a changed file makes the diff itself gate-relevant. These
# mirror the HARD-GATE classes (security baseline, access control, billing, deploy/infra, secrets).
_GATE_PATH_TOKENS = (
    "firestore.rules",
    "storage.rules",
    ".github/workflows",
    "auth",
    "security",
    "rbac",
    "acl",
    "access-control",
    "access_control",
    "permission",
    "governance",
    "billing",
    "stripe",
    "revenuecat",
    "payment",
    "secret",
    "credential",
    "token",
    "deploy",
    "terraform",
    "k8s",
    "kubernetes",
    "helm",
    "infra",
    "iam",
    "vault",
)

# Tokens in the PR title/body that mark an irreversible / capital / legal change — always gate.
_IRREVERSIBLE_TOKENS = (
    "irreversible",
    "capital",
    "legal",
    "contract",
    "production deploy",
    "prod deploy",
    "delete data",
    "drop table",
    "migration",  # data migrations are not auto-mergeable in v1 — escalate
)

# mergeStateStatus values that mean a normal merge cannot proceed without --admin / more work.
# DIRTY (conflicts), BEHIND (out of date), BLOCKED (failing required checks / unmet protections),
# DRAFT (still a draft). Only CLEAN is safe to auto-merge.
_CLEAN_MERGE_STATE = "CLEAN"


# --- the default gh runner -------------------------------------------------------------
def _gh_runner(args: list[str]) -> "tuple[int, str]":
    """Shell out to ``gh``; return (returncode, combined stdout/stderr). Never raises."""
    try:
        proc = subprocess.run(  # noqa: S603 — fixed argv, no shell
            ["gh", *args],
            capture_output=True,
            text=True,
            timeout=60,
        )
        out = proc.stdout or ""
        if proc.returncode != 0:
            # Fold stderr in so the caller can see WHY (tolerate-and-degrade upstream).
            out = (out + "\n" + (proc.stderr or "")).strip()
        return proc.returncode, out
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, f"gh invocation failed: {type(exc).__name__}"


# --- gather (injectable seam) ----------------------------------------------------------
_PR_VIEW_FIELDS = (
    "number,title,body,state,isDraft,baseRefName,headRefName,"
    "mergeable,mergeStateStatus,author,additions,deletions,changedFiles,files,url,labels"
)


def _gather(repo: str, number: int, runner: Optional[Runner] = None) -> dict:
    """Gather the raw facts for a PR via ``gh`` (or an injected ``runner``). FAIL-SOFT.

    Returns a dict with keys ``view`` (parsed ``gh pr view --json`` or {}), ``diff`` (str),
    ``checks`` (the ``gh pr checks`` text), and ``errors`` (a list of what could not be read).
    A failure on any call degrades that field but never raises — the classifier maps missing
    facts to UNKNOWN / not-safe rather than crashing.
    """
    run = runner or _gh_runner
    errors: list[str] = []

    # 1) PR metadata (JSON).
    view: dict = {}
    rc, out = run(["pr", "view", str(number), "--repo", repo, "--json", _PR_VIEW_FIELDS])
    if rc == 0 and out.strip():
        try:
            view = json.loads(out)
        except (ValueError, TypeError):
            errors.append("pr_view_unparseable")
    else:
        errors.append("pr_view_failed")

    # 2) Diff (text). Large diffs are fine — we only scan changed paths from `files`, but the
    #    raw diff is kept for the evidence block (truncated when rendered).
    diff = ""
    rc, out = run(["pr", "diff", str(number), "--repo", repo])
    if rc == 0:
        diff = out
    else:
        errors.append("pr_diff_failed")

    # 3) CI checks (text table). `gh pr checks` exits non-zero when checks fail OR are pending,
    #    so we keep BOTH the rc and the text and interpret them in the classifier.
    checks_rc, checks_out = run(["pr", "checks", str(number), "--repo", repo])

    return {
        "view": view,
        "diff": diff,
        "checks": checks_out,
        "checks_rc": checks_rc,
        "errors": errors,
    }


# --- classification helpers (pure) -----------------------------------------------------
def _changed_paths(view: dict) -> list[str]:
    """The changed file paths from ``gh pr view --json files`` (best-effort)."""
    files = view.get("files") or []
    paths: list[str] = []
    for f in files:
        if isinstance(f, dict):
            p = f.get("path")
            if isinstance(p, str) and p:
                paths.append(p)
    return paths


def _is_default_branch_target(base_ref: str) -> bool:
    """Whether the PR targets a repo's default/integration branch (main/master/etc.)."""
    return (base_ref or "").strip().lower() in {"main", "master", "develop", "release", "production"}


def _diff_is_gate_relevant(paths: list[str]) -> Optional[str]:
    """Return the first gate-relevant path token matched in the changed paths, else None."""
    low_paths = [p.lower() for p in paths]
    for p in low_paths:
        for tok in _GATE_PATH_TOKENS:
            if tok in p:
                return f"{tok} (in {p})"
    return None


def _irreversible_marker(view: dict) -> Optional[str]:
    """Return the first irreversible/capital/legal marker in the PR title/body, else None."""
    text = ((view.get("title") or "") + "\n" + (view.get("body") or "")).lower()
    for tok in _IRREVERSIBLE_TOKENS:
        if tok in text:
            return tok
    return None


def _checks_pass(checks_text: str, checks_rc: int) -> Optional[bool]:
    """Interpret ``gh pr checks`` output: True (all pass), False (a fail/pending), None (unknown).

    ``gh pr checks`` prints one row per check with a state column ("pass"/"fail"/"pending"/
    "skipping") and exits 0 only when every (non-skipped) check passed. We use BOTH signals:
    an empty output with rc!=0 is UNKNOWN (could not read), a populated output is parsed.
    """
    text = (checks_text or "").strip()
    if not text:
        # No checks output. rc==0 with no checks means "no checks configured" → treat as unknown
        # rather than pass, so the absence of CI never green-lights an auto-merge.
        return None
    low = text.lower()
    if "fail" in low or "failing" in low:
        return False
    if "pending" in low or "in_progress" in low or "queued" in low or "expected" in low:
        return False
    if "pass" in low or "success" in low or "skipping" in low:
        # Corroborate with the exit code: gh returns 0 only when nothing is failing/pending.
        return checks_rc == 0
    # Unrecognized shape — be conservative.
    return None


def _review_verdict(view: dict, checks_pass: Optional[bool], blast: str) -> str:
    """A deterministic review verdict from the facts (no LLM in v1).

    APPROVE / APPROVE_WITH_NITS only when there is no blocking signal; a draft, a non-clean
    merge state, failing/unknown CI, or a high blast radius downgrades the verdict so it can
    never silently satisfy the auto-merge precondition.
    """
    if not view:
        return VERDICT_UNKNOWN
    if view.get("isDraft"):
        return VERDICT_BLOCKED
    if (view.get("state") or "").upper() != "OPEN":
        return VERDICT_BLOCKED
    if checks_pass is False:
        return VERDICT_REQUEST_CHANGES
    if checks_pass is None:
        return VERDICT_UNKNOWN
    if blast == BLAST_HIGH:
        # A gate-relevant diff is reviewable but never an auto-approve — a human decides.
        return VERDICT_REQUEST_CHANGES
    # Clean facts, low/medium blast: approve (nits possible but non-blocking).
    return VERDICT_APPROVE_WITH_NITS if blast == BLAST_MEDIUM else VERDICT_APPROVE


def _render_summary(repo: str, number: int, view: dict, verdict: str, blast: str,
                    safe: bool, gate_reason: str, checks_pass: Optional[bool]) -> str:
    """A short, deterministic, human-readable review summary (no LLM)."""
    title = view.get("title") or "(unknown title)"
    base = view.get("baseRefName") or "?"
    head = view.get("headRefName") or "?"
    ci = {True: "passing", False: "failing/pending", None: "unknown"}[checks_pass]
    decision = "SAFE to auto-merge" if safe else f"HELD — {gate_reason}"
    return (
        f"PR {repo}#{number}: {title}\n"
        f"  {head} → {base} | verdict={verdict} | blast={blast} | CI={ci}\n"
        f"  decision: {decision}"
    )


def _render_evidence(view: dict, data: dict, checks_pass: Optional[bool]) -> str:
    """A compact evidence block: files, +/- lines, CI, mergeability, and any gather errors."""
    paths = _changed_paths(view)
    add = view.get("additions")
    dele = view.get("deletions")
    changed = view.get("changedFiles")
    mergeable = view.get("mergeable")
    state = view.get("mergeStateStatus")
    ci = {True: "pass", False: "fail/pending", None: "unknown"}[checks_pass]
    errors = data.get("errors") or []
    lines = [
        f"changedFiles={changed} (+{add}/-{dele})",
        f"mergeable={mergeable} mergeStateStatus={state}",
        f"CI={ci}",
    ]
    if paths:
        shown = paths[:20]
        more = f" (+{len(paths) - len(shown)} more)" if len(paths) > len(shown) else ""
        lines.append("files: " + ", ".join(shown) + more)
    if errors:
        lines.append("gather_errors: " + ", ".join(errors))
    return "\n".join(lines)


# --- public API ------------------------------------------------------------------------
def classify(repo: str, number: int, data: dict) -> dict:
    """Pure classifier: turn gathered ``data`` into the verdict dict. NO network, NO LLM.

    Split out from ``evaluate_pr`` so a test can drive the full decision with a hand-built
    ``data`` payload (exactly what ``_gather`` returns) and assert the gate outcome.
    """
    view = data.get("view") or {}
    checks_pass = _checks_pass(data.get("checks", ""), data.get("checks_rc", 1))
    paths = _changed_paths(view)
    base_ref = view.get("baseRefName") or ""

    # --- HARD-GATE classification (any one → not safe) ---------------------------------
    gate_reasons: list[str] = []

    # (1) Allow-list: a repo the workforce may not even write to is never auto-mergeable.
    try:
        assert_allowed_repo(repo)
    except GitHubWriteBlocked:
        gate_reasons.append(f"repo {repo} is not on the write allow-list")

    # (2) Production repo + default-branch target → a prod-deploy / customer-facing merge.
    targets_default = _is_default_branch_target(base_ref)
    if repo in PROD_DEPLOY_REPOS and targets_default:
        gate_reasons.append(
            f"merge to '{base_ref}' of production repo {repo} (deploys app/API/infra, "
            "customer-facing or billing/security baseline)"
        )

    # (3) The diff itself is gate-relevant (security / auth / access-control / governance /
    #     billing / secrets / deploy / infra).
    gate_path = _diff_is_gate_relevant(paths)
    if gate_path:
        gate_reasons.append(f"gate-relevant change: {gate_path}")

    # (4) Irreversible / capital / legal markers in the PR text.
    marker = _irreversible_marker(view)
    if marker:
        gate_reasons.append(f"irreversible/capital/legal marker: '{marker}'")

    # (5) Merge state requires --admin (conflicts / behind / blocked / draft) → never force.
    merge_state = (view.get("mergeStateStatus") or "").upper()
    mergeable = (view.get("mergeable") or "").upper()
    if view and merge_state and merge_state != _CLEAN_MERGE_STATE:
        gate_reasons.append(
            f"merge state {merge_state!r} is not CLEAN — would require --admin / more work"
        )

    # --- blast radius -------------------------------------------------------------------
    if gate_path:
        blast = BLAST_HIGH
    elif _all_low_risk_paths(paths):
        blast = BLAST_LOW
    else:
        blast = BLAST_MEDIUM

    verdict = _review_verdict(view, checks_pass, blast)

    # --- safe-to-automerge: ALL preconditions must hold --------------------------------
    safe = (
        not gate_reasons
        and verdict in _NON_BLOCKING_VERDICTS
        and checks_pass is True
        and mergeable == "MERGEABLE"
        and merge_state == _CLEAN_MERGE_STATE
        and blast == BLAST_LOW
    )
    gate_reason = "" if safe else (
        "; ".join(gate_reasons) if gate_reasons
        else _why_not_safe(verdict, checks_pass, mergeable, merge_state, blast)
    )

    summary = _render_summary(repo, number, view, verdict, blast, safe, gate_reason, checks_pass)
    evidence = _render_evidence(view, data, checks_pass)

    return {
        "pr": number,
        "repo": repo,
        "verdict": verdict,
        "safe_to_automerge": bool(safe),
        "gate_reason": gate_reason,
        "blast_radius": blast,
        "summary": summary,
        "evidence": evidence,
    }


def _all_low_risk_paths(paths: list[str]) -> bool:
    """Whether EVERY changed path is a low-risk doc/tooling/test/gated-off-config path.

    Empty path list (couldn't read files) is NOT low — absence of evidence is not low risk.
    """
    if not paths:
        return False
    low_ok = (
        ".md", "docs/", "readme", "license", "notice", "changelog",
        "test", "/tests/", "_test.", ".test.", "spec.", "fixture",
        ".txt", ".rst",
    )
    for p in paths:
        lp = p.lower()
        if not any(tok in lp for tok in low_ok):
            return False
    return True


def _why_not_safe(verdict: str, checks_pass: Optional[bool], mergeable: str,
                  merge_state: str, blast: str) -> str:
    """A concise reason a non-gated PR still isn't auto-merge-safe (precondition miss)."""
    reasons: list[str] = []
    if verdict not in _NON_BLOCKING_VERDICTS:
        reasons.append(f"verdict={verdict}")
    if checks_pass is not True:
        reasons.append("CI not confirmed passing")
    if mergeable != "MERGEABLE":
        reasons.append(f"mergeable={mergeable or 'unknown'}")
    if merge_state != _CLEAN_MERGE_STATE:
        reasons.append(f"mergeStateStatus={merge_state or 'unknown'}")
    if blast != BLAST_LOW:
        reasons.append(f"blast_radius={blast}")
    return "not auto-merge-safe: " + ", ".join(reasons) if reasons else "not auto-merge-safe"


def evaluate_pr(repo: str, number: int, runner: Optional[Runner] = None) -> dict:
    """Evaluate a PR and return the verdict dict. Deterministic, no LLM, no merge.

    Gathers facts via ``gh`` (or an injected ``runner``) then classifies. Returns:
      ``{pr, repo, verdict, safe_to_automerge, gate_reason, blast_radius, summary, evidence}``.
    The decision is REPORT-ONLY data — this function never mutates the PR or the repo.
    """
    data = _gather(repo, number, runner=runner)
    return classify(repo, number, data)
