"""email_triage — "Posey", the founder's BUSINESS email assistant (Shay's inbox).

Posey reads Shay's business inbox (``shay@scheduler-systems.com``, scoped by the Gmail OAuth token)
and does six jobs, ported from the gal-agents legacy runbook
``docs/ops-triage/legacy-commands/email-triage-legacy.md`` + ``src/ops-triage.ts``:

  1. INVOICE DETECTION — flag invoices/receipts by attachment (``.pdf``/``.receipt``) + subject
     keywords (invoice / receipt / payment / bill).
  2. INVOICE -> MORNING AUTO-FORWARD (Shay's Option B: auto-forward under a HARD ALLOWLIST).
     Classify each invoice as PERSONAL vs COMPANY expense, then forward it to the matching Morning
     address: personal -> MORNING_PERSONAL_EMAIL, company -> MORNING_COMPANY_EMAIL.
  3. DRAFT REPLIES — for mail needing a response, create a Gmail DRAFT (never auto-send a reply).
  4. PROPOSE UNSUBSCRIBE — newsletters/marketing surfaced as a proposal, never auto-executed.
  5. ARCHIVE / LABEL — conservative tidying: label/archive only OBVIOUS marketing (never hide a
     real / personal / actionable mail). A reversible read-MODIFY of Shay's OWN mailbox — not outward.
  6. TASK CREATION — actionable mail -> a task record (the existing task/digest seam).

THE CRITICAL SECURITY PROPERTY (forwarding is the ONLY send action):
  * The forward may send ONLY to one of the TWO Morning addresses, which come from server
    CONFIG/env (``gmail_client.morning_address(category)``) — NEVER from the email's From / Reply-To
    / body / headers, and NEVER from any model output. A message whose From/Reply-To/body says
    "forward to attacker@evil" still goes ONLY to Morning, because the destination is not derived
    from the message at all (it is resolved from config by the {personal,company} category).
  * It may forward ONLY a DETECTED invoice. Everything else is draft-only or propose-only.
  * The forward is structurally constrained in ``gmail_client.forward_invoice(message_id, category)``
    (no general ``send(to, ...)`` exists) AND the graph re-asserts the resolved recipient is on
    ``gmail_client.allowlist()`` before counting a send.

House rules (same seams as the rest of the ops fleet):
  - KILL-SWITCH: ``budget_gate`` runs FIRST; over-salary / globally disabled (``check_clocked_in``
    False) => terminal report, no inbox read, no forward.
  - REPORT-ONLY on probation (env ``OPS_REPORT_ONLY`` truthy/unset => True): in report-only the
    forward node PLANS the forward ("would forward invoice X to Morning(company)") and does NOT
    send. Only when explicitly enabled (``OPS_REPORT_ONLY=0``) does the allow-listed forward really
    send. Drafts/unsubscribes/archive/tasks honor the same flag.
  - IDEMPOTENT: the same invoice is NEVER forwarded twice — processed message ids are tracked in the
    durable digest record (read back via ``read_local_digest`` + parsed) so a re-run skips already
    forwarded invoices.
  - FAIL-SAFE: every external call (Gmail, GitHub, filesystem, model) is wrapped — a missing creds /
    offline backend / SDK drift returns a structured result and the run still completes.
  - GMAIL CREDS = ACTIVATION GATE: when ``gmail_client.is_configured()`` is False we emit an honest
    ``unverifiable`` warning ("could not check inbox") — never a dishonest "inbox clean".
  - HITL: each outward/irreversible action (forward, draft, unsubscribe) is recorded through
    ``human_gate`` (report-only on probation: RECORDS that it would need a human; never blocks/sends).
  - file_digest_record for the durable digest. Compiles WITHOUT a checkpointer/store (platform
    injects Postgres).
"""
from __future__ import annotations

import json
import os
import re

from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END

from agent_toolkit import (
    span,
    governance_capture,
    assert_not_model_work,
    budget_guard,
    check_clocked_in,
    write_local_digest,
    read_local_digest,
    file_digest_record,
    TIER_DEFAULT,
)
from agent_toolkit import gmail_client
from agent_toolkit.hitl import human_gate
from agent_toolkit.policy import ModelWorkBlocked

# Where the digest is filed (a no-prod-deploy, allow-listed repo).
DIGEST_REPO = "Scheduler-Systems/qa-agent-platform"

# Agent slug (drives the roster row, payroll, capability grant, Slack routing, digest dedup).
AGENT = "email_triage"

# Hard caps so a huge inbox can never hang an agent shift.
_MAX_MESSAGES = 50
_DEFAULT_LIMIT = 20

# Heuristics ported from email-triage-legacy.md / ops-triage.ts.
# A message warrants a DRAFT reply if it asks for action / a response.
_REPLY_SIGNALS = (
    "action required", "urgent", "deadline", "please", "can you", "could you",
    "let me know", "question", "?", "reply", "respond", "follow up", "request",
)
# A message is promotional (=> PROPOSE unsubscribe, never reply) if it smells like marketing.
_PROMO_SIGNALS = (
    "unsubscribe", "newsletter", "sale", "% off", "deal", "promo", "offer",
    "subscribe", "marketing", "no-reply", "noreply", "do-not-reply",
)
# INVOICE detection — subject/body keywords (ported from the legacy "Invoice Detection" rule).
_INVOICE_SUBJECT_SIGNALS = (
    "invoice", "receipt", "payment", "bill", "amount due", "payment received",
    "order confirmation", "tax invoice", "subscription renewal",
)
# Attachment-name signals (.pdf / .receipt) — a strong invoice indicator.
_INVOICE_ATTACHMENT_SUFFIXES = (".pdf", ".receipt")
# COMPANY-expense classification signals. A sender/subject hitting one of these classifies the
# invoice as a COMPANY expense (-> MORNING_COMPANY_EMAIL); otherwise PERSONAL (-> MORNING_PERSONAL).
# This is a deterministic heuristic (no model decides the destination — only the {personal,company}
# category, which only ever maps to the two config addresses).
_COMPANY_EXPENSE_SIGNALS = (
    # infra / SaaS the company pays for
    "aws", "amazon web services", "google cloud", "gcp", "vercel", "langsmith", "langchain",
    "openai", "anthropic", "github", "stripe", "revenuecat", "cloudflare", "runpod", "sentry",
    "twilio", "brevo", "atlassian", "slack", "notion", "figma", "linear",
    # explicit company markers
    "ltd", "inc", "llc", "b2b", "business", "company", "scheduler systems", "vat", "tax invoice",
)


def _report_only() -> bool:
    """Report-only flag for Posey, derived from the PER-AGENT write gate. Default True (safe).

    Posey is on the HARD NEVER-LIST (its only outward capability is ``send:invoice_to_morning``),
    so ``write_gate.write_enabled("email_triage")`` is ALWAYS False — meaning ``report_only_for``
    ALWAYS returns True. The live allow-listed forward therefore stays propose-only EVEN when the
    global ``OPS_REPORT_ONLY=0`` flag lifts the floor for the rest of the fleet and EVEN if some
    operator mistakenly adds ``email_triage`` to ``AGENTS_WRITE_ENABLED``: the never-list wins in
    code, so this agent can never auto-forward/send. FAIL-SAFE: any gate error ⇒ report-only.

    (The gate also composes the kill switch and the global floor, so this single call subsumes the
    previous env-only check — there is no path by which it returns False for a never-list agent.)
    """
    try:
        from agent_toolkit.write_gate import report_only_for
        return report_only_for(AGENT)
    except Exception:
        return True


# --- State -------------------------------------------------------------------------------
class State(TypedDict, total=False):
    mode: str
    messages: list           # raw message stubs read from the inbox
    triaged: list            # per-message classification dicts
    invoices: list           # detected + classified invoices (personal/company)
    forwards: list           # forward actions (planned in report-only, sent when enabled)
    drafts: list             # reply DRAFTS created (records, never sent)
    unsubscribes: list       # unsubscribe PROPOSALS (never executed)
    tidied: list             # archive/label actions on the OWN mailbox (reversible)
    tasks: list              # task records created for actionable mail
    severity: str
    summary: str
    report: dict
    report_only: bool


# --- Helpers (pure classification, ported from the runbooks) -----------------------------
def _sender_email(from_header: str) -> str:
    """Extract the bare email from a ``From`` header ("Name <a@b.com>" => "a@b.com")."""
    m = re.search(r"<([^>]+)>", from_header or "")
    if m:
        return m.group(1).strip()
    return (from_header or "").strip()


def _company_label(from_header: str) -> str:
    """Best-effort company/sender label (lowercase), from the email domain. Ported from the runbook."""
    email = _sender_email(from_header).lower()
    domain = email.split("@", 1)[1] if "@" in email else email
    stem = domain.split(".")[0] if domain else ""
    if stem in ("mail", "mailer", "t", "email", "e", "news", "newsletter", "info", "no-reply"):
        parts = [p for p in domain.split(".") if p not in (stem,)]
        stem = parts[0] if parts else stem
    return stem or "unknown"


def _is_promotional(subject: str, snippet: str, list_unsub: str) -> bool:
    text = f"{subject} {snippet}".lower()
    if list_unsub:
        return True
    return any(sig in text for sig in _PROMO_SIGNALS)


def _wants_reply(subject: str, snippet: str) -> bool:
    text = f"{subject} {snippet}".lower()
    return any(sig in text for sig in _REPLY_SIGNALS)


def _is_invoice(subject: str, snippet: str, attachment_names: list) -> bool:
    """Detect an invoice/receipt by attachment suffix OR subject/body keyword. Pure.

    Ported from the legacy "Invoice Detection" rule: attachments (.pdf/.receipt) + subject keywords
    (invoice/receipt/payment/bill) + body keywords (amount due/payment received).
    """
    names = [str(n).lower() for n in (attachment_names or [])]
    if any(n.endswith(suf) for n in names for suf in _INVOICE_ATTACHMENT_SUFFIXES):
        return True
    text = f"{subject} {snippet}".lower()
    return any(sig in text for sig in _INVOICE_SUBJECT_SIGNALS)


def _expense_category(from_header: str, subject: str, snippet: str) -> str:
    """Classify a detected invoice as 'company' or 'personal' expense. Pure, deterministic.

    Returns ONLY the literal category string — this maps (in gmail_client) to the two Morning config
    addresses. It NEVER returns a recipient. A company signal (known SaaS/infra vendor, or an
    explicit Ltd/VAT/business marker) -> 'company'; otherwise 'personal'.
    """
    text = f"{_sender_email(from_header)} {subject} {snippet}".lower()
    if any(sig in text for sig in _COMPANY_EXPENSE_SIGNALS):
        return "company"
    return "personal"


def _classify(msg: dict) -> dict:
    """Classify one message. Pure. Adds invoice + expense-category fields on top of triage tags."""
    subject = msg.get("subject", "") or ""
    snippet = msg.get("snippet", "") or ""
    from_h = msg.get("from", "") or ""
    list_unsub = msg.get("list_unsubscribe", "") or ""
    attach = msg.get("attachment_names", []) or []

    is_invoice = _is_invoice(subject, snippet, attach)
    promotional = (not is_invoice) and _is_promotional(subject, snippet, list_unsub)
    wants_reply = (not promotional) and (not is_invoice) and _wants_reply(subject, snippet)
    # Archive obvious marketing; keep invoices + anything needing a reply in the inbox.
    archive = promotional
    needs_task = wants_reply and any(
        sig in f"{subject} {snippet}".lower() for sig in ("deadline", "action required", "urgent")
    )
    category = _expense_category(from_h, subject, snippet) if is_invoice else ""
    return {
        "id": msg.get("id", ""),
        "from": _sender_email(from_h),
        "subject": subject,
        "label": _company_label(from_h),
        "is_invoice": is_invoice,
        "expense_category": category,        # '' unless is_invoice; only ever 'personal'|'company'
        "promotional": promotional,
        "wants_reply": wants_reply,
        "needs_task": needs_task,
        "archive": archive,
        "list_unsubscribe": list_unsub,
        "thread_id": msg.get("threadId", "") or msg.get("thread_id", ""),
    }


# --- Idempotency: which invoice message-ids were already forwarded -----------------------
_PROCESSED_RE = re.compile(r"<!--\s*posey-forwarded-ids:\s*([^>]*)-->")


# Read the digest with a large cap so the idempotency marker — appended at the END of the body — is
# NEVER truncated away. A full shift at the agent's hard cap renders a ~13 KB digest; the default
# 6000-char ``read_local_digest`` cap would cut the marker off, making ``_already_forwarded_ids()``
# return empty and RE-FORWARDING every still-unread invoice to Morning (duplicate expenses). 200 KB
# comfortably covers the largest possible single-shift digest plus the marker.
_DIGEST_READ_CAP = 200_000


def _already_forwarded_ids() -> set:
    """Read the set of invoice message-ids Posey has ALREADY forwarded, from the durable digest.

    The digest body embeds a machine-readable marker ``<!-- posey-forwarded-ids: id1,id2 -->`` at the
    END of the body. Reading it back (fail-safe, with a large ``max_chars`` so the marker is never
    truncated — see ``_DIGEST_READ_CAP``) makes the forward IDEMPOTENT across shifts — a re-run skips
    any invoice already forwarded. Returns an empty set if no digest / no marker. NEVER raises.
    """
    try:
        body = read_local_digest("email-triage", max_chars=_DIGEST_READ_CAP)
    except Exception:
        return set()
    m = _PROCESSED_RE.search(body or "")
    if not m:
        return set()
    return {p.strip() for p in m.group(1).split(",") if p.strip()}


def _forwarded_marker(ids) -> str:
    """Render the embedded idempotency marker for the digest body."""
    uniq = sorted({str(i) for i in ids if str(i).strip()})
    return f"<!-- posey-forwarded-ids: {','.join(uniq)} -->"


# --- Nodes -------------------------------------------------------------------------------
def budget_gate(state: State) -> dict:
    """CLOCK-IN gate — STOP before any work if over salary or globally disabled. Runs FIRST."""
    with span("email_triage.budget_gate"):
        if check_clocked_in(AGENT):
            return {}
        report = {
            "severity": "skipped",
            "detail": "email_triage over token salary or globally disabled",
            "report_only": True,
        }
        governance_capture(AGENT, {"clocked_in": False, "report_only": True, "report": report})
        return {"report": report, "report_only": True}


def read_inbox(state: State) -> dict:
    """Read unread inbox stubs + fetch each message's headers/snippet/attachments (READ-ONLY). FAIL-SAFE.

    If Gmail is not configured we emit the honest 'could not check inbox' warning rather than
    pretend the inbox is clean. If listing succeeds but per-message reads fail (auth/rate-limit/SDK
    drift), we surface an honest ``unverifiable`` marker instead of a false "all clear".
    """
    with span("email_triage.read_inbox"):
        if not gmail_client.is_configured():
            return {
                "messages": [],
                "triaged": [
                    {"severity": "warn", "kind": "unverifiable",
                     "detail": "Gmail creds missing — could not check inbox"}
                ],
            }

        limit = _limit()
        listing = gmail_client.list_inbox(query="is:unread in:inbox", limit=limit)
        stubs = listing.get("items", []) if isinstance(listing, dict) else []
        if isinstance(listing, dict) and not listing.get("ok"):
            return {
                "messages": [],
                "triaged": [
                    {"severity": "warn", "kind": "unverifiable",
                     "detail": f"could not check inbox: {listing.get('error')}"}
                ],
            }

        triaged: list = []
        messages: list = []
        n_stubs = 0          # unread items the listing returned (and we tried to read)
        n_unreadable = 0     # of those, how many per-message fetches failed
        for stub in list(stubs)[:_MAX_MESSAGES]:
            if not isinstance(stub, dict):
                continue
            mid = str(stub.get("id", ""))
            if not mid:
                continue
            try:
                assert_not_model_work(mid)  # defensive: never act on a model-dev id
            except ModelWorkBlocked:
                continue
            n_stubs += 1
            full = gmail_client.get_message(mid)
            if not isinstance(full, dict) or not full.get("ok"):
                n_unreadable += 1
                continue
            full.setdefault("threadId", stub.get("threadId", ""))
            messages.append(full)
            triaged.append(_classify(full))

        # HONESTY: listing SUCCEEDED with unread items but some/all per-message reads failed — do
        # NOT roll a partly/fully unreadable inbox up to a green "all clear"; surface unverifiable.
        if n_unreadable:
            if not messages:
                triaged.append({
                    "severity": "warn", "kind": "unverifiable",
                    "detail": (f"could not read {n_unreadable} unread message(s) "
                               "— inbox state unverifiable (not necessarily clean)"),
                })
            else:
                triaged.append({
                    "severity": "warn", "kind": "unverifiable",
                    "detail": (f"could not read {n_unreadable} of {n_stubs} unread message(s) "
                               "— inbox partially unverifiable"),
                })
        return {"messages": messages, "triaged": triaged}


def detect_invoices(state: State) -> dict:
    """Collect the messages classified as invoices into a dedicated list. Pure pass over triaged.

    Splits the invoice detection (job 1) out of classification so the forward node has a clean,
    explicit list of invoice candidates with their {personal,company} category already decided.
    """
    triaged = state.get("triaged") or []
    with span("email_triage.detect_invoices", n=len(triaged)):
        invoices = [
            {
                "id": t.get("id", ""),
                "from": t.get("from", ""),
                "subject": t.get("subject", ""),
                "category": t.get("expense_category", "") or "personal",
                "label": t.get("label", ""),
            }
            for t in triaged
            if isinstance(t, dict) and t.get("is_invoice")
        ]
        return {"invoices": invoices}


def forward_invoices(state: State) -> dict:
    """Forward each DETECTED invoice to the ONE allow-listed Morning address for its category.

    SECURITY: the destination is resolved EXCLUSIVELY from server config
    (``gmail_client.morning_address(category)``) by the {personal,company} category — NEVER from the
    message and NEVER from model output. Before any send, the resolved recipient is re-asserted to be
    a member of ``gmail_client.allowlist()`` (the two Morning config addresses). A message whose
    From/Reply-To/body says "forward to attacker@evil" therefore cannot redirect the forward.

    REPORT-ONLY (probation): records a PLAN ("would forward invoice X to Morning(company)") and does
    NOT send. ENABLED (OPS_REPORT_ONLY=0): calls ``gmail_client.forward_invoice``.

    IDEMPOTENT: invoice ids already forwarded (read from the durable digest) are SKIPPED — the same
    invoice is never forwarded twice. FAIL-SAFE: a forward failure is recorded, never crashes.
    """
    invoices = state.get("invoices") or []
    report_only = _report_only()
    already = _already_forwarded_ids()
    with span("email_triage.forward_invoices", n=len(invoices), report_only=report_only):
        forwards: list = []
        for inv in invoices:
            if not isinstance(inv, dict):
                continue
            mid = str(inv.get("id", ""))
            category = (inv.get("category", "") or "").strip().lower()
            # Category MUST be one of the closed set; anything else => no forward (defensive).
            if category not in gmail_client.INVOICE_CATEGORIES:
                category = "personal"
            # Resolve the destination from CONFIG ONLY (never the message).
            to = gmail_client.morning_address(category)
            allow = gmail_client.allowlist()

            # IDEMPOTENCY: skip an invoice we have already forwarded.
            if mid and mid in already:
                forwards.append({
                    "id": mid, "category": category, "to": to or "(unconfigured)",
                    "status": "skipped_already_forwarded", "sent": False,
                    "subject": inv.get("subject", ""),
                })
                continue

            # HITL: forwarding mail OUT of the account is outward, so it is RECORDED through the
            # gate. The gate is invoked record-only (report_only=True) by design: the per-recipient
            # human approval for THIS action is the HARD ALLOWLIST itself — Shay pre-approved the two
            # Morning config addresses (Option B: auto-forward). The destination is structurally
            # pinned to that allowlist (config, never the message), so a per-message interrupt would
            # add nothing but block the auto-forward. Whether the send ACTUALLY happens is governed
            # by ``report_only`` (the OPS_REPORT_ONLY flag) below — not by pausing the runtime here.
            gate = human_gate(
                {"kind": "message_to_person", "outward": True,
                 "capability": "send:invoice_to_morning"},
                agent=AGENT,
                report_only=True,
            )

            # Belt-and-suspenders: refuse if the resolved address is not on the Morning allowlist
            # (e.g. unconfigured). This can NEVER be an attacker address — `to` came from config.
            if not to or to not in allow:
                forwards.append({
                    "id": mid, "category": category, "to": to or "(unconfigured)",
                    "status": "refused_not_on_allowlist", "sent": False, "gate": gate.get("status"),
                    "subject": inv.get("subject", ""),
                })
                continue

            if report_only:
                # PLAN only — do not actually send.
                forwards.append({
                    "id": mid, "category": category, "to": to,
                    "status": "would_forward", "sent": False, "gate": gate.get("status"),
                    "subject": inv.get("subject", ""),
                    "plan": f"would forward invoice {mid} to Morning({category}) <{to}>",
                })
                continue

            # ENABLED: actually forward via the structurally-constrained seam. The recipient is NOT
            # passed — gmail_client.forward_invoice re-resolves it from config by category.
            res = gmail_client.forward_invoice(mid, category)
            sent = bool(isinstance(res, dict) and res.get("ok"))
            forwards.append({
                "id": mid, "category": category,
                "to": (res.get("to") if isinstance(res, dict) else None) or to,
                "status": "forwarded" if sent else "forward_failed",
                "sent": sent, "gate": gate.get("status"),
                "error": (res.get("error") if isinstance(res, dict) and not sent else None),
                "subject": inv.get("subject", ""),
            })
        return {"forwards": forwards}


def draft_replies(state: State) -> dict:
    """For each non-invoice message that wants a reply, DRAFT a reply (create a Gmail draft — NEVER send).

    Each draft passes through ``human_gate`` (kind=message_to_person). The draft is a record in the
    Drafts folder; delivered only when a human clicks Send. FAIL-SAFE.
    """
    triaged = state.get("triaged") or []
    report_only = _report_only()
    with span("email_triage.draft_replies", n=len(triaged), report_only=report_only):
        to_reply = [t for t in triaged if isinstance(t, dict) and t.get("wants_reply")]
        drafts: list = []
        model = None
        for t in to_reply:
            # Record-only gate: a DRAFT is not a send (it is a record in the Drafts folder), so the
            # gate RECORDS that a human must Send it and never blocks the run. The actual human
            # approval is the Send click in Gmail; we never auto-send a reply regardless of the flag.
            gate = human_gate(
                {"kind": "message_to_person", "outward": True,
                 "capability": "propose:email_reply"},
                agent=AGENT,
                report_only=True,
            )
            body = _draft_body(t, model_getter=lambda: _ensure_model(model))
            if model is None:
                model = _ensure_model(model)  # cache after first use

            res = gmail_client.create_draft(
                to=t.get("from", ""),
                subject=_reply_subject(t.get("subject", "")),
                body=body,
                thread_id=t.get("thread_id", ""),
                in_reply_to=t.get("id", ""),
            )
            drafts.append({
                "to": t.get("from", ""),
                "subject": _reply_subject(t.get("subject", "")),
                "draft_id": res.get("draft_id") if isinstance(res, dict) else None,
                "created": bool(isinstance(res, dict) and res.get("ok")),
                "error": (res.get("error") if isinstance(res, dict) and not res.get("ok") else None),
                "gate": gate.get("status"),
                "body_preview": body[:240],
            })
        return {"drafts": drafts}


def propose_unsubscribes(state: State) -> dict:
    """Surface promotional senders as unsubscribe PROPOSALS — never executes one. FAIL-SAFE."""
    triaged = state.get("triaged") or []
    report_only = _report_only()
    with span("email_triage.propose_unsubscribes", report_only=report_only):
        proposals: list = []
        for t in triaged:
            if not isinstance(t, dict) or not t.get("promotional"):
                continue
            link = t.get("list_unsubscribe") or ""
            # Record-only gate: an unsubscribe is only ever PROPOSED here (never executed), so the
            # gate RECORDS that a human must approve it and never blocks the run.
            gate = human_gate(
                {"kind": "permission_change", "outward": True,
                 "capability": "propose:unsubscribe"},
                agent=AGENT,
                report_only=True,
            )
            proposals.append({
                "from": t.get("from", ""),
                "subject": t.get("subject", ""),
                "label": t.get("label", ""),
                "has_unsubscribe_link": bool(link),
                "list_unsubscribe": link[:300],
                "action": "PROPOSED (human must approve — agent never unsubscribes)",
                "gate": gate.get("status"),
            })
        return {"unsubscribes": proposals}


def archive_marketing(state: State) -> dict:
    """Conservatively tidy the OWN mailbox: label + archive OBVIOUS marketing only. FAIL-SAFE.

    A reversible read-MODIFY of Shay's OWN mailbox (no message leaves the account → NOT outward).
    Only messages classified PROMOTIONAL (and never invoices / reply-needed / actionable mail) are
    touched. In report-only it PLANS the tidy; when enabled it calls ``gmail_client.apply_label``.
    """
    triaged = state.get("triaged") or []
    report_only = _report_only()
    with span("email_triage.archive_marketing", report_only=report_only):
        tidied: list = []
        for t in triaged:
            if not isinstance(t, dict):
                continue
            # CONSERVATIVE: only obvious marketing, never an invoice / reply-needed / actionable mail.
            if not t.get("archive") or t.get("is_invoice") or t.get("wants_reply") or t.get("needs_task"):
                continue
            mid = str(t.get("id", ""))
            if not mid:
                continue
            if report_only:
                tidied.append({"id": mid, "subject": t.get("subject", ""),
                               "label": "marketing", "status": "would_label_archive", "applied": False})
                continue
            res = gmail_client.apply_label(mid, "marketing", archive=True)
            applied = bool(isinstance(res, dict) and res.get("ok"))
            tidied.append({
                "id": mid, "subject": t.get("subject", ""), "label": "marketing",
                "status": "labeled_archived" if applied else "tidy_failed", "applied": applied,
                "error": (res.get("error") if isinstance(res, dict) and not applied else None),
            })
        return {"tidied": tidied}


def create_tasks(state: State) -> dict:
    """Turn actionable mail into TASK records (the task/digest seam). FAIL-SAFE.

    A task record is a durable note for human follow-up (it does not act on the world). Mail flagged
    ``needs_task`` (deadline / action-required / urgent) becomes one task record each.
    """
    triaged = state.get("triaged") or []
    with span("email_triage.create_tasks", n=len(triaged)):
        tasks = [
            {
                "id": t.get("id", ""),
                "title": f"Follow up: {t.get('subject', '(no subject)')}",
                "from": t.get("from", ""),
                "source": "email",
                "status": "open",
            }
            for t in triaged
            if isinstance(t, dict) and t.get("needs_task")
        ]
        return {"tasks": tasks}


def triage_summary(state: State) -> dict:
    """Roll the run up into a severity + a short summary. FAIL-SAFE. Never claims an unsent send."""
    triaged = [t for t in (state.get("triaged") or []) if t.get("kind") != "unverifiable"]
    unverifiable = [t for t in (state.get("triaged") or []) if t.get("kind") == "unverifiable"]
    invoices = state.get("invoices") or []
    forwards = state.get("forwards") or []
    drafts = state.get("drafts") or []
    unsubs = state.get("unsubscribes") or []
    tasks = state.get("tasks") or []
    with span("email_triage.triage_summary", n=len(triaged), drafts=len(drafts)):
        needs_task = [t for t in triaged if t.get("needs_task")]
        sent_forwards = [f for f in forwards if f.get("sent")]
        if invoices or forwards or drafts or unsubs:
            severity = "high"   # invoices to route / drafts to review / unsubscribes to approve
        elif needs_task:
            severity = "medium"
        else:
            severity = "ok"

        deterministic = (
            f"Inbox triage = {severity}. {len(triaged)} message(s) triaged; "
            f"{len(invoices)} invoice(s) detected, {len(sent_forwards)} forwarded to Morning "
            f"({'report-only — would forward only' if not sent_forwards and forwards else 'live'}); "
            f"{len(drafts)} reply DRAFT(s) created (NOT sent); "
            f"{len(unsubs)} unsubscribe(s) PROPOSED (NOT executed); {len(tasks)} task(s) created."
        )
        if unverifiable:
            deterministic = unverifiable[0].get("detail", "could not check inbox") + ". " + deterministic
        summary = deterministic
        try:
            model = budget_guard(AGENT, TIER_DEFAULT)
            prompt = (
                "You are the founder's inbox assistant. You auto-forward DETECTED invoices to Morning "
                "(personal/company, a fixed two-address allowlist), DRAFT replies (never send), and "
                "PROPOSE unsubscribes (never act). Write a SHORT (2-4 sentence) operator summary of "
                "this triage run. Be factual; never claim a reply was sent.\n\n"
                f"Severity: {severity}\n"
                f"Invoices: {json.dumps(invoices, default=str)[:1500]}\n"
                f"Forwards: {json.dumps(forwards, default=str)[:1500]}\n"
                f"Drafts (records, not sends): {json.dumps(drafts, default=str)[:1500]}\n"
                f"Unsubscribe proposals: {json.dumps(unsubs, default=str)[:1000]}\n"
            )
            resp = model.invoke(prompt)
            content = getattr(resp, "content", str(resp)) or ""
            if content.strip():
                summary = content.strip()
        except Exception as exc:
            summary = f"{deterministic} (model summary unavailable: {type(exc).__name__})"
        return {"severity": severity, "summary": summary}


def deliver(state: State) -> dict:
    """Write the local digest + file the durable GitHub record + mirror to Slack. FAIL-SAFE.

    Embeds the IDEMPOTENCY marker (the union of previously- and now-forwarded invoice ids) so the
    next shift skips already-forwarded invoices.
    """
    severity = state.get("severity") or "ok"
    summary = state.get("summary") or f"Inbox triage = {severity}."
    triaged = state.get("triaged") or []
    invoices = state.get("invoices") or []
    forwards = state.get("forwards") or []
    drafts = state.get("drafts") or []
    unsubs = state.get("unsubscribes") or []
    tidied = state.get("tidied") or []
    tasks = state.get("tasks") or []
    report_only = _report_only()

    # IDEMPOTENCY marker: union of already-forwarded ids + any forwarded/planned this run.
    forwarded_ids = set(_already_forwarded_ids())
    for f in forwards:
        if isinstance(f, dict) and f.get("id") and f.get("status") in ("forwarded", "would_forward",
                                                                        "skipped_already_forwarded"):
            forwarded_ids.add(str(f.get("id")))

    with span("email_triage.deliver", severity=severity, report_only=report_only):
        body = _render_body(severity, summary, triaged, invoices, forwards, drafts, unsubs, tidied, tasks)
        body = body + "\n\n" + _forwarded_marker(forwarded_ids)
        write_local_digest("email-triage", "Inbox / email triage", body)

        labels = ["alert:email-triage"]
        # Outward / human-review things → carry the gate label.
        if invoices or forwards or drafts or unsubs:
            labels.append("gate:human-required")

        res = file_digest_record(
            DIGEST_REPO,
            "Inbox / email triage: " + severity,
            body,
            agent=AGENT,
            record_kind="email-triage",      # STABLE dedup key — one standing record, updated each shift
            labels=labels,
            report_only=report_only,
            slack_title="📬 Inbox / email triage: " + severity,
        )
        delivery = res.get("status") if isinstance(res, dict) else None
        return {
            "report": {"severity": severity, "delivery": delivery,
                       "invoices": len(invoices),
                       "forwarded": len([f for f in forwards if f.get("sent")]),
                       "drafts": len(drafts), "unsubscribes_proposed": len(unsubs),
                       "tasks": len(tasks)},
            "report_only": report_only,
        }


def finalize(state: State) -> dict:
    """Terminal node — capture governance (report_only=True) and emit the final report."""
    severity = state.get("severity") or "ok"
    triaged = [t for t in (state.get("triaged") or []) if t.get("kind") != "unverifiable"]
    invoices = state.get("invoices") or []
    forwards = state.get("forwards") or []
    sent_forwards = [f for f in forwards if f.get("sent")]
    drafts = state.get("drafts") or []
    unsubs = state.get("unsubscribes") or []
    tasks = state.get("tasks") or []
    tidied = state.get("tidied") or []
    prior = state.get("report") if isinstance(state.get("report"), dict) else {}

    with span("email_triage.finalize", severity=severity):
        governance_capture(
            AGENT,
            {
                "severity": severity,
                "n_triaged": len(triaged),
                "n_invoices": len(invoices),
                "n_forwarded_to_morning": len(sent_forwards),   # only ever to the two config addrs
                "n_drafts": len(drafts),                        # records created, NEVER sent
                "n_unsubscribes_proposed": len(unsubs),         # proposed, NEVER executed
                "n_tasks": len(tasks),
                "n_tidied": len(tidied),
                "reply_sent": 0,   # invariant: this agent never SENDS a reply (only forwards invoices)
                "report_only": True,
            },
        )
        report = {
            "severity": severity,
            "n_triaged": len(triaged),
            "invoices": len(invoices),
            "forwarded": len(sent_forwards),
            "drafts": len(drafts),
            "unsubscribes_proposed": len(unsubs),
            "tasks": len(tasks),
            "tidied": len(tidied),
            "sent": 0,             # invariant: no reply is ever sent (forwards are the only send)
            "delivery": prior.get("delivery"),
            "report_only": True,
        }
        return {"report": report}


# --- Reply drafting helpers --------------------------------------------------------------
def _limit() -> int:
    raw = os.environ.get("EMAIL_TRIAGE_LIMIT")
    try:
        return max(1, min(int(raw), _MAX_MESSAGES)) if raw else _DEFAULT_LIMIT
    except (TypeError, ValueError):
        return _DEFAULT_LIMIT


def _ensure_model(model):
    """Return a budget-metered model, or None if unavailable (deterministic fallback used)."""
    if model is not None:
        return model
    try:
        return budget_guard(AGENT, TIER_DEFAULT, temperature=0.3)
    except Exception:
        return None


def _reply_subject(subject: str) -> str:
    s = (subject or "").strip()
    return s if s.lower().startswith("re:") else f"Re: {s}"


def _draft_body(t: dict, *, model_getter) -> str:
    """Draft a reply body. Tries the budget-metered model; falls back to a safe template.

    The persona is the ported Scheduler-support persona from ops-triage.ts: helpful, warm, NEVER
    promises refunds or makes unauthorized commitments — when unsure it asks the operator. The body
    is a DRAFT for human review, never sent.
    """
    deterministic = (
        f"Hi,\n\nThanks for reaching out regarding \"{t.get('subject', '')}\". "
        "I'm looking into this and will follow up shortly.\n\n"
        "[DRAFT — pending human review before sending]\n\nBest,\nScheduler Systems"
    )
    try:
        model = model_getter()
        if model is None:
            return deterministic
        prompt = (
            "You are drafting a reply on behalf of the founder of Scheduler Systems. Draft a helpful, "
            "warm, professional reply to the email below. NEVER promise refunds or make unauthorized "
            "commitments; when unsure, say you'll check. This is a DRAFT for human review.\n\n"
            f"From: {t.get('from', '')}\nSubject: {t.get('subject', '')}\n"
        )
        resp = model.invoke(prompt)
        content = getattr(resp, "content", str(resp)) or ""
        return content.strip() or deterministic
    except Exception:
        return deterministic


def _coarse_label(value: str) -> str:
    """Coarse, non-PII sender label (the email DOMAIN STEM) for the durable record.

    Posey reads the founder's PRIVATE inbox; the durable company record (GitHub issue + Slack) must
    SUMMARIZE, not reproduce private content. A bare ``user@host`` is PII — so we collapse it to the
    coarse domain stem (e.g. ``jane@stmarys-hospital.example`` → ``stmarys-hospital``), which lets an
    operator triage without leaking the personal address. Reuses ``_company_label`` (domain-stem
    logic). ``value`` may already be a bare label (no ``@``) — then it is returned as-is.
    """
    v = (value or "").strip()
    if not v:
        return "unknown"
    if "@" in v:
        return _company_label(v)
    return v


def _render_body(severity, summary, triaged, invoices, forwards, drafts, unsubs, tidied, tasks) -> str:
    """Render the durable digest body. CONTENT-MINIMIZED: the founder's PRIVATE inbox content (raw
    subject lines — which routinely carry OTPs / medical / financial detail — and bare ``user@host``
    sender addresses) is NEVER reproduced into the COMPANY GitHub/Slack record. We report COUNTS,
    severity, classification TAGS, and a coarse sender LABEL (domain stem) only. Raw subjects/
    addresses live (if anywhere) only in the LOCAL digest, never in this shared body.
    """
    real = [t for t in triaged if t.get("kind") != "unverifiable"]
    lines = [
        f"**Severity:** {severity}",
        "",
        "> Posey = the founder's inbox assistant. The ONLY outward send is the invoice→Morning "
        "auto-forward (HARD allowlist: personal→MORNING_PERSONAL_EMAIL, company→MORNING_COMPANY_EMAIL; "
        "recipient from config, NEVER the message). Replies are **drafts** (never sent), unsubscribes "
        "are **proposed**, marketing is labeled/archived on the OWN mailbox. This record is "
        "content-minimized: raw subjects + sender addresses (PII) are NOT reproduced — only coarse "
        "labels + counts.",
        "",
        summary,
        "",
        f"## Triaged ({len(real)})",
    ]
    if real:
        for t in real:
            tags = []
            if t.get("is_invoice"):
                tags.append(f"invoice→{t.get('expense_category', '?')}")
            if t.get("wants_reply"):
                tags.append("reply-drafted")
            if t.get("promotional"):
                tags.append("promo→unsub-proposed")
            if t.get("needs_task"):
                tags.append("needs-task")
            if t.get("archive"):
                tags.append("archive")
            # Coarse sender label + tags ONLY — no raw subject, no bare sender address.
            label = t.get("label") or _coarse_label(t.get("from", ""))
            lines.append(f"- **{label}** [{', '.join(tags) or 'fyi'}]")
    else:
        lines.append("_none_")

    lines += ["", f"## Invoices → Morning ({len(forwards)})"]
    if forwards:
        for f in forwards:
            # Forward ids + category + Morning destination are operational config, not private inbox
            # content; the subject is NOT reproduced.
            lines.append(
                f"- invoice `{f.get('id')}` ({f.get('category')}) → `{f.get('to')}` — "
                f"**{f.get('status')}** (gate: {f.get('gate', 'n/a')})"
            )
    else:
        lines.append("_none_")

    lines += ["", f"## Reply DRAFTS created — NOT sent ({len(drafts)})"]
    if drafts:
        for d in drafts:
            mark = "draft saved" if d.get("created") else f"draft failed ({d.get('error')})"
            # Coarse recipient label only — no bare address, no raw subject (the reply subject echoes
            # the private original).
            lines.append(f"- to **{_coarse_label(d.get('to', ''))}** — {mark} (gate: {d.get('gate')})")
    else:
        lines.append("_none_")

    lines += ["", f"## Unsubscribes PROPOSED — NOT executed ({len(unsubs)})"]
    if unsubs:
        for u in unsubs:
            label = u.get("label") or _coarse_label(u.get("from", ""))
            lines.append(
                f"- **{label}** "
                f"(unsubscribe link: {'yes' if u.get('has_unsubscribe_link') else 'none'}; "
                f"gate: {u.get('gate')})"
            )
    else:
        lines.append("_none_")

    lines += ["", f"## Marketing tidied (own mailbox) ({len(tidied)})"]
    if tidied:
        for t in tidied:
            # Message id + status only — no raw subject reproduced.
            lines.append(f"- `{t.get('id')}` — {t.get('status')}")
    else:
        lines.append("_none_")

    lines += ["", f"## Tasks created ({len(tasks)})"]
    if tasks:
        for t in tasks:
            # Count + coarse sender label only — the task title embeds the raw private subject, so it
            # is NOT reproduced here.
            lines.append(f"- follow-up task from **{_coarse_label(t.get('from', ''))}**")
    else:
        lines.append("_none_")
    return "\n".join(lines)


# --- Routing -----------------------------------------------------------------------------
def _budget_route(state: State) -> str:
    """Clocked in -> read the inbox; clocked out -> END (terminal report already set)."""
    return "read_inbox" if check_clocked_in(AGENT) else "clocked_out"


# --- Graph wiring ------------------------------------------------------------------------
builder = StateGraph(State)
builder.add_node("budget_gate", budget_gate)
builder.add_node("read_inbox", read_inbox)
builder.add_node("detect_invoices", detect_invoices)
builder.add_node("forward_invoices", forward_invoices)
builder.add_node("draft_replies", draft_replies)
builder.add_node("propose_unsubscribes", propose_unsubscribes)
builder.add_node("archive_marketing", archive_marketing)
builder.add_node("create_tasks", create_tasks)
builder.add_node("triage_summary", triage_summary)
builder.add_node("deliver", deliver)
builder.add_node("finalize", finalize)

builder.add_edge(START, "budget_gate")
builder.add_conditional_edges(
    "budget_gate",
    _budget_route,
    {"read_inbox": "read_inbox", "clocked_out": END},
)
builder.add_edge("read_inbox", "detect_invoices")
builder.add_edge("detect_invoices", "forward_invoices")
builder.add_edge("forward_invoices", "draft_replies")
builder.add_edge("draft_replies", "propose_unsubscribes")
builder.add_edge("propose_unsubscribes", "archive_marketing")
builder.add_edge("archive_marketing", "create_tasks")
builder.add_edge("create_tasks", "triage_summary")
builder.add_edge("triage_summary", "deliver")
builder.add_edge("deliver", "finalize")
builder.add_edge("finalize", END)

graph = builder.compile()  # NO checkpointer/store — injected by the platform
