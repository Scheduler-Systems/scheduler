#!/usr/bin/env python3
"""Capability-grant gate — machine-enforces the GAL-run Governance Charter.

Turns the charter's cardinal rules from prose into a CI gate over
``docs/governance/capabilities.yaml``:

  * Rule #1 (never mix identities) — no agent grant may reference a HUMAN-tier identity;
    no human owner may double as an agent identity; the human-owner set can never be
    empty; every agent identity must be ``issued_by`` a real human owner (the only legal
    cross-tier link is issuance); every capability's ``granted_by`` must be a human owner
    (no self-grant, no forged grantor).
  * Spend-only, never procure     — capability verbs are an ALLOW-LIST (default-deny:
    only read/post/propose/write/git — never buy/pay/transfer/execute/deploy/…); ``can_buy``
    must be a real boolean ``false`` on every grant AND identity (a quoted/cased truthy
    string is rejected, not silently treated as false).
  * Coverage (default-deny)        — every graph in ``langgraph.json`` MUST have a grant;
    every grant declares posture + can_buy + identities + capabilities, each capability a
    {capability, scope, why, granted_by, revocable}.
  * Funding                        — ``auto_recharge`` must be a real boolean and may not be
    ``true`` unless the pool is ``ring_fenced: true`` (bounds the real-money blast radius).
  * Probation guard                — every grant's ``posture`` must be ``report_only`` while
    the fleet is on probation; no identity may be smuggled via ``acts_as``/``run_as``/…
  * Email draft-only bright line    — email is OUTWARD to real people ("never send without
    approval"). An email-channel capability may ONLY ``read:``/``propose:`` (draft); a DELIVER
    verb (``post:``/``write:``) or a *send* token (``post:email``/``write:email_send``/
    ``propose:send_email``) FAILS — the no-send rule is enforced at the GRANT, not just by
    gmail_client lacking a send method.

The hardening above closes four author-side bypasses found by adversarial review
(2026-06-06): procurement-verb synonym evasion, quoted-truthy ``can_buy``/``auto_recharge``,
empty-owners collapse, and unvalidated ``granted_by``. Default-deny throughout: an
undeclared graph, a missing field, a human-identity reference, a non-bool flag, or a
non-allow-listed verb all FAIL the build. ``validate()`` is pure (no IO), unit-tested directly.

See docs/governance/gal-run-governance-charter.md + identity-mixing-audit-2026-06-06.md.
"""
from __future__ import annotations

import json
import pathlib
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "docs" / "governance" / "capabilities.yaml"
LANGGRAPH = ROOT / "langgraph.json"

REQUIRED_CAP_FIELDS = ("capability", "scope", "why", "granted_by")
# ALLOW-LIST (default-deny): the only capability verb-prefixes an agent may hold. Anything
# else — buy/pay/transfer/acquire/fund/subscribe/settle/execute/deploy/… — FAILS. Inverting
# to an allow-list is what makes "no procurement" un-bypassable by synonym (vs a blocklist).
#
# ``send`` is allow-listed ONLY for a single, narrowly-justified outward action, and ONLY behind
# the ALLOWLIST-SCOPING guard below: a ``send:`` grant must name a recipient ALLOWLIST in its
# capability noun + scope (the destination comes from server config, never from message content).
# A GENERAL email-send (``send:email`` / ``send:gmail`` / any send to an unbounded recipient) is
# FORBIDDEN — it is caught by the email draft-only bright line (``_is_email_channel``) and/or the
# allowlist-scoping guard, neither of which it can satisfy. See ``_send_allowlist_violation``.
ALLOWED_VERB_PREFIXES = ("read", "post", "propose", "write", "git", "message", "send")
# Grant keys an author may use; anything else is rejected (closes identity-smuggling keys).
ALLOWED_GRANT_KEYS = {"posture", "can_buy", "funding", "runtime", "identities", "capabilities"}
FORBIDDEN_GRANT_KEYS = ("acts_as", "run_as", "run_as_user", "impersonate", "login_as", "sudo")
ALLOWED_POSTURES = ("report_only",)  # probation: agents propose, never execute
WILDCARD_SCOPES = ("", "*", "all", "any", "everything", "everywhere", "global")

# EMAIL = OUTWARD-to-real-people: the draft-only bright line (Shay's firm "never send a message
# without approval"). On an email-channel capability the agent may only READ the inbox or PROPOSE
# (draft) a reply/unsubscribe — it may NEVER hold a DELIVER verb (post:/write:) and never a *send*
# token. This makes the bright line machine-enforced at the grant level, not merely structural
# (gmail_client having no send method). A future edit that grants e.g. post:email / write:email_send
# / propose:send_email FAILS the build instead of silently slipping a send path past CI.
EMAIL_DRAFT_VERB_PREFIXES = ("read", "propose")  # the only verbs an email-channel cap may use
EMAIL_SEND_TOKENS = ("send", "deliver", "dispatch", "transmit", "submit", "sendmail", "smtp")


# --- SEND verb (one narrow, allowlist-scoped outward action) ----------------------------
# The ``send`` verb is allow-listed (above) ONLY for an action whose recipient is pinned to a
# server-side ALLOWLIST — never to a recipient taken from message content or a free-form argument.
# A general email-send is FORBIDDEN. Concretely, the ONLY ``send:`` capability noun permitted is
# the invoice→Morning auto-forward, whose two destinations are the ``MORNING_PERSONAL_EMAIL`` /
# ``MORNING_COMPANY_EMAIL`` config addresses (HARD ALLOWLIST). The guard below requires BOTH:
#   (1) the noun is on this allow-list of allowlist-scoped send actions, AND
#   (2) the scope text names the allowlist (mentions "morning" + "allowlist", proving it is pinned
#       to the config addresses), AND it is NOT an email-channel *send* token (caught separately).
# Anything else with a ``send`` verb FAILS — a general ``send:email`` cannot satisfy (1) or (2).
ALLOWLISTED_SEND_NOUNS = ("invoice_to_morning",)
# A send scope must prove it is pinned to a named allowlist (not an open recipient).
SEND_SCOPE_REQUIRED_TOKENS = ("morning", "allowlist")


def _send_allowlist_violation(cap: str, scope: str) -> str:
    """Return an error string if a ``send:`` capability is NOT a narrow allowlist-scoped action, else "".

    Enforces that the ONLY ``send`` an agent may hold is a recipient-allowlist-pinned action:
      * the capability NOUN must be on ``ALLOWLISTED_SEND_NOUNS`` (today: only ``invoice_to_morning``);
      * the scope must name the allowlist (mention 'morning' AND 'allowlist'), proving the recipient
        is the server-config Morning address set — never taken from the message or a free argument.
    A general ``send:email`` / ``send:gmail`` / ``send:reply`` / unbounded send fails both. Pure; no IO.
    """
    noun = cap.split(":", 1)[1].strip().lower() if ":" in cap else cap.strip().lower()
    s = (scope or "").strip().lower()
    if noun not in ALLOWLISTED_SEND_NOUNS:
        return (
            f"capability '{cap}' uses the 'send' verb but its action '{noun}' is not an "
            f"allowlist-scoped send (allowed: {'/'.join(ALLOWLISTED_SEND_NOUNS)}). A GENERAL "
            f"email-send is forbidden — 'send' is permitted only for a recipient-allowlist-pinned "
            f"action whose destination comes from server config, never the message."
        )
    if not all(tok in s for tok in SEND_SCOPE_REQUIRED_TOKENS):
        return (
            f"capability '{cap}' send-scope must name the recipient ALLOWLIST "
            f"(mention {'/'.join(SEND_SCOPE_REQUIRED_TOKENS)}) so the destination is provably "
            f"pinned to the config addresses, not the message. Got scope: {scope!r}"
        )
    return ""


# Email-channel nouns (matched on the capability NOUN only — the word AFTER the verb prefix).
# Scope text is deliberately NOT scanned: an A2A ``message:email_triage`` peer-route or a
# ``message:coo`` whose scope mentions "inbox" is NOT an email-delivery capability, and the
# message-target check already governs those. The bright line is about a verb acting ON the email
# channel, which is expressed in the noun (``post:email`` / ``write:email_send`` / ``read:gmail``).
EMAIL_CHANNEL_TOKENS = ("email", "gmail", "inbox", "mailbox", "smtp")


def _is_email_channel(cap: str) -> bool:
    """True iff a capability's NOUN names the EMAIL channel (the draft-only bright line applies).

    Matches the capability NOUN (after the verb prefix) — ``post:email``, ``write:email_send``,
    ``propose:send_email``, ``read:gmail``, ``read:inbox``, ``propose:email_reply``. The A2A
    ``message:`` verb is exempt (peer routing, governed by the message-target check), so a peer
    literally named ``email_triage`` is not mistaken for an email-delivery capability. Pure; no IO.
    """
    verb = cap.split(":", 1)[0].strip().lower()
    if verb == "message":
        return False
    noun = cap.split(":", 1)[1].strip().lower() if ":" in cap else cap.strip().lower()
    return any(tok in noun for tok in EMAIL_CHANNEL_TOKENS)


def _is_false_bool(v):
    """True iff v is the real boolean False (rejects 'false'/'no'/0/None and any truthy)."""
    return isinstance(v, bool) and v is False


def validate(graphs, manifest):
    """Pure validation. Returns (errors, warnings) — each a list of strings.

    ``graphs`` = set of deployed graph names (langgraph.json keys).
    ``manifest`` = parsed capabilities.yaml dict.
    """
    errors: list[str] = []
    warnings: list[str] = []

    owners = manifest.get("owners") or []
    identities = manifest.get("identities") or {}
    funding = manifest.get("funding") or {}
    grants = manifest.get("grants") or {}

    # --- humans (owners): set must never be empty; each has id+tier; ≥1 is human ---------
    human_ids = set()
    if not owners:
        errors.append("owners is missing/empty — the human set may never be empty (Rule #1)")
    for o in owners:
        oid = o.get("id")
        if not oid or not o.get("tier"):
            errors.append(f"owner {o!r} must declare both id and tier")
        if oid and o.get("tier") == "human":
            human_ids.add(oid)
        elif o.get("tier") != "human":
            errors.append(f"owner '{oid}' must be tier: human (humans own/grant/approve)")
    if owners and not human_ids:
        errors.append("no tier: human owner declared — the founder must anchor the human set")

    # --- agent identities (NHI): tier:agent, spend-only, issued by a human --------------
    for name, ident in identities.items():
        if not isinstance(ident, dict):
            errors.append(f"identity '{name}' must be a mapping")
            continue
        if ident.get("tier") != "agent":
            errors.append(f"identity '{name}' must be tier: agent (humans belong under owners:)")
        if name in human_ids:
            errors.append(f"identity '{name}' collides with a human owner id — never mix tiers (Rule #1)")
        if "can_buy" not in ident:
            errors.append(f"identity '{name}' must declare can_buy: false")
        elif not _is_false_bool(ident.get("can_buy")):
            errors.append(f"identity '{name}' can_buy must be the boolean false (got {ident.get('can_buy')!r})")
        issued_by = ident.get("issued_by")
        if not issued_by:
            errors.append(f"identity '{name}' must declare issued_by (the human who issued it)")
        elif issued_by not in human_ids:
            errors.append(f"identity '{name}' issued_by '{issued_by}' is not a human owner — issuance chain broken")
        if ident.get("shared") is True:
            warnings.append(f"identity '{name}' is shared across agents (not isolated) — see audit item 3")
        secret_ref = str(ident.get("secret_ref", "")).lower()
        if "plaintext" in secret_ref or "pending" in secret_ref:
            warnings.append(f"identity '{name}' secret storage unresolved — {ident.get('secret_ref')}")

    # --- coverage: every deployed graph must have a grant (default-deny) -----------------
    for m in sorted(graphs - set(grants)):
        errors.append(f"deployed graph '{m}' has NO capability grant (default-deny)")

    # --- per-grant: keys + posture + spend-only + Rule #1 + capability schema ------------
    for agent, g in grants.items():
        if not isinstance(g, dict):
            errors.append(f"grant '{agent}' must be a mapping")
            continue
        if agent not in graphs:
            warnings.append(f"grant '{agent}' is not a deployed graph (stale grant?)")

        for k in g:
            if k in FORBIDDEN_GRANT_KEYS:
                errors.append(f"grant '{agent}' uses forbidden key '{k}' — identity-smuggling channel")
            elif k not in ALLOWED_GRANT_KEYS:
                errors.append(f"grant '{agent}' has unknown key '{k}' (allow-list only)")

        if g.get("posture") not in ALLOWED_POSTURES:
            errors.append(f"grant '{agent}' posture must be report_only on probation (got {g.get('posture')!r})")

        if "can_buy" not in g:
            errors.append(f"grant '{agent}' must declare can_buy: false explicitly")
        elif not _is_false_bool(g.get("can_buy")):
            errors.append(f"grant '{agent}' can_buy must be the boolean false (got {g.get('can_buy')!r}) — agents never procure")

        ids = g.get("identities") or []
        if not ids:
            errors.append(f"grant '{agent}' declares no identities")
        for ref in ids:
            if ref in human_ids:
                errors.append(f"grant '{agent}' references HUMAN identity '{ref}' — Rule #1 violation")
            elif ref not in identities:
                errors.append(f"grant '{agent}' references undeclared identity '{ref}'")

        caps = g.get("capabilities") or []
        if not caps:
            errors.append(f"grant '{agent}' declares no capabilities (default-deny)")
        for c in caps:
            if not isinstance(c, dict):
                errors.append(f"grant '{agent}' has a non-mapping capability entry")
                continue
            for f in REQUIRED_CAP_FIELDS:
                if not c.get(f):
                    errors.append(f"grant '{agent}' capability '{c.get('capability', '?')}' missing '{f}'")
            cap = str(c.get("capability", ""))
            verb = cap.split(":", 1)[0].strip().lower()
            if verb not in ALLOWED_VERB_PREFIXES:
                errors.append(
                    f"grant '{agent}' capability '{cap}' verb '{verb}' is not allow-listed "
                    f"(default-deny: only {'/'.join(ALLOWED_VERB_PREFIXES)} — never procure/execute/deploy)"
                )
            # SEND verb: permitted ONLY for a narrow, recipient-ALLOWLIST-scoped outward action
            # (today: the invoice→Morning auto-forward, destination pinned to config addresses). A
            # general email-send is forbidden — it cannot satisfy the allowlist-scoping guard.
            if verb == "send":
                send_err = _send_allowlist_violation(cap, str(c.get("scope", "")))
                if send_err:
                    errors.append(f"grant '{agent}' {send_err}")
            # EMAIL draft-only bright line: an email-channel capability may only READ or PROPOSE
            # (draft) — never a DELIVER verb (post:/write:) and never a *send* token. Email is
            # OUTWARD to real people; this machine-enforces "never send without approval" at the
            # grant level (not just gmail_client lacking a send method).
            if _is_email_channel(cap):
                noun = cap.split(":", 1)[1].strip().lower() if ":" in cap else cap.strip().lower()
                if any(tok in noun for tok in EMAIL_SEND_TOKENS):
                    errors.append(
                        f"grant '{agent}' capability '{cap}' is an email SEND/DELIVER capability — "
                        f"email is draft-only (never send without approval). Email may only be "
                        f"read:/propose: (draft); a *send*/deliver token is the bright line."
                    )
                elif verb not in EMAIL_DRAFT_VERB_PREFIXES:
                    errors.append(
                        f"grant '{agent}' email-channel capability '{cap}' uses deliver verb '{verb}' "
                        f"— email is draft-only: only {'/'.join(EMAIL_DRAFT_VERB_PREFIXES)} "
                        f"(read inbox / propose a draft) are allowed, never post:/write: (deliver)."
                    )
            # A2A: a `message:<target>` target must be a deployed graph, the human, or a slack channel.
            if verb == "message":
                target = cap.split(":", 1)[1].strip() if ":" in cap else ""
                if not (target in graphs or target == "human" or target.startswith("slack:")):
                    errors.append(
                        f"grant '{agent}' capability '{cap}' message-target '{target}' is not a "
                        f"deployed graph / 'human' / 'slack:<channel>' (no talking to undefined peers)"
                    )
            if str(c.get("scope", "")).strip().lower() in WILDCARD_SCOPES:
                errors.append(f"grant '{agent}' capability '{cap}' scope is a bare wildcard — least-privilege requires a specific scope")
            gb = c.get("granted_by")
            if gb and gb not in human_ids:
                errors.append(f"grant '{agent}' capability '{cap}' granted_by '{gb}' is not a human owner (no self-grant / forged grantor)")
            if c.get("revocable") is not True:
                errors.append(f"grant '{agent}' capability '{cap}' must set revocable: true")

        fund = g.get("funding")
        if fund is not None and fund not in funding:
            errors.append(f"grant '{agent}' funding '{fund}' is not a declared instrument")

    # --- funding: real-bool auto_recharge; may not be ON unless ring-fenced --------------
    for fname, f in funding.items():
        if not isinstance(f, dict):
            errors.append(f"funding '{fname}' must be a mapping")
            continue
        auto = f.get("auto_recharge")
        rf = f.get("ring_fenced")
        if not isinstance(auto, bool):
            errors.append(f"funding '{fname}' auto_recharge must be a real boolean (got {auto!r}) — no quoted/cased truthy values")
        elif auto and rf is not True:
            errors.append(f"funding '{fname}' auto_recharge is ON but not ring_fenced — unbounded real-money exposure")
        if not (isinstance(rf, bool) or rf == "pending"):
            errors.append(f"funding '{fname}' ring_fenced must be true/false or 'pending' (got {rf!r})")
        if rf == "pending":
            warnings.append(f"funding '{fname}' ring_fenced: pending — FOUNDER action (audit table C)")

    return errors, warnings


def _load():
    graphs = set(json.loads(LANGGRAPH.read_text())["graphs"])
    manifest = yaml.safe_load(MANIFEST.read_text())
    return graphs, manifest


def main() -> int:
    graphs, manifest = _load()
    errors, warnings = validate(graphs, manifest)
    if errors:
        print("❌ CAPABILITY GATE FAILED — governance-charter violations:")
        for e in errors:
            print(f"   - {e}")
        print("\nEvery deployed agent must declare AGENT-only, SPEND-ONLY, report-only capability grants.")
        print("See docs/governance/gal-run-governance-charter.md (Rule #1 + spend-only). Do not bypass.")
        return 1
    print(f"✅ capability gate OK: all {len(graphs)} deployed graphs have agent-only, "
          "spend-only, report-only capability grants.")
    for w in warnings:
        print(f"   ⚠ {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
