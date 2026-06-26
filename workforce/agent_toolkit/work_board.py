"""Work board — turn open GitHub issues into the fleet's pull-queue (issues #1, #2).

The dispatcher today is a blind round-robin with NO work-selection. This module is
the "board" the workforce pulls from: it fetches open org issues, drops STALE ones,
keeps only ALLOW-LISTED repos (default-deny, shared with github_ops), and assigns each
remaining item to a role. An agent on shift pulls the next item for its role and works
it through github_ops.

Design choices that keep "agents pick up the work they need" SAFE while unattended:
- **Allow-list, not deny-list.** Only issues in `github_ops.ALLOWED_REPOS` are visible;
  a new/unlabelled financial/legal issue is invisible by construction.
- **Staleness is first-class** (issue #2): an item is stale if it's been idle too long,
  is explicitly labelled stale/blocked/wontfix, or is a draft/needs-info. Stale items
  are never assigned — and the same check is reusable as a standalone sweep.
- **Pure/ testable core.** Classification + assignment + selection take injected data and
  a `now`, so they unit-test without network. Live fetch is a thin, separate helper.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from .github_ops import ALLOWED_REPOS

# Repo -> the role that owns its issues (v1 mapping; roster.yaml roles).
REPO_ROLE = {
    "Scheduler-Systems/scheduler-web": "web_automation_engineer",
    "Scheduler-Systems/scheduler-android": "android_automation_engineer",
    "Scheduler-Systems/scheduler-ios": "ios_automation_engineer",
    "Scheduler-Systems/qa-agent-platform": "qa_lead_aggregator",
    "Scheduler-Systems/workspace-governance": "qa_lead_aggregator",
}

# Labels that mark an item stale/not-actionable regardless of age.
STALE_LABELS = frozenset(
    {"stale", "wontfix", "won't fix", "blocked", "on-hold", "needs-info", "duplicate", "invalid"}
)
DEFAULT_MAX_IDLE_DAYS = 30


@dataclass(frozen=True)
class WorkItem:
    repo: str
    number: int
    title: str
    updated_at: str  # ISO-8601, e.g. "2026-05-01T12:00:00Z"
    labels: tuple[str, ...] = ()
    html_url: str = ""


@dataclass(frozen=True)
class StalenessVerdict:
    stale: bool
    reason: str


def _parse_iso(ts: str) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def classify_staleness(
    item: WorkItem, now: datetime, *, max_idle_days: int = DEFAULT_MAX_IDLE_DAYS
) -> StalenessVerdict:
    """Issue #2: decide if a work item is stale. Reusable as a standalone sweep."""
    lowered = {l.lower() for l in item.labels}
    hit = lowered & STALE_LABELS
    if hit:
        return StalenessVerdict(True, f"labelled {sorted(hit)[0]!r}")
    updated = _parse_iso(item.updated_at)
    if updated is None:
        return StalenessVerdict(True, "no/invalid updated_at")
    if now - updated > timedelta(days=max_idle_days):
        idle = (now - updated).days
        return StalenessVerdict(True, f"idle {idle}d (> {max_idle_days}d)")
    return StalenessVerdict(False, "fresh")


def assign_role(item: WorkItem) -> Optional[str]:
    """Map an item to the role that should pull it. None = not agent-shaped."""
    return REPO_ROLE.get(item.repo)


@dataclass
class BoardSelection:
    by_role: dict[str, list[WorkItem]] = field(default_factory=dict)
    stale: list[tuple[WorkItem, str]] = field(default_factory=list)
    skipped_not_allowed: list[WorkItem] = field(default_factory=list)
    unassigned: list[WorkItem] = field(default_factory=list)


def select_work(
    items: list[WorkItem], now: datetime, *, max_idle_days: int = DEFAULT_MAX_IDLE_DAYS
) -> BoardSelection:
    """Issue #1: schedule non-stale, allow-listed issues to roles. Pure + testable."""
    sel = BoardSelection()
    for item in items:
        if item.repo not in ALLOWED_REPOS:
            sel.skipped_not_allowed.append(item)
            continue
        verdict = classify_staleness(item, now, max_idle_days=max_idle_days)
        if verdict.stale:
            sel.stale.append((item, verdict.reason))
            continue
        role = assign_role(item)
        if role is None:
            sel.unassigned.append(item)
            continue
        sel.by_role.setdefault(role, []).append(item)
    return sel


# --- Live fetch (thin, not unit-tested against network) ------------------------------

def fetch_open_issues(org: str = "Scheduler-Systems", *, limit: int = 200) -> list[WorkItem]:
    """Fetch open issues across an org via the `gh` CLI (uses existing gh auth)."""
    out = subprocess.run(
        [
            "gh", "search", "issues", "--owner", org, "--state", "open",
            "--limit", str(limit),
            "--json", "repository,number,title,labels,updatedAt,url",
        ],
        capture_output=True, text=True, check=True,
    ).stdout
    items: list[WorkItem] = []
    for r in json.loads(out or "[]"):
        items.append(
            WorkItem(
                repo=r["repository"]["nameWithOwner"] if "nameWithOwner" in r.get("repository", {})
                else f"{org}/{r['repository']['name']}",
                number=r["number"],
                title=r.get("title", ""),
                updated_at=r.get("updatedAt", ""),
                labels=tuple(l.get("name", "") for l in r.get("labels", [])),
                html_url=r.get("url", ""),
            )
        )
    return items
