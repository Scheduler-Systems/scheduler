"""FAILING governance regression (review 2026-06-06): the org-collab router emits delegation
targets the a2a_gate DENIES, so the watcher silently DROPS the hand-off.

WHY THIS IS A REAL DEFECT (not the safe direction it looks like):
  * The fleet's governance claim (tests/test_org_collaboration.py docstring) is "the a2a_gate gates
    EVERY edge". The load-bearing coverage check there
    (GovernanceGatesEveryEdge.test_every_routed_edge_in_the_org_chart_is_granted) ONLY enumerates
    `reports_of(role)` (own-dept delegation) and `worker -> manager` (escalation). It NEVER probes
    the CROSS-department delegation edges that `route_collaboration` case 3d actually produces.
  * Meanwhile DelegationDown.test_cfo_funnel_question_reaches_the_conversion_analyst ASSERTS the
    CFO "delegates" to conversion_growth_analyst — a CMO report the CFO holds NO
    `message:conversion_growth_analyst` grant for. That test passes only because it checks the
    router in ISOLATION, never through the gate. It is a blind-pass: it green-lights an edge the
    gate denies.
  * End to end the gate is fail-CLOSED (good — nothing leaks), but the consequence is that EVERY
    cross-department exec hand-off is dropped: the watcher posts nothing, and the founder's exact
    complaint ("the executives do not pass work to the team") is reintroduced for any item that
    crosses a department boundary.

INVARIANT under test (the one the suite claims but does not enforce): for EVERY (sender,
routed-target) pair `route_collaboration` can emit from any C-suite sender, the a2a_gate must
ALLOW it. The router must never choose a target the sender has no capability to message.

THE FIX is one of: (a) router case 3d hands off to the OWNING PEER EXEC (cfo -> cmo), which is
granted and lets that exec delegate inside its own dept; or (b) add the cross-dept
`message:<foreign_report>` grants to every exec in capabilities.yaml. Until then this test fails.

Loaded by path so it runs in the deps-free CI venv (mirrors tests/test_org_collaboration.py).
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
WATCHER = _load("channel_watcher", "scripts/channel_watcher.py")
CAPS = yaml.safe_load((ROOT / "docs" / "governance" / "capabilities.yaml").read_text())


def _gate(from_role: str, to_role: str) -> dict:
    src = C.ROLE_TO_GRAPH.get(from_role, from_role)
    tgt = C.ROLE_TO_GRAPH.get(to_role, to_role)
    return G.gate_a2a(src, tgt, "x", capabilities=CAPS, report_only=True)


# Messages that fall in some OTHER department's lane (one per non-CEO department), so a C-suite
# sender outside that department triggers the cross-dept delegation path (route case 3d).
_CROSS_DEPT_PROBES = (
    "what is our conversion funnel and MRR trend",            # growth lane -> a CMO report
    "reposition the store listing keyword metadata for aso",  # growth/aso lane -> a CMO report
    "the scheduler-web deploy needs a playwright e2e test",   # cto lane -> an engineering report
    "store health sku purchasability offering drift",         # coo lane -> an ops report
    "the android espresso regression test suite is failing",  # qa/cto lane -> an engineering report
)


class RouterAndGateMustAgree(unittest.TestCase):
    def test_router_never_emits_an_edge_the_gate_denies(self):
        """UNIVERSAL invariant: every (sender, routed-target) the router can emit must be
        gate-ALLOWED. Any denied edge is a routed hand-off the watcher silently drops."""
        denied = []
        for sender in C.COLLAB_ROLES:
            for msg in _CROSS_DEPT_PROBES:
                target, reason = C.route_collaboration(msg, from_role=sender)
                if target is None or target == sender:
                    continue
                if not _gate(sender, target)["allowed"]:
                    denied.append((sender, target, reason))
        self.assertEqual(
            denied, [],
            "router emitted target(s) the a2a_gate DENIES — the watcher will DROP these turns, "
            "killing the cross-department hand-off:\n  "
            + "\n  ".join(f"{s} -> {t}  [{r}]" for s, t, r in denied),
        )


class WatcherActuallyDeliversTheHandoff(unittest.TestCase):
    """End-to-end proof: drive the REAL watcher chain with the REAL gate and the REAL manifest;
    a cross-dept item must result in SOME teammate posting (the hand-off lands)."""

    class _RealGate:
        @staticmethod
        def gate_a2a(src, tgt, text, capabilities=None, report_only=True, **kw):
            return G.gate_a2a(src, tgt, text, capabilities=CAPS, report_only=True)

    def _wire(self):
        WATCHER._collab = C
        WATCHER._a2a = self._RealGate
        WATCHER._CAPS = CAPS
        posts: list = []
        WATCHER._post_labeled = lambda cid, ts, role, body: posts.append((role, body))
        WATCHER.respond = lambda role, text: f"{role} replies"
        return posts

    def test_cfo_funnel_handoff_reaches_a_teammate(self):
        posts = self._wire()
        threads: dict = {}
        WATCHER._drive_collaboration(
            "C1", "finance", "T1",
            "what is our conversion funnel and MRR trend", "cfo", threads)
        self.assertTrue(
            posts,
            "CFO cross-dept hand-off produced NO post: the router picked a CMO report the CFO "
            "has no message grant for, the gate dropped it, and the collaboration silently died.",
        )


if __name__ == "__main__":
    unittest.main()
