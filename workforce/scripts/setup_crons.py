#!/usr/bin/env python3
"""setup_crons — register SERVER-SIDE crons on LangSmith for the SCHEDULED agents.

THE AUDIT FIX (scheduled half): the digest/board/exec agents were driven by a local launchd
cron (``qa-agent-shifts``) that dies on macOS TCC (``./.env: Operation not permitted``, needs
Touch ID). Server-side LangSmith crons need no Mac, no TCC, no Touch ID — the platform fires
them. This script registers them via ``langgraph_sdk`` ``client.crons.create``, idempotently.

SAFETY — creating crons IS the gated activation, so this DEFAULTS TO ``--dry-run``: it lists
what it WOULD create and exits without touching the deployment. ``--apply`` (the deploy-gated
action) actually creates the missing crons. Idempotent either way: it lists existing crons
first (``client.crons.search``) and skips any schedule already registered for an assistant, so
re-running ``--apply`` never duplicates.

Scope: ONLY the genuinely time-scheduled agents (the digest cadence). The QA agents are
EVENT-driven (handled by ``scripts/event_receiver.py``), NOT cron — per the frozen architecture
decision "QA is event-driven, not scheduled". We deliberately do not create QA crons here.

Auth: the SDK client is built with the same ``x-api-key`` + ``X-Tenant-Id`` the fleet uses
(read from env; never logged). ``LANGGRAPH_DEPLOYMENT_URL`` / ``LANGSMITH_API_KEY`` /
``LANGSMITH_TENANT_ID`` must be sourced from the fleet ``.env`` for ``--apply``.

Usage:
    python -m scripts.setup_crons                 # dry-run (default): print the plan, create nothing
    python -m scripts.setup_crons --apply         # create the missing crons (deploy-gated)
    python -m scripts.setup_crons --apply --yes   # skip the interactive confirm (CI)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Any

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


@dataclass(frozen=True)
class CronSpec:
    """One scheduled agent -> one server-side cron. ``schedule`` is a 5-field cron expr (UTC)."""
    assistant: str            # graph id as deployed (langgraph.json key)
    schedule: str             # standard cron, e.g. "0 8 * * *"
    description: str
    input: dict[str, Any] = field(default_factory=dict)


# === DERIVE the cron set from roster.yaml (FINDING 4) =====================================
# Previously DEFAULT_CRONS was a STATIC list of four agents (daily_digest/board_chair/ceo/
# revenue_reporter). A scheduled rostered agent NOT in that list silently NEVER fired. Now the
# set is derived from roster.yaml at runtime: any DEPLOYED rostered agent whose ``schedule:``
# names a "daily" or "weekly" cadence auto-registers — so a new scheduled officer (e.g. a future
# CISO/CLO daily digest) is picked up with no edit here.
#
# EXCLUSIONS (the frozen architecture "QA is event-driven, not scheduled"):
#   * the entire ``org.qa`` group — QA workers fire on GitHub/Sentry events, never on a clock,
#     even if a roster line says "daily" (e.g. web_manual_tester); and
#   * any schedule whose cadence is clearly EVENT-driven ("on every PR", "event-driven", "on
#     deploy", "on demand", "on shift", "webhook") with no standalone daily/weekly token.
# A local-only agent (not a deployed graph) is excluded automatically — it has no assistant to
# target. Report-only inputs throughout. NB: an EVENT-driven cadence ("on every PR", "event-driven",
# "on deploy", "on demand", "on shift", "nightly", …) carries NO standalone 'daily'/'weekly' token,
# so it is excluded by the cadence-token test below — no separate event denylist is needed.

# Canonical UTC times for the agents that historically had explicit/known slots, so re-running
# against an already-configured deployment is idempotent (same schedule string ⇒ no re-create).
# These mirror the roster's explicit times. Any scheduled agent WITHOUT an entry here (or an
# explicit HH:MM in its roster line) gets a deterministic staggered slot via _slot_for so the
# fleet does not thundering-herd at one minute.
_KNOWN_DAILY_UTC: dict[str, str] = {
    "daily_digest": "0 8 * * *",          # roster "daily (08:00)"
    "board_chair": "30 8 * * *",          # board/investor-update lead
    "ceo": "45 8 * * *",                  # exec digest cadence
    "store_health_checker": "30 8 * * *", # roster "daily (08:30)"
}
_KNOWN_WEEKLY_UTC: dict[str, str] = {
    "revenue_reporter": "0 9 * * 1",      # roster "weekly (Mon 09:00)"
}

_HHMM_RE = re.compile(r"\b(\d{1,2}):(\d{2})\b")


def _explicit_hhmm(schedule_text: str) -> tuple[int, int] | None:
    """Parse an explicit HH:MM from a roster schedule line (e.g. 'daily (08:30)'); else None."""
    m = _HHMM_RE.search(schedule_text or "")
    if not m:
        return None
    hh, mm = int(m.group(1)), int(m.group(2))
    if 0 <= hh <= 23 and 0 <= mm <= 59:
        return hh, mm
    return None


def _slot_for(assistant: str) -> tuple[int, int]:
    """Deterministic staggered (hour, minute) in the 08:00–09:55 UTC window for an un-timed daily
    agent — so adding agents spreads them out instead of all firing at one minute.

    Uses a STABLE hash (sha256 of the name), NOT Python's built-in ``hash()`` — the builtin is
    salted by PYTHONHASHSEED and varies per process, which would make the derived schedule
    non-deterministic and BREAK idempotency (a re-run would mint duplicate crons at new times).
    The same name always maps to the same slot, across processes and runs."""
    import hashlib
    h = int(hashlib.sha256(assistant.encode("utf-8")).hexdigest(), 16)
    minute = (h % 12) * 5            # 0,5,...,55
    hour = 8 + ((h // 12) % 2)       # 8 or 9
    return hour, minute


def _daily_cron(assistant: str, schedule_text: str) -> str:
    """5-field daily cron (UTC) for ``assistant``: explicit HH:MM if the roster line has one, else
    a known slot, else a deterministic staggered slot."""
    if assistant in _KNOWN_DAILY_UTC:
        return _KNOWN_DAILY_UTC[assistant]
    hm = _explicit_hhmm(schedule_text)
    if hm:
        return f"{hm[1]} {hm[0]} * * *"
    hour, minute = _slot_for(assistant)
    return f"{minute} {hour} * * *"


def _weekly_cron(assistant: str, schedule_text: str) -> str:
    """5-field weekly cron (UTC, Monday) for ``assistant``. Honors an explicit HH:MM, else a known
    slot, else a deterministic staggered Monday-morning slot."""
    if assistant in _KNOWN_WEEKLY_UTC:
        return _KNOWN_WEEKLY_UTC[assistant]
    hm = _explicit_hhmm(schedule_text)
    if hm:
        return f"{hm[1]} {hm[0]} * * 1"
    hour, minute = _slot_for(assistant)
    return f"{minute} {hour} * * 1"


def derive_crons_from_roster(roster: dict, graphs: set[str]) -> list[CronSpec]:
    """Derive the server-side cron set from roster.yaml — the FINDING-4 runtime derivation.

    Include a rostered agent iff ALL hold:
      * it is a DEPLOYED graph (in ``graphs`` / langgraph.json) — a cron needs an assistant id;
      * it is NOT in the ``org.qa`` group (QA is event-driven, never cron'd);
      * its ``schedule:`` contains a standalone 'daily' or 'weekly' cadence token; and
      * its schedule is not purely EVENT-driven (an event marker with no daily/weekly token).
    A 'daily' wins over 'weekly' if both somehow appear. Deterministic + sorted (stable plan).
    """
    agents = (roster.get("agents") or {})
    qa_group = set((roster.get("org") or {}).get("qa") or [])
    specs: list[CronSpec] = []
    for name in sorted(agents):
        if name not in graphs:
            continue                      # local-only / undeployed → no assistant to cron
        if name in qa_group:
            continue                      # QA is event-driven, not scheduled (frozen architecture)
        sched = str((agents[name] or {}).get("schedule") or "").lower()
        is_daily = bool(re.search(r"\bdaily\b", sched))
        is_weekly = bool(re.search(r"\bweekly\b", sched))
        if not (is_daily or is_weekly):
            continue                      # no clock cadence → not a cron (event/on-demand)
        # A line like "daily + on deploy/webhook event" IS a daily cron (the daily token wins);
        # only exclude when the cadence is purely event-driven with NO daily/weekly token (already
        # filtered above). So no extra event-marker exclusion is needed once a cadence token exists.
        cadence = "daily" if is_daily else "weekly"
        schedule = _daily_cron(name, sched) if is_daily else _weekly_cron(name, sched)
        role = str((agents[name] or {}).get("role") or name)
        specs.append(CronSpec(
            name, schedule,
            f"{cadence.capitalize()} scheduled shift (report-only) — {role[:80]}",
            {"event": "scheduled_shift", "trigger": "cron", "cadence": cadence},
        ))
    return specs


def _load_roster_and_graphs() -> tuple[dict, set[str]]:
    """Read roster.yaml + langgraph.json from the repo root. FAIL-SAFE: missing/corrupt → empty."""
    import yaml
    try:
        roster = yaml.safe_load(open(os.path.join(_REPO_ROOT, "roster.yaml")).read()) or {}
    except Exception:
        roster = {}
    try:
        graphs = set(json.load(open(os.path.join(_REPO_ROOT, "langgraph.json")))["graphs"])
    except Exception:
        graphs = set()
    return roster, graphs


def default_crons() -> list[CronSpec]:
    """The runtime cron set, DERIVED from roster.yaml ∩ langgraph.json (not a static list)."""
    roster, graphs = _load_roster_and_graphs()
    return derive_crons_from_roster(roster, graphs)


# Backwards-compatible module symbol: the DERIVED set (computed at import from the live roster).
# Callers/tests that reference ``DEFAULT_CRONS`` now get the roster-derived crons, so a new
# scheduled agent appears automatically.
DEFAULT_CRONS: list[CronSpec] = default_crons()


def _norm_schedule(s: str) -> str:
    """Normalize a cron expr for comparison (collapse internal whitespace, strip ends)."""
    return " ".join((s or "").split())


def diff_crons(specs: list[CronSpec], existing: list[dict[str, Any]]) -> tuple[list[CronSpec], list[CronSpec]]:
    """Split ``specs`` into (to_create, already_present) given the existing crons on the server.

    A spec is "already present" iff some existing cron targets the same assistant AND has the
    same (normalized) schedule. This is what makes ``--apply`` idempotent: re-running creates
    nothing new. ``existing`` items are the SDK's cron dicts (keys: assistant_id, schedule).
    """
    present_keys = set()
    for c in existing:
        assistant = c.get("assistant_id") or c.get("graph_id") or c.get("assistant")
        schedule = _norm_schedule(c.get("schedule", ""))
        if assistant and schedule:
            present_keys.add((str(assistant), schedule))
    to_create: list[CronSpec] = []
    already: list[CronSpec] = []
    for spec in specs:
        key = (spec.assistant, _norm_schedule(spec.schedule))
        (already if key in present_keys else to_create).append(spec)
    return to_create, already


def _build_client():
    """SDK client with the proven auth headers (x-api-key implied via api_key + X-Tenant-Id)."""
    url = (os.environ.get("LANGGRAPH_DEPLOYMENT_URL") or os.environ.get("LANGSMITH_DEPLOYMENT_URL") or "").rstrip("/")
    key = os.environ.get("LANGSMITH_API_KEY") or os.environ.get("LANGCHAIN_API_KEY") or ""
    tenant = os.environ.get("LANGSMITH_TENANT_ID") or ""
    if not (url and key and tenant):
        raise RuntimeError("cron setup needs LANGGRAPH_DEPLOYMENT_URL, LANGSMITH_API_KEY, LANGSMITH_TENANT_ID in env")
    from langgraph_sdk import get_client

    return get_client(url=url, api_key=key, headers={"X-Tenant-Id": tenant})


async def _list_existing(client) -> list[dict[str, Any]]:
    """List all crons currently registered on the deployment (paged search)."""
    out: list[dict[str, Any]] = []
    offset = 0
    while True:
        batch = await client.crons.search(limit=100, offset=offset)
        if not batch:
            break
        out.extend(dict(c) for c in batch)
        if len(batch) < 100:
            break
        offset += len(batch)
    return out


async def _create(client, spec: CronSpec) -> dict[str, Any]:
    return await client.crons.create(spec.assistant, schedule=spec.schedule, input=spec.input,
                                     metadata={"managed_by": "setup_crons", "cadence_desc": spec.description})


async def run(specs: list[CronSpec], *, apply: bool, client=None) -> dict[str, Any]:
    """Core: list existing, diff, and (only if ``apply``) create the missing crons.

    Returns a plan/result dict (testable). ``client`` is injectable for tests; in production it
    defaults to the env-built SDK client. With ``apply=False`` no client method that mutates is
    ever called — only ``crons.search`` — so dry-run is provably side-effect-free.
    """
    own = client is None
    if own:
        client = _build_client()
    existing = await _list_existing(client)
    to_create, already = diff_crons(specs, existing)
    plan = {
        "apply": apply,
        "existing": len(existing),
        "to_create": [{"assistant": s.assistant, "schedule": s.schedule, "description": s.description} for s in to_create],
        "already_present": [{"assistant": s.assistant, "schedule": s.schedule} for s in already],
        "created": [],
    }
    if apply:
        for spec in to_create:
            res = await _create(client, spec)
            plan["created"].append({"assistant": spec.assistant, "schedule": spec.schedule,
                                    "cron_id": (res or {}).get("cron_id") if isinstance(res, dict) else None})
    return plan


def _print_plan(plan: dict[str, Any]) -> None:
    mode = "APPLY" if plan["apply"] else "DRY-RUN"
    print(f"[setup_crons] mode={mode}  existing={plan['existing']}")
    if plan["already_present"]:
        print(f"  already present ({len(plan['already_present'])}):")
        for c in plan["already_present"]:
            print(f"    - {c['assistant']:<22} {c['schedule']}")
    if plan["to_create"]:
        verb = "WOULD create" if not plan["apply"] else "creating"
        print(f"  {verb} ({len(plan['to_create'])}):")
        for c in plan["to_create"]:
            print(f"    + {c['assistant']:<22} {c['schedule']}  — {c['description']}")
    else:
        print("  nothing to create (all scheduled crons already registered).")
    if plan["apply"] and plan["created"]:
        print(f"  created {len(plan['created'])} cron(s).")
    if not plan["apply"] and plan["to_create"]:
        print("  (dry-run — nothing was created. Re-run with --apply to create them.)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Register server-side LangSmith crons for the scheduled agents.")
    parser.add_argument("--apply", action="store_true",
                        help="actually create the missing crons (deploy-gated). Default: dry-run.")
    parser.add_argument("--yes", action="store_true", help="skip the interactive confirm when applying.")
    parser.add_argument("--json", action="store_true", help="emit the plan as JSON.")
    args = parser.parse_args(argv)

    if args.apply and not args.yes:
        try:
            resp = input("Create the missing server-side crons on the LIVE deployment? [y/N] ").strip().lower()
        except EOFError:
            resp = ""
        if resp not in ("y", "yes"):
            print("[setup_crons] aborted (no --yes / not confirmed). Nothing created.")
            return 1

    try:
        # Derive the cron set FRESH from the live roster at run time (not the import-time snapshot),
        # so a roster edit is picked up without re-import.
        plan = asyncio.run(run(default_crons(), apply=args.apply))
    except RuntimeError as exc:
        # Most commonly: the deployment/auth env isn't sourced. Even a dry-run must list the
        # live crons to compute an accurate diff, so it needs the read credentials. Fail with a
        # clear message and a non-zero exit (never a raw traceback / never log the values).
        print(f"[setup_crons] {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(plan, indent=2))
    else:
        _print_plan(plan)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
