"""daily_digest — the ONCE-A-DAY single pane Shay reads once a day.

This is the CLOUD ops agent that aggregates the WHOLE fleet into ONE report. It leads with
an AUTONOMY SCOREBOARD (the "when is the whole company operational 24/7?" answer) and then
walks the sections REVENUE/GROWTH FIRST, then QUALITY, then OPS, then WORKFORCE — because the
person reading it is revenue-first.

What it reads (all BEST-EFFORT / FAIL-SAFE):
  - roster.yaml via ``payroll.load_roster`` — who is staffed, statuses, salaries/spend.
  - ``docs/audit/processes.json`` — the FULL ~81-role workforce target (coverage denominator)
    (the denominator for operational coverage).
  - the other agents' local digests under ``<WORKSPACE_ROOT>/.tmp/<agent>/latest.md``
    (store-health-checker, conversion-growth-analyst, qa-first-assignment, git-sync-auditor,
    memory-sync) — a missing file is reported as "(no digest yet)", never an error.
  - ``revenuecat.metrics_overview`` — the money number (already fail-safe).
  - ``work_board.fetch_open_issues`` — to count proposals awaiting a human gate.
  - ``payroll.reconcile_with_langsmith`` — per-agent real runs/tokens (None when unavailable).
  - the prior run's scoreboard from ``<WORKSPACE_ROOT>/.tmp/daily-digest/scoreboard-history.jsonl``
    for the day-over-day delta; today's scoreboard is APPENDED as a new jsonl line.

House rules it follows (same seams as the rest of the ops fleet):
  - REPORT-ONLY on probation: delivery goes through ``file_digest_issue(..., report_only=
    _report_only())``; the default (env ``OPS_REPORT_ONLY`` truthy/unset) is True. Report-only
    NEVER contacts GitHub and NEVER enters the approval interrupt, so an unattended scheduled
    run always finishes and never hangs.
  - NEVER HANGS: there is no reachable ``request_approval``/interrupt on the scheduled path.
  - FAIL-SAFE: every RC / GitHub / LangSmith / filesystem / model call is wrapped — a missing
    key / offline backend / SDK drift returns a structured result and the run still completes.
    A telemetry/network problem never crashes a node.
  - SECRETS: env only, never logged. Error strings are type/status only.
  - ANTHROPIC-TERMS / ML boundary: ``assert_not_model_work`` guards every outward target
    string (agent names, the digest repo); gal-model / denylisted ids are skipped.
  - CLOCK-IN: ``budget_gate`` runs first; over-salary / globally-disabled => terminal report.
  - Compiles WITHOUT a checkpointer/store (the platform injects Postgres).

NOTE: this agent uses ``datetime.now()`` to stamp the scoreboard history — that is FINE in
agent code (the no-wall-clock rule is for the workflow SCRIPTS, not the agents).
"""
from __future__ import annotations

import json
import os
from datetime import datetime

from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END

from agent_toolkit import (
    span,
    governance_capture,
    assert_not_model_work,
    budget_guard,
    check_clocked_in,
    write_local_digest,
    file_digest_issue,
    TIER_DEFAULT,
)
from agent_toolkit import revenuecat, payroll, work_board
from agent_toolkit.ops_report import workspace_root
from agent_toolkit.policy import ModelWorkBlocked
from agent_toolkit import lanes

# Where the daily digest issue is filed (a no-prod-deploy, allow-listed repo).
DIGEST_REPO = "Scheduler-Systems/qa-agent-platform"

# THE WORKFORCE TARGET: the FULL audit workforce (~81 processes in docs/audit/processes.json)
# is the denominator for operational coverage — NOT the prioritized-10 subset in catalog.json.
# Read FAIL-SAFE (missing/corrupt => 0 total).
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
WORKFORCE_TARGET_PATH = os.path.join(_REPO_ROOT, "docs", "audit", "processes.json")  # the ~81

# Built-in class map (REVENUE/GROWTH FIRST, then QUALITY, then OPS, then HR). Used only when
# roster.yaml's ``org`` does not declare growth/qa/ops groups (it currently does not).
ROLE_CLASS = {
    "board": (
        "board_chair",
        "audit_risk_director",
        "growth_director",
    ),
    "executive": (
        "ceo",
        "cfo",
        "coo",
        "cto",
        "cmo",
    ),
    "growth": (
        "conversion_growth_analyst",
        "aso_store_listing_agent",
        "content_campaign_drafter",
    ),
    "qa": (
        "qa_lead_aggregator",
        "web_automation_engineer",
        "android_automation_engineer",
        "ios_automation_engineer",
        "web_manual_tester",
        "android_manual_tester",
        "ios_manual_tester",
    ),
    "ops": (
        # DEPLOYED ops graphs only — mirrors roster.yaml org.ops. git_sync_auditor / memory_sync are
        # LOCAL-ONLY launchd workers (not in langgraph.json, not on the roster), so they are excluded
        # here too — the deployed-fleet scoreboard never counts a ghost. Their LOCAL digests are
        # still stitched in via OPS_DIGESTS below (fail-safe file reads when the artifact exists).
        "revenue_reporter",
        "store_health_checker",
        "email_triage",
        "daily_digest",
    ),
    "hr": ("hr_ops_manager",),
}
# The order classes are rendered in: board leads (oversight), then executive, then revenue/growth,
# quality, ops, hr.
CLASS_ORDER = ("board", "executive", "growth", "qa", "ops", "hr")

# The per-section local digests this report stitches together (agent slug -> path segment).
# REVENUE leads, then QUALITY, then OPS.
REVENUE_DIGESTS = ("store-health-checker", "conversion-growth-analyst")
QUALITY_DIGESTS = ("qa-first-assignment",)
OPS_DIGESTS = ("git-sync-auditor", "memory-sync")

# Roster statuses that count as "active" (i.e. not on probation) for the coverage score.
_PROBATION = "probation"


def _report_only() -> bool:
    """Report-only default: env ``OPS_REPORT_ONLY`` truthy/unset => True; '0'/'false'/'no' => False.

    On probation the fleet must take NO mutating/outward action without a human gate, so the
    safe default is True. Only an explicit falsey value opts out.
    """
    return os.environ.get("OPS_REPORT_ONLY", "").lower() not in ("0", "false", "no")


# --- State -------------------------------------------------------------------------------
class State(TypedDict, total=False):
    mode: str
    scoreboard: dict        # the autonomy scoreboard (Section 0) + day-over-day delta
    revenue: dict           # revenue/growth section facts (rc + local digests)
    quality: dict           # quality section facts (local digests)
    ops: dict               # ops section facts (local digests)
    workforce: list         # per-agent workforce cards
    body: str               # the assembled markdown digest
    report: dict            # terminal verdict
    report_only: bool


# --- Catalog / history paths -------------------------------------------------------------
def _catalog_path() -> str:
    return os.environ.get("DAILY_DIGEST_CATALOG_PATH") or WORKFORCE_TARGET_PATH


def _catalog_total() -> int:
    """Count of roles in the FULL workforce target (~81) = the coverage denominator. FAIL-SAFE.

    Reads docs/audit/processes.json (a list of ~81 processes) by default. Handles both shapes:
    a JSON list (processes.json), or a dict carrying ``processes``/``prioritized_agents`` (the
    catalog.json shape, or a test fixture). Missing / unreadable / non-JSON / wrong-shape => 0
    (so a missing catalog never crashes; coverage degrades to 0% rather than raising).
    """
    try:
        with open(_catalog_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, list):                    # processes.json = the full ~81 workforce
            return sum(1 for r in data if r)
        if isinstance(data, dict):                    # catalog.json shape / test fixture
            roles = data.get("processes") or data.get("prioritized_agents") or []
            return sum(1 for r in roles if isinstance(r, dict))
        return 0
    except Exception:
        return 0


def _history_path() -> str:
    """``<WORKSPACE_ROOT>/.tmp/daily-digest/scoreboard-history.jsonl`` (same dir as latest.md)."""
    return os.path.join(workspace_root(), ".tmp", "daily-digest", "scoreboard-history.jsonl")


def _read_prior_scoreboard() -> dict:
    """Read the LAST line of the scoreboard history jsonl for the day-over-day delta. FAIL-SAFE.

    Missing file / empty / unparseable line => {} (no prior => no delta). Never raises.
    """
    try:
        path = _history_path()
        if not os.path.exists(path):
            return {}
        last = ""
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    last = line
        if not last.strip():
            return {}
        prior = json.loads(last)
        return prior if isinstance(prior, dict) else {}
    except Exception:
        return {}


def _append_scoreboard(scoreboard: dict) -> str:
    """Append today's scoreboard as one jsonl line (stamped with today's date). FAIL-SAFE.

    Returns the history path on success, "" on any error (never raises — a persistence
    failure must not crash the run).
    """
    try:
        path = _history_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        record = dict(scoreboard)
        record["date"] = datetime.now().date().isoformat()
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str) + "\n")
        return path
    except Exception:
        return ""


# --- Local digest reads ------------------------------------------------------------------
def _read_local_digest(slug: str) -> str:
    """Best-effort read of another agent's ``<WORKSPACE_ROOT>/.tmp/<slug>/latest.md``. FAIL-SAFE.

    Missing file / unreadable => "(no digest yet)" so the report is always assembled.
    """
    try:
        path = os.path.join(workspace_root(), ".tmp", slug, "latest.md")
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read().strip()
        return text or "(no digest yet)"
    except Exception:
        return "(no digest yet)"


# --- Single reconciled founder-ask count -------------------------------------------------
# The subordinate digests whose escalations the daily digest reconciles ITSELF when the board chair
# has not filed yet. Mirrors board_chair.SUBORDINATE_DIGESTS (the company synthesis inputs), read as
# the LOCAL slugs the daily digest already has fail-safe access to.
_ASK_SOURCE_SLUGS = (
    "ceo",
    "audit-risk-director",
    "growth-director",
    "daily-digest",
    "cfo",
)


def _reconciled_founder_asks(board_chair_text: str) -> int:
    """Parse the board chair's authoritative reconciled founder-ask count. FAIL-SAFE.

    The board_chair renders ``asks: N (reconciled)`` as the SINGLE company-wide count. When the
    board chair HAS filed, the daily digest defers to it rather than re-deriving its own (which is
    what produced the contradiction the founder flagged — one digest saying "no asks" while others
    said "Shay act now"). When the board chair has NOT reported yet, this returns 0; the caller
    (``compose``) then RELOCATES to computing the count itself from the subordinate reports via
    ``_reconciled_founder_asks_self`` — so the single reconciled count survives the board chair's
    offboard. NEVER raises.

    ANCHORED to the AUTHORITATIVE line. ``board_chair.compose`` PREPENDS an unconstrained model
    "chair's note" above the deterministic ``asks: N (reconciled)`` line, and routine LLM status
    prose can contain its own ``asks: <n>`` token (e.g. "decisions: 2, asks: 2 open items"). A
    greedy first-match ``asks:\\s*(\\d+)`` would grab THAT number and contradict the board chair
    (the bug the founder flagged). We therefore require the ``(reconciled)`` suffix so only the
    board chair's authoritative count is read; a stray model ``asks: N`` token is ignored.
    """
    import re
    text = board_chair_text or ""
    if not text.strip() or text.strip() == "(no digest yet)":
        return 0
    # Only the authoritative reconciled line counts — never a stray model-note "asks: N" token.
    m = re.search(r"asks:\s*(\d+)\s*\(reconciled\)", text, re.IGNORECASE)
    if m:
        try:
            return int(m.group(1))
        except (TypeError, ValueError):
            return 0
    # No authoritative reconciled count line — fall back to "no asks" rather than guess a stray
    # number (consistency over alarm).
    return 0


def _reconciled_founder_asks_self() -> int:
    """Compute the reconciled founder-ask count DIRECTLY from the subordinate digests. FAIL-SAFE.

    RELOCATED single-pane survival: when the board chair has NOT filed an authoritative
    ``asks: N (reconciled)`` line, the daily digest reconciles the founder asks ITSELF using the
    SHARED ``lanes.reconcile_founder_asks`` (the SAME algorithm the board chair uses — DRY), reading
    each subordinate's LOCAL digest. So the single reconciled count is still produced even with the
    board chair absent — it no longer DEPENDS on the board chair agent. NEVER raises (each read is
    already fail-safe; a missing digest is "(no digest yet)" and contributes no ask)."""
    try:
        reports = {slug: _read_local_digest(slug) for slug in _ASK_SOURCE_SLUGS}
        return lanes.reconciled_founder_ask_count(reports, order=_ASK_SOURCE_SLUGS)
    except Exception:
        return 0


# --- Pending approvals (fail-safe) -------------------------------------------------------
def _pending_approvals() -> dict:
    """Count open issues labelled ``gate:human-required`` = proposals awaiting a human. FAIL-SAFE.

    ``work_board.fetch_open_issues`` shells out to ``gh`` (which may be absent / unauth'd in
    the cloud). On ANY error we degrade to ``{"count": 0, "note": "unavailable"}`` so the
    scoreboard is always producible and the node never crashes.
    """
    try:
        items = work_board.fetch_open_issues()
    except Exception:
        return {"count": 0, "note": "unavailable"}
    try:
        count = 0
        for it in items or []:
            labels = {str(l).lower() for l in (getattr(it, "labels", ()) or ())}
            if "gate:human-required" in labels:
                count += 1
        return {"count": count, "note": None}
    except Exception:
        return {"count": 0, "note": "unavailable"}


# --- Class grouping ----------------------------------------------------------------------
def _class_map(roster: dict) -> dict:
    """Class -> list of role names. Prefer roster.yaml ``org`` growth/qa/ops groups; else the
    built-in ROLE_CLASS fallback.

    The current roster ``org`` only declares hr/team_lead/workers (no growth/qa/ops keys), so
    in practice this returns the built-in map — but if the orchestrator later adds explicit
    growth/qa/ops groups to ``org`` we honor them.
    """
    org = (roster or {}).get("org", {}) or {}
    if any(k in org for k in ("growth", "qa", "ops")):
        mapping: dict = {}
        for cls in CLASS_ORDER:
            group = org.get(cls)
            if isinstance(group, (list, tuple)):
                mapping[cls] = [str(x) for x in group]
            elif isinstance(group, str) and group:
                mapping[cls] = [group]
        # Carry through any built-in classes the org omitted so nothing is dropped.
        for cls in CLASS_ORDER:
            mapping.setdefault(cls, list(ROLE_CLASS.get(cls, ())))
        return mapping
    return {cls: list(ROLE_CLASS.get(cls, ())) for cls in CLASS_ORDER}


# =============================================================================
# Nodes
# =============================================================================
def budget_gate(state: State) -> dict:
    """CLOCK-IN gate — STOP before any work if over salary or globally disabled.

    Runs FIRST. Clocked in => proceed; clocked out => terminal report + governance, no reads,
    no model spend, no writes.
    """
    with span("daily_digest.budget_gate"):
        if check_clocked_in("daily_digest"):
            return {}
        report = {
            "status": "skipped",
            "detail": "daily_digest over token salary or globally disabled",
            "report_only": True,
        }
        governance_capture(
            "daily_digest",
            {"clocked_in": False, "report_only": True, "report": report},
        )
        return {"report": report, "report_only": True}


def scoreboard(state: State) -> dict:
    """Section 0 — compute the AUTONOMY SCOREBOARD + the day-over-day delta. FAIL-SAFE.

    OPERATIONAL COVERAGE (the 24/7 metric) is the single number that trends to 100% when the
    whole company is staffed AND operational:

        coverage = staffed_and_active / total_catalog_roles

    where ``staffed`` = number of agents in roster.yaml, ``staffed_and_active`` = roster
    agents whose status is NOT probation, and ``total_catalog_roles`` = the prioritized roles
    in the audit catalog (the full ~81-role workforce target). A coverage of 100% means every
    targeted role is staffed by a non-probation (operational) agent.

    Also computes per-class output (LangSmith runs/tokens summed via fail-safe reconciliation)
    grouped REVENUE/GROWTH FIRST, then QUALITY, then OPS, then HR; and the count of proposals
    pending a human gate. Reads the prior run's scoreboard for ▲/▼ deltas.
    """
    with span("daily_digest.scoreboard"):
        total = _catalog_total()

        try:
            roster = payroll.load_roster()
        except Exception:
            roster = {"agents": {}, "org": {}, "policy": {}}
        agents = roster.get("agents", {}) or {}

        staffed = 0
        active = 0
        probation = 0
        for name, record in agents.items():
            try:
                assert_not_model_work(name)  # never count a model-dev role
            except ModelWorkBlocked:
                continue
            staffed += 1
            status = str((record or {}).get("status") or "").strip().lower()
            if status == _PROBATION:
                probation += 1
            else:
                active += 1

        coverage = round(active / total, 4) if total else 0.0
        staffed_pct = round(staffed / total, 4) if total else 0.0

        # Per-class output: sum LangSmith runs/tokens (fail-safe None) grouped by class, in
        # the revenue-first CLASS_ORDER.
        class_map = _class_map(roster)
        per_class: dict = {}
        for cls in CLASS_ORDER:
            roles = class_map.get(cls, []) or []
            staffed_in_class = [r for r in roles if r in agents]
            runs = 0
            tokens = 0
            for role in staffed_in_class:
                ls = payroll.reconcile_with_langsmith(role)  # None when unavailable
                if isinstance(ls, dict):
                    runs += int(ls.get("run_count") or 0)
                    tokens += int(ls.get("total_tokens") or 0)
            per_class[cls] = {
                "roles": list(roles),
                "staffed": len(staffed_in_class),
                "runs": runs,
                "tokens": tokens,
            }

        pending = _pending_approvals()

        sb = {
            "staffed": staffed,
            "total": total,
            "staffed_pct": staffed_pct,
            "active": active,
            "probation": probation,
            "coverage": coverage,
            "pending_approvals": pending,
            "per_class": per_class,
        }

        prior = _read_prior_scoreboard()
        sb["delta"] = {
            "staffed": staffed - int(prior.get("staffed") or 0),
            "active": active - int(prior.get("active") or 0),
            "coverage": round(coverage - float(prior.get("coverage") or 0.0), 4),
            "had_prior": bool(prior),
        }
        return {"scoreboard": sb}


def gather(state: State) -> dict:
    """Collect the REVENUE / QUALITY / OPS / WORKFORCE section facts. Every read FAIL-SAFE.

    - revenue : ``revenuecat.metrics_overview`` (already fail-safe) + the store-health and
                conversion-growth local digests.
    - quality : the qa-first-assignment local digest.
    - ops     : the git-sync-auditor + memory-sync local digests.
    - workforce: per-agent card (status, salary/spent/remaining via payroll, LangSmith recon,
                roster scorecard). A missing/unparseable roster degrades to an empty list.
    """
    with span("daily_digest.gather"):
        # 1) REVENUE — the money number first, then the revenue-area digests.
        rc = revenuecat.metrics_overview()
        revenue = {
            "rc": rc,
            "digests": {slug: _read_local_digest(slug) for slug in REVENUE_DIGESTS},
        }

        # 2) QUALITY.
        quality = {"digests": {slug: _read_local_digest(slug) for slug in QUALITY_DIGESTS}}

        # 3) OPS.
        ops = {"digests": {slug: _read_local_digest(slug) for slug in OPS_DIGESTS}}

        # 4) WORKFORCE — per-agent cards (payroll math + fail-safe LangSmith recon).
        try:
            roster = payroll.load_roster()
        except Exception:
            roster = {"agents": {}}
        agents = roster.get("agents", {}) or {}
        workforce: list = []
        for name, record in agents.items():
            try:
                assert_not_model_work(name)
            except ModelWorkBlocked:
                continue
            record = record or {}
            try:
                sal = payroll.salary(name, roster=roster)
                sp = payroll.spent(name)
                rem = payroll.remaining(name, roster=roster)
            except Exception:
                sal, sp, rem = 0, 0, 0
            workforce.append(
                {
                    "agent": name,
                    "role": record.get("role"),
                    "status": record.get("status") or "unknown",
                    "salary_tokens": sal,
                    "spent_tokens": sp,
                    "remaining_tokens": rem,
                    "scorecard": record.get("scorecard", {}) or {},
                    "langsmith": payroll.reconcile_with_langsmith(name),  # None when unavailable
                }
            )

        return {"revenue": revenue, "quality": quality, "ops": ops, "workforce": workforce}


def compose(state: State) -> dict:
    """Assemble ONE markdown body: SCOREBOARD FIRST, then REVENUE, QUALITY, OPS, WORKFORCE.

    The body is built deterministically from the gathered facts so it is ALWAYS produced. An
    optional budget-metered model adds a one-paragraph narrative at the top; on ANY model
    failure (no key, budget, SDK drift) we keep the deterministic body unchanged — never empty.
    """
    sb = state.get("scoreboard") or {}
    revenue = state.get("revenue") or {}
    quality = state.get("quality") or {}
    ops = state.get("ops") or {}
    workforce = state.get("workforce") or []

    with span("daily_digest.compose", coverage=sb.get("coverage")):
        body = _render_body(sb, revenue, quality, ops, workforce)

        # SINGLE COMPANY SYNTHESIS: there is exactly ONE authoritative reconciled founder-ask count.
        # PREFERENCE ORDER (step-3 relocation — survive the board chair's offboard):
        #   1. When the board chair HAS filed, DEFER to its authoritative "asks: N (reconciled)"
        #      line (it owns the synthesis while it exists) — the company view stays CONSISTENT, no
        #      contradiction between "no asks" and "Shay act now" across the embedded sections.
        #   2. When the board chair has NOT filed, the daily digest RECONCILES the count ITSELF from
        #      the subordinate digests via the SHARED lanes algorithm — so the single reconciled
        #      count is still produced (the single pane no longer DEPENDS on the board chair agent).
        board_chair_text = _read_local_digest("board-chair")
        board_present = board_chair_text.strip() not in ("", "(no digest yet)")
        if board_present:
            asks_n = _reconciled_founder_asks(board_chair_text)
            asks_provenance = "owned by the board chair; individual exec reports feed it"
        else:
            asks_n = _reconciled_founder_asks_self()
            asks_provenance = (
                "reconciled by the daily digest from the exec/board reports "
                "(board-chair digest absent)"
            )
        asks_line = (
            f"## 📨 FOUNDER ASKS (single reconciled count): {asks_n}"
            + ("" if asks_n else " — none; everything resolved org-internal this cadence")
            + f"\n_(authoritative — {asks_provenance}; "
            "they do not each duplicate the company-wide ask count)_\n"
        )

        # BOARD INVESTOR-UPDATE leads the digest (oversight → Shay the investor). Consume the
        # board chair's update + the CEO synthesis read-only ("(no digest yet)" until produced).
        board_lead = (
            "# 🏛️ BOARD → INVESTOR UPDATE\n\n"
            + asks_line
            + "\n"
            + board_chair_text
            + "\n\n## 🧭 CEO synthesis\n\n"
            + _read_local_digest("ceo")
            + "\n\n---\n"
        )

        # Optional model narrative — fail-safe, phrasing only (no train/eval/distill).
        narrative = ""
        try:
            model = budget_guard("daily_digest", TIER_DEFAULT)
            prompt = (
                "You are the fleet's daily-digest writer for a revenue-first founder. In 2-3 "
                "sentences, summarize the autonomy scoreboard below: how close the company is "
                "to fully operational (coverage), what moved day-over-day, and the single most "
                "important revenue/ops signal. Be factual; do NOT invent numbers.\n\n"
                f"Scoreboard: {json.dumps(sb, default=str)[:3000]}\n"
            )
            resp = model.invoke(prompt)
            content = getattr(resp, "content", str(resp)) or ""
            narrative = content.strip()
        except Exception as exc:  # model/key unavailable — deterministic body stands
            narrative = f"_(model narrative unavailable: {type(exc).__name__})_"

        if narrative:
            body = f"{narrative}\n\n{body}"
        body = f"{board_lead}\n{body}"   # board investor-update is the TOP layer
        return {"body": body}


def persist(state: State) -> dict:
    """Append today's scoreboard to the history jsonl (for tomorrow's delta). FAIL-SAFE."""
    sb = state.get("scoreboard") or {}
    with span("daily_digest.persist"):
        path = _append_scoreboard(sb)
        return {"report": {"history": path}}


def deliver(state: State) -> dict:
    """Write the local digest + file the daily digest issue (report-only on probation). FAIL-SAFE.

    ``write_local_digest`` always runs (succeeds-or-"" ; never raises). ``file_digest_issue(...,
    report_only=_report_only())`` delivers the issue — on probation (the default) it returns an
    honest report-only plan dict with NO GitHub call and NO approval interrupt, so an unattended
    run can never hang or write.
    """
    body = state.get("body") or "(empty digest)"
    prior = state.get("report") if isinstance(state.get("report"), dict) else {}
    report_only = _report_only()

    with span("daily_digest.deliver", report_only=report_only):
        assert_not_model_work(DIGEST_REPO)  # never file into a model-dev repo

        digest_path = write_local_digest("daily-digest", "Daily fleet digest", body)

        res = file_digest_issue(
            DIGEST_REPO,
            "Daily fleet digest",
            body,
            labels=["digest:daily"],
            report_only=report_only,
            agent="daily_digest",
            slack_title="📅 Daily Fleet Digest",
        )
        delivery = res.get("status") if isinstance(res, dict) else None

        return {
            "report": {
                "delivery": delivery,
                "digest": digest_path,
                "history": prior.get("history"),
                "report_only": report_only,
                "slack": res.get("slack"),
            },
            "report_only": report_only,
        }


def finalize(state: State) -> dict:
    """Terminal node — capture governance (report_only=True) and emit the final report."""
    sb = state.get("scoreboard") or {}
    prior = state.get("report") if isinstance(state.get("report"), dict) else {}

    with span("daily_digest.finalize", coverage=sb.get("coverage")):
        governance_capture(
            "daily_digest",
            {
                "staffed": sb.get("staffed"),
                "total": sb.get("total"),
                "active": sb.get("active"),
                "coverage": sb.get("coverage"),
                "delivery": prior.get("delivery"),
                "report_only": True,
            },
        )
        return {
            "report": {
                "staffed": sb.get("staffed"),
                "total": sb.get("total"),
                "active": sb.get("active"),
                "coverage": sb.get("coverage"),
                "delivery": prior.get("delivery"),
                "digest": prior.get("digest"),
                "history": prior.get("history"),
                "report_only": True,
            }
        }


# =============================================================================
# Render helpers (deterministic, no model)
# =============================================================================
def _arrow(delta) -> str:
    try:
        d = float(delta)
    except (TypeError, ValueError):
        return ""
    if d > 0:
        return f" ▲{d:g}"
    if d < 0:
        return f" ▼{abs(d):g}"
    return " ="


def _pct(value) -> str:
    try:
        return f"{float(value) * 100:.0f}%"
    except (TypeError, ValueError):
        return "0%"


def _render_scoreboard(sb: dict) -> list:
    total = sb.get("total") or 0
    staffed = sb.get("staffed") or 0
    active = sb.get("active") or 0
    probation = sb.get("probation") or 0
    coverage = sb.get("coverage") or 0.0
    delta = sb.get("delta") or {}
    pending = sb.get("pending_approvals") or {}
    per_class = sb.get("per_class") or {}

    lines = [
        "## 🤖 AUTONOMY SCOREBOARD",
        "",
        f"- **STAFFED {staffed} / {total} ({_pct(sb.get('staffed_pct'))})**"
        + (_arrow(delta.get("staffed")) if delta.get("had_prior") else ""),
        f"- **OPERATIONAL COVERAGE: {_pct(coverage)}** "
        f"(active {active} / {total} catalog roles → 100% = fully operational 24/7)"
        + (_arrow(delta.get("coverage")) if delta.get("had_prior") else ""),
        f"- active: {active}"
        + (_arrow(delta.get("active")) if delta.get("had_prior") else "")
        + f" · probation: {probation}",
    ]
    if pending.get("note") == "unavailable":
        lines.append("- proposals pending approval: unavailable (gh not reachable)")
    else:
        lines.append(f"- proposals pending approval (gate:human-required): {pending.get('count', 0)}")
    if not delta.get("had_prior"):
        lines.append("- _(no prior scoreboard — day-over-day delta starts next run)_")

    lines += ["", "### Per-class output (revenue/growth → quality → ops)"]
    for cls in CLASS_ORDER:
        data = per_class.get(cls) or {}
        lines.append(
            f"- **{cls}**: staffed {data.get('staffed', 0)}/{len(data.get('roles', []) or [])} "
            f"· LangSmith runs={data.get('runs', 0)} tokens={data.get('tokens', 0)}"
        )
    return lines


def _render_rc(rc: dict) -> list:
    if not rc.get("ok"):
        return [f"- RevenueCat: unavailable ({rc.get('error') or 'no metrics'})"]
    metrics = rc.get("metrics") or {}
    if not metrics:
        return ["- RevenueCat: ok, but no metrics returned"]
    return ["- RevenueCat metrics:"] + [
        f"    - {key}: {value}" for key, value in sorted(metrics.items())
    ]


def _render_digest_block(title: str, slug: str, text: str) -> list:
    return [f"### {title} (`.tmp/{slug}/latest.md`)", "", text or "(no digest yet)", ""]


def _render_workforce(workforce: list) -> list:
    lines = ["## 👥 WORKFORCE", ""]
    if not workforce:
        lines.append("_(no roster agents)_")
        return lines
    for card in workforce:
        ls = card.get("langsmith")
        ls_note = (
            f"runs={ls.get('run_count')} tokens={ls.get('total_tokens')}"
            if isinstance(ls, dict)
            else "no LangSmith data"
        )
        sc = card.get("scorecard") or {}
        sc_note = ", ".join(f"{k}={v}" for k, v in sorted(sc.items())) or "no scorecard"
        lines.append(
            f"- **{card.get('agent')}** [{card.get('status')}] — "
            f"salary={card.get('salary_tokens')} spent={card.get('spent_tokens')} "
            f"remaining={card.get('remaining_tokens')} · {ls_note} · {sc_note}"
        )
    return lines


def _render_body(sb: dict, revenue: dict, quality: dict, ops: dict, workforce: list) -> str:
    rc = (revenue or {}).get("rc") or {}
    rev_digests = (revenue or {}).get("digests") or {}
    qual_digests = (quality or {}).get("digests") or {}
    ops_digests = (ops or {}).get("digests") or {}

    lines = ["# Daily fleet digest", ""]

    # Section 0 — the scoreboard LEADS.
    lines += _render_scoreboard(sb)

    # 1) REVENUE — leads the content sections.
    lines += ["", "## 💰 REVENUE / GROWTH", ""]
    lines += _render_rc(rc)
    lines.append("")
    for slug in REVENUE_DIGESTS:
        lines += _render_digest_block(slug, slug, rev_digests.get(slug, "(no digest yet)"))

    # 2) QUALITY.
    lines += ["## 🧪 QUALITY", ""]
    for slug in QUALITY_DIGESTS:
        lines += _render_digest_block(slug, slug, qual_digests.get(slug, "(no digest yet)"))

    # 3) OPS.
    lines += ["## 🛠️ OPS", ""]
    for slug in OPS_DIGESTS:
        lines += _render_digest_block(slug, slug, ops_digests.get(slug, "(no digest yet)"))

    # 4) WORKFORCE.
    lines += _render_workforce(workforce)

    return "\n".join(lines)


# =============================================================================
# Routing
# =============================================================================
def _budget_route(state: State) -> str:
    """Clocked in -> start the scoreboard; clocked out -> END (terminal report already set)."""
    return "scoreboard" if check_clocked_in("daily_digest") else "clocked_out"


# =============================================================================
# Graph wiring
# =============================================================================
builder = StateGraph(State)
builder.add_node("budget_gate", budget_gate)
builder.add_node("scoreboard", scoreboard)
builder.add_node("gather", gather)
builder.add_node("compose", compose)
builder.add_node("persist", persist)
builder.add_node("deliver", deliver)
builder.add_node("finalize", finalize)

builder.add_edge(START, "budget_gate")
builder.add_conditional_edges(
    "budget_gate",
    _budget_route,
    {"scoreboard": "scoreboard", "clocked_out": END},
)
builder.add_edge("scoreboard", "gather")
builder.add_edge("gather", "compose")
builder.add_edge("compose", "persist")
builder.add_edge("persist", "deliver")
builder.add_edge("deliver", "finalize")
builder.add_edge("finalize", END)

graph = builder.compile()  # NO checkpointer/store — injected by the platform
