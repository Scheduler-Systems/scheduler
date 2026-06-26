"""Unit tests for the Slack collaboration router (agent_toolkit/collaboration.py).

Proves the team COLLABORATES (a peer chimes in on another's lane) without ping-ponging forever:
in-lane routing, self-reply suppression, explicit-address override, the MAX_DEPTH cap, and — the
load-bearing one — that an A->B->A exchange TERMINATES within MAX_DEPTH turns (no infinite loop).

Loaded by path so it runs in the deps-free CI venv (collaboration.py is pure, no heavy imports).
"""
from __future__ import annotations

import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "agent_toolkit" / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


C = _load("collaboration")


class InLaneRouting(unittest.TestCase):
    def test_cfo_over_budget_routes_to_ceo(self):
        # CFO flags a budget problem in its own lane → escalates to a DIFFERENT, in-lane peer (CEO).
        target, reason = C.route_collaboration("we are over budget", from_role="cfo")
        self.assertEqual(target, "ceo")
        self.assertNotEqual(target, "cfo")          # a DIFFERENT agent
        self.assertIn(target, C.COLLAB_ROLES)        # a REAL agent

    def test_ceo_budget_message_routes_to_cfo(self):
        # The CEO raising a budget topic pulls in the lane owner (CFO).
        target, _ = C.route_collaboration("can we afford this budget?", from_role="ceo")
        self.assertEqual(target, "cfo")
        self.assertNotEqual(target, "ceo")

    def test_deploy_routes_to_cto(self):
        target, _ = C.route_collaboration("the deploy looks risky", from_role="qa")
        self.assertEqual(target, "cto")

    def test_coverage_routes_through_a_reachable_peer(self):
        # "coverage" → qa lane, "PR" → cto lane; the owning exec (qa/cto) is in a DIFFERENT
        # department. The COO holds NO message grant for qa/cto (only message:ceo), so a direct
        # COO -> qa/cto edge would be gate-DENIED and the watcher would drop it. The router must
        # therefore hand the cross-dept item to a GATE-REACHABLE peer — the CEO arbiter — who can
        # route it onward into the owning lane. Never the sender itself.
        target, _ = C.route_collaboration("coverage dropped on this PR", from_role="coo")
        self.assertEqual(target, "ceo")
        self.assertNotEqual(target, "coo")


class OffLaneAndSelf(unittest.TestCase):
    def test_off_lane_lunch_routes_to_nobody(self):
        target, reason = C.route_collaboration("lunch?", from_role="cfo")
        self.assertIsNone(target)

    def test_agent_never_routes_to_itself(self):
        # An explicit self-address is a no-op (you addressed yourself).
        target, _ = C.route_collaboration("@CFO what's the burn?", from_role="cfo")
        self.assertIsNone(target)
        # And the CEO posting in its own (ceo) lane has no escalation peer → no self-reply.
        target2, _ = C.route_collaboration("what's our strategy and priority?", from_role="ceo")
        self.assertIsNone(target2)

    def test_no_self_route_across_every_role(self):
        # For each role, a message squarely in its OWN lane must never return itself.
        own_lane = {
            "cfo": "the budget burn is high",
            "cto": "the deploy and CI are red",
            "qa": "test coverage regression",
            "cmo": "growth funnel conversion",
            "coo": "fleet ops health blocker",
            "ceo": "company strategy and priority decision",
        }
        for role, msg in own_lane.items():
            target, _ = C.route_collaboration(msg, from_role=role)
            self.assertNotEqual(target, role, f"{role} routed to itself on {msg!r}")


class DepthCap(unittest.TestCase):
    def test_at_max_depth_returns_settled(self):
        target, reason = C.route_collaboration("we are over budget", from_role="cfo",
                                               thread_depth=C.MAX_DEPTH)
        self.assertIsNone(target)
        self.assertEqual(reason, "settled")

    def test_over_max_depth_returns_settled(self):
        target, reason = C.route_collaboration("deploy now", from_role="qa",
                                               thread_depth=C.MAX_DEPTH + 5)
        self.assertIsNone(target)
        self.assertEqual(reason, "settled")


class ExplicitAddressOverridesLane(unittest.TestCase):
    def test_at_cto_overrides_budget_lane(self):
        # The text is about "budget" (cfo lane) but explicitly addresses @CTO → CTO wins.
        target, reason = C.route_collaboration("@CTO is the budget tooling deployed?", from_role="ceo")
        self.assertEqual(target, "cto")
        self.assertIn("explicit", reason)

    def test_comma_address_form(self):
        # The 'ROLE,' comma form is an explicit address. From a sender GRANTED to message that peer
        # (the CEO may message every exec) it routes there directly.
        target, reason = C.route_collaboration("CFO, what's our runway?", from_role="ceo")
        self.assertEqual(target, "cfo")
        self.assertIn("explicit", reason)

    def test_comma_address_to_unreachable_peer_goes_via_arbiter(self):
        # The comma form still parses as an address, but the COO holds NO message grant for the CFO
        # (only message:ceo). The router must NOT emit the gate-denied COO -> CFO edge; it hands the
        # item to the CEO arbiter (reachable by all execs), who can pull in the CFO on the next turn.
        target, _ = C.route_collaboration("CFO, what's our runway?", from_role="coo")
        self.assertEqual(target, "ceo")
        self.assertNotEqual(target, "coo")


class LoopTerminates(unittest.TestCase):
    def test_a_to_b_to_a_terminates_within_max_depth(self):
        """Simulate the watcher's loop: A posts, B auto-replies, A auto-replies… each agent turn
        increments the thread depth. Assert the chain STOPS within MAX_DEPTH turns — no infinite
        ping-pong — exactly as the watcher caps it."""
        # A budget thread is the worst case: it bounces CFO <-> CEO every turn.
        speaker = "cfo"
        text = "we are over budget and burning runway"
        depth = 0
        turns = []
        # Guard the harness itself: if routing ever fails to terminate, this hard cap trips the test.
        for _ in range(50):
            target, reason = C.route_collaboration(text, from_role=speaker, thread_depth=depth)
            if target is None:
                self.assertEqual(reason, "settled")
                break
            self.assertNotEqual(target, speaker)     # never self-route, even mid-loop
            turns.append((speaker, target, depth))
            speaker = target                          # B becomes the next speaker (A->B->A…)
            depth += 1                                # each agent auto-reply increments thread depth
        else:
            self.fail("route_collaboration never terminated — infinite loop")

        self.assertLessEqual(len(turns), C.MAX_DEPTH, "more agent turns than MAX_DEPTH allows")
        self.assertEqual(depth, C.MAX_DEPTH, "loop must stop exactly at the depth cap")

    def test_off_lane_thread_dies_immediately(self):
        target, _ = C.route_collaboration("anyone up for lunch?", from_role="ceo", thread_depth=0)
        self.assertIsNone(target)


class IncidentalMentionIsNotAnAddress(unittest.TestCase):
    """A bare role/department word occurring anywhere in prose is an incidental MENTION, not an
    explicit @address. It must NOT (a) summon that peer on off-lane chatter [spam / wrong-responder],
    nor (b) suppress a legitimate own-lane escalation when the sender names its own role."""

    def test_incidental_alias_word_does_not_summon_a_peer(self):
        # "every agent chimes on everything that names its department" — must NOT happen.
        casual = [
            "the marketing numbers look great today",    # 'marketing' (cmo) — but off-lane chatter
            "our ops are running smoothly",              # 'ops' (coo)
            "nice engineering blog post",                # 'engineering' (cto)
            "I really enjoy QA work",                    # 'qa'
        ]
        for text in casual:
            target, reason = C.route_collaboration(text, from_role="ceo", thread_depth=0)
            self.assertIsNone(
                target,
                f"incidental word in {text!r} wrongly summoned {target!r} ({reason}) — "
                f"a bare alias mention must not route",
            )

    def test_incidental_self_mention_still_escalates(self):
        # A CFO flagging a budget problem must escalate to the CEO even if it names 'cfo' in prose.
        t, r = C.route_collaboration("the cfo says we are over budget", from_role="cfo")
        self.assertEqual(t, "ceo", f"incidental self-mention suppressed escalation (got {t!r}: {r})")

    def test_incidental_self_mention_cto_deploy_still_escalates(self):
        t, r = C.route_collaboration("this deploy from the cto is risky", from_role="cto")
        self.assertEqual(t, "ceo", f"incidental self-mention suppressed escalation (got {t!r}: {r})")

    def test_explicit_self_address_still_suppresses(self):
        # The STRONG self-address forms remain no-ops (you addressed yourself, nothing to do).
        self.assertIsNone(C.route_collaboration("@CFO what's the burn?", from_role="cfo")[0])
        self.assertIsNone(C.route_collaboration("CTO: our deploy is broken", from_role="cto")[0])

    def test_strong_cross_address_still_overrides_lane(self):
        # Strong @address / 'ROLE,' forms must still override the lane (regression guard for the fix).
        # From a sender GRANTED to message the addressed peer, the address routes there directly: the
        # CEO may message every exec, so @CTO from the CEO wins over the "budget" (cfo) lane.
        self.assertEqual(
            C.route_collaboration("@CTO is the budget tooling deployed?", from_role="ceo")[0], "cto")
        # When the addressed peer is NOT reachable from the sender (COO holds only message:ceo), the
        # address is honored as a cross-dept hand-off via the CEO arbiter — never the gate-denied
        # COO -> CFO edge. The address still overrides the lane (it does NOT fall back to off-lane).
        self.assertEqual(
            C.route_collaboration("CFO, what's our runway?", from_role="coo")[0], "ceo")


class RoleGraphMapping(unittest.TestCase):
    def test_every_collab_role_maps_to_a_graph(self):
        for role in C.COLLAB_ROLES:
            self.assertIn(role, C.ROLE_TO_GRAPH)
            self.assertTrue(C.ROLE_TO_GRAPH[role])

    def test_qa_maps_to_aggregator_graph(self):
        self.assertEqual(C.ROLE_TO_GRAPH["qa"], "qa_lead_aggregator")


if __name__ == "__main__":
    unittest.main()
