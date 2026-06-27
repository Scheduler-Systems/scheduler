"""Regression test: webhook REPLAY-DEFENSE BYPASS in scripts/event_receiver.py.

The replay guard keys on the X-GitHub-Delivery / Sentry-Hook-Resource HEADERS, but
GitHub and Sentry sign only the request BODY — those headers are outside the HMAC.
So a single captured, validly-signed webhook can be replayed unbounded times by
mutating that one unsigned header per replay: the signature still verifies (body is
byte-identical) and each fresh header value is a new replay-key, so the agent fires
again every time.

These tests assert the property the module docstring (event_receiver.py:17-20)
PROMISES — "a captured-and-replayed request cannot re-fire an agent." They FAIL
against the current code (the agent fires 5x), proving the bypass. They will pass
once the replay key is derived from signed material (e.g. the body / its HMAC) so an
attacker cannot mint a fresh replay-key for an unchanged signed body.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import unittest

from scripts import event_receiver as er

_GH_SECRET = "gh-test-secret"
_SENTRY_SECRET = "sentry-test-secret"


def _sign_github(secret: str, raw: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


def _sign_sentry(secret: str, raw: bytes) -> str:
    return hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


class _Recorder:
    def __init__(self):
        self.calls: list = []

    def __call__(self, agent, thread_id, agent_input):
        self.calls.append((agent, thread_id, dict(agent_input)))
        return {"run_id": "stub"}


def _make(fire):
    return er.EventReceiver(github_secret=_GH_SECRET, sentry_secret=_SENTRY_SECRET, fire=fire)


def _pr_body():
    return {
        "action": "opened", "number": 1487,
        "pull_request": {"number": 1487, "node_id": "PR_node_abc", "merged": False,
                         "head": {"ref": "feat/x", "sha": "deadbeef"}},
        "repository": {"full_name": "Scheduler-Systems/scheduler-web"},
    }


def _sentry_body():
    return {"action": "triggered", "data": {"issue": {"id": "ISSUE-42", "title": "TypeError"}}}


class ReplayBypass(unittest.TestCase):
    def test_github_replay_with_mutated_delivery_header_is_rejected(self):
        """One captured signed PR-opened, replayed with fresh X-GitHub-Delivery ids,
        must be ACCEPTED EXACTLY ONCE. The delivery header is not signed, so it must not be
        usable to mint a fresh replay-key for an unchanged signed body. A single accepted
        PR-open fans out to the QA chain + the board PR-review agent (2 fires); the 4 replays
        are rejected and add nothing, so the agents fire a total of 2x (not 5x2)."""
        rec = _Recorder()
        r = _make(rec)
        raw = json.dumps(_pr_body()).encode()
        sig = _sign_github(_GH_SECRET, raw)  # ONE captured signature
        for i in range(5):
            r.handle("github",
                     {"X-GitHub-Event": "pull_request",
                      "X-GitHub-Delivery": f"forged-{i}",   # attacker-chosen, UNSIGNED
                      "X-Hub-Signature-256": sig},
                     raw)
        # 2 = the fan-out of the SINGLE accepted delivery (qa_lead_aggregator + board_pr_review);
        # the 4 unsigned-header replays are all rejected, so the count never grows beyond it.
        self.assertEqual([c[0] for c in rec.calls],
                         ["qa_lead_aggregator", "board_pr_review"],
                         f"replay bypass: 1 captured webhook re-fired via mutated unsigned "
                         f"delivery header; got calls={[c[0] for c in rec.calls]}")

    def test_sentry_replay_with_mutated_resource_header_is_rejected(self):
        """One captured signed Sentry issue alert, replayed with fresh
        Sentry-Hook-Resource values, must fire EXACTLY ONCE."""
        rec = _Recorder()
        r = _make(rec)
        raw = json.dumps(_sentry_body()).encode()
        sig = _sign_sentry(_SENTRY_SECRET, raw)  # ONE captured signature
        for i in range(5):
            r.handle("sentry",
                     {"Sentry-Hook-Resource": f"issue-{i}",  # attacker-chosen, UNSIGNED
                      "Sentry-Hook-Signature": sig},
                     raw)
        self.assertEqual(len(rec.calls), 1,
                         f"replay bypass: 1 captured webhook re-fired the agent "
                         f"{len(rec.calls)}x via mutated unsigned resource header")


if __name__ == "__main__":
    unittest.main()
