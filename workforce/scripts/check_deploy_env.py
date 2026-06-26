#!/usr/bin/env python3
"""check_deploy_env — the LOUD deploy preflight for the fleet's deployment secrets.

WHY (FINDING 2 + 3, prod-harden 2026-06-07): several deployment secrets fail SILENTLY when unset,
so a half-configured activation looks healthy but does nothing:
  * ``scripts/event_receiver.py`` 401s EVERY webhook when ``GITHUB_WEBHOOK_SECRET`` /
    ``SENTRY_CLIENT_SECRET`` are unset — but only logs a coarse "rejected" line, so "nothing fires"
    looks like "no traffic".
  * ``agent_toolkit/gmail_client.py`` (Posey) degrades to "could not check inbox" with no creds —
    an honest report, but easy to miss as a config gap rather than an empty inbox.
  * the per-agent WRITE GATE needs THREE coordinated env vars to graduate an agent; a HALF config
    (allowlist set but ``OPS_REPORT_ONLY`` still report-only, or the floor lifted but the allowlist
    empty) silently keeps everyone report-only — the activation "did nothing" with no error.

This script is the OPERATOR-RUN preflight: it reports, BY NAME, which required deployment secrets
are SET vs MISSING (grouped: LangSmith, GitHub-webhook, Gmail/Morning, Slack), and it flags the
write-gate misconfig. It is READ-ONLY and prints **names + set/unset ONLY** — it NEVER prints a
secret VALUE. Run it before flipping activation / write-enable.

Exit codes:
  0  — all REQUIRED groups configured AND no write-gate misconfig (safe to activate).
  1  — a required group is incomplete OR a write-gate misconfig is detected (do NOT activate yet).
Use ``--strict`` to also fail when an OPTIONAL group (Gmail/Morning, Slack) is incomplete.
``--json`` emits the structured report (names only).

Usage:
    python -m scripts.check_deploy_env            # human-readable preflight (names only)
    python -m scripts.check_deploy_env --json     # machine-readable (names + bool set/unset)
    python -m scripts.check_deploy_env --strict    # also require the optional groups
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


# --- secret groups (NAMES only — values are never read into the report) -----------------
@dataclass(frozen=True)
class EnvGroup:
    name: str
    required: bool
    # Each entry is (canonical_name, [acceptable_alias_names...]). A var is SET if the canonical
    # name OR any alias is non-empty. ``any_of`` groups (Gmail send vs Slack token vs webhook) note
    # which subset is sufficient.
    vars: tuple[tuple[str, tuple[str, ...]], ...]
    note: str = ""
    # When True, the group is satisfied if ANY of its vars is set (e.g. a webhook secret for EITHER
    # GitHub or Sentry is enough to receive that source). When False, ALL vars must be set.
    any_of: bool = False


# The deployment-secret contract, grouped. Names are derived from the code that reads them:
#   LangSmith    : agent_toolkit/a2a_client.py + scripts/setup_crons.py (the fire/cron path)
#   GitHub-webhook: scripts/event_receiver.py (verify_github_signature / verify_sentry_signature)
#   Gmail/Morning : agent_toolkit/gmail_client.py (Posey read/draft/forward)
#   Slack         : agent_toolkit/slack_tool.py (digest posting)
GROUPS: tuple[EnvGroup, ...] = (
    EnvGroup(
        "LangSmith",
        required=True,
        vars=(
            ("LANGGRAPH_DEPLOYMENT_URL", ("LANGSMITH_DEPLOYMENT_URL",)),
            ("LANGSMITH_API_KEY", ("LANGCHAIN_API_KEY",)),
            ("LANGSMITH_TENANT_ID", ()),
        ),
        note="the fire path (runs.create) + server-side crons need URL + api-key + tenant.",
    ),
    EnvGroup(
        "GitHub-webhook",
        required=True,
        any_of=True,
        vars=(
            ("GITHUB_WEBHOOK_SECRET", ()),
            ("SENTRY_CLIENT_SECRET", ()),
        ),
        note="event_receiver REJECTS (401) every webhook for a source whose secret is unset — at "
             "least one is required to receive ANY event. Set BOTH to receive GitHub AND Sentry.",
    ),
    EnvGroup(
        "Gmail/Morning",
        required=False,
        vars=(
            ("GMAIL_OAUTH_TOKEN", ()),
            ("MORNING_PERSONAL_EMAIL", ()),
            ("MORNING_COMPANY_EMAIL", ()),
        ),
        note="Posey (email_triage) runs report-only ('could not check inbox') without GMAIL_OAUTH_"
             "TOKEN; the two Morning addresses are the HARD allowlist for the invoice forward.",
    ),
    EnvGroup(
        "Slack",
        required=False,
        any_of=True,
        vars=(
            ("SLACK_BOT_TOKEN", ()),
            ("SLACK_WEBHOOK_URL", ()),
        ),
        note="agents post digests to Slack via a bot token (full API) OR an incoming webhook URL; "
             "without either, digests are computed but not posted.",
    ),
)


def _is_set(name: str) -> bool:
    """True iff env var ``name`` is present and non-empty (after strip). NEVER returns the value."""
    return bool((os.environ.get(name) or "").strip())


def _var_set(canonical: str, aliases: tuple[str, ...]) -> bool:
    """A var is 'set' if its canonical name OR any acceptable alias is non-empty."""
    return _is_set(canonical) or any(_is_set(a) for a in aliases)


# --- write-gate coordination check (FINDING 3) ------------------------------------------
def write_gate_status() -> dict:
    """Diagnose the 3-var write-gate coordination WITHOUT importing live gate side-effects.

    The per-agent write gate (agent_toolkit/write_gate.py) graduates an agent ONLY when BOTH:
      * the master floor is LIFTED — ``OPS_REPORT_ONLY`` explicitly falsey ('0'/'false'/'no'/'off'),
        AND
      * the agent is named on ``AGENTS_WRITE_ENABLED`` (comma-separated), AND it is not never-listed
        and is clocked-in.
    A HALF config is the silent-fail this flags:
      * allowlist NON-EMPTY but floor STILL ON      ⇒ those agents STAY report-only (no error);
      * floor LIFTED but NO EFFECTIVE writer         ⇒ NOBODY writes (the lift did nothing). This
        covers allowlist EMPTY *and* allowlist names ONLY hard-never-listed agents — keyed on the
        EFFECTIVE set, not raw allowlist emptiness, so a non-empty all-never-listed allowlist is
        still caught.
    Returns a names-only diagnostic dict (the allowlisted agent NAMES are config, not secrets).
    """
    from agent_toolkit import write_gate as wg

    floor_on = wg.global_report_only()           # True ⇒ report-only floor engaged
    allow = sorted(wg.write_allowlist())         # the named agents (config, safe to show)
    never_listed = sorted(a for a in allow if wg.never_listed(a))
    effective = sorted(a for a in allow if not floor_on and not wg.never_listed(a))

    misconfig = None
    if allow and floor_on:
        misconfig = (
            f"AGENTS_WRITE_ENABLED names {len(allow)} agent(s) {allow} but OPS_REPORT_ONLY is still "
            f"ON (report-only floor engaged) → those agents STAY report-only. To graduate them set "
            f"OPS_REPORT_ONLY=0 on the deployment."
        )
    elif (not floor_on) and (not effective):
        # The floor is LIFTED but NO agent is EFFECTIVELY write-enabled — "the lift did nothing".
        # This catches BOTH the allowlist-EMPTY case AND the case where the allowlist names ONLY
        # hard-never-listed agents (e.g. email_triage): the allowlist is syntactically non-empty,
        # so keying on ``not allow`` would MISS it and the gate would be reported as coordinated
        # while no agent actually graduates. Key on the EFFECTIVE set so the silent no-op is caught.
        if not allow:
            misconfig = (
                "OPS_REPORT_ONLY is OFF (floor lifted) but AGENTS_WRITE_ENABLED is EMPTY → NOBODY "
                "is write-enabled (the lift did nothing). Name the first-wave agents in "
                "AGENTS_WRITE_ENABLED (see TIER1 below)."
            )
        else:
            misconfig = (
                f"OPS_REPORT_ONLY is OFF (floor lifted) but AGENTS_WRITE_ENABLED names ONLY "
                f"hard-never-listed agent(s) {never_listed} → NOBODY effectively graduates (the "
                f"lift did nothing). Never-listed agents can NEVER be write-enabled; name a "
                f"write-eligible agent in AGENTS_WRITE_ENABLED (see TIER1 below)."
            )

    return {
        "ops_report_only_floor_engaged": floor_on,
        "allowlisted_agents": allow,
        "never_listed_in_allowlist": never_listed,   # named but hard-blocked (will not write)
        "effective_write_enabled_pre_killswitch": effective,
        "recommended_first_wave_TIER1": sorted(wg.TIER1_WRITE_ENABLED),
        "misconfig": misconfig,
    }


def collect() -> dict:
    """Build the names-only preflight report. Pure-ish (reads env + the write_gate manifest)."""
    groups = []
    for g in GROUPS:
        members = []
        for canonical, aliases in g.vars:
            members.append({"name": canonical, "aliases": list(aliases),
                            "set": _var_set(canonical, aliases)})
        set_names = [m["name"] for m in members if m["set"]]
        missing_names = [m["name"] for m in members if not m["set"]]
        complete = (len(set_names) >= 1) if g.any_of else (len(missing_names) == 0)
        groups.append({
            "group": g.name, "required": g.required, "any_of": g.any_of, "complete": complete,
            "set": set_names, "missing": missing_names, "note": g.note,
        })
    wg = write_gate_status()
    required_incomplete = [grp["group"] for grp in groups if grp["required"] and not grp["complete"]]
    optional_incomplete = [grp["group"] for grp in groups if not grp["required"] and not grp["complete"]]
    return {
        "groups": groups,
        "write_gate": wg,
        "required_incomplete": required_incomplete,
        "optional_incomplete": optional_incomplete,
    }


def _print_report(report: dict) -> None:
    print("=== deploy-env preflight (names only — NO secret values printed) ===")
    for grp in report["groups"]:
        req = "REQUIRED" if grp["required"] else "optional"
        kind = "any-of" if grp["any_of"] else "all"
        flag = "✅" if grp["complete"] else ("❌" if grp["required"] else "⚠️ ")
        print(f"{flag} {grp['group']} [{req}, {kind}] — {'complete' if grp['complete'] else 'INCOMPLETE'}")
        if grp["set"]:
            print(f"     set:     {', '.join(grp['set'])}")
        if grp["missing"]:
            print(f"     missing: {', '.join(grp['missing'])}")
        if grp["note"]:
            print(f"     ↳ {grp['note']}")
    wg = report["write_gate"]
    print("\n--- write gate (per-agent graduation) ---")
    print(f"  OPS_REPORT_ONLY floor engaged: {wg['ops_report_only_floor_engaged']}")
    print(f"  AGENTS_WRITE_ENABLED names:    {wg['allowlisted_agents'] or '(empty)'}")
    if wg["never_listed_in_allowlist"]:
        print(f"  ⚠️  named but HARD never-listed (will NOT write): {wg['never_listed_in_allowlist']}")
    print(f"  effective write-enabled (pre kill-switch): {wg['effective_write_enabled_pre_killswitch'] or '(none)'}")
    print(f"  recommended FIRST WAVE (TIER1): {wg['recommended_first_wave_TIER1']}")
    if wg["misconfig"]:
        print(f"  ❌ WRITE-GATE MISCONFIG: {wg['misconfig']}")
    else:
        print("  ✅ write-gate env is coordinated (no half-config).")
    print()


def evaluate(report: dict, *, strict: bool) -> int:
    """Exit-code policy: 1 if any REQUIRED group incomplete OR write-gate misconfig; with --strict
    also 1 if an OPTIONAL group is incomplete. Else 0."""
    bad = bool(report["required_incomplete"]) or bool(report["write_gate"]["misconfig"])
    if strict and report["optional_incomplete"]:
        bad = True
    return 1 if bad else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Deploy-env preflight (names only, never values).")
    parser.add_argument("--json", action="store_true", help="emit the report as JSON (names only).")
    parser.add_argument("--strict", action="store_true",
                        help="also fail when an OPTIONAL group (Gmail/Morning, Slack) is incomplete.")
    args = parser.parse_args(argv)

    report = collect()
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_report(report)
        if report["required_incomplete"]:
            print(f"❌ required group(s) INCOMPLETE: {', '.join(report['required_incomplete'])} — "
                  f"do NOT activate until set.")
        if report["write_gate"]["misconfig"]:
            print("❌ write-gate is half-configured — fix before write-enable.")
        if not report["required_incomplete"] and not report["write_gate"]["misconfig"]:
            print("✅ all required groups configured + write-gate coordinated.")
    return evaluate(report, strict=args.strict)


if __name__ == "__main__":
    raise SystemExit(main())
