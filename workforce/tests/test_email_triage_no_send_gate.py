"""FAILING regression test — the capability GATE must enforce email's draft-only bright line.

Onboarding gap (found 2026-06-06): "Posey" (email_triage) is correctly onboarded — roster row,
capability grant, langgraph.json entry, both coverage gates green, posture report_only / probation,
and the live grant has NO send verb. BUT the *machine enforcement* of the bright line is missing:

  scripts/check_capability_coverage.py allow-lists capability **verb prefixes**
  (read/post/propose/write/git/message). It has NO email-channel rule. So an outbound-email
  *delivery* capability added to email_triage — e.g. ``post:email`` (mirrors the already-accepted
  ``post:slack``), ``write:email_send`` or ``propose:send_email`` — PASSES the gate with zero errors.

The "email = read + propose/draft only, NEVER send" rule (Shay's firm "never send without approval"
+ the graph/gmail_client docstrings) is therefore enforced ONLY by gmail_client having no send
method — a future edit could add a send path and grant ``post:email`` without any CI gate or test
failing. The existing bespoke unit test (test_email_triage.test_capability_grant_is_draft_only_no
_send_verb) also misses it: its ``'send' in cap`` substring check does not match ``post:email``.

These tests assert the GATE itself must reject an outbound-email-delivery grant on a draft-only
agent. They FAIL today (the gate passes the malicious grant) and will pass once the gate grows an
email-channel rule: on a draft-only/triage agent, any ``email``-channel capability must be a
``read:``/``propose:`` (draft) verb — never ``post:``/``write:`` (deliver) and never ``*send*``.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import pathlib
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent

_spec = importlib.util.spec_from_file_location(
    "check_capability_coverage", ROOT / "scripts" / "check_capability_coverage.py"
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
validate = _mod.validate


def _real():
    graphs = set(json.loads((ROOT / "langgraph.json").read_text())["graphs"])
    manifest = yaml.safe_load((ROOT / "docs" / "governance" / "capabilities.yaml").read_text())
    return graphs, manifest


def _with_email_triage_cap(manifest, capability):
    """Return a deep-copied manifest with one extra capability on email_triage's grant."""
    m = copy.deepcopy(manifest)
    m["grants"]["email_triage"]["capabilities"].append({
        "capability": capability,
        "scope": "deliver the drafted reply to the customer",
        "why": "send email",
        "granted_by": "shay",
        "revocable": True,
    })
    return m


class EmailTriageSendGateRegression(unittest.TestCase):
    """The gate MUST machine-enforce email's draft-only bright line — not rely on gmail_client."""

    def _gate_errors_for(self, capability):
        graphs, manifest = _real()
        m = _with_email_triage_cap(manifest, capability)
        errors, _ = validate(graphs, m)
        return [e for e in errors if "email_triage" in e]

    def test_post_email_send_is_rejected(self):
        # ``post:email`` = outbound email DELIVERY (mirrors the accepted ``post:slack``). The verb
        # prefix ``post`` is allow-listed, so the gate passes it today — the bright line is unguarded.
        errs = self._gate_errors_for("post:email")
        self.assertTrue(
            errs,
            "GAP: the capability gate accepts 'post:email' on the draft-only email_triage agent — "
            "an outbound-email-DELIVERY grant slips past CI. The gate must reject any email-channel "
            "post:/write: (deliver) verb on a draft-only agent; email may only be read:/propose:.",
        )

    def test_write_email_send_is_rejected(self):
        errs = self._gate_errors_for("write:email_send")
        self.assertTrue(
            errs,
            "GAP: the gate accepts 'write:email_send' on email_triage — a send path past CI.",
        )

    def test_propose_send_email_is_rejected(self):
        # Even a 'propose:'-prefixed *send* must be rejected — drafting is propose:email_reply,
        # not propose:send_email; the channel+intent, not just the prefix, defines the bright line.
        errs = self._gate_errors_for("propose:send_email")
        self.assertTrue(
            errs,
            "GAP: the gate accepts 'propose:send_email' on email_triage — a disguised send past CI.",
        )

    def test_send_email_channel_is_rejected(self):
        # A 'send'-verb on the EMAIL channel (send:email / send:gmail) is a general email-send —
        # rejected by the email draft-only bright line (send is not read:/propose:).
        for cap in ("send:email", "send:gmail", "send:inbox_reply"):
            errs = self._gate_errors_for(cap)
            self.assertTrue(errs, f"GAP: the gate accepts '{cap}' on email_triage — a general send path.")

    def test_general_send_noun_is_rejected(self):
        # A 'send' to an un-allowlisted action (not invoice_to_morning) is rejected: 'send' is only
        # permitted for a recipient-allowlist-pinned action.
        for cap in ("send:anywhere", "send:customer", "send:vendor"):
            errs = self._gate_errors_for(cap)
            self.assertTrue(errs, f"GAP: the gate accepts un-allowlisted send '{cap}'.")

    def test_send_invoice_to_morning_requires_allowlist_scope(self):
        # The allowlist-scoped send is accepted ONLY when its scope names the Morning allowlist.
        graphs, manifest = _real()
        # A bad scope (does not name morning + allowlist) must FAIL even with the right noun.
        m = copy.deepcopy(manifest)
        m["grants"]["email_triage"]["capabilities"].append({
            "capability": "send:invoice_to_morning",
            "scope": "send the invoice somewhere",   # does not name the allowlist
            "why": "x", "granted_by": "shay", "revocable": True,
        })
        errs = [e for e in validate(graphs, m)[0] if "email_triage" in e]
        self.assertTrue(errs, "send:invoice_to_morning with a non-allowlist scope must be rejected.")

    def test_live_grant_with_allowlisted_send_passes(self):
        # Guard: the real grant — draft-only PLUS the single allowlist-scoped invoice→Morning send —
        # must stay valid. (Replaces the old draft-only-only guard now that Posey forwards invoices.)
        graphs, manifest = _real()
        errors, _ = validate(graphs, manifest)
        live = [e for e in errors if "email_triage" in e]
        self.assertEqual(live, [], f"the real email_triage grant must stay valid; got: {live}")
        # And the real grant DOES carry the one allowlist-scoped send.
        caps = {c["capability"] for c in manifest["grants"]["email_triage"]["capabilities"]}
        self.assertIn("send:invoice_to_morning", caps)


if __name__ == "__main__":
    unittest.main()
