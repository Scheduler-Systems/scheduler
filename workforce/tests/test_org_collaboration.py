"""Org-aware collaboration tests (agent_toolkit/collaboration.py + scripts/channel_watcher.py).

The founder's complaint was "the executives do not pass work to the team; I do not see enough
collaboration." This proves the fix: collaboration now follows the ORG CHART loaded from
roster.yaml — execs DELEGATE down to the right report, workers ESCALATE up to their manager, the
chain still TERMINATES under a hard cap, a worker never triggers itself, off-org/cross-dept
misroutes are blocked, the WORKER agents actually respond, and the a2a_gate gates EVERY edge.

Loaded by path so it runs in the deps-free CI venv (collaboration/a2a_gate are pure; the watcher's
own `from agent_toolkit import …` pulls heavy ML deps and fails there — which is why these
integration paths are otherwise untested).
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


# =================================================================================================
# 1. ORG-CHART LOADER — manager_of / reports_of / dept_of from roster.yaml
# =================================================================================================
class OrgChartFromRoster(unittest.TestCase):
    def test_dept_of_reads_roster_org_groups(self):
        self.assertEqual(C.dept_of("web_automation_engineer"), "qa")
        self.assertEqual(C.dept_of("conversion_growth_analyst"), "growth")
        self.assertEqual(C.dept_of("revenue_reporter"), "ops")
        self.assertEqual(C.dept_of("ceo"), "executive")
        self.assertEqual(C.dept_of("board_chair"), "board")

    def test_manager_of_is_the_dept_csuite_role(self):
        # growth -> cmo, ops -> coo, qa workers -> qa lead, board -> ceo.
        self.assertEqual(C.manager_of("conversion_growth_analyst"), "cmo")
        self.assertEqual(C.manager_of("aso_store_listing_agent"), "cmo")
        self.assertEqual(C.manager_of("revenue_reporter"), "coo")
        self.assertEqual(C.manager_of("store_health_checker"), "coo")
        self.assertEqual(C.manager_of("web_automation_engineer"), "qa")
        self.assertEqual(C.manager_of("web_manual_tester"), "qa")
        self.assertEqual(C.manager_of("board_chair"), "ceo")

    def test_reports_of_lists_only_deployed_in_dept_reports(self):
        self.assertEqual(set(C.reports_of("cmo")),
                         {"conversion_growth_analyst", "aso_store_listing_agent", "content_campaign_drafter"})
        self.assertEqual(set(C.reports_of("coo")),
                         {"revenue_reporter", "store_health_checker", "email_triage", "daily_digest"})
        # CTO delegates to the engineering-tier qa workers (operational reach) PLUS its own
        # platform department report (Lennox owns the LangSmith runtime under the CTO).
        self.assertEqual(set(C.reports_of("cto")),
                         {"web_automation_engineer", "android_automation_engineer",
                          "ios_automation_engineer", "platform_specialist"})

    def test_roster_only_agents_are_never_delegation_targets(self):
        # git_sync_auditor / memory_sync are LOCAL launchd workers (not deployed LangSmith graphs),
        # so as of 2026-06-07 they are NOT on the deployed-workforce roster at all (removed from
        # roster.yaml org.ops to kill the "ghost employee" confusion — see roster.yaml note +
        # docs/ops-fleet/local-only-agents.md). They therefore have NO department and are NEVER
        # offered as a delegation target (no channel, no capability grant).
        self.assertIsNone(C.dept_of("git_sync_auditor"))
        self.assertIsNone(C.dept_of("memory_sync"))
        self.assertNotIn("git_sync_auditor", C.reports_of("coo"))
        self.assertNotIn("memory_sync", C.reports_of("coo"))

    def test_execs_are_not_workers(self):
        for exec_role in C.COLLAB_ROLES:
            self.assertFalse(C.load_org_chart().is_worker(exec_role), f"{exec_role} wrongly a worker")
        self.assertTrue(C.load_org_chart().is_worker("web_automation_engineer"))


# =================================================================================================
# 2. DELEGATION (down) — an exec hands the specific piece to the right in-dept report
# =================================================================================================
class DelegationDown(unittest.TestCase):
    def test_cto_deploy_item_delegates_to_web_engineer(self):
        # The founder's example: a web-deploy/test item under the CTO routes to the web engineer.
        target, reason = C.route_collaboration(
            "the scheduler-web deploy needs a playwright e2e test", from_role="cto")
        self.assertEqual(target, "web_automation_engineer")
        self.assertIn("delegation", reason)
        # And it's a REPORT in the CTO's department (an actual hand-off down, not a peer).
        self.assertIn(target, C.reports_of("cto"))

    def test_cto_android_item_delegates_to_android_engineer(self):
        target, _ = C.route_collaboration(
            "the scheduler-android espresso suite is failing on the deploy", from_role="cto")
        self.assertEqual(target, "android_automation_engineer")

    def test_cmo_listing_item_delegates_to_aso_agent(self):
        target, reason = C.route_collaboration(
            "we should reposition the store listing for ASO", from_role="cmo")
        self.assertEqual(target, "aso_store_listing_agent")
        self.assertIn("delegation", reason)

    def test_cfo_funnel_question_hands_off_to_a_messageable_peer(self):
        # A CFO funnel/MRR question belongs to the CMO's lane (a DIFFERENT department). The CFO holds
        # NO message grant for the CMO or any CMO report (only message:ceo), so the router must NOT
        # reach past the peer into conversion_growth_analyst (the gate would deny that and the watcher
        # would silently drop the hand-off — the founder's exact complaint). It hands the item to the
        # CEO arbiter (the only peer the CFO can message), who routes it onward into the growth lane.
        target, reason = C.route_collaboration(
            "what is our conversion funnel and MRR trend", from_role="cfo")
        self.assertEqual(target, "ceo")
        # And the chosen target is one the CFO is actually GRANTED to message (gate-allowed).
        self.assertTrue(G.gate_a2a(
            C.ROLE_TO_GRAPH.get("cfo", "cfo"), C.ROLE_TO_GRAPH.get(target, target),
            "x", capabilities=CAPS, report_only=True)["allowed"],
            f"router emitted CFO -> {target} ({reason}) which the a2a_gate denies")

    def test_one_report_per_turn_no_fanout(self):
        # route returns a SINGLE report, never a set — no fan-out to the whole department.
        target, _ = C.route_collaboration(
            "web deploy test and android deploy test and ios deploy test", from_role="cto")
        self.assertIsInstance(target, str)
        self.assertIn(target, C.reports_of("cto"))


# =================================================================================================
# 3. ESCALATION (up) — a worker goes to its manager, never sideways / never skips to CEO
# =================================================================================================
class EscalationUp(unittest.TestCase):
    def test_worker_escalates_to_its_manager(self):
        target, reason = C.route_collaboration(
            "this web test failure exceeds my scope", from_role="web_automation_engineer")
        self.assertEqual(target, "qa")                       # its manager (qa lead)
        self.assertEqual(target, C.manager_of("web_automation_engineer"))
        self.assertIn("escalation", reason)

    def test_growth_worker_escalates_to_cmo_not_sideways(self):
        target, _ = C.route_collaboration("found a funnel anomaly beyond me",
                                          from_role="conversion_growth_analyst")
        self.assertEqual(target, "cmo")
        # NOT to a peer growth worker, NOT straight to the CEO.
        self.assertNotIn(target, ("aso_store_listing_agent", "content_campaign_drafter", "ceo"))

    def test_ops_worker_escalates_to_coo(self):
        target, _ = C.route_collaboration("store SKU not purchasable, beyond me",
                                          from_role="store_health_checker")
        self.assertEqual(target, "coo")

    def test_worker_never_skips_level_to_ceo(self):
        # Even a 'strategy/priority/decision' (CEO-lane) message from a worker goes to its MANAGER,
        # never straight to the CEO — only the manager may escalate further up.
        target, _ = C.route_collaboration(
            "this is a company strategy priority decision", from_role="web_automation_engineer")
        self.assertEqual(target, "qa")
        self.assertNotEqual(target, "ceo")

    def test_worker_never_addresses_a_peer_outside_its_lane(self):
        # A worker shouting another department's keyword still only reaches its own manager.
        target, _ = C.route_collaboration("the marketing growth funnel looks off",
                                          from_role="web_automation_engineer")
        self.assertEqual(target, "qa")
        self.assertNotIn(target, ("cmo", "conversion_growth_analyst"))


# =================================================================================================
# 4. NO SELF-TRIGGER — a worker (or exec) is never routed to itself
# =================================================================================================
class NoSelfTrigger(unittest.TestCase):
    def test_worker_never_self_triggers(self):
        # A worker speaking squarely in its own skill area routes to its MANAGER, never itself.
        for w, msg in [
            ("web_automation_engineer", "web web web deploy test playwright"),
            ("aso_store_listing_agent", "aso aso store listing keyword metadata"),
            ("revenue_reporter", "revenue report weekly digest pipeline"),
        ]:
            target, _ = C.route_collaboration(msg, from_role=w)
            self.assertNotEqual(target, w, f"{w} self-triggered")
            self.assertEqual(target, C.manager_of(w))

    def test_exec_delegating_never_picks_itself_as_report(self):
        # An exec is not its own report; delegation always lands on a DIFFERENT agent.
        for role in C.COLLAB_ROLES:
            self.assertNotIn(role, C.reports_of(role), f"{role} is its own report")


# =================================================================================================
# 5. LOOP TERMINATION — even with delegation+escalation the chain settles within the cap
# =================================================================================================
class LoopTerminates(unittest.TestCase):
    def _run_chain(self, seed_role, text):
        speaker, depth, turns = seed_role, 0, []
        for _ in range(60):  # harness backstop — a true infinite loop trips this, failing the test
            target, reason = C.route_collaboration(text, from_role=speaker, thread_depth=depth)
            if target is None:
                self.assertEqual(reason, "settled")
                return turns, depth
            self.assertNotEqual(target, speaker, f"SELF-ROUTE at depth {depth}")
            turns.append((speaker, target))
            speaker, depth = target, depth + 1
        self.fail("route_collaboration never terminated — infinite loop")

    def test_exec_to_exec_budget_bounce_terminates(self):
        turns, depth = self._run_chain("cfo", "we are over budget and burning runway")
        self.assertLessEqual(len(turns), C.MAX_DEPTH)
        self.assertEqual(depth, C.MAX_DEPTH)

    def test_delegation_escalation_chain_terminates(self):
        # cto -> web eng -> qa -> web eng -> … : the DEEPER org chain still terminates at the cap.
        turns, depth = self._run_chain(
            "cto", "the scheduler-web deploy needs a playwright e2e test")
        self.assertLessEqual(len(turns), C.MAX_DEPTH)
        self.assertEqual(depth, C.MAX_DEPTH, "delegation chain must stop exactly at the cap")

    def test_worker_seeded_chain_terminates(self):
        turns, depth = self._run_chain(
            "web_automation_engineer", "web deploy test failure beyond scope")
        self.assertLessEqual(len(turns), C.MAX_DEPTH)
        self.assertEqual(depth, C.MAX_DEPTH)

    def test_growth_delegation_chain_terminates(self):
        turns, depth = self._run_chain("cfo", "what is our conversion funnel and MRR trend")
        self.assertLessEqual(len(turns), C.MAX_DEPTH)

    def test_bound_is_a_hard_cap_not_a_soft_target(self):
        # At/over the cap the router settles regardless of how the chain is shaped.
        for role in ("cfo", "cto", "web_automation_engineer", "conversion_growth_analyst"):
            t, r = C.route_collaboration("anything at all", from_role=role, thread_depth=C.MAX_DEPTH)
            self.assertIsNone(t)
            self.assertEqual(r, "settled")


# =================================================================================================
# 6. MISROUTING BLOCKED — off-org / cross-dept / peer-worker edges are denied
# =================================================================================================
class MisroutingBlocked(unittest.TestCase):
    def test_off_lane_dies_immediately(self):
        self.assertIsNone(C.route_collaboration("anyone up for lunch?", from_role="ceo")[0])
        self.assertIsNone(C.route_collaboration("happy friday everyone", from_role="cto")[0])

    def test_exec_does_not_delegate_outside_its_department(self):
        # The CTO has no growth reports — a growth-flavored item never lands on a growth worker via
        # the CTO. (The router only delegates to reports_of(owning_exec).)
        target, _ = C.route_collaboration("the deploy of the new aso listing copy", from_role="cto")
        self.assertNotIn(target, ("aso_store_listing_agent", "content_campaign_drafter"))

    def test_worker_cannot_be_summoned_by_a_foreign_exec(self):
        # A web-deploy item raised by the CMO does NOT pull a CTO/QA engineering report into the
        # marketing lane — the router routes by the OWNING exec's department, and the CMO owns none
        # of the engineering reports.
        target, _ = C.route_collaboration("the deploy CI build is red", from_role="cmo")
        self.assertNotIn(target, C.reports_of("cto"))


# =================================================================================================
# 7. GOVERNANCE — the a2a_gate gates EVERY delegation/escalation/peer edge (allow grant / deny none)
# =================================================================================================
class GovernanceGatesEveryEdge(unittest.TestCase):
    def _gate(self, from_role, to_role):
        src = C.ROLE_TO_GRAPH.get(from_role, from_role)
        tgt = C.ROLE_TO_GRAPH.get(to_role, to_role)
        return G.gate_a2a(src, tgt, "x", capabilities=CAPS, report_only=True)

    def test_every_routed_edge_in_the_org_chart_is_granted(self):
        """For every (sender, routed-target) the org chart can actually produce, the a2a_gate must
        ALLOW it — i.e. the manager↔report grants were added. This is the load-bearing check that the
        routing and the capability manifest agree."""
        chart = C.load_org_chart()
        edges = set()
        # delegation down: exec -> each of its reports
        for role in C.COLLAB_ROLES:
            for rpt in chart.reports_of(role):
                edges.add((role, rpt))
        # escalation up: each deployed worker -> its manager
        for w in chart.all_workers():
            if w not in GRAPHS:
                continue
            edges.add((w, chart.manager_of(w)))
        self.assertTrue(edges)
        for frm, tgt in sorted(edges):
            v = self._gate(frm, tgt)
            self.assertTrue(v["allowed"], f"org edge {frm} -> {tgt} is NOT gated-allowed: {v['reason']}")

    def test_every_crossdept_edge_the_router_emits_is_granted(self):
        """The check above only enumerates reports_of(role) (own-dept delegation) and worker->manager
        (escalation) edges. But route_collaboration case 3d ALSO emits CROSS-department peer hand-offs.
        This drives the REAL router over signature cross-dept messages from every C-suite sender and
        asserts the gate ALLOWS whatever it returns — closing the false-coverage that let a cross-dept
        misroute (e.g. CFO -> conversion_growth_analyst, gate-denied) ship green."""
        cross_dept_probes = (
            "what is our conversion funnel and MRR trend",            # growth lane
            "reposition the store listing keyword metadata for aso",  # growth/aso lane
            "the scheduler-web deploy needs a playwright e2e test",   # cto lane
            "store health sku purchasability offering drift",         # coo lane
            "the android espresso regression test suite is failing",  # qa/cto lane
            "we are over budget and burning runway",                  # cfo lane
        )
        denied = []
        for sender in C.COLLAB_ROLES:
            for msg in cross_dept_probes:
                target, reason = C.route_collaboration(msg, from_role=sender)
                if target is None or target == sender:
                    continue
                if not self._gate(sender, target)["allowed"]:
                    denied.append(f"{sender} -> {target}  [{reason}]")
        self.assertEqual(
            denied, [],
            "route_collaboration emitted cross-dept edge(s) the a2a_gate DENIES — the watcher drops "
            "these and the hand-off silently dies:\n  " + "\n  ".join(denied))

    def test_off_org_edges_are_denied_default_deny(self):
        for frm, tgt in [
            ("web_automation_engineer", "cmo"),                 # worker -> wrong manager
            ("aso_store_listing_agent", "coo"),                 # growth worker -> ops manager
            ("cto", "conversion_growth_analyst"),               # exec delegate to off-dept worker
            ("revenue_reporter", "cto"),                        # ops worker -> cto
            ("web_automation_engineer", "ios_automation_engineer"),  # peer-to-peer worker
        ]:
            v = self._gate(frm, tgt)
            self.assertFalse(v["allowed"], f"off-org edge {frm} -> {tgt} was wrongly allowed")

    def test_every_edge_has_a_hash_chained_audit_entry(self):
        # Governance is auditable: every gated turn (allowed or denied) emits an audit entry.
        v = self._gate("cto", "web_automation_engineer")
        self.assertIn("hash", v["audit"])
        self.assertTrue(v["audit"]["capability_ok"])
        d = self._gate("revenue_reporter", "cto")
        self.assertFalse(d["audit"]["capability_ok"])


# =================================================================================================
# 8. WORKERS ACTUALLY RESPOND — the watcher responder covers any rostered agent
# =================================================================================================
WATCHER = _load("channel_watcher", "scripts/channel_watcher.py")


class WorkersParticipateInTheWatcher(unittest.TestCase):
    def test_every_worker_has_a_recognizable_slack_label(self):
        # Without a label, a worker's own reply is mistaken for an unlabeled bot post and the
        # escalation chain dies. Every deployed worker must have a unique label the watcher can
        # round-trip back to its role-key.
        for w in C.load_org_chart().all_workers():
            if w not in GRAPHS:
                continue
            self.assertIn(w, WATCHER.ROLE_LABEL, f"worker {w} has no Slack label")
            # round-trip: label -> role (so the watcher recognizes the worker's own turn).
            label = WATCHER.ROLE_LABEL[w]
            self.assertEqual(WATCHER._LABEL_TO_ROLE.get(label), w)

    def test_labels_are_unique_across_roles(self):
        labels = list(WATCHER.ROLE_LABEL.values())
        self.assertEqual(len(labels), len(set(labels)), "duplicate Slack labels collide role-keys")

    def test_worker_reply_is_recognized_as_an_agent_turn(self):
        # A worker's labeled reply must be recoverable as an agent turn (so a DIFFERENT peer/manager
        # can continue the chain — and the worker never re-triggers itself).
        label = WATCHER.ROLE_LABEL["web_automation_engineer"]
        post = f"*{label}*\nweb e2e is green on the deploy."
        self.assertEqual(WATCHER._role_from_agent_text(post), "web_automation_engineer")

    def test_grounded_answer_has_a_persona_for_every_rostered_agent(self):
        # The responder map / persona must cover ANY rostered agent (worker persona derived from the
        # roster role text), so a worker answers in-character rather than being unhandled.
        for w in ("web_automation_engineer", "conversion_growth_analyst", "store_health_checker"):
            persona = WATCHER._persona_for(w)
            self.assertTrue(persona and isinstance(persona, str))
            self.assertNotEqual(persona.strip(), w)  # a real persona, not just the bare key

    def test_worker_graph_module_is_resolvable_for_grounding(self):
        # The grounded answer resolves a worker's OWN graph module (for gather/analyze) from
        # langgraph.json — present for the worker graphs.
        self.assertIn("web_automation_engineer", WATCHER._ROLE_MODULE)
        self.assertTrue(WATCHER._ROLE_MODULE["web_automation_engineer"].startswith("graphs."))


# =================================================================================================
# 9. WATCHER-DRIVEN CHAIN — the real _drive_collaboration delegates+escalates and settles, gated
# =================================================================================================
class _AllowGate:
    """Permissive gate stub that records every (src,tgt) it was asked to gate (proves the watcher
    actually routes EACH turn through the gate)."""
    calls: list = []

    @classmethod
    def gate_a2a(cls, src, tgt, text, capabilities=None, report_only=True, **kw):
        cls.calls.append((src, tgt))
        return {"allowed": True, "reason": "test-allow"}


class _RealGate:
    """The real gate over the real manifest — drops any ungranted edge (proves misroutes are cut)."""
    @staticmethod
    def gate_a2a(src, tgt, text, capabilities=None, report_only=True, **kw):
        return G.gate_a2a(src, tgt, text, capabilities=CAPS, report_only=True)


class WatcherDrivenDelegation(unittest.TestCase):
    def _wire(self, gate):
        WATCHER._collab = C
        WATCHER._a2a = gate
        WATCHER._CAPS = CAPS
        posts: list = []
        WATCHER._post_labeled = lambda cid, ts, role, body: posts.append((role, body))
        WATCHER.respond = lambda role, text: f"{role} replies"
        return posts

    def test_cto_deploy_thread_delegates_to_web_engineer_and_it_answers(self):
        _AllowGate.calls = []
        posts = self._wire(_AllowGate)
        threads: dict = {}
        WATCHER._drive_collaboration(
            "C1", "engineering", "T1",
            "the scheduler-web deploy needs a playwright e2e test", "cto", threads)
        # The web engineer (a report) actually answered in-thread.
        roles_posted = [r for r, _ in posts]
        self.assertIn("web_automation_engineer", roles_posted,
                      f"web engineer did not answer; posts={roles_posted}")
        # And every agent->agent turn went through the gate.
        self.assertTrue(_AllowGate.calls, "no turn was gated")
        self.assertIn(("cto", "web_automation_engineer"),
                      [(s, t) for s, t in _AllowGate.calls])
        # Bounded: never more than MAX_DEPTH agent turns on the thread.
        self.assertLessEqual(int(threads.get("T1", 0)), C.MAX_DEPTH)

    def test_driven_chain_terminates_and_never_exceeds_cap(self):
        self._wire(_AllowGate)
        threads: dict = {}
        WATCHER._drive_collaboration(
            "C1", "engineering", "T1",
            "the scheduler-web deploy needs a playwright e2e test", "cto", threads)
        self.assertLessEqual(int(threads.get("T1", 0)), C.MAX_DEPTH,
                             "watcher let the thread exceed MAX_DEPTH")

    def test_real_gate_blocks_an_ungranted_turn(self):
        # Force a seed whose routed target the sender is NOT granted to message: a worker seed whose
        # only routed edge (to its manager) IS granted — so to prove the DROP we check a denied edge
        # directly is not posted. Use a manufactured ungranted scenario via the real gate.
        posts = self._wire(_RealGate)
        threads: dict = {}
        # web_manual_tester -> qa is granted; assert it posts. Then assert an off-grant pair drops.
        WATCHER._drive_collaboration(
            "C1", "qa-reports", "T2", "exploratory web finding beyond my scope",
            "web_manual_tester", threads)
        self.assertTrue(posts, "granted escalation should have posted")
        # A direct gated call on an UNGRANTED edge must be dropped (allowed=False).
        v = _RealGate.gate_a2a("web_manual_tester", "cmo", "x")
        self.assertFalse(v["allowed"])


if __name__ == "__main__":
    unittest.main()
