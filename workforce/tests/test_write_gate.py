"""Per-agent write-enable gate — the graduation seam (report-only → WRITE, one agent at a time).

Covers ``agent_toolkit/write_gate.py`` and its wiring into ``ops_report.file_digest_record``.
The gate replaces the all-or-nothing global ``OPS_REPORT_ONLY`` with a PER-AGENT allowlist, so
the proven low-risk Tier-1 agents are write-enabled first while everyone else stays report-only.

Required cases under test:
  * a Tier-1 agent on the allowlist + clocked-in WRITES (files a real, guarded record);
  * the same agent NOT on the allowlist stays report-only (record withheld);
  * a NEVER-LIST agent (email_triage / security_officer) stays report-only EVEN on the allowlist
    AND with OPS_REPORT_ONLY=0 globally — the never-list (code constant ∪ capability-derived) wins;
  * the global OPS_REPORT_ONLY=1 floor forces everyone report-only regardless of the allowlist;
  * check_clocked_in False (kill switch / bench / over-budget) stops a write even for a
    write-enabled agent;
  * the guards (authorship/dedup) are UNCHANGED — a write-enabled record still dedups and is
    authorship-guarded.

stdlib unittest + mock, no network, MOCKED GitHub. Run:
    .venv/bin/python -m unittest tests.test_write_gate -v
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

from agent_toolkit import budget
from agent_toolkit import ops_report
from agent_toolkit import write_gate as wg
from agent_toolkit import github_ops as go
from tests.test_github_records import _make_client, _make_issue

REPO = "Scheduler-Systems/qa-agent-platform"


def _env(**kw):
    """A clean env: drop both gate vars, then apply overrides."""
    env = dict(os.environ)
    env.pop("OPS_REPORT_ONLY", None)
    env.pop("AGENTS_WRITE_ENABLED", None)
    env.update(kw)
    return env


# =============================================================================================
# 1. write_enabled() — the four-AND gate, default-deny
# =============================================================================================
class WriteEnabledGateTests(unittest.TestCase):
    def setUp(self):
        # Default: not over budget, not kill-switched, so check_clocked_in is True unless a test
        # says otherwise. The capability never-list cache is process-wide; nothing here mutates it.
        self._p = mock.patch.object(budget.payroll, "is_over_budget", return_value=False)
        self._p.start()
        self._k = mock.patch.object(budget, "fleet_disabled", return_value=False)
        self._k.start()
        self._b = mock.patch.object(budget, "is_benched", return_value=False)
        self._b.start()

    def tearDown(self):
        self._p.stop(); self._k.stop(); self._b.stop()

    def test_tier1_on_allowlist_floor_lifted_is_write_enabled(self):
        with mock.patch.dict(os.environ, _env(OPS_REPORT_ONLY="0", AGENTS_WRITE_ENABLED="cfo"), clear=True):
            self.assertTrue(wg.write_enabled("cfo"))
            self.assertFalse(wg.report_only_for("cfo"))

    def test_not_on_allowlist_is_report_only(self):
        # Floor lifted, but cfo not named → default-deny.
        with mock.patch.dict(os.environ, _env(OPS_REPORT_ONLY="0", AGENTS_WRITE_ENABLED="ceo"), clear=True):
            self.assertFalse(wg.write_enabled("cfo"))
            self.assertTrue(wg.report_only_for("cfo"))

    def test_empty_allowlist_means_nobody(self):
        with mock.patch.dict(os.environ, _env(OPS_REPORT_ONLY="0"), clear=True):  # allowlist unset
            for a in ("cfo", "ceo", "daily_digest", "revenue_reporter"):
                self.assertFalse(wg.write_enabled(a), f"{a} must be report-only with empty allowlist")

    def test_global_floor_forces_everyone_report_only(self):
        # OPS_REPORT_ONLY=1 (or unset) ⇒ nobody writes, even a named Tier-1 agent.
        for floor in ("1", "true", "yes", None):
            env = _env(AGENTS_WRITE_ENABLED="cfo")
            if floor is not None:
                env["OPS_REPORT_ONLY"] = floor
            with mock.patch.dict(os.environ, env, clear=True):
                self.assertFalse(wg.write_enabled("cfo"),
                                 f"OPS_REPORT_ONLY={floor!r} must force report-only")

    def test_kill_switch_stops_write_enabled_agent(self):
        # cfo is on the allowlist + floor lifted, but the kill switch / over-budget stops it.
        with mock.patch.dict(os.environ, _env(OPS_REPORT_ONLY="0", AGENTS_WRITE_ENABLED="cfo"), clear=True):
            self.assertTrue(wg.write_enabled("cfo"))  # baseline: enabled
            with mock.patch.object(budget, "check_clocked_in", return_value=False):
                self.assertFalse(wg.write_enabled("cfo"), "kill switch / budget must stop a write")

    def test_unknown_or_empty_agent_default_denied(self):
        with mock.patch.dict(os.environ, _env(OPS_REPORT_ONLY="0", AGENTS_WRITE_ENABLED="cfo"), clear=True):
            self.assertFalse(wg.write_enabled(""))
            self.assertFalse(wg.write_enabled("not_a_real_agent"))


# =============================================================================================
# 2. never_listed() — code constant ∪ capability-derived (send/buy/deploy/merge)
# =============================================================================================
class NeverListTests(unittest.TestCase):
    def test_code_constant_never_list(self):
        for a in ("security_officer", "clo", "platform_specialist", "email_triage", "cfo_deepagents"):
            self.assertTrue(wg.never_listed(a), f"{a} must be hard never-listed")

    def test_email_triage_is_capability_derived_too(self):
        # email_triage holds send:invoice_to_morning → also caught by the capability scan.
        self.assertIn("email_triage", wg._capability_never_list())

    def test_tier1_agents_not_never_listed(self):
        for a in ("cfo", "ceo", "cto", "coo", "board_chair", "audit_risk_director",
                  "growth_director", "daily_digest", "store_health_checker", "revenue_reporter"):
            self.assertFalse(wg.never_listed(a), f"Tier-1 {a} must NOT be never-listed")

    def test_capability_scan_flags_outward_verbs(self):
        # The scan flags any grant carrying an outward/irreversible verb. email_triage (send:) is the
        # canonical case; assert the matcher itself recognizes the verb/noun families.
        self.assertTrue(wg._cap_is_outward_irreversible("send:invoice_to_morning"))
        self.assertTrue(wg._cap_is_outward_irreversible("buy:credits"))
        self.assertTrue(wg._cap_is_outward_irreversible("deploy:web"))
        self.assertTrue(wg._cap_is_outward_irreversible("merge:pr"))
        self.assertTrue(wg._cap_is_outward_irreversible("post:merge_pr"))   # noun match
        # benign verbs are NOT flagged
        self.assertFalse(wg._cap_is_outward_irreversible("write:github_issue"))
        self.assertFalse(wg._cap_is_outward_irreversible("git:prune_merged"))  # guarded → not auto-never
        self.assertFalse(wg._cap_is_outward_irreversible("post:slack"))
        self.assertFalse(wg._cap_is_outward_irreversible("read:financials"))

    def test_never_list_beats_allowlist_and_lifted_floor(self):
        # The cardinal property: a never-list agent stays report-only EVEN on the allowlist AND
        # with OPS_REPORT_ONLY=0 globally.
        with mock.patch.object(budget, "check_clocked_in", return_value=True):
            for a in ("email_triage", "security_officer"):
                with mock.patch.dict(
                    os.environ,
                    _env(OPS_REPORT_ONLY="0", AGENTS_WRITE_ENABLED=f"cfo,{a}"),
                    clear=True,
                ):
                    self.assertFalse(wg.write_enabled(a),
                                     f"never-listed {a} must never be write-enabled")
                    self.assertTrue(wg.report_only_for(a))

    def test_outward_action_as_noun_under_benign_verb_is_auto_blocked(self):
        # LEAK (#1): the module PROMISES (write_gate.py + _cap_is_outward_irreversible docstring)
        # to auto-block a "write:deploy / post:merge_pr style smuggle even if the verb prefix is
        # benign". But the noun defense only covers merge/force_push/wire_transfer/deploy/billing/
        # payment/purchase — it MISSES the outward VERBS expressed as a NOUN (send/forward/release/
        # buy/pay/fund/transfer/acquire/subscribe). So a NEW agent that LATER gets an outward action
        # written as a noun under a benign verb is NOT auto-blocked, contradicting the never-list's
        # stated guarantee. `forward` (Posey's literal outward action) is in neither list.
        for cap in (
            "write:forward_invoice_external",  # outward FORWARD, benign verb
            "action:send_newsletter",          # outward SEND as noun, benign verb
            "post:release_to_prod",            # RELEASE as noun, benign verb
        ):
            self.assertTrue(
                wg._cap_is_outward_irreversible(cap),
                f"{cap!r}: an outward action under a benign verb MUST be flagged (it is not — LEAK)",
            )

    def test_new_outward_agent_cannot_be_write_enabled_end_to_end(self):
        # The cardinal end-to-end property the never-list claims: an agent that LATER gets an
        # outward verb is AUTO-BLOCKED even when added to the allowlist with the floor lifted.
        # Here the outward action is a NOUN under a benign verb (the documented smuggle case).
        import tempfile, textwrap
        manifest = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)
        manifest.write(textwrap.dedent(
            """
            grants:
              rogue_forwarder:
                capabilities:
                  - { capability: "write:forward_invoice_external" }
              rogue_sender:
                capabilities:
                  - { capability: "action:send_newsletter" }
            """
        ))
        manifest.flush()
        wg._capability_never_list.cache_clear()
        with mock.patch.object(wg, "_MANIFEST_PATH", manifest.name), \
             mock.patch.object(budget, "check_clocked_in", return_value=True), \
             mock.patch.dict(
                 os.environ,
                 _env(OPS_REPORT_ONLY="0", AGENTS_WRITE_ENABLED="rogue_forwarder,rogue_sender"),
                 clear=True,
             ):
            for agent in ("rogue_forwarder", "rogue_sender"):
                self.assertTrue(
                    wg.never_listed(agent),
                    f"{agent}: a newly-outward agent MUST be auto-never-listed from its capability",
                )
                self.assertFalse(
                    wg.write_enabled(agent),
                    f"{agent}: a newly-outward agent MUST NOT be write-enabled (it IS — NEVER-LIST LEAK)",
                )
        wg._capability_never_list.cache_clear()

    def test_manifest_read_failure_keeps_code_constant(self):
        # If the capability manifest can't be read, the code-constant never-list still holds (a
        # manifest error can never UN-block a named never-list agent).
        wg._capability_never_list.cache_clear()
        with mock.patch.object(wg, "_MANIFEST_PATH", wg._MANIFEST_PATH.parent / "does-not-exist.yaml"):
            self.assertEqual(wg._capability_never_list(), frozenset())
            self.assertTrue(wg.never_listed("security_officer"))   # code constant unaffected
        wg._capability_never_list.cache_clear()  # restore the real cache for other tests


# =============================================================================================
# 3. SEAM WIRING — file_digest_record writes ONLY when the agent is write-enabled
# =============================================================================================
class SeamWiringTests(unittest.TestCase):
    def setUp(self):
        self._p = mock.patch.object(budget.payroll, "is_over_budget", return_value=False)
        self._p.start()
        self._k = mock.patch.object(budget, "fleet_disabled", return_value=False)
        self._k.start()
        self._b = mock.patch.object(budget, "is_benched", return_value=False)
        self._b.start()

    def tearDown(self):
        self._p.stop(); self._k.stop(); self._b.stop()

    def _file(self, agent, env, *, created=None, existing=None):
        client, repo = _make_client(created_holder=created if created is not None else [],
                                    existing_issues=existing or [])
        ops = go.GitHubOps(report_only=True, gh_client=client)
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch("agent_toolkit.github_ops.GitHubOps", return_value=ops), \
             mock.patch("agent_toolkit.slack_tool.post_digest", return_value={"status": "posted"}):
            out = ops_report.file_digest_record(
                REPO, f"{agent} digest", "shift body", agent=agent, record_kind="shift",
            )
        return out, repo

    def test_tier1_write_enabled_files_a_real_record(self):
        created = []
        out, repo = self._file("cfo", _env(OPS_REPORT_ONLY="0", AGENTS_WRITE_ENABLED="cfo"), created=created)
        self.assertEqual(out["status"], "done")            # a REAL (mocked) write happened
        repo.create_issue.assert_called_once()
        self.assertEqual(out["slack"], "posted")           # outward delivery happened
        self.assertEqual(len(created), 1)

    def test_tier1_off_allowlist_is_withheld_report_only(self):
        created = []
        out, repo = self._file("cfo", _env(OPS_REPORT_ONLY="0", AGENTS_WRITE_ENABLED="ceo"), created=created)
        self.assertEqual(out["status"], "report_only")     # withheld
        repo.create_issue.assert_not_called()              # NO GitHub write
        self.assertEqual(out["slack"], "report_only")      # NO outward post
        self.assertEqual(created, [])

    def test_never_list_agent_withheld_even_on_allowlist_and_floor_lifted(self):
        created = []
        out, repo = self._file(
            "email_triage",
            _env(OPS_REPORT_ONLY="0", AGENTS_WRITE_ENABLED="email_triage"),
            created=created,
        )
        self.assertEqual(out["status"], "report_only")     # never-list wins
        repo.create_issue.assert_not_called()
        self.assertEqual(created, [])

    def test_global_floor_withholds_even_listed_agent(self):
        out, repo = self._file("cfo", _env(OPS_REPORT_ONLY="1", AGENTS_WRITE_ENABLED="cfo"))
        self.assertEqual(out["status"], "report_only")
        repo.create_issue.assert_not_called()

    def test_kill_switch_withholds_write_enabled_agent(self):
        with mock.patch.object(budget, "check_clocked_in", return_value=False):
            out, repo = self._file("cfo", _env(OPS_REPORT_ONLY="0", AGENTS_WRITE_ENABLED="cfo"))
        self.assertEqual(out["status"], "report_only")
        repo.create_issue.assert_not_called()

    def test_dedup_guard_unchanged_for_write_enabled_agent(self):
        # Guard intact: a SECOND filing of the same (agent, record_kind) finds-and-updates the
        # fleet-owned record (one issue + one comment), never a duplicate. Authorship-guarded:
        # the existing issue is authored by the fleet bot AND carries the agent:cfo label.
        marker = go._record_marker("record:cfo:shift")
        existing = _make_issue(
            number=7, body=f"prior body\n{marker}", labels=[go.agent_label("cfo")],
            author="fleet[bot]",
        )
        env = _env(OPS_REPORT_ONLY="0", AGENTS_WRITE_ENABLED="cfo")
        out, repo = self._file("cfo", env, existing=[existing])
        self.assertTrue(out.get("deduped"), "write-enabled record must still dedup (guard unchanged)")
        self.assertEqual(out["dedup_key"], "record:cfo:shift")
        repo.create_issue.assert_not_called()              # found-and-updated, not re-created
        self.assertEqual(len(existing._comments), 1)       # appended one update comment

    def test_authorship_guard_unchanged_human_issue_not_mutated(self):
        # A HUMAN-authored issue carrying the (invisible, copyable) marker must NOT be mutated by a
        # write-enabled record — a fresh fleet record is filed instead. Guard is unchanged.
        marker = go._record_marker("record:cfo:shift")
        human = _make_issue(number=3, body=f"human triage thread\n{marker}",
                            labels=[go.agent_label("cfo")], author="shay-human")
        created = []
        client, repo = _make_client(created_holder=created, existing_issues=[human])
        ops = go.GitHubOps(report_only=True, gh_client=client)
        env = _env(OPS_REPORT_ONLY="0", AGENTS_WRITE_ENABLED="cfo")
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch("agent_toolkit.github_ops.GitHubOps", return_value=ops), \
             mock.patch("agent_toolkit.slack_tool.post_digest", return_value={"status": "posted"}):
            out = ops_report.file_digest_record(
                REPO, "cfo digest", "body", agent="cfo", record_kind="shift",
            )
        self.assertFalse(out.get("deduped"))               # did NOT latch onto the human issue
        self.assertEqual(human._comments, [])              # human issue untouched
        repo.create_issue.assert_called_once()             # filed its OWN fresh record


# =============================================================================================
# 4. Explicit report_only=True caller is honored unchanged (legacy RECORD-on-probation path)
# =============================================================================================
class ExplicitReportOnlyContractTests(unittest.TestCase):
    def test_explicit_report_only_true_still_writes_record_without_gate(self):
        # An explicit report_only=True caller keeps the legacy RECORD-vs-CODE behaviour (records
        # write even on probation) and does NOT consult the per-agent gate — even with an EMPTY
        # allowlist. Asking for report-only is always allowed; only asking to WRITE is gated.
        created = []
        client, repo = _make_client(created_holder=created)
        ops = go.GitHubOps(report_only=True, gh_client=client)
        with mock.patch.dict(os.environ, _env(), clear=True), \
             mock.patch("agent_toolkit.github_ops.GitHubOps", return_value=ops), \
             mock.patch("agent_toolkit.slack_tool.post_digest", return_value={"status": "posted"}):
            out = ops_report.file_digest_record(
                REPO, "cfo digest", "body", agent="cfo", record_kind="shift", report_only=True,
            )
        self.assertEqual(out["status"], "done")            # legacy: record writes on probation
        repo.create_issue.assert_called_once()


if __name__ == "__main__":
    unittest.main()
