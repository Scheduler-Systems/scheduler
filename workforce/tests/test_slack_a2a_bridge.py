"""Tests for the Slack↔A2A bridge routing + sender-auth (the pure, deps-light surface).

Runs in the deps CI lane (the module imports a2a_client/slack_tool). Covers the human-facing
decisions: who may pilot the fleet (allowFrom), which agent a mention routes to, and the stable
contextId that ties a Slack thread to one LangSmith conversation.
"""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("OPENCLAW_ALLOW_FROM", "U08L384N6VD,U0OWNER")
from agent_toolkit import slack_a2a_bridge as b  # noqa: E402


class Routing(unittest.TestCase):
    def test_channel_default(self):
        self.assertEqual(b.resolve_target("qa-reports", "what's the verdict")[0], "qa_lead_aggregator")
        self.assertEqual(b.resolve_target("#executive-updates", "status?")[0], "ceo")

    def test_explicit_at_role_wins_over_channel(self):
        agent, clean = b.resolve_target("executive-updates", "@CFO what's burn")
        self.assertEqual(agent, "cfo_deepagents")  # CFO alias → the conversational deepagents graph
        self.assertEqual(clean, "what's burn")  # the @ROLE token is stripped

    def test_unknown_channel_falls_back(self):
        self.assertIn(b.resolve_target("random-channel", "hi")[0], b._agent_slugs() | {"daily_digest"})


class SenderAuth(unittest.TestCase):
    def test_allowlisted_user_allowed(self):
        self.assertTrue(b.sender_authorized("U08L384N6VD"))

    def test_unknown_user_denied(self):
        self.assertFalse(b.sender_authorized("U_INTRUDER"))


class ContextId(unittest.TestCase):
    def test_stable_per_thread(self):
        # same thread → same contextId (one Slack thread == one LangSmith conversation)
        self.assertEqual(b.context_id("C1", "17.5"), b.context_id("C1", "17.5"))
        self.assertNotEqual(b.context_id("C1", "17.5"), b.context_id("C1", "18.0"))


if __name__ == "__main__":
    unittest.main()
