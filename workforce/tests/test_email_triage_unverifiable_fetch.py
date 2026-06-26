"""Regression: read_inbox must stay HONEST when it can't read the unread items it listed.

Honesty hole (found 2026-06-06): read_inbox emits an ``unverifiable`` warning for two failure
modes (no Gmail creds; list_inbox ok==False), but NOT a third — when ``list_inbox`` SUCCEEDS and
returns N unread stubs, yet every per-message ``get_message`` returns ``ok: False`` (transient
auth / rate-limit / HttpError / SDK drift on the per-message read). The fetch loop ``continue``s on
all of them and the node returned ``messages=[]`` / ``triaged=[]`` with NO unverifiable marker —
rolling up to ``severity="ok"`` / ``n_triaged=0``, a false "inbox clean" digest. That is exactly
the dishonest-clean outcome the module docstring promises this agent never produces.

These tests assert read_inbox surfaces an ``unverifiable`` marker when listing succeeds but the
per-message reads fail (all OR some). stdlib unittest + mock, no network. Run:
    .venv/bin/python -m unittest tests.test_email_triage_unverifiable_fetch -v
"""
from __future__ import annotations

import unittest
from unittest import mock

from graphs.ops import email_triage as m


class AllMessageFetchesFailIsUnverifiable(unittest.TestCase):
    def test_list_ok_but_all_fetches_fail_is_unverifiable_not_clean(self):
        # Listing SUCCEEDS with two unread stubs...
        listing = {"ok": True, "items": [{"id": "1", "threadId": "t1"},
                                         {"id": "2", "threadId": "t2"}]}
        # ...but every per-message read fails (transient auth / rate-limit / SDK drift).
        with mock.patch.object(m.gmail_client, "is_configured", return_value=True), \
             mock.patch.object(m.gmail_client, "list_inbox", return_value=listing), \
             mock.patch.object(m.gmail_client, "get_message",
                               return_value={"ok": False, "error": "message get failed: HttpError"}):
            out = m.read_inbox({})

        kinds = [t.get("kind") for t in out.get("triaged", [])]
        self.assertIn(
            "unverifiable", kinds,
            "read_inbox saw unread items it could not read, yet produced NO unverifiable "
            "warning — it is pretending the inbox is clean (fail-safe / honesty violation). "
            f"triaged={out.get('triaged')!r}",
        )

    def test_partial_fetch_failure_is_unverifiable(self):
        # Two unread stubs; the first reads fine, the second fails — partial visibility must be
        # surfaced honestly, not silently dropped.
        listing = {"ok": True, "items": [{"id": "1", "threadId": "t1"},
                                         {"id": "2", "threadId": "t2"}]}

        def _get(mid, **_):
            if mid == "1":
                return {"ok": True, "id": "1", "from": "a@b.com", "subject": "hi",
                        "snippet": "", "list_unsubscribe": "", "labelIds": []}
            return {"ok": False, "error": "message get failed: HttpError"}

        with mock.patch.object(m.gmail_client, "is_configured", return_value=True), \
             mock.patch.object(m.gmail_client, "list_inbox", return_value=listing), \
             mock.patch.object(m.gmail_client, "get_message", side_effect=_get):
            out = m.read_inbox({})

        kinds = [t.get("kind") for t in out.get("triaged", [])]
        self.assertIn(
            "unverifiable", kinds,
            "read_inbox read only some of the unread items but did not flag the gap — "
            f"triaged={out.get('triaged')!r}",
        )
        # The one readable message is still triaged (not lost).
        self.assertTrue(any(t.get("kind") != "unverifiable" for t in out.get("triaged", [])))

    def test_all_fetches_ok_has_no_unverifiable_marker(self):
        # Guard: when every read succeeds there must be NO false unverifiable noise.
        listing = {"ok": True, "items": [{"id": "1", "threadId": "t1"}]}
        good = {"ok": True, "id": "1", "from": "a@b.com", "subject": "hi",
                "snippet": "", "list_unsubscribe": "", "labelIds": []}
        with mock.patch.object(m.gmail_client, "is_configured", return_value=True), \
             mock.patch.object(m.gmail_client, "list_inbox", return_value=listing), \
             mock.patch.object(m.gmail_client, "get_message", return_value=good):
            out = m.read_inbox({})
        kinds = [t.get("kind") for t in out.get("triaged", [])]
        self.assertNotIn("unverifiable", kinds, out.get("triaged"))

    def test_empty_inbox_is_not_unverifiable(self):
        # Guard: a genuinely empty inbox (listing ok, zero items) is clean, NOT unverifiable.
        with mock.patch.object(m.gmail_client, "is_configured", return_value=True), \
             mock.patch.object(m.gmail_client, "list_inbox",
                               return_value={"ok": True, "items": []}):
            out = m.read_inbox({})
        kinds = [t.get("kind") for t in out.get("triaged", [])]
        self.assertNotIn("unverifiable", kinds, out.get("triaged"))


if __name__ == "__main__":
    unittest.main()
