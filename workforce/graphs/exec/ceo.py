"""ceo — the Chief Executive Officer that synthesizes the exec suite and chairs the queue.

Runtime: cloud/CI (LangGraph Platform managed Cloud SaaS); register-able in
``langgraph.json`` (the orchestrator owns that file — not this module).

MISSION: the CEO does NOT re-do the executives' work. It CONSUMES the four exec officers'
latest local digests (CFO / COO / CTO / CMO), synthesizes them into the company's TOP
PRIORITIES, and chairs the consolidated PROPOSAL QUEUE — separating what the org can resolve
itself from the few items that are genuine ASKS FOR SHAY (capital / irreversible / legal).
The CEO PROPOSES; Shay (founder + investor) ratifies. Every action lands as a PROPOSAL in
the digest — there is NO auto-execution and NO approval interrupt on the scheduled path.

LOAD-BEARING DECISIONS (match the ops-fleet cloud house style — see revenue_reporter,
daily_digest):

  * PROBATION / REPORT-ONLY by default. The strategy digest + proposal queue are delivered
    via ``file_digest_issue(..., report_only=_report_only())`` where ``_report_only()``
    defaults True (env ``OPS_REPORT_ONLY``; only "0"/"false"/"no" turns it off). On probation
    the delivery is an honest ``{"status": "report_only", ...}`` plan dict — NO GitHub write
    and, critically, NO approval interrupt — so a scheduled unattended run can never hang or
    write.

  * NEVER HANG. With no credentials the run still completes: every exec digest read, the model
    synthesis, and the GitHub delivery are each wrapped so a missing file / offline / SDK drift
    returns a structured result and the node moves on. There is NO reachable
    request_approval/interrupt.

  * FAIL-SAFE compose. The model is used ONLY to phrase the gathered exec digests + the derived
    priorities/queue; on ANY model failure (no key, budget, SDK drift) we fall back to a
    DETERMINISTIC strategy report built directly from the digests, so a digest is always
    produced AND the proposal queue is always present (the queue is derived deterministically,
    never by the model).

  * ESCALATION SPLIT — PER PROPOSAL, not per officer. Each officer digest is parsed into up to
    ``_MAX_PROPOSALS_PER_OFFICER`` distinct proposal lines, and EACH line is classified on its
    OWN text (``_is_shay_ask`` is scoped to the candidate line, never the whole body) so an
    incidental keyword elsewhere in the digest can't spuriously escalate an unrelated headline.
    Each proposal carries ``escalate_to: "org" | "shay"``; only capital / irreversible / legal
    items are asks for Shay. Classification is conservative and the tags survive delivery.

  * FRESHNESS + PROVENANCE. ``gather`` stats each digest file's mtime and records its age; a
    digest older than ``CEO_DIGEST_STALE_HOURS`` (default 24h) is flagged ``stale`` rather than
    silently treated as current, and its proposals are tagged so a missed officer schedule is
    visible. The consumed input set (per-officer mtime + age + a short content hash) is embedded
    in the delivered body so "what did the CEO see, and when" is auditable. All stat calls are
    fail-safe — a missing/unreadable file degrades to "unknown age", never an error.

  * QUEUE CONTINUITY. Before composing, the CEO reads its OWN prior digest and marks each queue
    item ``new`` vs ``carried`` (a proposal already raised last cycle) so the chaired queue has
    memory across runs. This is best-effort local-fs only — no persistence service, no gate.

  * MODEL CROSS-CHECK. The model phrases the synthesis ONLY; the deterministic queue (org/shay
    split, per-officer counts) is the source of truth and is appended VERBATIM, with the model
    prose clearly labelled "advisory synthesis". A counts mismatch between the model's framing
    and the deterministic queue is not possible to act on — the deterministic queue always wins.

  * ANTHROPIC-TERMS / ML BOUNDARY. ``assert_not_model_work`` guards every outward target string
    (the four exec officer names + the digest repo). No model train/eval/distill; gal-model and
    the policy denylist are never read or reported.

  * Compiles WITHOUT a checkpointer/store (the platform injects Postgres). Every node body is
    wrapped in ``span("ceo.<node>", ...)``; governance is captured at the end (report_only=True).
"""
from __future__ import annotations

import hashlib
import os
import time

from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END

from agent_toolkit import (
    span,
    governance_capture,
    assert_not_model_work,
    budget_guard,
    check_clocked_in,
    read_local_digest,
    write_local_digest,
    file_digest_issue,
    TIER_DEFAULT,
)
from agent_toolkit.ops_report import workspace_root
from agent_toolkit.policy import ModelWorkBlocked
from agent_toolkit import lanes

# Where the CEO strategy digest issue is filed (a no-prod-deploy, allow-listed repo).
DIGEST_REPO = "Scheduler-Systems/qa-agent-platform"

# An exec digest older than this is treated as STALE — its officer likely did not run this
# cycle, so its proposals are flagged (not silently treated as current). Overridable via env
# ``CEO_DIGEST_STALE_HOURS`` for other cadences; fail-safe to the default on a bad value.
_DEFAULT_STALE_HOURS = 24.0

# How many distinct proposal lines we lift from a single officer's digest. The CEO no longer
# collapses each officer to ONE headline — multiple distinct asks are parsed and classified
# per-line. Capped so a verbose digest can't flood the queue.
_MAX_PROPOSALS_PER_OFFICER = 5

# The four exec officers the CEO synthesizes (officer name -> local-digest slug). The CEO reads
# their REPORTS — it does not recompute spend/ops/repo/growth posture. Order is revenue-first:
# the CFO (money) and CMO (growth) lead, then COO/CTO (ops/repo). A missing digest is tolerated
# and reported as "(no digest yet)", never an error.
EXEC_OFFICERS = {
    "cfo": "cfo",
    "cmo": "cmo",
    "coo": "coo",
    "cto": "cto",
}
# The rendering / synthesis order: revenue (cfo, cmo) FIRST, then ops/repo (coo, cto).
OFFICER_ORDER = ("cfo", "cmo", "coo", "cto")

# Words in an exec digest line that mark a proposal as a genuine ASK FOR SHAY (capital /
# irreversible / legal) rather than an org-resolvable item. Conservative + lowercase-matched.
_SHAY_MARKERS = (
    "capital",
    "fund",
    "funding",
    "raise",
    "investment",
    "spend approval",
    "budget increase",
    "hire",
    "fire",
    "terminat",
    "legal",
    "contract",
    "lawyer",
    "compliance",
    "irreversible",
    "delete",
    "production deploy",
    "prod deploy",
    "pricing change",
    "refund",
)


def _report_only() -> bool:
    """Report-only default for the probation officer: truthy/unset env => True.

    Only an explicit ``OPS_REPORT_ONLY`` of "0"/"false"/"no" turns delivery into a real
    (gated) GitHub write. Everything else — including the env being unset — keeps the officer
    in honest report-only mode (no GitHub call, no approval interrupt).
    """
    return os.environ.get("OPS_REPORT_ONLY", "").lower() not in ("0", "false", "no")


class State(TypedDict, total=False):
    mode: str            # reserved for future read-only/observe variants
    digests: dict        # officer slug -> latest local digest text (or "(no digest yet)")
    provenance: dict     # officer slug -> {mtime, age_hours, stale, sha8, present} (audit)
    priorities: list     # derived top company priorities (deterministic)
    queue: list          # the consolidated proposal queue (each tagged escalate_to org|shay)
    references: list     # one-line "see <owner>" pointers for deduped non-owner systemic mentions
    summary: str         # composed strategy report text
    report: dict         # terminal verdict
    report_only: bool    # whether delivery stayed report-only


def budget_gate(state: State) -> dict:
    """CLOCK-IN gate — STOP before any work if over salary or globally disabled.

    Runs FIRST. If clocked in, control passes to ``gather``; if not, we capture governance
    (report-only) and route to END. No digest reads, no model spend, no writes on the
    clocked-out path.
    """
    with span("ceo.budget_gate"):
        if check_clocked_in("ceo"):
            return {}
        report = {
            "status": "skipped",
            "detail": "ceo over token salary or globally disabled",
            "report_only": True,
        }
        governance_capture(
            "ceo",
            {"clocked_in": False, "delivery": "skipped", "report_only": True, "report": report},
        )
        return {"report": report, "report_only": True}


def gather(state: State) -> dict:
    """Read the four exec officers' latest local digests + their FRESHNESS. FAIL-SAFE.

    For each officer (CFO / CMO / COO / CTO) we guard the officer name against the Anthropic-
    terms denylist, then read its ``<WORKSPACE_ROOT>/.tmp/<slug>/latest.md`` via
    ``read_local_digest`` (which never raises — a missing file becomes "(no digest yet)"). A
    denylisted officer is skipped entirely. The CEO does NOT recompute spend/ops/repo/growth.

    We ALSO stat each digest file (``_digest_provenance``) so the synthesis is honest about WHEN
    each officer last reported: a digest older than ``CEO_DIGEST_STALE_HOURS`` is flagged
    ``stale`` (its officer likely did not run this cycle) instead of being treated as current,
    and the consumed input set + ages + a short content hash are carried for an audit appendix.
    All stat calls are fail-safe — a missing/unreadable file degrades to "unknown age".
    """
    with span("ceo.gather", officers=len(EXEC_OFFICERS)):
        digests: dict = {}
        provenance: dict = {}
        for officer in OFFICER_ORDER:
            slug = EXEC_OFFICERS[officer]
            try:
                assert_not_model_work(officer)  # never consume/report a model-dev role
            except ModelWorkBlocked:
                continue
            try:
                text = read_local_digest(slug)
            except Exception:  # read_local_digest is already fail-safe; belt-and-suspenders
                text = "(no digest yet)"
            digests[officer] = text
            provenance[officer] = _digest_provenance(slug, text)
        return {"digests": digests, "provenance": provenance}


def analyze(state: State) -> dict:
    """Derive the top company priorities + the consolidated proposal queue. DETERMINISTIC.

    The queue is built directly from the exec digests (NOT by the model) so it is ALWAYS
    present and auditable. For each present, reporting officer we parse up to
    ``_MAX_PROPOSALS_PER_OFFICER`` DISTINCT proposal lines (``_parse_proposals``) rather than
    collapsing the officer to a single headline — a digest with several distinct asks keeps all
    of them. Each proposal line is classified on ITS OWN text (``_is_shay_ask`` scoped to that
    line), so an incidental capital/legal keyword elsewhere in the body can't spuriously
    escalate an unrelated proposal. Capital / irreversible / legal lines are tagged
    ``escalate_to: "shay"``; everything else stays ``"org"``.

    Freshness is folded in from ``provenance``: a STALE digest's officer still surfaces a
    priority/queue entries, but each entry is marked ``stale: True`` so a missed officer
    schedule is visible (not silently treated as current). An officer with no digest at all
    yields a "(no digest yet)" priority and no queue entry, so coverage gaps stay visible.
    """
    digests = state.get("digests") or {}
    provenance = state.get("provenance") or {}

    with span("ceo.analyze", officers=len(digests)):
        priorities: list = []
        queue: list = []
        # LANE DISCIPLINE: a SYSTEMIC company-wide item (over-budget, IDOR, missing RC keys,
        # staffing) must enter the consolidated queue ONCE, attributed to its OWNER — not once per
        # officer that happened to mention it. We track which systemic items are already in the
        # queue and drop a non-owner's duplicate (recording a single "see <owner>" pointer instead).
        systemic_seen: set = set()
        see_pointers: dict = {}
        for officer in OFFICER_ORDER:
            text = digests.get(officer)
            if text is None:
                continue  # officer was skipped (denylist) — not part of the queue
            reported = bool(text and text.strip() and text.strip() != "(no digest yet)")
            prov = provenance.get(officer) or {}
            stale = bool(prov.get("stale"))
            headline = _headline(text) if reported else "(no digest yet)"
            priorities.append(
                {
                    "officer": officer,
                    "reported": reported,
                    "headline": headline,
                    "stale": stale,
                    "age_hours": prov.get("age_hours"),
                }
            )
            if not reported:
                continue
            # Per-proposal parsing + per-line escalation (NOT one headline / whole-body match).
            for proposal in _parse_proposals(text):
                item_key = lanes.systemic_item_for(proposal)
                if item_key is not None:
                    # Systemic item: only the OWNER contributes it, and only once.
                    if not lanes.owns_systemic_item(officer, item_key):
                        # Non-owner re-flag — drop the duplicate; keep a single see-owner pointer.
                        ptr = lanes.see_owner_pointer(officer, proposal)
                        if ptr:
                            see_pointers.setdefault(item_key, ptr)
                        continue
                    if item_key in systemic_seen:
                        continue  # owner already contributed this systemic item once
                    systemic_seen.add(item_key)
                escalate = "shay" if _is_shay_ask(proposal) else "org"
                queue.append(
                    {
                        "officer": officer,
                        "proposal": proposal,
                        "escalate_to": escalate,
                        "stale": stale,
                        "report_only": True,
                    }
                )
        # Surface a single cross-reference for each systemic item a non-owner mentioned but did
        # not own (so the context is not lost, without re-raising the alert).
        references = [
            {"item": k, "see": v} for k, v in see_pointers.items() if k not in systemic_seen
        ]
        return {"priorities": priorities, "queue": queue, "references": references}


def compose(state: State) -> dict:
    """Phrase the priorities + queue as a concise strategy report. FAIL-SAFE.

    First we add QUEUE CONTINUITY deterministically: the CEO reads its OWN prior digest and
    marks each queue item ``new`` vs ``carried`` (already raised last cycle) so the chaired
    queue has memory across runs — best-effort, local-fs only, fail-safe.

    The model (TIER_DEFAULT, metered via ``budget_guard``) is then used ONLY to phrase the
    already-derived priorities/queue + the exec digests — it is ADVISORY. The deterministic
    queue remains the source of truth (re-rendered verbatim in ``deliver``); the model is never
    allowed to alter the org/shay split or the per-officer counts. On ANY model failure (no key,
    budget, SDK drift) we fall back to the DETERMINISTIC memo, so a digest is always produced.
    No model train/eval/distill — phrasing only.
    """
    digests = state.get("digests") or {}
    priorities = state.get("priorities") or []
    queue = _mark_queue_continuity(state.get("queue") or [])
    provenance = state.get("provenance") or {}

    with span("ceo.compose", priorities=len(priorities), queue=len(queue)):
        facts = _deterministic_report(digests, priorities, queue, provenance)
        summary = ""
        try:
            model = budget_guard("ceo", TIER_DEFAULT)
            prompt = (
                "You are the CEO of the Scheduler product company. The CFO, CMO, COO and CTO "
                "have each filed a digest (below). Write a CONCISE STATUS MEMO (this is your "
                "report, not an alarm): (1) the top company priorities this cycle, (2) the "
                "consolidated proposal queue, clearly separating what the org will resolve "
                "itself from the FEW items that genuinely need the founder/investor (capital, "
                "irreversible, or legal). FRAMING RULES: do NOT address the founder ('Shay, "
                "urgent / act now') for operational items — those are resolved inside the org or "
                "routed to the board; address the founder ONLY for the bright-line (escalate_to "
                "shay) items, if any. Do NOT invent numbers or proposals; only synthesize what "
                "the exec digests show — the authoritative proposal queue and its org/shay split "
                "are computed deterministically and shown below; treat them as ground truth and "
                "do not contradict the counts. You PROPOSE; the founder ratifies. Be direct and "
                "skimmable.\n\n"
                f"{facts}"
            )
            resp = model.invoke(prompt)
            model_text = getattr(resp, "content", str(resp)) or ""
            if model_text.strip():
                # Model prose is ADVISORY — clearly labelled; the deterministic queue (appended
                # verbatim in deliver) is the source of truth, so the model cannot silently
                # restate the org/shay split or counts.
                summary = "## Synthesis (advisory)\n\n" + model_text
            else:
                summary = facts
        except Exception as exc:  # model unavailable — deterministic fallback (never empty)
            summary = (
                f"(model synthesis unavailable: {type(exc).__name__}) — deterministic memo:\n\n"
                f"{facts}"
            )

        if not summary.strip():  # belt-and-suspenders: never deliver an empty summary
            summary = facts
        return {"summary": summary, "queue": queue}


def deliver(state: State) -> dict:
    """Write a local digest artifact and file the CEO digest issue (report-only on probation).

    - ``write_local_digest`` always runs (succeeds-or-"" ; never raises) so there is a local
      artifact even with zero credentials.
    - ``file_digest_issue(..., report_only=_report_only())`` delivers the issue. On probation
      (the default) this returns an honest report-only plan dict with NO GitHub call and NO
      approval interrupt — an unattended run can never hang or write. The proposal queue (with
      escalate_to tags preserved) is appended to the issue body for auditability.
    """
    summary = state.get("summary") or ""
    digests = state.get("digests") or {}
    priorities = state.get("priorities") or []
    queue = state.get("queue") or []
    references = state.get("references") or []
    provenance = state.get("provenance") or {}
    report_only = _report_only()

    with span("ceo.deliver", report_only=report_only, queue=len(queue)):
        assert_not_model_work(DIGEST_REPO)  # never file into a model-dev repo

        body = (
            summary
            + "\n\n---\n\n## Proposal queue (authoritative — deterministic)\n\n"
            + _render_queue(queue)
            + _render_references(references)
            + "\n\n## Inputs consumed (provenance)\n\n"
            + _provenance_appendix(provenance)
            + "\n\n## Raw exec digests\n\n"
            + _digests_appendix(digests, priorities)
        )

        # Local artifact first — always, fail-safe.
        digest_path = write_local_digest("ceo", "CEO: priorities + proposal queue", body)

        # GitHub issue delivery — report-only by default (no write, no interrupt).
        res = file_digest_issue(
            DIGEST_REPO,
            "CEO: priorities + proposal queue",
            body,
            labels=["exec:ceo"],
            report_only=report_only,
            agent="ceo",
            slack_title="🏢 CEO: priorities + proposal queue",
        )
        delivery = res.get("status") if isinstance(res, dict) else None

        shay_asks = sum(1 for item in queue if item.get("escalate_to") == "shay")
        carried = sum(1 for item in queue if item.get("continuity") == "carried")
        stale_officers = sum(1 for p in priorities if p.get("stale"))
        return {
            "report": {
                "delivery": delivery,
                "digest": digest_path,
                "priorities": len(priorities),
                "queue": len(queue),
                "shay_asks": shay_asks,
                "carried": carried,
                "stale_officers": stale_officers,
                "report_only": report_only,
            },
            "report_only": report_only,
        }


def finalize(state: State) -> dict:
    """Terminal node — capture governance (report-only) and emit the verdict."""
    priorities = state.get("priorities") or []
    queue = state.get("queue") or []
    prior = state.get("report") if isinstance(state.get("report"), dict) else {}
    delivery = prior.get("delivery")
    shay_asks = sum(1 for item in queue if item.get("escalate_to") == "shay")
    carried = sum(1 for item in queue if item.get("continuity") == "carried")
    stale_officers = sum(1 for p in priorities if p.get("stale"))

    with span("ceo.finalize", delivery=delivery, queue=len(queue)):
        governance_capture(
            "ceo",
            {
                "priorities": len(priorities),
                "queue": len(queue),
                "shay_asks": shay_asks,
                "carried": carried,
                "stale_officers": stale_officers,
                "delivery": delivery,
                "report_only": True,
            },
        )
        return {
            "report": {
                "priorities": len(priorities),
                "queue": len(queue),
                "shay_asks": shay_asks,
                "carried": carried,
                "stale_officers": stale_officers,
                "delivery": delivery,
                "digest": prior.get("digest"),
                "report_only": True,
            }
        }


def _budget_route(state: State) -> str:
    """Route past the clock-in gate: clocked in -> gather; clocked out -> END."""
    return "gather" if check_clocked_in("ceo") else "clocked_out"


# --- Deterministic synthesis helpers (used by compose fallback + the issue appendix) -----
def _headline(text: str) -> str:
    """First meaningful line of an exec digest = its headline (markdown heading stripped)."""
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        line = line.lstrip("#").strip()
        if line:
            return line[:200]
    return "(no digest yet)"


def _is_shay_ask(text: str) -> bool:
    """True when THIS proposal line mentions a capital / irreversible / legal concern.

    Scoped to the candidate proposal text (a single parsed line), NOT the whole digest body —
    so an incidental keyword elsewhere in an officer's digest can't escalate an unrelated
    proposal. Conservative + lowercase-matched against ``_SHAY_MARKERS``.
    """
    low = (text or "").lower()
    return any(marker in low for marker in _SHAY_MARKERS)


def _parse_proposals(text: str) -> list:
    """Parse a digest into up to ``_MAX_PROPOSALS_PER_OFFICER`` DISTINCT proposal lines.

    Real exec digests phrase asks as bullet/numbered lines or sentences containing a verb like
    "propose"/"recommend"/"need"/"request". We prefer such candidate lines (in document order,
    de-duplicated); if none are found we fall back to the single headline so an officer with a
    terse one-line digest still contributes exactly one proposal. NEVER raises.
    """
    candidates: list = []
    seen: set = set()

    def _add(line: str) -> None:
        clean = line.strip().lstrip("#").lstrip("-*0123456789.) ").strip()
        if not clean:
            return
        key = clean.lower()[:200]
        if key in seen:
            return
        seen.add(key)
        candidates.append(clean[:200])

    verbs = ("propose", "recommend", "request", "need", "ask", "should", "must", "escalat")
    for raw in (text or "").splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        is_bullet = stripped.lstrip("#").lstrip().startswith(("-", "*")) or (
            stripped[:2].rstrip(".)").isdigit()
        )
        low = stripped.lower()
        if is_bullet or any(v in low for v in verbs):
            _add(stripped)
        if len(candidates) >= _MAX_PROPOSALS_PER_OFFICER:
            break

    if not candidates:
        headline = _headline(text)
        if headline and headline != "(no digest yet)":
            candidates.append(headline)
    return candidates[:_MAX_PROPOSALS_PER_OFFICER]


def _digest_provenance(slug: str, text: str) -> dict:
    """Stat an exec digest file and return its freshness + a short content hash. FAIL-SAFE.

    Returns ``{present, mtime, age_hours, stale, sha8}``. ``present`` is False (and age/mtime
    None) when the file is missing/unreadable or the text is the "(no digest yet)" placeholder.
    ``stale`` is True when the file's age exceeds ``CEO_DIGEST_STALE_HOURS``. The hash is a short
    sha256 prefix of the consumed text, so the audit appendix can pin "what content did the CEO
    see" without storing the whole body twice. NEVER raises.
    """
    present = bool(text and text.strip() and text.strip() != "(no digest yet)")
    sha8 = ""
    try:
        sha8 = hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:8]
    except Exception:
        sha8 = ""

    mtime = None
    age_hours = None
    stale = not present  # a missing/placeholder digest is, definitionally, not fresh
    try:
        safe = "".join(c if (c.isalnum() or c in "-_") else "-" for c in (slug or "")).strip("-") or "ops"
        path = os.path.join(workspace_root(), ".tmp", safe, "latest.md")
        mtime = os.stat(path).st_mtime
        age_hours = max(0.0, (time.time() - mtime) / 3600.0)
        if present:
            stale = age_hours > _stale_hours()
    except Exception:
        # No stat (missing file / FS error) — keep age unknown; staleness defers to `present`.
        pass

    return {
        "present": present,
        "mtime": mtime,
        "age_hours": round(age_hours, 2) if isinstance(age_hours, float) else None,
        "stale": stale,
        "sha8": sha8,
    }


def _stale_hours() -> float:
    """The staleness threshold in hours (env ``CEO_DIGEST_STALE_HOURS``). Fail-safe to default."""
    try:
        value = float(os.environ.get("CEO_DIGEST_STALE_HOURS", "") or _DEFAULT_STALE_HOURS)
        return value if value > 0 else _DEFAULT_STALE_HOURS
    except (TypeError, ValueError):
        return _DEFAULT_STALE_HOURS


def _prior_queue_keys() -> set:
    """Read the CEO's OWN prior digest and extract the proposals it raised last cycle. FAIL-SAFE.

    Continuity has no persistence service — the CEO simply re-reads its own
    ``.tmp/ceo/latest.md`` and harvests the queue lines it rendered (``- **[officer]** text``).
    Returns a set of normalized ``"officer::proposal"`` keys, or an empty set on any error / a
    first-ever run. NEVER raises.
    """
    keys: set = set()
    try:
        prior = read_local_digest("ceo")
    except Exception:
        return keys
    if not prior or prior.strip() == "(no digest yet)":
        return keys
    for raw in prior.splitlines():
        line = raw.strip()
        # Match the rendered queue line shape: "- **[officer]** proposal text  _(escalate_to: …)_"
        if not line.startswith("- **["):
            continue
        try:
            officer = line.split("[", 1)[1].split("]", 1)[0].strip().lower()
            after = line.split("]**", 1)[1]
            proposal = after.split("_(", 1)[0].strip()
            if officer and proposal:
                keys.add(_continuity_key(officer, proposal))
        except Exception:
            continue
    return keys


def _continuity_key(officer: str, proposal: str) -> str:
    return f"{(officer or '').lower()}::{(proposal or '').strip().lower()[:120]}"


def _mark_queue_continuity(queue: list) -> list:
    """Tag each queue item ``continuity: new|carried`` vs the CEO's prior digest. FAIL-SAFE.

    Pure annotation — never drops or reorders items; on any error every item is simply ``new``.
    """
    try:
        prior_keys = _prior_queue_keys()
    except Exception:
        prior_keys = set()
    marked: list = []
    for item in queue:
        out = dict(item)
        key = _continuity_key(out.get("officer", ""), out.get("proposal", ""))
        out["continuity"] = "carried" if key in prior_keys else "new"
        marked.append(out)
    return marked


def _queue_line(q: dict) -> str:
    """One rendered queue line, preserving escalate_to + new/carried + stale tags.

    The audience is made explicit via ``lanes.addressee`` so ONLY a bright-line (shay) item is
    addressed to the founder; every org item reads "org (internal)" and is never pushed at Shay.
    """
    escalate = q.get("escalate_to", "org")
    tags = [f"escalate_to: {escalate}", f"audience: {lanes.addressee(escalate)}"]
    if q.get("continuity") == "carried":
        tags.append("carried")
    if q.get("stale"):
        tags.append("stale")
    return f"- **[{q.get('officer')}]** {q.get('proposal')}  _({'; '.join(tags)})_"


def _render_queue(queue: list) -> str:
    """Render the proposal queue with escalate_to / continuity / staleness tags preserved."""
    if not queue:
        return "_(no proposals this cycle)_"
    shay = [q for q in queue if q.get("escalate_to") == "shay"]
    org = [q for q in queue if q.get("escalate_to") != "shay"]
    carried = sum(1 for q in queue if q.get("continuity") == "carried")
    lines: list[str] = []
    lines.append(
        f"### Asks for Shay (capital / irreversible / legal) — {len(shay)}"
    )
    if shay:
        for q in shay:
            lines.append(_queue_line(q))
    else:
        lines.append("- _(none — nothing requires the founder this cycle)_")
    lines.append("")
    lines.append(f"### Org-resolvable — {len(org)}")
    if org:
        for q in org:
            lines.append(_queue_line(q))
    else:
        lines.append("- _(none)_")
    lines.append("")
    lines.append(f"_Continuity: {carried} carried over from last cycle, {len(queue) - carried} new._")
    return "\n".join(lines)


def _render_references(references: list) -> str:
    """Render the deduped 'see <owner>' cross-references for systemic items a non-owner mentioned.

    LANE DISCIPLINE: a systemic company-wide item lives in the queue ONCE, under its owner. When a
    non-owner officer mentioned the same item, we do not re-raise it as a duplicate alert — we keep
    a single pointer here so the context survives without the spam."""
    if not references:
        return ""
    lines = ["", "### Cross-references (systemic items owned elsewhere — not re-raised here)"]
    for r in references:
        lines.append(f"- {r.get('see')}")
    return "\n".join(lines)


def _deterministic_report(digests: dict, priorities: list, queue: list,
                          provenance: dict | None = None) -> str:
    """A skimmable plain-text strategy memo built ENTIRELY from the gathered facts (no model)."""
    lines = ["CEO: priorities + proposal queue", ""]
    lines.append("## Top company priorities")
    if priorities:
        for p in priorities:
            if not p.get("reported"):
                mark = " (no digest yet)"
            elif p.get("stale"):
                age = p.get("age_hours")
                mark = f" ⚠️ STALE ({age}h old — officer likely did not run this cycle)"
            else:
                mark = ""
            lines.append(f"- [{p.get('officer')}] {p.get('headline')}{mark}")
    else:
        lines.append("- (no exec digests available)")
    lines.append("")
    lines.append("## Proposal queue")
    lines.append(_render_queue(queue))
    if provenance:
        lines.append("")
        lines.append("## Inputs consumed (provenance)")
        lines.append(_provenance_appendix(provenance))
    return "\n".join(lines)


def _provenance_appendix(provenance: dict) -> str:
    """Audit row per officer: presence, mtime/age, freshness, and the consumed content hash."""
    if not provenance:
        return "_(no inputs recorded)_"
    lines: list[str] = []
    lines.append(f"_Threshold: a digest older than {_stale_hours():g}h is flagged stale._")
    lines.append("")
    for officer in OFFICER_ORDER:
        prov = provenance.get(officer)
        if not prov:
            continue
        if not prov.get("present"):
            state = "missing/empty"
        elif prov.get("stale"):
            state = "STALE"
        else:
            state = "fresh"
        age = prov.get("age_hours")
        age_str = f"{age}h" if age is not None else "unknown age"
        sha = prov.get("sha8") or "—"
        lines.append(
            f"- **{officer}** (`.tmp/{EXEC_OFFICERS[officer]}/latest.md`): {state}, {age_str}, sha256:{sha}"
        )
    return "\n".join(lines) if lines else "_(no inputs recorded)_"


def _digests_appendix(digests: dict, priorities: list) -> str:
    """The raw exec digests, appended verbatim (revenue-first order) for auditability."""
    lines: list[str] = []
    for officer in OFFICER_ORDER:
        if officer not in digests:
            continue
        lines.append(f"### {officer.upper()} (`.tmp/{EXEC_OFFICERS[officer]}/latest.md`)")
        lines.append("")
        lines.append(digests.get(officer) or "(no digest yet)")
        lines.append("")
    return "\n".join(lines) if lines else "_(no exec digests available)_"


# --- Graph wiring ------------------------------------------------------------------------
builder = StateGraph(State)
builder.add_node("budget_gate", budget_gate)
builder.add_node("gather", gather)
builder.add_node("analyze", analyze)
builder.add_node("compose", compose)
builder.add_node("deliver", deliver)
builder.add_node("finalize", finalize)
# CLOCK-IN gate runs first: clocked out -> governance + END; otherwise enter the pipeline.
builder.add_edge(START, "budget_gate")
builder.add_conditional_edges(
    "budget_gate",
    _budget_route,
    {"gather": "gather", "clocked_out": END},
)
builder.add_edge("gather", "analyze")
builder.add_edge("analyze", "compose")
builder.add_edge("compose", "deliver")
builder.add_edge("deliver", "finalize")
builder.add_edge("finalize", END)

graph = builder.compile()  # NO checkpointer/store — injected by the platform
