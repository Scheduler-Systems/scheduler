"""Lane discipline + escalation framing for the deployed exec/board fleet.

A one-hour run-in exposed two cross-cutting quality problems in the agents' digests:

  * SPAM / NO LANE DISCIPLINE — every exec re-flagged the SAME company-wide items
    (over-budget, the IDOR #1487, missing RevenueCat keys, "0 active staff"), producing ~10
    near-duplicate alerts. A SYSTEMIC item must be surfaced ONCE, by its OWNER; a non-owner
    must NOT re-report it (it may, at most, reference "see <owner>").
  * OVER-ESCALATION — nearly every message was addressed "Shay, urgent, act now". A digest is
    the agent's REPORT; only a genuine BRIGHT-LINE item (capital / legal / irreversible / a real
    founder decision) is addressed to the founder. Operational items stay org-internal.

This module is the single source of truth for BOTH:

  1. ``SYSTEMIC_ITEMS`` / ``owns_systemic_item`` / ``filter_owned`` — the owned-set registry. Each
     company-wide concern has exactly ONE owning agent. An agent reports a systemic item only if
     it owns it; otherwise it is dropped (a non-owner may render a one-line ``see_owner`` pointer).
  2. ``frame_escalation`` / ``is_bright_line`` / ``founder_ask_count`` — the escalation-framing
     helpers. A digest is framed as the agent's status report; only an ``escalate_to == "shay"``
     bright-line item is addressed to the founder. Everything else routes ``org``-internal.

Pure / deterministic / FAIL-SAFE — no I/O, no model, never raises. Imported by the exec/board
agents (cfo/ceo/cto/coo/cmo/clo/security_officer, audit_risk_director/growth_director/board_chair,
daily_digest) so the policy is defined ONCE and cannot drift per agent.
"""
from __future__ import annotations

from typing import Iterable, Optional

# =============================================================================
# (2) LANE DISCIPLINE — the owned-set of SYSTEMIC (company-wide) items.
# =============================================================================
# Each systemic concern has exactly ONE owner. A systemic item is one that is true of the WHOLE
# company (not a single agent's own domain finding): the team-budget spend, the live IDOR, the
# missing RevenueCat keys, the staffing/active-count. Only the owner surfaces it as an alert;
# every other agent stays in its own lane (and may at most say "see <owner>").
#
# Owner rationale (matches the org design + the existing lane keywords):
#   * spend / over-budget / team-cap  -> the CFO owns the money.
#   * security / IDOR #1487           -> the CTO owns deploy/security posture (the CISO and CLO
#                                        read the SAME underlying issue through DIFFERENT lenses —
#                                        security_officer = the security finding, clo = the breach-
#                                        notification legal angle, audit_risk_director = the risk
#                                        oversight — those are DISTINCT domain items, not a re-flag
#                                        of the CTO's deploy item; see DISTINCT_LENS_OWNERS below).
#   * missing RevenueCat keys / funnel-> the growth/revenue agent that NEEDS them (the CMO).
#   * staffing / active-count / "0 active" -> HR / the board (board_chair) own the headcount view.
SYSTEMIC_ITEMS: dict[str, dict] = {
    # The salary-ALLOCATION re-balance (a PLANNING item, NOT a spend breach). When the roster's
    # promised salary allocation exceeds the cap but ACTUAL SPEND is under it, the CFO surfaces a
    # re-balance proposal (a budget INCREASE = capital, so it can carry escalate_to: shay). This is
    # a DISTINCT systemic item from "spend vs cap" — classified FIRST so the truthful spend-UNDER
    # CFO digest is never mislabelled as a spend breach. See ``systemic_item_for`` for the
    # allocation/negation-aware discrimination.
    "team_budget_allocation": {
        "owner": "cfo",
        "aliases": ("allocation, not spend", "allocation re-balance", "allocation rebalance",
                    "roster salary allocation", "re-balance so the allocated",
                    "allocation exceeds the cap", "salary allocation"),
        "label": "team-budget allocation re-balance",
    },
    "team_budget_spend": {
        "owner": "cfo",
        "aliases": ("over budget", "over-budget", "over cap", "over the cap", "team budget",
                    "team token budget", "over salary", "exceeded budget", "spend over"),
        "label": "team-budget spend vs cap",
    },
    "security_idor_1487": {
        # The DEPLOY/posture owner is the CTO. Other officers read the same root issue through a
        # DISTINCT lens (security finding / legal breach-notification / risk oversight) — those are
        # their OWN lane items, not a re-flag of the CTO's deploy item.
        "owner": "cto",
        "aliases": ("idor", "#1487", "1487", "schedule_acl", "firestore idor"),
        "label": "Firestore IDOR #1487 deploy hold",
        "distinct_lens_owners": ("security_officer", "clo", "audit_risk_director"),
        # The standing dossier (the FACTS the owner emits every run) lives here too, so the
        # IDOR posture survives the owner's eventual offboard — see ``IDOR_SECURITY_ITEM`` below.
        "dossier": "IDOR_SECURITY_ITEM",
    },
    "missing_revenuecat_keys": {
        "owner": "cmo",
        "aliases": ("revenuecat key", "revenuecat keys", "missing rc key", "missing revenuecat",
                    "rc keys", "funnel unavailable", "revenuecat funnel", "restore funnel"),
        "label": "missing RevenueCat keys / dark funnel",
    },
    "staffing_active_count": {
        "owner": "board_chair",
        "aliases": ("0 active", "zero active", "no active staff", "active staff", "staffing",
                    "headcount", "active /", "staffed /"),
        "label": "staffing / active-count",
        "distinct_lens_owners": ("hr_ops_manager",),
    },
}

# Reverse index: agent -> set of systemic item keys it OWNS.
_OWNER_INDEX: dict[str, set] = {}
for _key, _spec in SYSTEMIC_ITEMS.items():
    _OWNER_INDEX.setdefault(_spec["owner"], set()).add(_key)


# =============================================================================
# (2a) STANDING IDOR DOSSIER — the SINGLE SOURCE OF TRUTH for the held IDOR facts.
# =============================================================================
# THE STANDING OPEN SECURITY ITEM: the Firestore IDOR entitlement-rollout is fixed but HELD —
# validated server-maintained schedule_acl rules (20/20) are NOT deployed to production, so the
# live IDOR remains open until a human ships the gated multi-step rollout. This dossier (the
# standing FACTS that the owner — the CTO — emits every run) is RELOCATED here so the IDOR posture
# is owned by the lane registry rather than any single agent: the CTO reads it from here, and the
# Board's audit_risk_director reads it from here too, so the IDOR is surfaced even if/when the CTO
# agent is offboarded (the deploy is irreversible to prod, so it escalates to Shay).
IDOR_SECURITY_ITEM: dict = {
    "id": "firestore-idor-entitlement-rollout",
    "title": "HELD: Firestore IDOR entitlement rollout (schedule_acl) not yet deployed",
    "severity": "high",
    "status": "held",
    "detail": (
        "Server-maintained schedule_acl rules close the live #1487 IDOR and validated 20/20, "
        "but are NOT deployed to production — the IDOR stays open until the gated multi-step "
        "rollout ships. Deploy is irreversible to paying users → human-gated."
    ),
    "escalate_to": "shay",
    # The systemic-item key this dossier is the content for (round-trips with SYSTEMIC_ITEMS).
    "systemic_key": "security_idor_1487",
}


def idor_security_item() -> dict:
    """Return a COPY of the standing IDOR dossier (the held-IDOR facts). FAIL-SAFE.

    A copy so a caller mutating the returned dict can never corrupt the module constant. This is
    the authoritative source both the CTO (deploy/posture owner) and the Board audit_risk_director
    (risk-oversight lens) read, so the IDOR posture survives any single owner's offboard."""
    return dict(IDOR_SECURITY_ITEM)


def idor_is_open() -> bool:
    """True while the standing IDOR is still HELD/pending/open (i.e. should be surfaced). FAIL-SAFE."""
    return str(IDOR_SECURITY_ITEM.get("status") or "").strip().lower() in ("held", "pending", "open")


# Budget-axis discrimination (allocation re-balance vs spend breach). The CFO's truthful digest
# carries BOTH the spend line ("under cap (spent X / cap Y)") and the allocation re-balance line
# ("PLANNING (allocation, NOT spend) ... propose a re-balance") plus the "team token budget" string
# that the spend aliases match. A NEGATION-UNAWARE substring scan would mislabel the spend-UNDER
# digest as a "spend vs cap" breach — re-introducing the exact spend/allocation conflation the CFO
# digest was hardened to avoid. So we discriminate the budget axis explicitly:
#   * a POSITIVE spend-over-cap assertion ("over cap (spent ...", "OVER CAP", "spend over cap",
#     "spent ... > cap", an over-budget agent/fleet) => team_budget_spend (a real breach);
#   * otherwise, an allocation re-balance signal ("allocation, NOT spend" / "re-balance ... cap")
#     => team_budget_allocation (a planning item, NOT a spend breach).
# A POSITIVE spend-over-cap assertion — a real breach (the CFO renders "⚠️ OVER CAP (spent ...").
_SPEND_OVER_POSITIVE = (
    "over cap (spent", "⚠️ over cap", "over budget", "over-budget", "over salary",
    "exceeded budget", "spend over",
)
# Generic "team budget" mentions — a breach claim ONLY when not negated/allocation-framed.
_SPEND_GENERIC = ("over the cap", "over cap", "team token budget", "team budget")
# Negations / allocation framing that mean the SPEND is NOT over cap (so not a spend breach).
_SPEND_NEGATIONS = (
    "under cap", "under the cap", "within budget", "within its salary", "within their salary",
    "not over", "no agent over", "allocation, not spend",
)


def _budget_axis_item(low: str) -> Optional[str]:
    """Classify the budget axis: spend breach vs allocation re-balance. NEGATION-AWARE.

    Returns ``"team_budget_spend"`` for a real spend-over-cap breach; ``"team_budget_allocation"``
    for the allocation re-balance planning item; ``None`` if the text is not a budget item at all.

    The CFO's truthful digest carries BOTH a generic "team token budget" mention AND the allocation
    re-balance line AND "under cap (spent ...)". So the order is deliberate:
      1. a POSITIVE, non-negated spend-over-cap assertion ("OVER CAP (spent ...") => spend breach;
      2. else an allocation re-balance signal => the allocation item (NOT a spend breach) — this is
         what keeps a spend-UNDER digest from being mislabelled "spend vs cap";
      3. else a generic "team budget" mention that is NOT spend-under-negated => spend breach
         (so the bare "we are over the team budget cap" run-in line still classifies as spend);
      4. else None.
    """
    # 1) A genuine spend-over-cap breach: a POSITIVE assertion not negated on its own line.
    for raw in low.splitlines():
        if any(tok in raw for tok in _SPEND_OVER_POSITIVE) and not any(
            neg in raw for neg in _SPEND_NEGATIONS
        ):
            return "team_budget_spend"
    # 2) Otherwise an allocation re-balance (planning) signal => the allocation item, NOT a breach.
    for alias in SYSTEMIC_ITEMS["team_budget_allocation"]["aliases"]:
        if alias in low:
            return "team_budget_allocation"
    # 3) A generic "team budget" mention that is NOT spend-under-negated is still a spend item.
    if any(tok in low for tok in _SPEND_GENERIC) and not any(neg in low for neg in _SPEND_NEGATIONS):
        return "team_budget_spend"
    # 4) Not a budget item (or a purely spend-under all-clear with no allocation signal).
    return None


def systemic_item_for(text: str) -> Optional[str]:
    """Return the SYSTEMIC item key a piece of text refers to, or None. FAIL-SAFE, case-insensitive.

    The BUDGET axis is discriminated FIRST and NEGATION-AWARE (``_budget_axis_item``): a positive
    spend-over-cap assertion is ``team_budget_spend`` (a real breach), an allocation re-balance is
    ``team_budget_allocation`` (a planning item), so a truthful spend-UNDER CFO digest is never
    mislabelled as a spend breach. For every other axis it is a conservative substring scan over the
    item aliases, returning the FIRST match in registry order so the classification is deterministic.
    Non-systemic text (a plain own-lane finding) returns None and is never lane-filtered.
    """
    low = (text or "").lower()
    if not low:
        return None
    # Budget axis: explicit, negation-aware (spend breach vs allocation re-balance).
    budget_key = _budget_axis_item(low)
    if budget_key is not None:
        return budget_key
    # Every other axis: conservative alias substring scan (skip the budget items handled above).
    for key, spec in SYSTEMIC_ITEMS.items():
        if key in ("team_budget_spend", "team_budget_allocation"):
            continue
        for alias in spec.get("aliases", ()):  # type: ignore[union-attr]
            if alias in low:
                return key
    return None


def owns_systemic_item(agent: str, item_key: str) -> bool:
    """True if ``agent`` is the registered OWNER of systemic ``item_key``. FAIL-SAFE.

    Only the owner may surface a systemic item as its OWN alert. A distinct-lens owner (the CISO
    reading the IDOR as a security finding, the CLO as a breach-notification) is NOT the owner of
    the systemic deploy item — it owns its OWN domain item, which is classified separately by the
    agent (it is not one of these systemic aliases in that agent's framing)."""
    spec = SYSTEMIC_ITEMS.get(item_key)
    if not spec:
        return False
    return (agent or "") == spec.get("owner")


def may_report(agent: str, text: str) -> bool:
    """True if ``agent`` may surface ``text`` as its OWN alert. FAIL-SAFE.

    - Non-systemic text (an own-lane finding) is ALWAYS reportable (returns True).
    - Systemic text is reportable ONLY by the owner of that systemic item.

    This is the single gate a non-owner uses to drop a duplicate company-wide alert.
    """
    key = systemic_item_for(text)
    if key is None:
        return True  # own-lane finding — always in scope
    return owns_systemic_item(agent, key)


def filter_owned(agent: str, items: Iterable, *, key=lambda x: x) -> list:
    """Drop systemic items ``agent`` does NOT own; keep own-lane items + owned systemic items.

    ``items`` is any iterable; ``key`` extracts the text to classify from each element (default:
    the element itself). Order is preserved. Pure / FAIL-SAFE — a bad element is kept rather than
    crash (fail-open on classification, never on the data).
    """
    kept: list = []
    for it in items or []:
        try:
            text = key(it)
        except Exception:
            kept.append(it)
            continue
        if may_report(agent, str(text)):
            kept.append(it)
    return kept


def see_owner_pointer(agent: str, text: str) -> Optional[str]:
    """For a systemic item a NON-owner is dropping, return a one-line 'see <owner>' pointer.

    Returns None when the agent IS the owner (it should report the item itself) or the text is not
    systemic (nothing to point at). The pointer lets a non-owner REFERENCE a systemic item without
    re-raising it as a duplicate alert (e.g. "see cfo for team-budget spend vs cap")."""
    key = systemic_item_for(text)
    if key is None:
        return None
    spec = SYSTEMIC_ITEMS[key]
    owner = spec.get("owner")
    if (agent or "") == owner:
        return None
    return f"see {owner} for {spec.get('label', key)}"


# =============================================================================
# (4) ESCALATION FRAMING — a digest is the agent's REPORT; only bright-line items ask the founder.
# =============================================================================
# The ONLY lane value that addresses the founder. Everything else is org-internal (resolved by the
# org / routed to the CEO/board), NOT pushed at Shay.
FOUNDER_LANE = "shay"
ORG_LANE = "org"


def is_bright_line(escalate_to: Optional[str]) -> bool:
    """True only for a genuine BRIGHT-LINE founder item (``escalate_to == 'shay'``). FAIL-SAFE.

    Capital / legal / irreversible / a real founder decision is tagged ``escalate_to: "shay"`` by
    the producing agent. Only such items are addressed to the founder; everything else is the
    agent's own status / org-internal routing."""
    return (escalate_to or "").strip().lower() == FOUNDER_LANE


def founder_ask_count(items: Iterable, *, key=lambda x: x.get("escalate_to") if isinstance(x, dict) else None) -> int:
    """Count the bright-line (founder) asks in ``items``. FAIL-SAFE.

    ``key`` extracts each item's ``escalate_to`` (default: dict ``escalate_to``). A non-dict / bad
    element contributes 0 rather than crash. This is the SINGLE reconciled count the board synthesis
    reports — "asks: N" — so the company view never contradicts itself."""
    n = 0
    for it in items or []:
        try:
            if is_bright_line(key(it)):
                n += 1
        except Exception:
            continue
    return n


def frame_escalation(escalate_to: Optional[str], *, agent: str = "", report_only: bool = True) -> str:
    """Return the AUDIENCE framing for an item: ``"founder-ask"`` vs ``"org-internal"``. FAIL-SAFE.

    A digest is framed as the agent's status REPORT. Only a bright-line (``shay``) item is a
    ``founder-ask`` (explicitly addressed to the founder). Every operational item is
    ``org-internal`` — resolved inside the org / routed to the CEO/board — NEVER pushed at the
    founder. This is the single helper the agents use so the "Shay, urgent" over-escalation can't
    recur: an item is addressed to Shay IFF ``frame_escalation(...) == 'founder-ask'``."""
    return "founder-ask" if is_bright_line(escalate_to) else "org-internal"


def addressee(escalate_to: Optional[str]) -> str:
    """Human-readable addressee for a rendered line: 'Shay (founder ask)' vs 'org (internal)'.

    Used by digest renderers so only bright-line items literally name the founder; operational
    items name the org. Keeps the "only bright-line items get an explicit founder ask" rule in one
    place."""
    return "Shay (founder ask)" if is_bright_line(escalate_to) else "org (internal)"


# =============================================================================
# (5) FOUNDER-ASK RECONCILIATION — relocated SHARED logic (board_chair survives offboard).
# =============================================================================
# A Shay-level item is one a subordinate explicitly escalated to "shay", OR one whose text mentions
# a capital/irreversible/legal trigger. Everything else stays inside the org. This was the
# board_chair's private logic; it is RELOCATED here as a SHARED helper so the single-pane company
# view (the daily_digest) can compute the SAME reconciled founder-ask count WITHOUT depending on the
# board_chair agent — i.e. it survives the board_chair's eventual offboard. Both agents call the
# same source (DRY): there is still exactly ONE reconciliation algorithm.
SHAY_TRIGGERS: tuple = (
    "escalate_to: shay",
    "escalate_to:shay",
    '"escalate_to": "shay"',
    "capital",
    "spend approval",
    "irreversible",
    "legal",
    "contract",
    "lawsuit",
    "liability",
    "fundraise",
    "equity",
)


def reconcile_founder_asks(reports: dict, *, order: Optional[Iterable[str]] = None) -> list[dict]:
    """RECONCILE the founder asks across ALL subordinate digests into ONE deduped list. FAIL-SAFE.

    The single company synthesis must be CONSISTENT: a systemic company-wide concern (the IDOR, the
    team-budget spend) that several subordinates each mention is reconciled into ONE ask, attributed
    to its OWNER, rather than counted once per mention. The result is the authoritative
    "asks: N (reconciled)" the whole company view uses, so the update can never contradict itself
    ("no asks" vs "Shay act now").

    ``reports`` is a ``{slug: digest_text}`` mapping; ``order`` optionally fixes the slug iteration
    order for deterministic attribution (defaults to ``reports`` insertion order). Returns a list of
    ``{"ask", "source", "escalate_to": "shay"[, "systemic"]}``. Empty when no subordinate flagged a
    Shay-level item (the update then reads "no asks"). Never fabricates an ask; never raises.
    """
    reports = reports or {}
    slugs = list(order) if order is not None else list(reports.keys())
    asks: list[dict] = []
    seen_systemic: set = set()
    for slug in slugs:
        text = reports.get(slug) or ""
        low = str(text).lower()
        hit = next((trig for trig in SHAY_TRIGGERS if trig in low), None)
        if not hit:
            continue
        # Reconcile: if this ask is a SYSTEMIC item, count it ONCE under its owner, not per source.
        item_key = systemic_item_for(str(text))
        if item_key is not None:
            if item_key in seen_systemic:
                continue
            seen_systemic.add(item_key)
            spec = SYSTEMIC_ITEMS.get(item_key, {})
            asks.append(
                {
                    "ask": f"{spec.get('label', item_key)} (owner: {spec.get('owner')})",
                    "source": spec.get("owner") or slug,
                    "escalate_to": "shay",
                    "systemic": item_key,
                }
            )
            continue
        asks.append(
            {
                "ask": f"{slug} escalated a capital/irreversible/legal item ('{hit}')",
                "source": slug,
                "escalate_to": "shay",
            }
        )
    return asks


def reconciled_founder_ask_count(reports: dict, *, order: Optional[Iterable[str]] = None) -> int:
    """The single reconciled founder-ask COUNT computed directly from subordinate reports. FAIL-SAFE.

    A convenience over ``reconcile_founder_asks`` + ``founder_ask_count`` so a survivor (the daily
    digest) can compute the authoritative count itself when the board chair's digest is absent."""
    return founder_ask_count(reconcile_founder_asks(reports, order=order))


# =============================================================================
# (6) STAFFING / HEADCOUNT VIEW — relocated SHARED helper (board_chair survives offboard).
# =============================================================================
def staffing_view(
    roster: dict,
    *,
    is_clocked_in=None,
    is_model_work=None,
) -> dict:
    """Compute the staffed/active headcount view off a roster dict. PURE / FAIL-SAFE.

    Relocated from the board_chair's private KPI assembly so the single-pane survivor (the daily
    digest) can compute the SAME staffing/headcount view WITHOUT depending on the board_chair agent.

      - ``staffed`` : number of roster agents (excluding any model-dev role).
      - ``active``  : roster agents that are operationally ON-SHIFT (clocked-in: not
                      fleet-disabled / benched / over-budget). A probation agent working its
                      report-only shift IS active — this stops a false "0 active" while the fleet
                      is in fact working.

    ``is_clocked_in(name) -> bool`` and ``is_model_work(name) -> bool`` are injected so this helper
    stays PURE (no import of the agent toolkit's I/O). When ``is_clocked_in`` is omitted, every
    counted agent is treated as active (fail-safe: never under-report a working fleet). When
    ``is_model_work`` is omitted, no agent is treated as a model-dev role. Never raises.
    """
    agents = (roster or {}).get("agents", {}) or {}
    staffed = 0
    active = 0
    for name in agents:
        try:
            if is_model_work is not None and is_model_work(name):
                continue  # never count a model-dev role (Anthropic terms)
        except Exception:
            pass
        staffed += 1
        if is_clocked_in is None:
            active += 1
            continue
        try:
            if is_clocked_in(name):
                active += 1
        except Exception:
            active += 1  # fail-safe: count as active rather than under-report a working fleet
    return {"staffed": staffed, "active": active}
