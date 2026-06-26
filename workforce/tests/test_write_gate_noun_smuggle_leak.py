"""FAILING regression: the per-agent write-gate never-list leaks on outward-action-as-NOUN.

THE GUARANTEE UNDER TEST
------------------------
``agent_toolkit/write_gate.py`` documents (lines ~150-153 + ``_cap_is_outward_irreversible``
docstring) that the capability-derived never-list "catches a ``write:deploy`` / ``post:merge_pr``
style smuggle even if the verb prefix is benign". The cardinal safety property that rests on it:
an agent whose grant carries an OUTWARD/IRREVERSIBLE action is AUTO-never-listed and therefore
can NEVER be write-enabled — even if it is added to ``AGENTS_WRITE_ENABLED`` with the global
``OPS_REPORT_ONLY`` floor lifted and the kill switch clocked-in.

THE DEFECT
----------
The never-list's noun defense (``_NEVER_NOUN_WORDS`` ∪ ``_NEVER_NOUN_SUBSTRINGS``) only covers
``merge / force_push / wire_transfer / deploy / billing / payment / purchase``. It MISSES the
outward VERBS the module already treats as dangerous in the VERB position
(``send / forward / release / buy / pay / fund / transfer / acquire / subscribe``) when they
appear as the NOUN under a benign verb prefix. The single worst case: ``forward`` — Posey's
literal outward action — is in NEITHER the verb-prefix set NOR either noun set.

CONSEQUENCE
-----------
A future agent granted, e.g., ``write:forward_invoice_external`` or ``action:send_newsletter``
is NOT auto-never-listed. Add it to ``AGENTS_WRITE_ENABLED`` (a Shay-set deployment env) with the
floor lifted and ``write_enabled()`` returns True — the gate fails OPEN on exactly the outward
action it promises to block, silently. No CURRENT manifest grant triggers it (the only outward
``send:`` today is verb-position ``send:invoice_to_morning``), so this is LATENT until a grant
expresses an outward action as a noun — at which point it ships a real bypass with no warning.

THE FIX (for whoever picks this up)
-----------------------------------
Make the noun matcher reuse the SAME outward family as the verb matcher: any
``_NEVER_VERB_PREFIXES`` token (send/forward/buy/pay/fund/transfer/release/acquire/subscribe/…)
appearing as a whole word in the noun must flag too. (Add ``forward`` — currently absent from
BOTH lists — to the outward family.)

stdlib unittest, no network, no real writes. Run:
    PYTHONPATH=. <venv>/bin/python -m unittest tests.test_write_gate_noun_smuggle_leak -v
"""
from __future__ import annotations

import os
import tempfile
import textwrap
import unittest
from unittest import mock

from agent_toolkit import budget
from agent_toolkit import write_gate as wg


def _clean_env(**kw):
    env = dict(os.environ)
    env.pop("OPS_REPORT_ONLY", None)
    env.pop("AGENTS_WRITE_ENABLED", None)
    env.update(kw)
    return env


class NeverListNounSmuggleLeak(unittest.TestCase):
    # The outward actions-as-noun that the verb matcher would catch in verb position, expressed
    # under a BENIGN verb prefix. Each MUST be flagged (the documented "even if the verb prefix
    # is benign" guarantee). ``forward`` is the headline case — Posey's literal outward verb.
    SMUGGLED = (
        "write:forward_invoice_external",  # FORWARD as noun, benign verb
        "action:send_newsletter",          # SEND as noun
        "post:release_to_prod",            # RELEASE as noun
        "task:pay_vendor",                 # PAY as noun
        "do:buy_compute",                  # BUY as noun
    )

    def test_outward_action_as_noun_is_flagged(self):
        """``_cap_is_outward_irreversible`` must flag an outward action under a benign verb."""
        for cap in self.SMUGGLED:
            self.assertTrue(
                wg._cap_is_outward_irreversible(cap),
                f"{cap!r}: outward action under a benign verb MUST be flagged — never-list LEAK",
            )

    def test_new_outward_agent_is_auto_never_listed_and_not_write_enabled(self):
        """End-to-end: a grant carrying an outward-action-as-noun auto-never-lists the agent, so
        it can NEVER be write-enabled even on the allowlist with the floor lifted + clocked-in."""
        manifest = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)
        manifest.write(textwrap.dedent(
            """
            grants:
              rogue_forwarder:
                capabilities:
                  - { capability: "write:forward_invoice_external" }
            """
        ))
        manifest.flush()
        wg._capability_never_list.cache_clear()
        try:
            with mock.patch.object(wg, "_MANIFEST_PATH", manifest.name), \
                 mock.patch.object(budget, "check_clocked_in", return_value=True), \
                 mock.patch.dict(
                     os.environ,
                     _clean_env(OPS_REPORT_ONLY="0", AGENTS_WRITE_ENABLED="rogue_forwarder"),
                     clear=True,
                 ):
                self.assertTrue(
                    wg.never_listed("rogue_forwarder"),
                    "an agent granted write:forward_* MUST be auto-never-listed (it is NOT — LEAK)",
                )
                self.assertFalse(
                    wg.write_enabled("rogue_forwarder"),
                    "an agent granted an outward forward MUST NOT be write-enabled "
                    "(gate fails OPEN on the action it promises to block — LEAK)",
                )
        finally:
            wg._capability_never_list.cache_clear()
            os.unlink(manifest.name)


if __name__ == "__main__":
    unittest.main()
