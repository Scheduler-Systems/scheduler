"""Shared reporting seam for the ops fleet — one consistent way to emit a digest.

The ops agents (git-sync auditor, memory-sync, revenue reporter, store-health checker) all
produce a human-readable digest. They deliver it two ways, both FAIL-SAFE:

  - ``write_local_digest`` — always: write the digest to ``<root>/.tmp/<agent>/latest.md``
    so there is a local artifact even with zero credentials (mirrors git_local_maintainer).
  - ``file_digest_issue`` — for the cloud agents: file the digest as a GitHub issue via
    ``github_ops.open_issue``, which is itself guarded (allow-list → report-only? →
    AGENT_AUTONOMY=auto SAFE_AUTO? → human gate). With no token / GITHUB_OPS_REPORT_ONLY it
    returns an honest ``{"status": "report_only", ...}`` plan dict instead of writing.

Neither helper EVER raises — a reporting failure must not crash an agent run.
"""
from __future__ import annotations

import os
from typing import Optional

# LangGraph control-flow base. ``interrupt()`` (the HITL approval gate in approval.py) signals
# a pause by RAISING ``GraphInterrupt``, a subclass of ``GraphBubbleUp`` (itself an Exception
# subclass). The broad ``except Exception`` around the GitHub write below MUST NOT swallow it —
# a control-flow signal has to propagate so the runtime can pause/resume the run. We re-raise
# ``_BubbleUp`` before the generic catch. Imported defensively so this module never hard-requires
# langgraph (its contract is fail-safe + lazy imports); when unavailable, ``_BubbleUp`` is an
# unsatisfiable sentinel so the ``except _BubbleUp`` clause is simply inert.
try:  # pragma: no cover - import shim
    from langgraph.errors import GraphBubbleUp as _BubbleUp  # type: ignore
except Exception:  # langgraph not installed / different version
    class _BubbleUp(Exception):  # type: ignore
        """Sentinel: matches nothing real when langgraph is unavailable."""

# The enterprise workspace root (where .tmp lives), overridable for tests / other hosts.
_DEFAULT_ROOT = "/Users/scheduler-systems/Documents/scheduler-systems-ltd"


def workspace_root(root: Optional[str] = None) -> str:
    return root or os.environ.get("WORKSPACE_ROOT") or _DEFAULT_ROOT


def write_local_digest(agent: str, title: str, body_md: str, *, root: Optional[str] = None) -> str:
    """Write ``body_md`` to ``<root>/.tmp/<agent>/latest.md``. Returns the path, or "" on error.

    ``agent`` is used as a path segment, so it is sanitized to a safe slug. FAIL-SAFE.
    """
    slug = "".join(c if (c.isalnum() or c in "-_") else "-" for c in (agent or "ops")).strip("-") or "ops"
    try:
        digest_dir = os.path.join(workspace_root(root), ".tmp", slug)
        os.makedirs(digest_dir, exist_ok=True)
        path = os.path.join(digest_dir, "latest.md")
        header = f"# {title}\n\n" if title else ""
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(header + (body_md or "") + "\n")
        return path
    except OSError:
        return ""


def read_local_digest(slug: str, *, root: Optional[str] = None, max_chars: int = 6000) -> str:
    """Read another agent's latest local digest (the inverse of ``write_local_digest``). FAIL-SAFE.

    Executives and the board CONSUME subordinate agents' reports rather than re-doing work; this
    is how they read them. Returns the digest text (capped), or "(no digest yet)" when the file is
    missing/unreadable. NEVER raises.
    """
    safe = "".join(c if (c.isalnum() or c in "-_") else "-" for c in (slug or "")).strip("-") or "ops"
    try:
        path = os.path.join(workspace_root(root), ".tmp", safe, "latest.md")
        with open(path, "r", encoding="utf-8") as fh:
            data = fh.read(max_chars + 1)
        if not data.strip():
            return "(no digest yet)"
        return data[:max_chars] + ("\n…(truncated)…" if len(data) > max_chars else "")
    except Exception:
        return "(no digest yet)"


def _title_kind(title: str) -> str:
    """Derive a STABLE record-kind slug from a digest ``title``.

    The exec/ops/board digests file the SAME titled digest every shift (e.g. "CFO: spend +
    budget allocation (proposal)"), so a slug of the title is a stable per-recurring-record key.
    Sanitized to ``[a-z0-9-]`` and capped so it is a safe, bounded dedup-key segment. Falls back
    to ``"digest"`` for an empty/symbol-only title."""
    slug = "".join(c if (c.isalnum() or c in "-_") else "-" for c in (title or "").lower())
    slug = "-".join(p for p in slug.split("-") if p)  # collapse runs of separators
    return (slug[:64].strip("-")) or "digest"


def file_digest_issue(
    repo: str,
    title: str,
    body: str,
    *,
    labels: Optional[list[str]] = None,
    report_only: Optional[bool] = None,
    agent: Optional[str] = None,
    slack_title: Optional[str] = None,
    related: Optional[list] = None,
    record_kind: Optional[str] = None,
) -> dict:
    """File the digest as a DURABLE, DEDUPED GitHub record + post to Slack. FAIL-SAFE.

    This is the close-the-loop seam for EVERY agent that posts a digest (exec/CFO/CTO/audit/
    ops/board/marketing/sales). It delegates to ``file_digest_record`` so the digest is captured
    as a durable GitHub issue — even on probation — instead of scrolling away in Slack:

      * **Records write even under ``report_only=True``.** An issue is a durable RECORD of work,
        not an irreversible CODE action, so ``github_ops`` writes it on probation while CODE
        actions (open PR, merge, push) stay gated (the HITL line is unchanged).
      * **Deduped per (agent, kind) — re-runs UPDATE, never duplicate.** When ``agent`` is given,
        a stable ``dedup_key = record:{agent}:{record_kind or slug(title)}`` is derived so the
        SAME issue is found-and-updated each shift (kills the #33/#35/#43 duplicate-issue spam)
        instead of re-filing. The find-or-update is authorship-guarded in ``github_ops`` so a
        record can never overwrite a human-authored issue.
      * **Slack delivery is preserved.** The digest is still mirrored to the agent's Slack
        channel exactly as before, and the returned dict carries the ``slack`` status.

    ``record_kind`` (optional): override the recurring-record kind; defaults to a slug of the
    title. ``related`` (optional): cross-link refs rendered into the issue body.

    BACKWARD-COMPAT: the public signature is a superset of the original (the new ``related`` /
    ``record_kind`` are keyword-only with defaults), so every existing caller keeps working
    unchanged. When ``agent`` is None (no per-agent attribution to dedup on), behaviour falls
    back to the original non-deduped single-issue path so no caller silently changes semantics.

    Returns the ``open_issue`` result dict on success / report-only, or a structured
    ``{"status": "error" | "blocked", "error": ...}`` on any failure (no token, not
    allow-listed, human-rejected, network). NEVER raises.
    """
    # When we know WHO is filing, route through the durable deduped record path so the digest
    # is captured in GitHub (deduped + per-agent labelled + cross-linked) and mirrored to Slack.
    if agent:
        return file_digest_record(
            repo,
            title,
            body,
            agent=agent,
            record_kind=record_kind or _title_kind(title),
            related=related,
            labels=labels,
            report_only=report_only,  # None ⇒ file_digest_record derives it from the per-agent gate
            slack_title=slack_title,
        )

    # No agent → cannot prove per-agent ownership for find-or-update, so keep the original
    # single-issue path (an anonymous digest must not latch onto another agent's record).
    try:
        from .github_ops import GitHubOps, GitHubNotConfigured, GitHubWriteBlocked
    except Exception as exc:
        result: dict = {"status": "error", "error": f"github_ops unavailable: {type(exc).__name__}"}
    else:
        try:
            result = GitHubOps(report_only=report_only).open_issue(
                repo, title, body, labels=labels or [], agent=agent, related=related
            )
        except GitHubNotConfigured:
            result = {"status": "report_only", "action": "open_issue", "repo": repo,
                      "payload": {"title": title, "labels": labels or []},
                      "note": "no GitHub credentials — issue not filed (report-only)"}
        except GitHubWriteBlocked as exc:
            result = {"status": "blocked", "error": str(exc)[:200]}
        except _BubbleUp:
            # LangGraph control-flow signal (HITL pause / resume). It is an Exception subclass
            # but MUST propagate so the runtime can pause the run — never swallow it as a
            # generic "github error" (that would silently defeat the human-in-the-loop gate).
            raise
        except Exception as exc:
            result = {"status": "error", "error": type(exc).__name__}

    return result


def file_digest_record(
    repo: str,
    title: str,
    body: str,
    *,
    agent: str,
    record_kind: str,
    related: Optional[list] = None,
    labels: Optional[list[str]] = None,
    report_only: Optional[bool] = None,
    slack_title: Optional[str] = None,
) -> dict:
    """Route an agent's report-only PLAN to GitHub as a DURABLE record + mirror to Slack. FAIL-SAFE.

    This is the close-the-loop seam: a probation agent's decision-grade work (exec/CFO/CTO/
    audit) is captured as a durable GitHub issue instead of scrolling away in Slack. Built on
    the RECORD vs CODE boundary in ``github_ops``: an issue/comment is a durable RECORD, not an
    irreversible CODE action, so it writes EVEN under ``report_only=True`` (the whole point),
    while code actions (open PR, merge, push) stay gated.

    Args:
        repo:        Allow-listed target repo (``owner/name``).
        title:       Issue title.
        body:        Markdown digest body.
        agent:       Agent slug — drives the per-agent ``agent:<slug>`` label AND the Slack
                     channel routing.
        record_kind: A stable kind for this recurring record (e.g. ``"branch-review"``,
                     ``"cfo-burn"``). Combined with ``agent`` into the dedup key
                     ``record:{agent}:{record_kind}`` so the SAME issue is found-and-updated
                     each shift instead of re-filed (kills #33/#35/#43-style duplicates).
        related:     Cross-link refs (ints / ``#n`` / ``owner/repo#n`` / URLs) rendered into
                     the issue body as GitHub references.
        labels:      Extra labels beyond the auto per-agent label.
        report_only: Probation flag forwarded to ``GitHubOps``. For a RECORD this does NOT
                     suppress the write — it only governs whether code actions would write.
                     Leave None to honor ``GITHUB_OPS_REPORT_ONLY``.
        slack_title: Override the Slack headline (defaults to ``title``).

    Returns the ``open_issue`` result dict (carrying ``deduped``/``dedup_key`` and a ``slack``
    status), or a structured ``{"status": "error"|"blocked", ...}`` on any failure. NEVER raises.
    """
    dedup_key = f"record:{agent}:{record_kind}"

    # --- Per-agent write-enable gate (the graduation seam) ---------------------------------
    # A digest RECORD is the lowest-risk write (deduped + authorship-guarded), but graduating an
    # agent from report-only is PER-AGENT, not global. The gate is consulted whenever the caller
    # did NOT pin ``report_only`` (the production path — a graph passes its per-agent posture
    # through, or None to defer entirely) AND whenever the caller asked to WRITE
    # (``report_only=False``). In both those cases the record writes for real ONLY IF
    # ``write_enabled(agent)``:
    #   * NOT write-enabled (off the AGENTS_WRITE_ENABLED allowlist, on the never-list,
    #     kill-switched/over-budget, or under the global OPS_REPORT_ONLY floor) ⇒ the record is
    #     WITHHELD: an honest report-only plan dict is returned with NO GitHub call and NO outward
    #     Slack post. This is true report-only — a non-graduated agent takes no real/outward action,
    #     and a ``report_only=False`` from a globally-lifted flag can NEVER write a non-allowlisted
    #     or never-list agent's record (that is the whole point of the per-agent gate).
    #   * write-enabled ⇒ file the record for real (the guards in ``github_ops`` — allow-list,
    #     authorship, dedup, RECORD-vs-CODE — are UNTOUCHED).
    # An explicit ``report_only=True`` is a CALLER VETO honored unchanged (it does NOT consult the
    # gate and keeps the legacy RECORD-writes-on-probation contract that durable-record tests rely
    # on): asking for report-only is always allowed; only asking to WRITE is gated per-agent.
    if report_only is not True:  # None (defer) or False (write) ⇒ the per-agent gate decides
        try:
            from .write_gate import write_enabled as _write_enabled
            enabled = _write_enabled(agent)
        except Exception:
            enabled = False  # fail-safe: any gate error ⇒ report-only
        if not enabled:
            return {
                "status": "report_only",
                "action": "open_issue",
                "repo": repo,
                "payload": {"title": title, "labels": list(labels or []), "dedup_key": dedup_key},
                "agent": agent,
                "note": "per-agent write gate: agent not write-enabled — record withheld (report-only)",
                "slack": "report_only",
            }
        report_only = False  # write-enabled ⇒ file the record for real

    # GitHub delivery (durable record — deduped, per-agent labelled, cross-linked)
    try:
        from .github_ops import GitHubOps, GitHubNotConfigured, GitHubWriteBlocked
    except Exception as exc:
        result: dict = {"status": "error", "error": f"github_ops unavailable: {type(exc).__name__}"}
    else:
        try:
            result = GitHubOps(report_only=report_only).open_issue(
                repo,
                title,
                body,
                labels=labels or [],
                dedup_key=dedup_key,
                agent=agent,
                related=related,
            )
        except GitHubNotConfigured:
            result = {"status": "report_only", "action": "open_issue", "repo": repo,
                      "payload": {"title": title, "labels": labels or [], "dedup_key": dedup_key},
                      "note": "no GitHub credentials — record not filed (report-only)"}
        except GitHubWriteBlocked as exc:
            result = {"status": "blocked", "error": str(exc)[:200]}
        except _BubbleUp:
            # LangGraph control-flow signal (HITL pause / resume). It is an Exception subclass
            # but MUST propagate so the runtime can pause the run — never swallow it as a
            # generic "github error" (that would silently defeat the human-in-the-loop gate
            # AND post to Slack on an unapproved run).
            raise
        except Exception as exc:
            result = {"status": "error", "error": type(exc).__name__}

    # Slack delivery (always mirror — fail-safe)
    try:
        from .slack_tool import post_digest as _slack_post
        slack_res = _slack_post(agent, slack_title or title, body)
        result["slack"] = slack_res.get("status")
    except Exception:
        result["slack"] = "error"

    return result
