"""FAILING regression test — Posey's digest/GitHub/Slack record must SUMMARIZE, not REPRODUCE.

Privacy finding (2026-06-06): "Posey" (email_triage) reads the founder's PRIVATE business inbox
(``shay@scheduler-systems.com``) and then files a durable record of the run to a COMPANY GitHub
issue (``Scheduler-Systems/qa-agent-platform`` via ``file_digest_record``) and mirrors it to Slack.

That record is built by ``_render_body`` — and it currently REPRODUCES private email content into
the company record instead of SUMMARIZING it:

  * Verbatim, unredacted **subject lines** of the founder's private mail
    (e.g. "Your verification code is 558213", "Re: your biopsy results", "Wire $40,000 to ...").
    A subject routinely carries OTP codes, medical / legal / financial details, account numbers.
  * Full **sender email addresses (PII)** — printed in the Triaged list, AND again per reply draft,
    AND again per unsubscribe proposal.

The digest body is then filed VERBATIM to a deduped, persisted GitHub issue (read by other agents
and humans, accumulating across shifts) and mirrored to Slack. That is an over-share: a digest of an
inbox triage should report COUNTS / severity / coarse sender labels (the email domain stem, which
``_company_label`` already computes) — NOT reproduce the raw subject text or the bare sender address.

These tests assert the minimization property: the rendered digest body must NOT contain the raw
subject text or the bare ``user@host`` sender address of a triaged message. They FAIL today (both
leak) and will pass once ``_render_body`` is changed to summarize (e.g. show only the coarse
``label`` / domain stem and a redacted or omitted subject) rather than reproduce private content.

stdlib unittest only, no network, no Gmail. Run:
    .venv/bin/python -m unittest tests.test_email_triage_digest_privacy -v
"""
from __future__ import annotations

import unittest

from graphs.ops import email_triage as m


# A sender address (PII) and a subject that carries sensitive content (an OTP). Neither should be
# reproduced verbatim into the company GitHub record / Slack post — the digest should summarize.
SENDER_PII = "jane.patient@stmarys-hospital.example"
SECRET_SUBJECT = "Your one-time verification code is 558213"
OTP = "558213"


def _triaged_message(**over):
    base = {
        "id": "m1",
        "from": SENDER_PII,
        "subject": SECRET_SUBJECT,
        "label": "stmarys-hospital",   # coarse domain stem — this IS safe to show
        "is_invoice": False,
        "expense_category": "",
        "promotional": False,
        "wants_reply": True,
        "needs_task": False,
        "archive": False,
        "list_unsubscribe": "",
        "thread_id": "t1",
    }
    base.update(over)
    return base


class DigestMinimizationTests(unittest.TestCase):
    """The durable GitHub/Slack digest body must summarize private mail, not reproduce it."""

    def test_render_body_does_not_reproduce_raw_subject_line(self):
        """The verbatim private subject (and any OTP/secret it carries) must NOT be in the record."""
        t = _triaged_message()
        drafts = [{
            "to": SENDER_PII,
            "subject": "Re: " + SECRET_SUBJECT,
            "created": True,
            "gate": "would_require_human",
            "error": None,
            "body_preview": "Hi, thanks for reaching out ...",
        }]
        body = m._render_body("high", "1 message triaged; 1 reply drafted.",
                              [t], [], [], drafts, [], [], [])
        self.assertNotIn(
            SECRET_SUBJECT, body,
            "Posey leaks the verbatim subject of the founder's private mail into the COMPANY "
            "GitHub/Slack record — it must summarize, not reproduce the subject line.",
        )
        self.assertNotIn(
            OTP, body,
            "Posey leaks a one-time code carried in a private subject line into the company record.",
        )

    def test_render_body_does_not_reproduce_bare_sender_address(self):
        """The bare ``user@host`` sender (PII) must NOT appear in the company record.

        A coarse sender LABEL (the domain stem, e.g. 'stmarys-hospital') is fine and lets an
        operator triage; the full personal address is PII that should not be reproduced.
        """
        t = _triaged_message()
        unsubs = [{
            "from": SENDER_PII,
            "subject": SECRET_SUBJECT,
            "label": "stmarys-hospital",
            "has_unsubscribe_link": True,
            "list_unsubscribe": "<https://stmarys-hospital.example/u>",
            "gate": "would_require_human",
        }]
        body = m._render_body("high", "summary", [t], [], [], [], unsubs, [], [])
        self.assertNotIn(
            SENDER_PII, body,
            "Posey reproduces the bare sender email address (PII) of the founder's private mail "
            "into the COMPANY GitHub/Slack record — it should show only a coarse label, not the "
            "full address.",
        )

    def test_full_deliver_path_files_no_raw_content_to_github(self):
        """End-to-end: the body handed to ``file_digest_record`` (GitHub + Slack) must be minimized.

        This pins the actual seam that reaches the durable company record, so a future refactor of
        ``_render_body`` cannot quietly reintroduce the leak through ``deliver``.
        """
        from unittest import mock

        captured = {}

        def fake_record(repo, title, body, **kwargs):
            captured["body"] = body
            return {"status": "report_only"}

        triaged = [_triaged_message()]
        drafts = [{"to": SENDER_PII, "subject": "Re: " + SECRET_SUBJECT,
                   "created": True, "gate": "would_require_human", "error": None,
                   "body_preview": "..."}]
        state = {
            "severity": "high",
            "summary": "1 message triaged; 1 reply drafted (not sent).",
            "triaged": triaged,
            "invoices": [],
            "forwards": [],
            "drafts": drafts,
            "unsubscribes": [],
            "tidied": [],
            "tasks": [],
        }
        with mock.patch.object(m, "_report_only", return_value=True), \
             mock.patch.object(m, "write_local_digest", return_value=""), \
             mock.patch.object(m, "_already_forwarded_ids", return_value=set()), \
             mock.patch.object(m, "file_digest_record", side_effect=fake_record):
            m.deliver(state)

        body = captured.get("body", "")
        self.assertNotIn(SECRET_SUBJECT, body,
                         "deliver() files the raw private subject to the company GitHub/Slack record.")
        self.assertNotIn(OTP, body,
                         "deliver() files a private OTP to the company GitHub/Slack record.")
        self.assertNotIn(SENDER_PII, body,
                         "deliver() files the bare sender PII to the company GitHub/Slack record.")


if __name__ == "__main__":
    unittest.main()
