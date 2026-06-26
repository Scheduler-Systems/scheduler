"""Integration test for the channel_watcher loop-prevention (NOT just the pure router).

tests/test_collaboration.py proves the *pure* router caps a thread at MAX_DEPTH. But the actual
loop-prevention lives in scripts/channel_watcher.py: the per-thread depth counter (`threads` map)
that route_collaboration is FED, plus the map-size guard that trims that counter. The router can be
perfect and the watcher can STILL ping-pong forever if the counter that enforces the cap is dropped
while the thread is live.

This test drives the REAL watcher functions (`_drive_collaboration`, `_collaborate`) — with the
router injected and Slack/respond stubbed — and asserts the cap actually holds across the watcher's
own map-trim. It currently FAILS: the trim in main() evicts an active thread's depth counter AND its
`:escalated` guard (oldest-by-insertion-order, and re-touching a key does NOT refresh its order), so
a SETTLED, already-escalated thread re-bounces a full MAX_DEPTH round and re-escalates to Shay.

Loaded by path so it runs in the deps-free CI venv (collaboration.py is pure; the watcher's own
`from agent_toolkit import collaboration` pulls heavy ML deps and fails there — which is itself why
this integration path is otherwise untested).
"""
from __future__ import annotations

import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _load_path(name, relpath):
    spec = importlib.util.spec_from_file_location(name, ROOT / relpath)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


COLLAB = _load_path("collaboration", "agent_toolkit/collaboration.py")
WATCHER = _load_path("channel_watcher", "scripts/channel_watcher.py")


class _AllowGate:
    """Permissive A2A gate stub: every internal turn allowed (matches the real grants for the
    cfo<->ceo budget bounce, which ARE granted, so the gate is not what stops this loop)."""

    @staticmethod
    def gate_a2a(src, tgt, text, capabilities=None, report_only=True, **kw):
        return {"allowed": True, "reason": "test-allow"}


class _GateStallsMidChain:
    """A gate that DENIES exactly one mid-chain delegation edge (the qa lead → its report
    cross-dept hand-off) and allows everything else.

    This models a real, common condition: a transient gate denial (a not-yet-granted manager↔report
    edge, a fail-closed HITL, a rate-limit) that makes `_drive_collaboration` return EARLY — leaving
    the DEEPER org-chain thread LIVE at an intermediate depth (1 < depth < MAX_DEPTH) instead of fully
    settling at the cap. That is the state the longer delegation/escalation chain spends most of its
    poll-cycles in, and it is exactly the state the trim must not be allowed to forget.
    """

    @staticmethod
    def gate_a2a(src, tgt, text, capabilities=None, report_only=True, **kw):
        # 'qa' routes to its graph name 'qa_lead_aggregator' (ROLE_TO_GRAPH) — deny the qa→report
        # delegation so the cto→web→qa chain stalls at depth 2 (a hot, unresolved deeper thread).
        if src == COLLAB.ROLE_TO_GRAPH.get("qa", "qa"):
            return {"allowed": False, "reason": "transient-deny (ungranted/HITL/rate-limit)"}
        return {"allowed": True, "reason": "test-allow"}


def _wire_watcher(gate=_AllowGate):
    """Inject the real router + a gate, and capture posts instead of calling Slack."""
    WATCHER._collab = COLLAB
    WATCHER._a2a = gate
    WATCHER._CAPS = {}
    posts: list = []
    WATCHER._post_labeled = lambda cid, thread_ts, role, body: posts.append((thread_ts, role, body))
    WATCHER.respond = lambda role, text: f"{role} replies"
    return posts


def _trim_threads(threads: dict) -> None:
    """Run the REAL map-trim from channel_watcher.main() (runs once per poll iteration).

    This deliberately calls the PRODUCTION trim (not a local copy) so the test validates the actual
    shipped loop-cap maintenance: the fix is correct only if the production trim refuses to evict a
    key that still enforces the cap (a settled thread's counter or its `:escalated` guard).
    """
    WATCHER._trim_threads(threads)


class WatcherLoopCapHolds(unittest.TestCase):
    def test_settled_thread_does_not_rebounce_after_map_trim(self):
        posts = _wire_watcher()
        threads: dict = {}
        budget = "we are over budget and burning runway"

        # 1) A budget thread bounces CFO<->CEO and SETTLES at MAX_DEPTH, escalating once to Shay.
        WATCHER._drive_collaboration("C1", "executive-updates", "T1", budget, "cfo", threads)
        self.assertEqual(threads.get("T1"), COLLAB.MAX_DEPTH, "thread should be capped at MAX_DEPTH")
        self.assertTrue(threads.get("T1:escalated"), "settled thread should be marked escalated")
        first_round_posts = len(posts)

        # 2) The watcher's own map-size guard fires (long-lived, busy watcher accumulates >4000
        #    threads). Re-touching threads['T1'] during the bounce did NOT move it to the end, so the
        #    HOT, still-active thread sits at an early insertion position and is evicted FIRST.
        for i in range(4100):
            threads[f"other-{i}"] = 1
        _trim_threads(threads)

        # 3) A new agent turn lands on the SAME, still-active thread T1 (its channel cursor has not
        #    advanced past it). With the cap counter evicted, the watcher MUST NOT let the settled
        #    thread ping-pong again or re-escalate.
        posts.clear()
        WATCHER._drive_collaboration("C1", "executive-updates", "T1", budget, "cfo", threads)

        self.assertEqual(
            len(posts), 0,
            f"RUNAWAY: settled+escalated thread re-bounced after the map-trim evicted its depth "
            f"counter — {len(posts)} new posts (incl. a duplicate 'escalating to Shay'). "
            f"First round posted {first_round_posts}; the cap must survive the trim.",
        )

    def test_hot_midchain_deeper_thread_is_not_evicted_then_rebounced(self):
        """A LIVE deeper-chain thread stalled mid-bounce (depth 1..MAX_DEPTH-1) must NOT be evicted.

        The DEEPER org chain — exec DELEGATES down, worker ESCALATES up — makes a chain up to
        MAX_DEPTH agent turns long, so a thread spends most of its life at an INTERMEDIATE depth, not
        at the cap. A chain can pause there across polls: a transient gate denial (a not-yet-granted
        manager↔report edge, a fail-closed HITL, a rate-limit) makes `_drive_collaboration` return
        early, leaving the thread LIVE and unresolved at e.g. depth 2.

        But `_is_pinned` only pins a counter at/above MAX_DEPTH (fully settled) or an `:escalated`
        guard — a hot thread paused at depth 2 is treated as EVICTABLE. When a busy, long-lived
        watcher's map-trim fires, that live counter is dropped; the SAME unresolved thread is then
        fed depth 0 by `route_collaboration` and gets a SECOND full delegation/escalation round of up
        to MAX_DEPTH turns layered on top of the turns it already took, ending in a fresh 'escalating
        to Shay'. The invariant the loop-cap exists to guarantee — at most MAX_DEPTH agent turns and
        at most ONE page to the founder PER THREAD — is violated.

        This drives the REAL watcher glue (`_drive_collaboration` + the production `_trim_threads`),
        counting agent turns across the thread's WHOLE life, and currently FAILS.
        """
        posts = _wire_watcher(_GateStallsMidChain)
        threads: dict = {}
        # A cto-owned web-deploy item: cto -> web_automation_engineer -> qa -> (qa's report)…
        deploy = "the scheduler-web deploy needs a playwright e2e test"

        # 1) The gate stalls the chain at the qa→report hand-off, so the thread is left LIVE at an
        #    intermediate depth (1 < depth < MAX_DEPTH) — unresolved, NOT yet at the cap.
        WATCHER._drive_collaboration("C1", "engineering", "T1", deploy, "cto", threads)
        stalled_depth = int(threads.get("T1", 0))
        self.assertGreater(stalled_depth, 0, "chain should have advanced at least one agent turn")
        self.assertLess(stalled_depth, COLLAB.MAX_DEPTH,
                        "gate should have stalled the deeper chain BELOW the cap (hot, live thread)")
        turns_round1 = sum(1 for p in posts if "replies" in p[2])

        # 2) The watcher's map-size guard fires on a busy, long-lived watcher.
        for i in range(4100):
            threads[f"other-{i}"] = 1
        _trim_threads(threads)

        # 3) The SAME live thread keeps getting agent turns (its channel cursor hasn't passed it). The
        #    transient denial has cleared, so a permissive gate now lets every turn through. If the
        #    depth counter survived the trim the chain RESUMES (and finishes within the cap); if it
        #    was evicted, the thread re-bounces from scratch — exceeding the cap and re-paging Shay.
        WATCHER._a2a = _AllowGate
        WATCHER._drive_collaboration("C1", "engineering", "T1", deploy, "cto", threads)

        total_turns = sum(1 for p in posts if "replies" in p[2])
        escalations = [p for p in posts if "escalating to Shay" in p[2]]

        # The whole point of the cap: a single thread NEVER takes more than MAX_DEPTH agent turns and
        # NEVER pages the founder more than once — regardless of how many trims fire mid-chain.
        self.assertLessEqual(
            total_turns, COLLAB.MAX_DEPTH,
            f"RUNAWAY: a hot mid-chain deeper thread (stalled at depth {stalled_depth}, "
            f"{turns_round1} turn(s)) had its cap counter evicted by the trim, then re-bounced from "
            f"depth 0 — {total_turns} total agent turns on ONE thread vs cap {COLLAB.MAX_DEPTH}. A "
            f"live thread below the cap must be pinned against the trim too, not just one at/over it.",
        )
        self.assertLessEqual(
            len(escalations), 1,
            f"RUNAWAY: the evicted live thread re-escalated — {len(escalations)} pages to the "
            f"founder for ONE thread. The loop cap must survive the trim for in-flight threads.",
        )


if __name__ == "__main__":
    unittest.main()
