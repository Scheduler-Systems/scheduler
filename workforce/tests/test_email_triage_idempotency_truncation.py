"""Regression: idempotency must survive a LARGE digest (real read_local_digest cap).

THE BUG (this test FAILS on the unfixed code):
  ``deliver`` appends the idempotency marker ``<!-- posey-forwarded-ids: ... -->`` to the VERY END
  of the digest body, but ``read_local_digest`` caps its return at ``max_chars=6000``. A normal full
  shift (the agent's hard cap is 50 messages) renders a ~13 KB digest, so the marker sits well past
  the 6000-char cut and is TRUNCATED away on read-back. The next shift's ``_already_forwarded_ids()``
  then recovers ZERO ids and RE-FORWARDS every invoice — duplicate invoices land in Morning.

This is the load-bearing IDEMPOTENT property of Posey's one outward send ("the same invoice is NEVER
forwarded twice"). It is exercised here through the REAL ``write_local_digest`` /
``read_local_digest`` round-trip (a temp WORKSPACE_ROOT) rather than a mock that hands the body back
verbatim — which is why the existing ``test_idempotent_across_two_runs`` did not catch it.

stdlib unittest + unittest.mock, no network, MOCKED Gmail. Run:
    .venv/bin/python -m unittest tests.test_email_triage_idempotency_truncation -v
"""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from agent_toolkit import gmail_client
from graphs.ops import email_triage as m

PERSONAL = "me-personal@expenses.morning.co"
COMPANY = "exp+company123@expenses.morning.co"


def _morning_env(root: str):
    env = dict(os.environ)
    env.pop("OPS_REPORT_ONLY", None)
    env[gmail_client.MORNING_PERSONAL_ENV] = PERSONAL
    env[gmail_client.MORNING_COMPANY_ENV] = COMPANY
    env["OPS_REPORT_ONLY"] = "0"          # LIVE — real (mocked) forwards, not report-only plans
    env["WORKSPACE_ROOT"] = root          # local digest read/write lands here
    return env


class _FakeGmail:
    """Records every forward + to where, mirroring forward_invoice's real config-only contract."""

    def __init__(self, messages):
        self._messages = messages
        self.forwards = []

    def list_inbox(self, *, query="", limit=20, client=None):
        return {"ok": True, "items": [{"id": mid, "threadId": f"t{mid}"} for mid in self._messages]}

    def get_message(self, message_id, *, client=None):
        msg = dict(self._messages.get(message_id, {}))
        msg.setdefault("ok", True)
        msg.setdefault("id", message_id)
        return msg

    def create_draft(self, *, to, subject, body, thread_id="", in_reply_to="", client=None):
        return {"ok": True, "draft_id": "d", "to": to, "subject": subject}

    def apply_label(self, message_id, label, *, archive=False, client=None):
        return {"ok": True, "id": message_id, "label": label, "archived": archive}

    def forward_invoice(self, message_id, category, *, client=None):
        to = gmail_client.morning_address(category)
        if category not in gmail_client.INVOICE_CATEGORIES or not to or to not in gmail_client.allowlist():
            return {"ok": False, "error": "refused"}
        self.forwards.append((message_id, category, to))
        return {"ok": True, "id": message_id, "category": category, "to": to}


def _invoice(mid, subject):
    # A company invoice (AWS) with a .pdf — detected + classified 'company'. Stays UNREAD across shifts.
    return {"ok": True, "id": mid, "from": f"AWS billing {mid} <b{mid}@amazon.com>",
            "subject": subject, "snippet": "your invoice is attached",
            "list_unsubscribe": "", "threadId": f"t{mid}", "labelIds": ["INBOX", "UNREAD"],
            "attachment_names": [f"{mid}.pdf"], "has_attachments": True}


class IdempotencySurvivesLargeDigestTests(unittest.TestCase):
    def _run_one_shift(self, root, fake):
        """Invoke the whole graph once — NOT mocking write/read_local_digest (real round-trip)."""
        # Posey is NEVER-LISTED, so its real ``_report_only()`` can never be False. This test
        # exercises the forward IDEMPOTENCY mechanics across shifts, so it patches ``_report_only``
        # to False (LIVE forwards) — decoupling "is the marker round-trip idempotent?" from the
        # separate never-list gate (proven in test_email_triage_write_gate).
        with mock.patch.dict(os.environ, _morning_env(root), clear=True), \
             mock.patch.object(m, "_report_only", return_value=False), \
             mock.patch.object(m, "check_clocked_in", return_value=True), \
             mock.patch.object(m.gmail_client, "is_configured", return_value=True), \
             mock.patch.object(m.gmail_client, "list_inbox", side_effect=fake.list_inbox), \
             mock.patch.object(m.gmail_client, "get_message", side_effect=fake.get_message), \
             mock.patch.object(m.gmail_client, "create_draft", side_effect=fake.create_draft), \
             mock.patch.object(m.gmail_client, "forward_invoice", side_effect=fake.forward_invoice), \
             mock.patch.object(m.gmail_client, "apply_label", side_effect=fake.apply_label), \
             mock.patch.object(m, "budget_guard", side_effect=RuntimeError("no model")), \
             mock.patch.object(m, "file_digest_record", return_value={"status": "report_only"}):
            m.graph.invoke({})

    def test_full_inbox_invoice_not_re_forwarded_on_second_shift(self):
        # A full shift at the agent's hard cap (_MAX_MESSAGES = 50) of company invoices that remain
        # unread across both shifts. The rendered digest is ~13 KB, so the forwarded-ids marker lands
        # past read_local_digest's 6000-char cap. IDEMPOTENCY must STILL hold: 50 forwards total.
        n = m._MAX_MESSAGES  # 50
        messages = {
            f"msg-{i:04d}": _invoice(
                f"msg-{i:04d}",
                f"AWS Invoice {1000 + i} for monthly cloud subscription renewal services and support",
            )
            for i in range(n)
        }
        fake = _FakeGmail(messages)
        with tempfile.TemporaryDirectory() as root:
            self._run_one_shift(root, fake)
            after_first = len(fake.forwards)
            self.assertEqual(after_first, n, "first shift should forward each invoice exactly once")

            # Second shift: the SAME unread invoices. Idempotency must skip them all → no new forwards.
            self._run_one_shift(root, fake)
            after_second = len(fake.forwards)

        self.assertEqual(
            after_second, n,
            f"IDEMPOTENCY VIOLATED: {after_second - after_first} invoice(s) re-forwarded to Morning "
            f"on the 2nd shift (total {after_second}, expected {n}). The forwarded-ids marker is "
            f"appended at the END of a ~13 KB digest and truncated away by read_local_digest's "
            f"6000-char cap, so _already_forwarded_ids() recovers nothing.",
        )

        # Each invoice id appears exactly once across all forwards (no duplicate sends).
        forwarded_ids = [mid for (mid, _cat, _to) in fake.forwards]
        self.assertEqual(
            len(forwarded_ids), len(set(forwarded_ids)),
            "the same invoice was forwarded to Morning more than once",
        )


if __name__ == "__main__":
    unittest.main()
