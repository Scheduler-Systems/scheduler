"""content_campaign_drafter — CLOUD growth agent that DRAFTS content + campaigns.

Runtime: cloud/CI (LangGraph Platform managed Cloud SaaS); register-able in
``langgraph.json`` (the orchestrator owns that file — not this module). REVENUE-generating
growth role.

MISSION: draft content + campaigns (email / social / blog) aligned to the Scheduler
repositioning — reposition the mispositioned "to-do" listing to **B2B shift scheduling for
SMB teams**. The output is DRAFTS ONLY, for human review. This agent NEVER sends anything:
there is no Brevo / social / email send path in this module — pushing a campaign live is a
human action. The only outward delivery is a report-only digest issue (no GitHub write, no
approval interrupt on the scheduled path).

LOAD-BEARING DECISIONS (match the ops-fleet house style — see revenue_reporter,
store_health_checker, hr_ops_manager):

  * NO SEND PATH. This module imports NO email/social send client and calls NO send/publish
    API. The drafts are delivered only as a local digest + a report-only ``file_digest_issue``.
    Pushing copy live is a human action taken outside this agent.

  * PROBATION / REPORT-ONLY by default. The digest is delivered via
    ``file_digest_issue(..., report_only=_report_only())`` where ``_report_only()`` defaults
    True (env ``OPS_REPORT_ONLY``; only "0"/"false"/"no" turns it off). On probation the
    delivery is an honest ``{"status": "report_only", ...}`` plan dict — NO GitHub write and,
    critically, NO approval interrupt — so a scheduled unattended run can never hang or write.

  * DO-NOT-CLAIM GUARDRAIL. Every drafted string is run through a ``compliance_scan`` against
    the ``do_not_claim`` list from ``docs/growth/scheduler_positioning.json`` (time tracking /
    AI scheduling / clock-in-out / offline — features Scheduler does NOT ship). Flagged drafts
    are surfaced to the human reviewer (the directory submission already over-claimed those).

  * FAIL-SAFE. The positioning read, the model draft, the digest write, and the GitHub call
    are each wrapped so a missing key / offline / SDK drift returns a structured result and the
    run still completes. A telemetry/network problem never crashes a node. On ANY model failure
    we fall back to a DETERMINISTIC draft built from the positioning facts (never empty).

  * SECRETS: env only, never logged. Error strings are type/status only (no bodies/keys).

  * ANTHROPIC-TERMS / ML BOUNDARY. ``assert_not_model_work`` guards the outward digest repo
    (defensive); no model train/eval/distill — phrasing only. gal-model / the policy denylist
    are never read or reported.

  * CLOCK-IN: ``budget_gate`` runs first; over-salary / globally-disabled => terminal report.
  * Compiles WITHOUT a checkpointer/store (the platform injects Postgres). Every node body is
    wrapped in ``span("content_campaign_drafter.<node>", ...)``; governance is captured at the
    end with ``report_only: True``.
"""
from __future__ import annotations

import json
import os

from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END

from agent_toolkit import (
    budget_guard,
    check_clocked_in,
    span,
    governance_capture,
    assert_not_model_work,
    write_local_digest,
    file_digest_issue,
    TIER_DEFAULT,
)

# The repo the campaign-content digest issue is filed into (allow-listed in github_ops).
DIGEST_REPO = "Scheduler-Systems/qa-agent-platform"

# Declared, VERIFIED product facts the drafts are anchored to (the orchestrator owns it).
# Read FAIL-SAFE — a missing/corrupt file degrades to a safe built-in default.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DEFAULT_POSITIONING_PATH = os.path.join(
    _REPO_ROOT, "docs", "growth", "scheduler_positioning.json"
)

# The default campaign brief when neither state.brief nor env CONTENT_BRIEF is set.
DEFAULT_BRIEF = "Reposition Scheduler to B2B shift scheduling for SMB teams"

# Conservative built-in do_not_claim fallback (used only if positioning can't be read), so the
# compliance scan is NEVER toothless even with zero files.
_DEFAULT_DO_NOT_CLAIM = ["time tracking", "ai scheduling", "clock-in/out", "offline"]


def _report_only() -> bool:
    """Report-only default for the probation agent: truthy/unset env => True.

    Only an explicit ``OPS_REPORT_ONLY`` of "0"/"false"/"no" turns delivery into a real
    (gated) GitHub write. Everything else — including the env being unset — keeps the agent in
    honest report-only mode (no GitHub call, no approval interrupt). Drafts only.
    """
    return os.environ.get("OPS_REPORT_ONLY", "").lower() not in ("0", "false", "no")


def _positioning_path() -> str:
    return os.environ.get("SCHEDULER_POSITIONING_PATH") or DEFAULT_POSITIONING_PATH


class State(TypedDict, total=False):
    brief: str           # optional campaign brief override (else env CONTENT_BRIEF / default)
    positioning: dict    # the loaded positioning facts (fail-safe)
    content: dict        # drafted {email_subject, email_body, social_posts, blog_outline}
    compliance: dict     # {flags: [...], clean: bool} from the do_not_claim scan
    summary: str         # short reviewer-facing summary
    report: dict         # terminal verdict
    report_only: bool    # whether delivery stayed report-only


# --- Positioning (FAIL-SAFE read) --------------------------------------------------------
def _load_positioning() -> dict:
    """Read the declared positioning facts. FAIL-SAFE — never raises.

    Returns the parsed JSON dict on success, or ``{}`` (missing / unreadable / non-JSON).
    """
    try:
        with open(_positioning_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:  # missing / unreadable / non-JSON — degrade to empty
        return {}


def _do_not_claim(positioning: dict) -> list[str]:
    """The do_not_claim terms from positioning (fail-safe), or a conservative default."""
    product = positioning.get("product") if isinstance(positioning, dict) else {}
    terms = (product or {}).get("do_not_claim") if isinstance(product, dict) else None
    if isinstance(terms, list) and terms:
        return [str(t).strip() for t in terms if str(t).strip()]
    return list(_DEFAULT_DO_NOT_CLAIM)


def _ships(positioning: dict) -> list[str]:
    product = positioning.get("product") if isinstance(positioning, dict) else {}
    ships = (product or {}).get("ships") if isinstance(product, dict) else None
    return [str(s) for s in ships] if isinstance(ships, list) else []


def _what_it_is(positioning: dict) -> str:
    product = positioning.get("product") if isinstance(positioning, dict) else {}
    what = (product or {}).get("what_it_is") if isinstance(product, dict) else None
    return str(what) if what else "B2B shift scheduling for small businesses"


# --- Nodes -------------------------------------------------------------------------------
def budget_gate(state: State) -> dict:
    """CLOCK-IN gate — STOP before any work if over salary or globally disabled.

    Runs FIRST. Clocked in => proceed; clocked out => terminal report + governance
    (report-only), no positioning read, no model spend, no writes.
    """
    with span("content_campaign_drafter.budget_gate"):
        if check_clocked_in("content_campaign_drafter"):
            return {}
        report = {
            "delivery": "skipped",
            "detail": "content_campaign_drafter over token salary or globally disabled",
            "report_only": True,
        }
        governance_capture(
            "content_campaign_drafter",
            {"clocked_in": False, "delivery": "skipped", "report_only": True},
        )
        return {"report": report, "report_only": True}


def gather(state: State) -> dict:
    """Load the positioning facts + resolve the campaign brief. FAIL-SAFE.

    brief precedence: ``state.brief`` -> env ``CONTENT_BRIEF`` -> ``DEFAULT_BRIEF``.
    Positioning is read fail-safe (empty dict on any error) so drafting still runs.
    """
    brief = (state.get("brief") or os.environ.get("CONTENT_BRIEF") or DEFAULT_BRIEF).strip()
    with span("content_campaign_drafter.gather", brief_len=len(brief)):
        positioning = _load_positioning()
        return {"positioning": positioning, "brief": brief}


def draft_content(state: State) -> dict:
    """Draft email / social / blog content from the brief + positioning facts. FAIL-SAFE.

    The model (TIER_DEFAULT, metered via ``budget_guard``) drafts a JSON object
    ``{email_subject, email_body, social_posts:[...], blog_outline}``. On ANY failure
    (no key, budget, SDK drift, malformed output) we fall back to a DETERMINISTIC draft
    built directly from the positioning facts, so a draft is always produced (never empty).
    Phrasing only — no model train/eval/distill.
    """
    positioning = state.get("positioning") or {}
    brief = (state.get("brief") or DEFAULT_BRIEF).strip()

    with span("content_campaign_drafter.draft_content", brief_len=len(brief)):
        deterministic = _deterministic_content(brief, positioning)
        content = deterministic
        try:
            model = budget_guard("content_campaign_drafter", TIER_DEFAULT)
            prompt = (
                "You are the content + campaign drafter for the Scheduler product. Draft "
                "marketing content aligned to the repositioning brief below. Scheduler is "
                f"{_what_it_is(positioning)}. It SHIPS: {', '.join(_ships(positioning)) or 'n/a'}. "
                "CRITICAL: do NOT claim any feature Scheduler does not ship — specifically do "
                f"NOT mention: {', '.join(_do_not_claim(positioning))}. These are DRAFTS for a "
                "human reviewer; do not invent metrics or features.\n\n"
                f"BRIEF: {brief}\n\n"
                "Return ONLY a JSON object with keys: "
                '"email_subject" (string), "email_body" (string), '
                '"social_posts" (array of short strings), "blog_outline" (string). '
                "No prose, no code fences."
            )
            resp = model.invoke(prompt)
            raw = getattr(resp, "content", str(resp)) or ""
            parsed = _parse_json_object(raw)
            normalized = _normalize_content(parsed)
            if normalized:
                content = normalized
        except Exception as exc:  # model unavailable — deterministic fallback (never empty)
            content = dict(deterministic)
            content["_note"] = f"model draft unavailable: {type(exc).__name__}"

        return {"content": content}


def compliance_scan(state: State) -> dict:
    """Scan every drafted string against the do_not_claim list. FAIL-SAFE.

    A drafted string that mentions a forbidden term (time tracking / AI scheduling /
    clock-in-out / offline) is flagged for the human reviewer. ``clean`` is True only when
    NO draft trips the guardrail. This NEVER raises and never mutates the drafts — it only
    surfaces what a reviewer must check.
    """
    content = state.get("content") or {}
    positioning = state.get("positioning") or {}

    with span("content_campaign_drafter.compliance_scan"):
        terms = _do_not_claim(positioning)
        flags: list[dict] = []
        for field, text in _content_strings(content):
            low = (text or "").lower()
            for term in terms:
                t = term.strip().lower()
                if t and t in low:
                    flags.append({
                        "field": field,
                        "term": term,
                        "detail": f"draft '{field}' mentions do-not-claim term '{term}'",
                    })
        return {"compliance": {"flags": flags, "clean": not flags}}


def deliver(state: State) -> dict:
    """Write the local digest + file the campaign-content digest issue (report-only). FAIL-SAFE.

    There is NO send path: the drafts go out only as a local artifact + a report-only GitHub
    digest. ``write_local_digest`` always runs (succeeds-or-"" ; never raises).
    ``file_digest_issue(..., report_only=_report_only())`` delivers the issue — on probation
    (the default) it returns an honest report-only plan dict with NO GitHub call and NO
    approval interrupt, so an unattended run can never hang or send.
    """
    content = state.get("content") or {}
    compliance = state.get("compliance") or {"flags": [], "clean": True}
    brief = (state.get("brief") or DEFAULT_BRIEF).strip()
    report_only = _report_only()

    with span("content_campaign_drafter.deliver", report_only=report_only,
              clean=bool(compliance.get("clean"))):
        # Defensive Anthropic-terms guard on the only outward target (the digest repo).
        assert_not_model_work(DIGEST_REPO)

        summary = _summary(brief, content, compliance)
        body = _render_body(brief, content, compliance, summary)

        # Local artifact first — always, fail-safe.
        digest_path = write_local_digest(
            "content-campaign-drafter", "Campaign content (draft)", body
        )

        labels = ["growth:content"]
        if not compliance.get("clean"):
            labels.append("gate:human-required")  # a flagged draft needs a human

        res = file_digest_issue(
            DIGEST_REPO,
            "Campaign content (draft)",
            body,
            labels=labels,
            report_only=report_only,
            agent="content_campaign_drafter",
        )
        delivery = res.get("status") if isinstance(res, dict) else None
        return {
            "summary": summary,
            "report": {
                "delivery": delivery,
                "digest": digest_path,
                "clean": bool(compliance.get("clean")),
                "flags": len(compliance.get("flags") or []),
                "report_only": report_only,
            },
            "report_only": report_only,
        }


def finalize(state: State) -> dict:
    """Terminal node — capture governance (report_only=True) and emit the final report."""
    compliance = state.get("compliance") or {"flags": [], "clean": True}
    prior = state.get("report") if isinstance(state.get("report"), dict) else {}
    n_flags = len(compliance.get("flags") or [])

    with span("content_campaign_drafter.finalize", flags=n_flags):
        governance_capture(
            "content_campaign_drafter",
            {
                "delivery": prior.get("delivery"),
                "clean": bool(compliance.get("clean")),
                "n_flags": n_flags,
                "report_only": True,
            },
        )
        report = {
            "delivery": prior.get("delivery"),
            "digest": prior.get("digest"),
            "clean": bool(compliance.get("clean")),
            "n_flags": n_flags,
            "report_only": True,
        }
        return {"report": report}


# --- Deterministic draft + helpers -------------------------------------------------------
def _deterministic_content(brief: str, positioning: dict) -> dict:
    """A complete, on-message draft built ENTIRELY from the brief + positioning (no model).

    Stays inside the do_not_claim guardrail by construction (it only mentions shipped
    features), so the deterministic fallback is always compliance-clean.
    """
    what_it_is = _what_it_is(positioning)
    ships = _ships(positioning)
    ships_line = ", ".join(ships) if ships else "shift scheduling for small teams"

    email_subject = "Stop wrangling shifts — schedule your team in one click"
    email_body = (
        f"Scheduler is {what_it_is}.\n\n"
        f"{brief}.\n\n"
        f"What you get: {ships_line}.\n\n"
        "Build next week's roster in a click, share it with your team, and export to CSV. "
        "Reply to this email if you'd like a walkthrough."
    )
    social_posts = [
        f"Scheduler: {what_it_is}. One-click rosters, team chat, CSV export.",
        f"{brief}. Spend minutes, not hours, on next week's shifts.",
        "Built next week's schedule in one click and shared it with the whole team.",
    ]
    blog_outline = (
        "# Reposition Scheduler for SMB shift scheduling\n"
        f"1. The problem: {brief}.\n"
        "2. Who it's for: small businesses (~10-100 employees) running shift teams.\n"
        f"3. What ships today: {ships_line}.\n"
        "4. The one-click roster builder walkthrough.\n"
        "5. Pricing (per-user) and how to get started.\n"
    )
    return {
        "email_subject": email_subject,
        "email_body": email_body,
        "social_posts": social_posts,
        "blog_outline": blog_outline,
    }


def _normalize_content(parsed) -> dict:
    """Coerce a parsed model object into the expected content shape. ``{}`` if unusable.

    Accepts only a dict with at least one expected key; missing keys default to safe empties
    and ``social_posts`` is coerced to a list of strings. Returns ``{}`` (=> use the
    deterministic fallback) when the model output is unusable.
    """
    if not isinstance(parsed, dict):
        return {}
    keys = ("email_subject", "email_body", "social_posts", "blog_outline")
    if not any(k in parsed for k in keys):
        return {}
    posts = parsed.get("social_posts")
    if isinstance(posts, str):
        posts = [posts]
    elif isinstance(posts, list):
        posts = [str(p) for p in posts if str(p).strip()]
    else:
        posts = []
    out = {
        "email_subject": str(parsed.get("email_subject") or ""),
        "email_body": str(parsed.get("email_body") or ""),
        "social_posts": posts,
        "blog_outline": str(parsed.get("blog_outline") or ""),
    }
    # An all-empty model object (valid shape, no usable copy) is unusable — return {} so the
    # caller keeps the DETERMINISTIC fallback. Guarantees draft_content is NEVER empty even
    # when the model echoes a hollow JSON skeleton.
    if not (out["email_subject"].strip() or out["email_body"].strip()
            or out["social_posts"] or out["blog_outline"].strip()):
        return {}
    return out


def _content_strings(content: dict):
    """Yield ``(field, text)`` for every drafted string (so the scan covers ALL of them)."""
    if not isinstance(content, dict):
        return
    yield "email_subject", str(content.get("email_subject") or "")
    yield "email_body", str(content.get("email_body") or "")
    yield "blog_outline", str(content.get("blog_outline") or "")
    posts = content.get("social_posts")
    if isinstance(posts, list):
        for i, post in enumerate(posts):
            yield f"social_posts[{i}]", str(post or "")


def _parse_json_object(text: str):
    """Best-effort parse of a JSON object from model output (tolerates code fences/prose)."""
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except Exception:
            return None
    return None


def _summary(brief: str, content: dict, compliance: dict) -> str:
    n_posts = len(content.get("social_posts") or []) if isinstance(content, dict) else 0
    n_flags = len(compliance.get("flags") or [])
    status = "CLEAN" if compliance.get("clean") else f"{n_flags} do-not-claim flag(s)"
    return (
        f"Campaign content draft for: {brief}. "
        f"Email + {n_posts} social post(s) + blog outline. Compliance: {status}. "
        "Drafts only — human review required before anything is sent."
    )


def _render_body(brief: str, content: dict, compliance: dict, summary: str) -> str:
    lines = [
        "**Status:** draft (report-only) — human review required before any send.",
        "",
        summary,
        "",
        f"## Brief\n{brief}",
        "",
        "## Email",
        f"- **Subject:** {content.get('email_subject', '')}",
        "",
        content.get("email_body", "") or "_none_",
        "",
        "## Social posts",
    ]
    posts = content.get("social_posts") or []
    if posts:
        for post in posts:
            lines.append(f"- {post}")
    else:
        lines.append("_none_")
    lines += ["", "## Blog outline", content.get("blog_outline", "") or "_none_", ""]

    flags = compliance.get("flags") or []
    lines.append(f"## Compliance scan ({len(flags)} flag(s))")
    if flags:
        for f in flags:
            lines.append(
                f"- **[do-not-claim] {f.get('term')}** in `{f.get('field')}` — {f.get('detail')}"
            )
    else:
        lines.append("_clean — no do-not-claim terms found_")

    note = content.get("_note") if isinstance(content, dict) else None
    if note:
        lines += ["", f"_({note})_"]
    return "\n".join(lines)


# --- Routing -----------------------------------------------------------------------------
def _budget_route(state: State) -> str:
    """Clocked in -> start drafting; clocked out -> END (terminal report already set)."""
    return "gather" if check_clocked_in("content_campaign_drafter") else "clocked_out"


# --- Graph wiring ------------------------------------------------------------------------
builder = StateGraph(State)
builder.add_node("budget_gate", budget_gate)
builder.add_node("gather", gather)
builder.add_node("draft_content", draft_content)
builder.add_node("compliance_scan", compliance_scan)
builder.add_node("deliver", deliver)
builder.add_node("finalize", finalize)

builder.add_edge(START, "budget_gate")
builder.add_conditional_edges(
    "budget_gate",
    _budget_route,
    {"gather": "gather", "clocked_out": END},
)
builder.add_edge("gather", "draft_content")
builder.add_edge("draft_content", "compliance_scan")
builder.add_edge("compliance_scan", "deliver")
builder.add_edge("deliver", "finalize")
builder.add_edge("finalize", END)

graph = builder.compile()  # NO checkpointer/store — injected by the platform
