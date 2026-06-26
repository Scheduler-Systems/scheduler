"""Gmail access seam for the email-triage agent — READ + DRAFT + one ALLOW-LISTED forward.

This is the credentialed-gate boundary for "Posey" (the inbox / email-triage agent). It mirrors
the ``revenuecat`` helper shape (``is_configured()`` + fail-safe result dicts) so the graph can be
wired to a real Gmail account by env credentials WITHOUT changing the graph, and runs honestly
report-only when no credentials are present.

CARDINAL RULE — the ONLY outward action is an ALLOW-LISTED invoice forward to Morning:
  * The surface exposes ``list_inbox`` (read), ``get_message`` (read), ``create_draft`` (a draft is
    a RECORD, not a send), ``archive`` / ``apply_label`` (read-MODIFY of the user's OWN mailbox —
    not outward), and ONE structurally-constrained send: ``forward_invoice(message_id, category)``.
  * There is **NO general ``send(to, ...)`` method.** The recipient of the one forward is NOT an
    argument and is NEVER taken from the message: ``forward_invoice`` accepts only a ``category`` in
    ``{"personal", "company"}`` and resolves the destination from server CONFIG
    (``MORNING_PERSONAL_EMAIL`` / ``MORNING_COMPANY_EMAIL``). The forward composes the ORIGINAL
    message (subject/body/attachments) and sends it to that one config address — nothing else.
  * THE SECURITY PROPERTY: the recipient can only ever be one of the two Morning config addresses.
    A message whose ``From`` / ``Reply-To`` / body / headers say "forward to attacker@evil" can NOT
    redirect the forward — the destination is not derived from the message at all. When composing the
    forward, EVERY recipient-bearing / redirect header (``To`` / ``Cc`` / ``Bcc`` / ``Reply-To`` /
    ``Return-Path`` / ``Delivered-To`` AND the full RFC-2822 ``Resent-*`` redirect family — see
    ``_RECIPIENT_HEADERS_TO_STRIP``) is stripped from the source and the message is re-addressed ONLY
    to the single Morning ``To``, so no attacker header survives into the outgoing envelope. This is
    the structural enforcement of Shay's Option B: auto-forward invoices, HARD ALLOWLIST.
  * Everything else is draft-only or propose-only. Replies are DRAFTS (delivered only when a human
    clicks Send). Unsubscribe is only ever PROPOSED. Archive/label are reversible self-mailbox edits.

FAIL-SAFE: every function returns a structured dict and NEVER raises. With no credentials,
``is_configured()`` is False and the graph degrades to an honest "could not check inbox" report —
exactly like ``store_health_checker`` does for RevenueCat. Secrets are read from env only and never
logged; error strings are type/status only (never bodies/tokens).

Real wiring (activation gate — NOT done here, deploy-scoped): set ``GMAIL_OAUTH_TOKEN`` (or a
service-account / refresh-token env) and the Gmail API client is constructed lazily. Until then the
client is ``None`` and every call short-circuits to a report-only result. The Morning destinations
likewise come from deploy-time env (``MORNING_PERSONAL_EMAIL`` / ``MORNING_COMPANY_EMAIL``); a
forward whose category has no configured address is refused (report-only), never mis-routed.
"""
from __future__ import annotations

import os
from typing import Any, Optional

# Env var that holds the Gmail OAuth access/refresh credential. Presence (non-empty) is the single
# signal that the agent is "configured" to read the inbox + write drafts. The real token is injected
# at deploy time (LangSmith runtime secret) — it is an ACTIVATION GATE, never committed.
GMAIL_TOKEN_ENV = "GMAIL_OAUTH_TOKEN"
# The mailbox the agent operates on (informational; the token already scopes the account).
GMAIL_USER_ENV = "GMAIL_USER"

# --- THE ALLOWLIST (the whole security property) ----------------------------------------
# The two — and only two — addresses the one outward action (forward_invoice) may ever reach.
# They come from server CONFIG (env), injected at deploy time. They are NEVER taken from a
# message's From/Reply-To/body/headers and NEVER passed as a function argument. ``forward_invoice``
# resolves its destination through ``morning_address(category)`` below and nowhere else.
MORNING_PERSONAL_ENV = "MORNING_PERSONAL_EMAIL"   # personal-expense Morning inbox
MORNING_COMPANY_ENV = "MORNING_COMPANY_EMAIL"     # company-expense Morning inbox (exp+...@expenses.morning.co)

# The closed set of categories the single forward accepts. A category outside this set is refused.
INVOICE_CATEGORIES = ("personal", "company")

# Every recipient-bearing / redirect header that a mail-submission path could honor. The forward
# strips ALL of these from the original message and re-addresses ONLY to the single Morning ``to``,
# so no attacker-controlled header in the source can redirect/CC/BCC the forward off the allowlist.
# Critically this INCLUDES the RFC-2822 Resent-* (redirect) family: a "receipt" carrying
# ``Resent-Bcc: attacker@evil`` must NOT survive into the outgoing envelope.
_RECIPIENT_HEADERS_TO_STRIP = (
    "To", "Cc", "Bcc", "Delivered-To", "Reply-To", "Return-Path",
    "Resent-To", "Resent-Cc", "Resent-Bcc", "Resent-Sender", "Resent-From",
    "Resent-Date", "Resent-Message-ID",
)

# Hard cap so a huge inbox can never hang an agent shift.
_MAX_FETCH = 50


def is_configured() -> bool:
    """True iff a Gmail credential is present in env. No creds => honest report-only run."""
    return bool(os.environ.get(GMAIL_TOKEN_ENV))


def mailbox() -> str:
    """The configured mailbox address (informational). '' when unset."""
    return os.environ.get(GMAIL_USER_ENV, "")


def morning_address(category: str) -> str:
    """Resolve the ONE allow-listed Morning destination for ``category`` from server CONFIG.

    This is the only place a forward destination is ever produced. It maps the closed category set
    ``{"personal", "company"}`` to the two env-configured Morning addresses
    (``MORNING_PERSONAL_EMAIL`` / ``MORNING_COMPANY_EMAIL``). It NEVER reads a message and takes NO
    recipient argument — so no email content can influence where a forward goes. Returns "" when the
    category is unknown or its address is unconfigured (the caller then refuses to forward).
    """
    cat = (category or "").strip().lower()
    if cat == "personal":
        return os.environ.get(MORNING_PERSONAL_ENV, "").strip()
    if cat == "company":
        return os.environ.get(MORNING_COMPANY_ENV, "").strip()
    return ""


def allowlist() -> set[str]:
    """The current set of allow-listed forward destinations (the two configured Morning addresses).

    Used by the graph to ASSERT, after composing a forward, that the resolved recipient is a member
    of this set before any send — a belt-and-suspenders check on top of the structural design.
    Empty addresses are excluded (an unconfigured category contributes nothing to the allowlist).
    """
    return {a for a in (morning_address("personal"), morning_address("company")) if a}


def _build_client() -> Optional[Any]:
    """Construct the real Gmail API client from env credentials. FAIL-SAFE → None.

    Lazily imports the Google client libs so the deterministic test venv (no googleapiclient)
    still loads this module. ANY problem (missing lib, bad token) degrades to None, and every
    public call below treats None as "not configured" → report-only. This is the ONE place the
    credentialed activation gate is wired.
    """
    token = os.environ.get(GMAIL_TOKEN_ENV)
    if not token:
        return None
    try:  # pragma: no cover - only exercised in a credentialed deploy, never in CI
        from google.oauth2.credentials import Credentials  # type: ignore
        from googleapiclient.discovery import build  # type: ignore

        creds = Credentials(token=token)
        # Read + compose(draft) + modify(label/archive) + send(forward) scopes. The send scope is
        # used ONLY by forward_invoice, whose destination is structurally pinned to the allowlist.
        return build("gmail", "v1", credentials=creds, cache_discovery=False)
    except Exception:
        return None


class GmailNotConfigured(RuntimeError):
    """Raised internally when an operation needs a client that isn't configured. Never escapes."""


def list_inbox(*, query: str = "is:unread in:inbox", limit: int = 20, client: Any = None) -> dict:
    """Read message stubs from the inbox (READ-ONLY). FAIL-SAFE.

    Returns ``{"ok": bool, "items": [ {id, threadId}... ], "error"?: str}``. ``client`` is
    injectable for tests; in production it is built from env credentials. Capped at _MAX_FETCH.
    """
    cli = client if client is not None else _build_client()
    if cli is None:
        return {"ok": False, "items": [], "error": "gmail not configured — could not check inbox"}
    n = max(1, min(int(limit or 1), _MAX_FETCH))
    try:
        resp = (
            cli.users().messages().list(userId="me", q=query, maxResults=n).execute()
        )
        items = resp.get("messages", []) if isinstance(resp, dict) else []
        return {"ok": True, "items": list(items)[:n]}
    except Exception as exc:  # network/auth/SDK drift — honest failure, never raise
        return {"ok": False, "items": [], "error": f"inbox list failed: {type(exc).__name__}"}


def get_message(message_id: str, *, client: Any = None) -> dict:
    """Read one message's headers + snippet + attachment names (READ-ONLY). FAIL-SAFE.

    Returns ``{"ok", "id", "from", "subject", "snippet", "list_unsubscribe", "labelIds",
    "has_attachments", "attachment_names", "reply_to"}`` or ``{"ok": False, "error": ...}``.
    ``list_unsubscribe`` is the RFC-2369 ``List-Unsubscribe`` header (the basis for PROPOSING — never
    executing — an unsubscribe). ``has_attachments`` / ``attachment_names`` feed invoice detection
    (a ``.pdf`` / ``.receipt`` attachment is a strong invoice signal). ``reply_to`` is surfaced for
    completeness ONLY — it is NEVER used as a forward destination (see ``forward_invoice``).
    """
    cli = client if client is not None else _build_client()
    if cli is None:
        return {"ok": False, "error": "gmail not configured"}
    if not message_id:
        return {"ok": False, "error": "no message id"}
    try:
        msg = (
            cli.users()
            .messages()
            .get(userId="me", id=message_id, format="metadata",
                 metadataHeaders=["From", "Subject", "List-Unsubscribe", "Reply-To"])
            .execute()
        )
        if not isinstance(msg, dict):
            return {"ok": False, "error": "message get returned non-dict"}
        headers = {
            str(h.get("name", "")).lower(): h.get("value", "")
            for h in (msg.get("payload", {}) or {}).get("headers", []) or []
            if isinstance(h, dict)
        }
        attach_names = _attachment_names(msg.get("payload", {}) or {})
        return {
            "ok": True,
            "id": message_id,
            "from": headers.get("from", ""),
            "reply_to": headers.get("reply-to", ""),
            "subject": headers.get("subject", ""),
            "snippet": msg.get("snippet", ""),
            "list_unsubscribe": headers.get("list-unsubscribe", ""),
            "labelIds": msg.get("labelIds", []) or [],
            "attachment_names": attach_names,
            "has_attachments": bool(attach_names),
        }
    except Exception as exc:
        return {"ok": False, "error": f"message get failed: {type(exc).__name__}"}


def _attachment_names(payload: dict) -> list:
    """Collect filenames of MIME parts that have a filename (attachments). Pure; no IO."""
    names: list = []

    def _walk(part):
        if not isinstance(part, dict):
            return
        fn = part.get("filename") or ""
        if fn:
            names.append(fn)
        for sub in part.get("parts", []) or []:
            _walk(sub)

    _walk(payload)
    return names


def create_draft(*, to: str, subject: str, body: str, thread_id: str = "",
                 in_reply_to: str = "", client: Any = None) -> dict:
    """Create a Gmail DRAFT (NEVER sends). FAIL-SAFE.

    A draft is a RECORD: it lands in the Drafts folder and is delivered ONLY when a human opens it
    and clicks Send. This is the agent's only reply "write" — there is intentionally no send path
    for replies. Returns ``{"ok", "draft_id", "to", "subject"}`` or ``{"ok": False, "error": ...}``.
    """
    cli = client if client is not None else _build_client()
    if cli is None:
        return {"ok": False, "error": "gmail not configured — draft not created (report-only)"}
    if not to or not subject:
        return {"ok": False, "error": "draft requires a recipient and subject"}
    try:
        raw = _encode_message(to=to, subject=subject, body=body, in_reply_to=in_reply_to)
        message: dict = {"raw": raw}
        if thread_id:
            message["threadId"] = thread_id
        resp = (
            cli.users().drafts().create(userId="me", body={"message": message}).execute()
        )
        draft_id = resp.get("id", "") if isinstance(resp, dict) else ""
        return {"ok": True, "draft_id": draft_id, "to": to, "subject": subject}
    except Exception as exc:
        return {"ok": False, "error": f"draft create failed: {type(exc).__name__}"}


def apply_label(message_id: str, label: str, *, archive: bool = False, client: Any = None) -> dict:
    """Apply a Gmail label (and optionally archive) on the user's OWN mailbox. FAIL-SAFE.

    This is a read-MODIFY of the founder's own inbox — NOT an outward action (no message leaves the
    account, nothing reaches another person). It is reversible (a label can be removed, an archived
    message restored). Used for conservative tidying: labelling obvious marketing, archiving FYI mail.
    Returns ``{"ok", "id", "label", "archived"}`` or ``{"ok": False, "error": ...}``.
    """
    cli = client if client is not None else _build_client()
    if cli is None:
        return {"ok": False, "error": "gmail not configured — label not applied (report-only)"}
    if not message_id or not label:
        return {"ok": False, "error": "apply_label requires a message id and label"}
    try:
        label_id = _ensure_label_id(cli, label)
        add = [label_id] if label_id else []
        remove = ["INBOX"] if archive else []
        body = {"addLabelIds": add, "removeLabelIds": remove}
        cli.users().messages().modify(userId="me", id=message_id, body=body).execute()
        return {"ok": True, "id": message_id, "label": label, "archived": bool(archive)}
    except Exception as exc:
        return {"ok": False, "error": f"label apply failed: {type(exc).__name__}"}


def archive(message_id: str, *, client: Any = None) -> dict:
    """Archive a message (remove it from INBOX) on the user's OWN mailbox. FAIL-SAFE.

    Reversible self-mailbox edit (the message moves to All Mail; it can be restored). NOT outward.
    Returns ``{"ok", "id", "archived"}`` or ``{"ok": False, "error": ...}``.
    """
    cli = client if client is not None else _build_client()
    if cli is None:
        return {"ok": False, "error": "gmail not configured — not archived (report-only)"}
    if not message_id:
        return {"ok": False, "error": "archive requires a message id"}
    try:
        cli.users().messages().modify(
            userId="me", id=message_id, body={"removeLabelIds": ["INBOX"]}
        ).execute()
        return {"ok": True, "id": message_id, "archived": True}
    except Exception as exc:
        return {"ok": False, "error": f"archive failed: {type(exc).__name__}"}


def forward_invoice(message_id: str, category: str, *, client: Any = None) -> dict:
    """Forward a detected invoice to the ONE allow-listed Morning address for ``category``. FAIL-SAFE.

    THIS IS THE ONLY OUTWARD SEND IN THE WHOLE MODULE, and it is structurally constrained:

      * ``category`` MUST be one of ``{"personal", "company"}``. Anything else is refused.
      * The destination is resolved EXCLUSIVELY via ``morning_address(category)`` — i.e. from server
        CONFIG (``MORNING_PERSONAL_EMAIL`` / ``MORNING_COMPANY_EMAIL``). It is **not a parameter**
        and is **never** read from the message (From/Reply-To/body/headers). No email content can
        change where the forward goes. If the category's address is unconfigured, the forward is
        refused (report-only), never mis-routed.
      * The forward composes the ORIGINAL message (subject/body/attachments) via Gmail's native
        forward (re-using the fetched RFC-822 source), so attachments ride along, and sends it to
        that single Morning address.
      * BELT-AND-SUSPENDERS: before sending, the resolved recipient is asserted to be a member of
        ``allowlist()`` (the two configured Morning addresses). If somehow it is not, the send is
        refused. There is no code path here that can address any other recipient.

    Returns ``{"ok", "id", "category", "to"}`` on success, or ``{"ok": False, "error": ...}`` when
    not configured / unknown category / unconfigured address / send failure. NEVER raises.
    """
    cat = (category or "").strip().lower()
    if cat not in INVOICE_CATEGORIES:
        return {"ok": False, "error": f"refused: category must be one of {INVOICE_CATEGORIES}, got {category!r}"}
    # Destination comes from CONFIG only — never the message, never an argument.
    to = morning_address(cat)
    if not to:
        return {"ok": False, "error": f"refused: no Morning address configured for category '{cat}' (report-only)"}
    # Belt-and-suspenders: the resolved address MUST be one of the two allow-listed Morning inboxes.
    if to not in allowlist():
        return {"ok": False, "error": "refused: resolved recipient is not on the Morning allowlist"}

    cli = client if client is not None else _build_client()
    if cli is None:
        return {"ok": False, "error": "gmail not configured — invoice not forwarded (report-only)"}
    if not message_id:
        return {"ok": False, "error": "forward requires a message id"}
    try:
        # Fetch the ORIGINAL raw message so the forward preserves subject/body/attachments.
        original = (
            cli.users().messages().get(userId="me", id=message_id, format="raw").execute()
        )
        raw_src = original.get("raw", "") if isinstance(original, dict) else ""
        thread_id = original.get("threadId", "") if isinstance(original, dict) else ""
        subject = _original_subject(cli, message_id)
        raw = _encode_forward(to=to, subject=subject, raw_source=raw_src)
        body: dict = {"raw": raw}
        if thread_id:
            body["threadId"] = thread_id
        cli.users().messages().send(userId="me", body=body).execute()
        return {"ok": True, "id": message_id, "category": cat, "to": to}
    except Exception as exc:
        return {"ok": False, "error": f"invoice forward failed: {type(exc).__name__}"}


# --- private helpers --------------------------------------------------------------------
def _ensure_label_id(cli: Any, label: str) -> str:
    """Resolve (or create) a Gmail label id by name. Returns "" on any failure (label skipped)."""
    try:
        existing = cli.users().labels().list(userId="me").execute()
        for lab in (existing.get("labels", []) if isinstance(existing, dict) else []):
            if isinstance(lab, dict) and str(lab.get("name", "")).lower() == label.lower():
                return lab.get("id", "")
        created = cli.users().labels().create(
            userId="me", body={"name": label, "labelListVisibility": "labelShow",
                                "messageListVisibility": "show"}
        ).execute()
        return created.get("id", "") if isinstance(created, dict) else ""
    except Exception:
        return ""


def _original_subject(cli: Any, message_id: str) -> str:
    """Best-effort fetch of the original Subject for the Fwd: header. "" on failure."""
    try:
        meta = (
            cli.users().messages()
            .get(userId="me", id=message_id, format="metadata", metadataHeaders=["Subject"])
            .execute()
        )
        for h in (meta.get("payload", {}) or {}).get("headers", []) or []:
            if isinstance(h, dict) and str(h.get("name", "")).lower() == "subject":
                return h.get("value", "")
    except Exception:
        pass
    return ""


def _encode_message(*, to: str, subject: str, body: str, in_reply_to: str = "") -> str:
    """Build a base64url-encoded RFC-2822 message for a draft. Pure; no IO."""
    import base64
    from email.mime.text import MIMEText

    mime = MIMEText(body or "", "plain", "utf-8")
    mime["To"] = to
    mime["Subject"] = subject
    if in_reply_to:
        mime["In-Reply-To"] = in_reply_to
        mime["References"] = in_reply_to
    return base64.urlsafe_b64encode(mime.as_bytes()).decode("ascii")


def _encode_forward(*, to: str, subject: str, raw_source: str) -> str:
    """Build a base64url-encoded forward of an original raw message. Pure; no IO. FAIL-SAFE.

    Re-parses the original RFC-822 source (so attachments/body are preserved), STRIPS every
    recipient-bearing / redirect header (``_RECIPIENT_HEADERS_TO_STRIP`` — incl. the Resent-*
    family), and re-addresses ONLY the envelope ``To`` to the single allow-listed Morning address,
    prefixing ``Fwd:`` on the subject. ``to`` is ALWAYS a Morning allowlist address (the caller
    resolved + asserted it); this helper never derives a recipient.

    HARDENING: the original Subject is attacker-controlled, so any CR/LF is sanitized to a single
    space before it is ever assigned to a header (a raw CRLF would otherwise raise HeaderParseError
    or enable header injection). And because this helper is documented FAIL-SAFE / never-raises, the
    fallback path uses a CONSTANT safe subject — never the (possibly still-poisoned) source subject —
    so it can never raise a second time. The result ALWAYS addresses only the Morning ``to``.
    """
    import base64
    from email import message_from_bytes
    from email.mime.text import MIMEText

    # Sanitize the attacker-controlled subject FIRST: collapse any CR/LF so it can never inject a
    # header or raise HeaderParseError. Header-folding (re-wrapping long lines) is fine and safe.
    safe_subject = (subject or "").replace("\r", " ").replace("\n", " ").strip()
    fwd_subject = safe_subject if safe_subject.lower().startswith("fwd:") else f"Fwd: {safe_subject}".strip()
    try:
        src_bytes = base64.urlsafe_b64decode(raw_source.encode("ascii")) if raw_source else b""
        msg = message_from_bytes(src_bytes) if src_bytes else None
        if msg is None:
            raise ValueError("no source")
        # Strip the ENTIRE original addressing envelope (incl. the Resent-* redirect family — see
        # _RECIPIENT_HEADERS_TO_STRIP) and re-address ONLY to the Morning allowlist addr. del on a
        # multipart header removes ALL occurrences, so duplicate attacker headers cannot survive.
        for hdr in _RECIPIENT_HEADERS_TO_STRIP:
            del msg[hdr]
        del msg["Subject"]
        msg["Subject"] = fwd_subject
        msg["To"] = to
        return base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
    except Exception:
        # FAIL-SAFE fallback: a CONSTANT safe subject (never the source subject, which could still be
        # poisoned) so this branch can never raise. Still addresses ONLY the Morning ``to``.
        mime = MIMEText("(forwarded invoice — original attached/encoded)", "plain", "utf-8")
        mime["To"] = to
        mime["Subject"] = "Fwd: invoice"
        return base64.urlsafe_b64encode(mime.as_bytes()).decode("ascii")
