"""Per-agent write-enable gate — graduate the fleet from report-only one agent at a time.

THE PROBLEM THIS SOLVES
-----------------------
Today every mutating/outward action is gated by a SINGLE global flag (``OPS_REPORT_ONLY``,
default report-only) consulted by each graph's local ``_report_only()`` and by the shared
seams (``ops_report.file_digest_*`` → ``github_ops``, ``store_ops``, the email forward). Flip
that one flag and EVERYONE writes at once — Posey forwards email, git_maintainer prunes, the
officers act. That is an unsafe, all-or-nothing graduation.

This module replaces "one global switch" with a PER-AGENT graduation gate so the proven,
low-risk agents are write-enabled first while everyone else stays report-only.

THE GATE  (``write_enabled(agent)``)  — default-DENY, three independent ANDs:
  1. **Allowlist** — the agent is on ``AGENTS_WRITE_ENABLED`` (env, comma-separated). Empty/
     unset ⇒ NOBODY is write-enabled (report-only floor preserved). Unknown agent ⇒ denied.
  2. **Never-list** — the agent is NOT hard-blocked. The never-list is a CODE CONSTANT
     (``HARD_NEVER_LIST``) PLUS every agent whose capability grant in ``capabilities.yaml``
     carries an OUTWARD/IRREVERSIBLE verb (a ``send:`` / ``buy:`` / ``deploy`` / ``merge`` /
     unguarded prune). A never-list agent can NEVER be write-enabled even if added to the
     allowlist — its write is outward/irreversible/propose-only-by-design.
  3. **Kill switch / budget** — ``check_clocked_in(agent)`` is True (fleet not disabled, agent
     not benched, not over budget). The kill switch stays the MASTER stop and COMPOSES here.

GLOBAL SAFETY FLOOR (``OPS_REPORT_ONLY``):
  If ``OPS_REPORT_ONLY`` is set truthy (or unset — the default), ``write_enabled`` returns
  False for EVERYONE regardless of the allowlist. The global flag remains the master
  report-only override / kill-floor. Graduation = (a) set ``OPS_REPORT_ONLY=0`` on the
  deployment AND (b) name the agent in ``AGENTS_WRITE_ENABLED`` — BOTH are Shay-set env on the
  deployment, never code. (An agent on the allowlist with ``OPS_REPORT_ONLY=0`` writes; the
  same agent off the allowlist, or any never-list agent, stays report-only.)

WHERE THIS IS WIRED:
  * ``ops_report.file_digest_issue`` / ``file_digest_record`` — the shared digest seam every
    agent uses — derive their effective ``report_only`` from ``write_enabled(agent)``. The
    underlying guards in ``github_ops`` are UNCHANGED (records stay authorship+dedup-guarded).
  * Per-graph ``_report_only()`` helpers that gate an outward/irreversible action (e.g. the
    email forward, store live-billing) compose with ``report_only_for(agent)``.

This module is FAIL-SAFE and pure-ish: any error reading the manifest/env degrades to the
SAFE answer (report-only / not-write-enabled). It NEVER raises.
"""
from __future__ import annotations

import functools
import os
import pathlib
from typing import Optional

# --- The global master report-only floor ------------------------------------------------
# Unset OR truthy ⇒ report-only for everyone (the safe default). Only an explicit falsey value
# ("0"/"false"/"no"/"off") lifts the floor so the per-agent allowlist can take effect. This is
# the SAME contract the per-graph ``_report_only()`` helpers already use, kept identical so the
# floor cannot drift.
_REPORT_ONLY_FALSEY = ("0", "false", "no", "off")


def global_report_only() -> bool:
    """The master report-only floor: env ``OPS_REPORT_ONLY`` unset/truthy ⇒ True (safe default).

    When True, NO agent is write-enabled regardless of the allowlist — the global flag is the
    always-available master override / safety floor. Only an explicit falsey value opts the
    fleet out of the floor so the per-agent allowlist governs.
    """
    raw = os.environ.get("OPS_REPORT_ONLY")
    if raw is None:
        return True
    return raw.strip().lower() not in _REPORT_ONLY_FALSEY


# --- The per-agent write-enable allowlist (env) -----------------------------------------
# Comma-separated agent slugs that MAY write once the global floor is lifted. DEFAULT EMPTY =
# everyone report-only. Graduating an agent = adding its slug here on the DEPLOYMENT (Shay's
# gate), never in code.
_ALLOWLIST_ENV = "AGENTS_WRITE_ENABLED"


def write_allowlist() -> frozenset[str]:
    """Parse ``AGENTS_WRITE_ENABLED`` into a set of allowlisted agent slugs. Empty when unset."""
    raw = os.environ.get(_ALLOWLIST_ENV, "") or ""
    return frozenset(p.strip() for p in raw.split(",") if p.strip())


# --- TIER 1 graduates (documented default — the FIRST agents safe to write-enable) ------
# Their write is a GUARDED GitHub record (deduped + authorship-guarded, low-risk). This is the
# RECOMMENDED value for ``AGENTS_WRITE_ENABLED`` on the first graduation step. It is NOT applied
# automatically — the env on the deployment is the actual gate — but it is exported so the
# deployment/runbook and tests reference ONE source of truth.
TIER1_WRITE_ENABLED: frozenset[str] = frozenset(
    {
        # C-suite + board — their write is the durable GitHub digest record (guarded)
        "cfo",
        "ceo",
        "cto",
        "coo",
        "board_chair",
        "audit_risk_director",
        "growth_director",
        # Ops reporters — guarded record writes
        "daily_digest",
        "store_health_checker",
        "revenue_reporter",
    }
)

# --- TIER 2 (graduate LATER, after Tier 1 proves out — real guarded ACTIONS) -------------
# These take real actions (prune, file QA bugs, HR proposals) — each guarded — but are NOT in
# the first wave. Documented here so the ladder is explicit; they are write-enabled by ADDING
# them to ``AGENTS_WRITE_ENABLED`` once Tier 1 is proven. NOT auto-applied.
TIER2_WRITE_ENABLED: frozenset[str] = frozenset(
    {
        "git_maintainer",        # prune (has the recency/unpushed guard)
        "web_qa_regression",     # files a bug on real regression (deduped)
        "hr_ops_manager",        # hire/fire PROPOSALS over the job board
    }
)

# --- HARD NEVER-LIST (code constant — can NEVER be write-enabled via the allowlist) ------
# These agents' "write" is outward / irreversible / propose-only-by-design. Even if a slug
# here is added to ``AGENTS_WRITE_ENABLED`` (by mistake or malice) AND ``OPS_REPORT_ONLY=0``,
# ``write_enabled`` returns False — the never-list wins. The list is the named-by-policy set;
# it is UNIONED with the capability-derived set (any agent holding an outward/irreversible
# verb) computed from ``capabilities.yaml`` so a new such agent is auto-blocked too.
HARD_NEVER_LIST: frozenset[str] = frozenset(
    {
        # propose-only officers — their output BINDS/affects the company; never auto-executes
        "security_officer",
        "clo",
        "platform_specialist",
        # Posey — the ONLY agent with a send: capability (forwards/sends email outward)
        "email_triage",
        # broken bake-off twin — must never write
        "cfo_deepagents",
    }
)

# --- Capability verbs / nouns that make a grant outward/irreversible (⇒ never-list) ------
# Computed against ``capabilities.yaml``. An agent holding ANY capability whose VERB or NOUN
# matches is auto-added to the never-list, so the policy ("any agent holding a
# send:/buy:/deploy/merge/unguarded-prune capability") is enforced from the manifest, not a
# hand-maintained list. NB: ``git:prune_merged`` (git_maintainer) is GUARDED (recency/unpushed),
# so a plain ``git:`` prune verb is NOT auto-never-listed here — git_maintainer is Tier 2, gated
# by being absent from the allowlist, not by the hard never-list. Only an UNGUARDED destructive
# git verb (force-push / hard delete of unmerged) would match.
#
# ``forward`` (Posey's literal outward action) is included so a forward-as-verb grant matches.
_NEVER_VERB_PREFIXES: frozenset[str] = frozenset(
    {"send", "forward", "buy", "pay", "transfer", "acquire", "fund", "subscribe", "settle",
     "deploy", "merge", "release", "purchase", "procure"}
)
# Nouns that signal an outward/irreversible action regardless of verb (defensive — catches a
# ``write:deploy`` / ``post:merge_pr`` / ``write:forward_invoice`` style smuggle even if the verb
# prefix is benign). Matched on the noun's underscore/colon/dot-separated WORDS (not a raw
# substring) so a benign noun like ``prune_merged`` does NOT false-positive on the word ``merge`` —
# only a standalone ``merge`` / ``merge_pr`` word matches. The outward family is DERIVED from
# ``_NEVER_VERB_PREFIXES`` (so the verb and noun defenses can never drift): any outward verb token
# appearing as a whole word in the noun (``forward_invoice_external`` → ``forward``,
# ``send_newsletter`` → ``send``, ``release_to_prod`` → ``release``) flags too. ``deploy`` /
# ``billing`` / ``payment`` are also matched as substrings since they have no benign superword.
_NEVER_NOUN_WORDS: frozenset[str] = frozenset(
    _NEVER_VERB_PREFIXES | {"merge", "merge_pr", "force_push", "wire_transfer"}
)
_NEVER_NOUN_SUBSTRINGS: frozenset[str] = frozenset(
    {"deploy", "live_billing", "billing_change", "payment", "purchase"}
)

_MANIFEST_PATH = (
    pathlib.Path(__file__).resolve().parent.parent / "docs" / "governance" / "capabilities.yaml"
)


def _cap_verb_noun(cap: str) -> tuple[str, str]:
    """Split a capability string ``verb:noun`` into (verb, noun), both lowercased. Fail-soft."""
    s = (cap or "").strip().lower()
    if ":" in s:
        verb, noun = s.split(":", 1)
        return verb.strip(), noun.strip()
    return s, ""


def _cap_is_outward_irreversible(cap: str) -> bool:
    """True iff a capability's verb or noun marks it as an outward/irreversible action.

    ``send:invoice_to_morning`` (verb ``send``), ``deploy:web`` (verb ``deploy``),
    ``post:merge_pr`` (noun word ``merge_pr``) all return True. A benign guarded noun like
    ``git:prune_merged`` does NOT match (``merge`` is only a SUBWORD of ``merged`` there — the
    word-set match is on the underscore/colon/dot-split tokens, not a raw substring). Pure; no IO."""
    verb, noun = _cap_verb_noun(cap)
    if verb in _NEVER_VERB_PREFIXES:
        return True
    # Whole-word noun match (split on _ : . -) so ``prune_merged`` ≠ ``merge``.
    words = set()
    cur = noun
    for sep in ("_", ":", ".", "-"):
        cur = cur.replace(sep, " ")
    words.update(cur.split())
    # Also test multi-word tokens (e.g. ``merge_pr`` / ``force_push``) against the original noun.
    if words & {w for w in _NEVER_NOUN_WORDS if "_" not in w}:
        return True
    if any(w in noun for w in _NEVER_NOUN_WORDS if "_" in w):
        return True
    if any(sub in noun for sub in _NEVER_NOUN_SUBSTRINGS):
        return True
    return False


@functools.lru_cache(maxsize=1)
def _capability_never_list() -> frozenset[str]:
    """Agents whose capability grant carries an outward/irreversible verb — derived from the
    manifest. FAIL-SAFE: a missing/unparseable manifest yields an EMPTY set (the code-constant
    ``HARD_NEVER_LIST`` always remains, so a manifest read failure can never UN-block a named
    never-list agent). Cached — the manifest is static at runtime."""
    try:
        import yaml  # lazy: importing this module must not hard-require PyYAML
        with open(_MANIFEST_PATH, "r", encoding="utf-8") as fh:
            manifest = yaml.safe_load(fh) or {}
        grants = manifest.get("grants") or {}
    except Exception:
        return frozenset()

    flagged: set[str] = set()
    for agent, grant in grants.items():
        if not isinstance(grant, dict):
            continue
        for cap_entry in grant.get("capabilities") or []:
            cap = cap_entry.get("capability") if isinstance(cap_entry, dict) else None
            if cap and _cap_is_outward_irreversible(cap):
                flagged.add(agent)
                break
    return frozenset(flagged)


def never_listed(agent: str) -> bool:
    """True iff ``agent`` is HARD-BLOCKED from being write-enabled (can never write via the gate).

    Union of the code constant ``HARD_NEVER_LIST`` and the capability-derived set (agents whose
    grant carries a ``send:``/``buy:``/``deploy``/``merge``/outward verb). FAIL-SAFE: any error
    degrades to the code constant only (never UN-blocks a named agent on a manifest read error)."""
    if not agent:
        return True  # an unknown/empty agent is never write-enabled (default-deny)
    if agent in HARD_NEVER_LIST:
        return True
    try:
        return agent in _capability_never_list()
    except Exception:
        return False  # capability set unavailable ⇒ fall back to the code constant (already checked)


def write_enabled(agent: str) -> bool:
    """Return True ONLY IF ``agent`` may perform a real (guarded) write right now. Default-DENY.

    All FOUR must hold (any failure ⇒ report-only):
      1. the global report-only floor is LIFTED (``OPS_REPORT_ONLY`` explicitly falsey), AND
      2. ``agent`` is on the ``AGENTS_WRITE_ENABLED`` allowlist (empty/unset ⇒ nobody), AND
      3. ``agent`` is NOT on the never-list (code constant ∪ capability-derived outward verbs), AND
      4. ``check_clocked_in(agent)`` is True (kill switch / bench / budget — the MASTER stop).

    FAIL-SAFE: any error degrades to False (report-only). NEVER raises.
    """
    try:
        if not agent:
            return False
        # (1) master floor: unset/truthy OPS_REPORT_ONLY ⇒ nobody writes.
        if global_report_only():
            return False
        # (3) never-list wins over the allowlist — a hard-blocked agent can never write.
        if never_listed(agent):
            return False
        # (2) allowlist (default-deny): must be explicitly named.
        if agent not in write_allowlist():
            return False
        # (4) kill switch / budget — the master stop, composed last.
        from .budget import check_clocked_in
        if not check_clocked_in(agent):
            return False
        return True
    except Exception:
        return False  # any unexpected failure ⇒ the SAFE answer is report-only


def report_only_for(agent: str) -> bool:
    """The report-only flag for ``agent`` derived from the gate: ``not write_enabled(agent)``.

    This is the seam the shared digest path and per-graph ``_report_only()`` helpers consult so
    a single agent's posture follows the per-agent allowlist instead of one global flag. An
    agent that is NOT write-enabled (off the allowlist, never-listed, kill-switched, or under
    the global floor) is report-only. FAIL-SAFE (errors ⇒ report-only)."""
    return not write_enabled(agent)
