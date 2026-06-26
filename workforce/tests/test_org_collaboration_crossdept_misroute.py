"""FAILING regression: the org router emits cross-dept delegation targets the a2a_gate DENIES.

Bug (agent_toolkit/collaboration.py, route_collaboration case 3d "cross-dept report"):
when a C-suite sender posts an item that belongs to a DIFFERENT exec's lane, the router does not
hand off to that peer exec — it reaches PAST the peer straight into the foreign department's WORKER
(e.g. CFO funnel question -> conversion_growth_analyst, a CMO report). But an exec only holds
`message:<own-reports>` + `message:ceo` capability grants (capabilities.yaml). So every such
cross-dept edge `from_role -> foreign_worker` is DEFAULT-DENIED by a2a_gate, and the watcher
(scripts/channel_watcher.py `_collaborate`) DROPS the turn — the collaboration silently dies.

That is exactly the founder's complaint the org-collab feature claims to fix ("the executives do
not pass work to the team"): for any cross-department concern the hand-off never reaches anyone.

The router MUST NOT pick a target the sender has no authority to message. The correct cross-dept
behavior is a PEER hand-off to the owning exec (CFO -> CMO), which the gate allows and which the
exec can then delegate inside its OWN department.

Loaded by path (deps-free CI venv), mirroring tests/test_org_collaboration.py.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _load(name, relpath):
    spec = importlib.util.spec_from_file_location(name, ROOT / relpath)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


C = _load("collaboration", "agent_toolkit/collaboration.py")
G = _load("a2a_gate", "agent_toolkit/a2a_gate.py")
CAPS = yaml.safe_load((ROOT / "docs" / "governance" / "capabilities.yaml").read_text())
GRAPHS = set(json.loads((ROOT / "langgraph.json").read_text())["graphs"])


def _gate(from_role: str, to_role: str) -> dict:
    src = C.ROLE_TO_GRAPH.get(from_role, from_role)
    tgt = C.ROLE_TO_GRAPH.get(to_role, to_role)
    return G.gate_a2a(src, tgt, "x", capabilities=CAPS, report_only=True)


class CrossDeptDelegationIsNotAMisroute(unittest.TestCase):
    def test_router_never_emits_a_target_the_gate_denies(self):
        """UNIVERSAL invariant: for every (sender, routed-target) the router can produce, the
        a2a_gate must ALLOW the edge. The router must not choose a target the sender has no
        capability to message — otherwise the watcher drops the turn and collaboration dies."""
        # One signature message per OTHER department's lane, probed from each C-suite sender.
        probes = [
            "what is our conversion funnel and MRR trend",            # growth lane (cmo report)
            "reposition the store listing keyword metadata for aso",  # cmo/aso lane
            "the scheduler-web deploy needs a playwright e2e test",   # cto lane (web engineer)
            "store health sku purchasability offering drift",         # coo lane
        ]
        misroutes = []
        for sender in C.COLLAB_ROLES:
            for msg in probes:
                target, reason = C.route_collaboration(msg, from_role=sender)
                if target is None or target == sender:
                    continue
                verdict = _gate(sender, target)
                if not verdict["allowed"]:
                    misroutes.append((sender, target, reason))
        self.assertEqual(
            misroutes, [],
            "router emitted target(s) the a2a_gate denies (sender has no message grant) — "
            "the watcher will DROP these, killing the hand-off:\n  "
            + "\n  ".join(f"{s} -> {t}  [{r}]" for s, t, r in misroutes),
        )

    def test_cfo_funnel_question_must_reach_a_messageable_target(self):
        """Concrete case: a CFO funnel/MRR question belongs to the CMO's lane. Whatever the router
        returns, the CFO must actually be ALLOWED to message it (peer CMO, or — only if granted —
        a report). Today it returns conversion_growth_analyst, which the CFO cannot message."""
        target, reason = C.route_collaboration(
            "what is our conversion funnel and MRR trend", from_role="cfo")
        self.assertIsNotNone(target, "CFO cross-dept item routed nowhere")
        verdict = _gate("cfo", target)
        self.assertTrue(
            verdict["allowed"],
            f"router sent CFO -> {target} ({reason}) but the gate DENIES it: {verdict['reason']}",
        )

    def test_every_crossdept_routed_edge_is_gate_granted(self):
        """The governance suite only checks reports_of(role) and worker->manager edges. The router
        ALSO produces cross-dept delegation edges (case 3d). Those must be granted too."""
        # cross-dept item: a deploy/test item raised by NON-cto execs (cto's lane).
        for sender in ("cfo", "cmo", "coo", "ceo"):
            target, reason = C.route_collaboration(
                "the scheduler-web deploy needs a playwright e2e test", from_role=sender)
            if target is None or target == sender:
                continue
            verdict = _gate(sender, target)
            self.assertTrue(
                verdict["allowed"],
                f"cross-dept edge {sender} -> {target} ({reason}) is NOT gate-allowed: "
                f"{verdict['reason']}",
            )


# End-to-end: prove the watcher actually DROPS the misrouted turn (collaboration silently dies).
WATCHER = _load("channel_watcher", "scripts/channel_watcher.py")


class _RealGate:
    @staticmethod
    def gate_a2a(src, tgt, text, capabilities=None, report_only=True, **kw):
        return G.gate_a2a(src, tgt, text, capabilities=CAPS, report_only=True)


class WatcherDropsTheCrossDeptHandoff(unittest.TestCase):
    def _wire(self):
        WATCHER._collab = C
        WATCHER._a2a = _RealGate
        WATCHER._CAPS = CAPS
        posts: list = []
        WATCHER._post_labeled = lambda cid, ts, role, body: posts.append((role, body))
        WATCHER.respond = lambda role, text: f"{role} replies"
        return posts

    def test_cfo_funnel_handoff_actually_reaches_a_teammate(self):
        """Under the REAL gate, a CFO funnel question in the finance lane must result in SOME
        teammate actually posting (the hand-off lands). Today nothing posts: the router picks
        conversion_growth_analyst, the gate denies CFO->that-worker, and the turn is dropped."""
        posts = self._wire()
        threads: dict = {}
        WATCHER._drive_collaboration(
            "C1", "finance", "T1",
            "what is our conversion funnel and MRR trend", "cfo", threads)
        self.assertTrue(
            posts,
            "CFO cross-dept hand-off produced NO post — the gate dropped the misrouted turn and "
            "the collaboration silently died (the founder's exact complaint).",
        )


if __name__ == "__main__":
    unittest.main()
