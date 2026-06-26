"""Tests for email_triage — "Posey", the DRAFT-ONLY inbox / email-triage agent.

The cardinal invariant under test: the agent READS/triages the inbox, CREATES Gmail DRAFTS
(never sends), and PROPOSES unsubscribes (never executes). It honors report-only + the clock-in
kill-switch, never hangs without creds, and routes its digest through file_digest_record.

stdlib unittest + unittest.mock, no network, MOCKED Gmail client (no real email). Run:
    .venv/bin/python -m unittest tests.test_email_triage -v
"""
import json
import os
import pathlib
import unittest
from unittest import mock

import yaml

from agent_toolkit import gmail_client
from graphs.ops import email_triage as m

ROOT = pathlib.Path(__file__).resolve().parent.parent


# A fake Gmail client whose ONLY mutating call is create_draft (records every call, NEVER sends).
class FakeGmail:
    def __init__(self, messages=None, draft_ok=True):
        self._messages = messages or {}
        self.draft_ok = draft_ok
        self.created_drafts = []   # records of create_draft calls
        self.sends = []            # MUST stay empty — proves nothing was ever sent

    def list_inbox(self, *, query="", limit=20, client=None):
        return {"ok": True, "items": [{"id": mid, "threadId": f"t{mid}"} for mid in self._messages]}

    def get_message(self, message_id, *, client=None):
        msg = dict(self._messages.get(message_id, {}))
        msg.setdefault("ok", True)
        msg.setdefault("id", message_id)
        return msg

    def create_draft(self, *, to, subject, body, thread_id="", in_reply_to="", client=None):
        self.created_drafts.append({"to": to, "subject": subject, "body": body})
        if not self.draft_ok:
            return {"ok": False, "error": "draft create failed: RuntimeError"}
        return {"ok": True, "draft_id": f"draft-{len(self.created_drafts)}", "to": to, "subject": subject}


def _msg(mid, frm, subject, snippet="", list_unsub=""):
    return {"ok": True, "id": mid, "from": frm, "subject": subject, "snippet": snippet,
            "list_unsubscribe": list_unsub, "threadId": f"t{mid}", "labelIds": ["INBOX", "UNREAD"]}


# --- The Gmail seam has NO send verb (structural enforcement of draft-only) --------------
class GmailSeamHasNoSendTests(unittest.TestCase):
    def test_no_send_method_exists_on_gmail_client(self):
        public = [a for a in dir(gmail_client) if not a.startswith("_")]
        self.assertFalse(any("send" in a.lower() for a in public),
                         f"a send verb exists on gmail_client — bright line broken: {public}")
        # The compose path is present and is a DRAFT, not a send.
        self.assertTrue(hasattr(gmail_client, "create_draft"))

    def test_not_configured_without_token(self):
        env = dict(os.environ)
        env.pop(gmail_client.GMAIL_TOKEN_ENV, None)
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertFalse(gmail_client.is_configured())

    def test_create_draft_reports_when_not_configured_never_raises(self):
        # No client + no env creds → honest report-only result, never a send, never a raise.
        env = dict(os.environ)
        env.pop(gmail_client.GMAIL_TOKEN_ENV, None)
        with mock.patch.dict(os.environ, env, clear=True):
            res = gmail_client.create_draft(to="a@b.com", subject="hi", body="x")
        self.assertFalse(res["ok"])
        self.assertIn("not configured", res["error"])


# --- read_inbox: read-only, unverifiable when no creds ----------------------------------
class ReadInboxTests(unittest.TestCase):
    def test_no_creds_emits_unverifiable_could_not_check(self):
        with mock.patch.object(m.gmail_client, "is_configured", return_value=False):
            out = m.read_inbox({})
        self.assertEqual(out["messages"], [])
        self.assertEqual(len(out["triaged"]), 1)
        f = out["triaged"][0]
        self.assertEqual(f["kind"], "unverifiable")
        self.assertIn("could not check inbox", f["detail"])

    def test_list_failure_is_unverifiable(self):
        with mock.patch.object(m.gmail_client, "is_configured", return_value=True), \
             mock.patch.object(m.gmail_client, "list_inbox",
                               return_value={"ok": False, "items": [], "error": "auth"}):
            out = m.read_inbox({})
        self.assertEqual(out["triaged"][0]["kind"], "unverifiable")

    def test_reads_and_classifies_messages(self):
        fake = FakeGmail({
            "1": _msg("1", "Customer <cust@acme.com>", "Question about my schedule", "can you help?"),
            "2": _msg("2", "Deals <promo@shopmail.com>", "50% off sale!", "unsubscribe here",
                      list_unsub="<https://shopmail.com/u>"),
        })
        with mock.patch.object(m.gmail_client, "is_configured", return_value=True), \
             mock.patch.object(m.gmail_client, "list_inbox", side_effect=fake.list_inbox), \
             mock.patch.object(m.gmail_client, "get_message", side_effect=fake.get_message):
            out = m.read_inbox({})
        self.assertEqual(len(out["triaged"]), 2)
        by_id = {t["id"]: t for t in out["triaged"]}
        self.assertTrue(by_id["1"]["wants_reply"])        # a real question → reply
        self.assertFalse(by_id["1"]["promotional"])
        self.assertTrue(by_id["2"]["promotional"])         # has List-Unsubscribe → promo
        self.assertFalse(by_id["2"]["wants_reply"])


# --- draft_replies: CREATES drafts, NEVER sends -----------------------------------------
class DraftRepliesTests(unittest.TestCase):
    def test_creates_draft_and_never_sends(self):
        fake = FakeGmail()
        triaged = [{"id": "1", "from": "cust@acme.com", "subject": "Help please",
                    "wants_reply": True, "promotional": False, "thread_id": "t1"}]
        with mock.patch.object(m, "_report_only", return_value=True), \
             mock.patch.object(m.gmail_client, "create_draft", side_effect=fake.create_draft), \
             mock.patch.object(m, "budget_guard", side_effect=RuntimeError("no model")):
            out = m.draft_replies({"triaged": triaged})
        self.assertEqual(len(out["drafts"]), 1)
        d = out["drafts"][0]
        self.assertTrue(d["created"])
        self.assertEqual(d["to"], "cust@acme.com")
        self.assertTrue(d["subject"].lower().startswith("re:"))
        # The DRAFT was created exactly once; NOTHING was ever sent.
        self.assertEqual(len(fake.created_drafts), 1)
        self.assertEqual(fake.sends, [])

    def test_no_reply_for_promotional_messages(self):
        # Promotional messages are never drafted a reply (wants_reply is False).
        triaged = [{"id": "2", "from": "promo@x.com", "subject": "Sale",
                    "wants_reply": False, "promotional": True}]
        with mock.patch.object(m, "_report_only", return_value=True), \
             mock.patch.object(m, "budget_guard", side_effect=RuntimeError("no model")):
            out = m.draft_replies({"triaged": triaged})
        self.assertEqual(out["drafts"], [])

    def test_draft_failure_recorded_not_raised(self):
        fake = FakeGmail(draft_ok=False)
        triaged = [{"id": "1", "from": "c@x.com", "subject": "Q", "wants_reply": True}]
        with mock.patch.object(m, "_report_only", return_value=True), \
             mock.patch.object(m.gmail_client, "create_draft", side_effect=fake.create_draft), \
             mock.patch.object(m, "budget_guard", side_effect=RuntimeError("no model")):
            out = m.draft_replies({"triaged": triaged})   # must not raise
        self.assertFalse(out["drafts"][0]["created"])
        self.assertIsNotNone(out["drafts"][0]["error"])

    def test_draft_gate_recorded_report_only(self):
        # The HITL gate for an outward reply is RECORDED (would_require_human), never blocks.
        fake = FakeGmail()
        triaged = [{"id": "1", "from": "c@x.com", "subject": "Q", "wants_reply": True}]
        with mock.patch.object(m, "_report_only", return_value=True), \
             mock.patch.object(m.gmail_client, "create_draft", side_effect=fake.create_draft), \
             mock.patch.object(m, "budget_guard", side_effect=RuntimeError("no model")):
            out = m.draft_replies({"triaged": triaged})
        self.assertEqual(out["drafts"][0]["gate"], "would_require_human")


# --- propose_unsubscribes: PROPOSES, NEVER executes -------------------------------------
class ProposeUnsubscribesTests(unittest.TestCase):
    def test_promotional_is_proposed_not_executed(self):
        triaged = [{"id": "2", "from": "promo@x.com", "subject": "Sale", "label": "x",
                    "promotional": True, "list_unsubscribe": "<https://x.com/u>"}]
        with mock.patch.object(m, "_report_only", return_value=True):
            out = m.propose_unsubscribes({"triaged": triaged})
        self.assertEqual(len(out["unsubscribes"]), 1)
        u = out["unsubscribes"][0]
        self.assertTrue(u["has_unsubscribe_link"])
        self.assertIn("PROPOSED", u["action"])
        self.assertIn("never unsubscribes", u["action"])
        self.assertEqual(u["gate"], "would_require_human")

    def test_non_promotional_not_proposed(self):
        triaged = [{"id": "1", "from": "c@x.com", "subject": "Q", "promotional": False}]
        with mock.patch.object(m, "_report_only", return_value=True):
            out = m.propose_unsubscribes({"triaged": triaged})
        self.assertEqual(out["unsubscribes"], [])


# --- triage_summary: severity + never claims a send -------------------------------------
class TriageSummaryTests(unittest.TestCase):
    def test_drafts_escalate_to_high(self):
        state = {"triaged": [{"id": "1", "wants_reply": True}],
                 "drafts": [{"created": True}], "unsubscribes": []}
        with mock.patch.object(m, "budget_guard", side_effect=RuntimeError("no model")):
            out = m.triage_summary(state)
        self.assertEqual(out["severity"], "high")
        self.assertIn("NOT sent", out["summary"])

    def test_needs_task_only_is_medium(self):
        state = {"triaged": [{"id": "1", "needs_task": True}], "drafts": [], "unsubscribes": []}
        with mock.patch.object(m, "budget_guard", side_effect=RuntimeError("no model")):
            out = m.triage_summary(state)
        self.assertEqual(out["severity"], "medium")

    def test_clean_is_ok(self):
        with mock.patch.object(m, "budget_guard", side_effect=RuntimeError("no model")):
            out = m.triage_summary({"triaged": [], "drafts": [], "unsubscribes": []})
        self.assertEqual(out["severity"], "ok")


# --- deliver: routes through file_digest_record, report-only, gate label -----------------
class DeliverTests(unittest.TestCase):
    def test_deliver_uses_file_digest_record_report_only(self):
        captured = {}
        def fake_record(repo, title, body, *, agent, record_kind, labels=None,
                        report_only=None, **kwargs):
            captured.update(repo=repo, agent=agent, record_kind=record_kind,
                            labels=labels, report_only=report_only)
            return {"status": "report_only"}
        with mock.patch.object(m, "_report_only", return_value=True), \
             mock.patch.object(m, "write_local_digest", return_value="/tmp/x.md") as wd, \
             mock.patch.object(m, "file_digest_record", side_effect=fake_record):
            out = m.deliver({"severity": "high", "summary": "s",
                             "triaged": [{"id": "1"}], "drafts": [{"created": True}],
                             "unsubscribes": [{"from": "p@x.com"}]})
        self.assertTrue(captured["report_only"])               # report-only → never hangs/writes
        self.assertEqual(captured["agent"], "email_triage")    # digest routed via file_digest_record(agent=...)
        self.assertEqual(captured["record_kind"], "email-triage")
        self.assertEqual(captured["repo"], m.DIGEST_REPO)
        self.assertIn("alert:email-triage", captured["labels"])
        self.assertIn("gate:human-required", captured["labels"])  # drafts/unsubs → human gate label
        self.assertEqual(out["report"]["delivery"], "report_only")
        wd.assert_called_once()

    def test_clean_run_omits_gate_label(self):
        captured = {}
        def fake_record(repo, title, body, *, agent, record_kind, labels=None, **kwargs):
            captured.update(labels=labels)
            return {"status": "report_only"}
        with mock.patch.object(m, "_report_only", return_value=True), \
             mock.patch.object(m, "write_local_digest", return_value=""), \
             mock.patch.object(m, "file_digest_record", side_effect=fake_record):
            m.deliver({"severity": "ok", "summary": "s", "triaged": [], "drafts": [], "unsubscribes": []})
        self.assertIn("alert:email-triage", captured["labels"])
        self.assertNotIn("gate:human-required", captured["labels"])


# --- _report_only contract (PER-AGENT GATE: Posey is hard NEVER-LISTED) -----------------
class ReportOnlyEnvTests(unittest.TestCase):
    def test_unset_defaults_true(self):
        env = dict(os.environ); env.pop("OPS_REPORT_ONLY", None)
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertTrue(m._report_only())

    def test_never_listed_stays_report_only_even_when_globally_enabled(self):
        """Posey (email_triage) is on the per-agent NEVER-LIST, so ``_report_only()`` is True even
        when the global ``OPS_REPORT_ONLY=0`` flag lifts the floor AND Posey is on the
        ``AGENTS_WRITE_ENABLED`` allowlist. The never-list (a code constant) wins — there is no env
        by which Posey's outward forward/send can be enabled. This replaces the old env-only
        contract (``OPS_REPORT_ONLY=0`` ⇒ False), which would have let a single global flag enable
        Posey's email send."""
        with mock.patch.dict(os.environ, {"OPS_REPORT_ONLY": "0",
                                          "AGENTS_WRITE_ENABLED": "email_triage"}):
            self.assertTrue(m._report_only(), "never-listed Posey must stay report-only")


# --- budget gate / clock-in: kill-switch honored ----------------------------------------
class BudgetGateTests(unittest.TestCase):
    def test_clocked_out_routes_to_end_and_reports(self):
        with mock.patch.object(m, "check_clocked_in", return_value=False):
            out = m.budget_gate({})
            self.assertTrue(out["report_only"])
            self.assertEqual(m._budget_route({}), "clocked_out")

    def test_clocked_in_routes_to_read_inbox(self):
        with mock.patch.object(m, "check_clocked_in", return_value=True):
            self.assertEqual(m.budget_gate({}), {})
            self.assertEqual(m._budget_route({}), "read_inbox")


# --- end-to-end graph: drafts created, NOTHING sent, report-only, never hangs -----------
class GraphInvokeTests(unittest.TestCase):
    def test_full_run_drafts_but_never_sends(self):
        fake = FakeGmail({
            "1": _msg("1", "Customer <c@acme.com>", "Please help with my schedule", "can you?"),
            "2": _msg("2", "Promo <deals@x.com>", "Big sale", "unsubscribe", list_unsub="<https://x/u>"),
        })
        env = dict(os.environ); env.pop("OPS_REPORT_ONLY", None)
        record_calls = {}
        def fake_record(repo, title, body, *, agent, record_kind, labels=None, report_only=None, **kw):
            record_calls.update(agent=agent, report_only=report_only, labels=labels)
            return {"status": "report_only"}
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch.object(m, "check_clocked_in", return_value=True), \
             mock.patch.object(m.gmail_client, "is_configured", return_value=True), \
             mock.patch.object(m.gmail_client, "list_inbox", side_effect=fake.list_inbox), \
             mock.patch.object(m.gmail_client, "get_message", side_effect=fake.get_message), \
             mock.patch.object(m.gmail_client, "create_draft", side_effect=fake.create_draft), \
             mock.patch.object(m, "budget_guard", side_effect=RuntimeError("no model")), \
             mock.patch.object(m, "write_local_digest", return_value=""), \
             mock.patch.object(m, "file_digest_record", side_effect=fake_record):
            out = m.graph.invoke({})
        # One reply DRAFT created; one unsubscribe PROPOSED; NOTHING sent or executed.
        self.assertEqual(out["report"]["drafts"], 1)
        self.assertEqual(out["report"]["unsubscribes_proposed"], 1)
        self.assertEqual(out["report"]["sent"], 0)              # invariant: never sends
        self.assertEqual(len(fake.created_drafts), 1)
        self.assertEqual(fake.sends, [])
        self.assertEqual(out["report"]["severity"], "high")
        self.assertTrue(out["report"]["report_only"])
        # The digest routed through file_digest_record(agent="email_triage", report_only=True).
        self.assertEqual(record_calls["agent"], "email_triage")
        self.assertTrue(record_calls["report_only"])
        self.assertIn("gate:human-required", record_calls["labels"])

    def test_no_creds_run_is_report_only_and_never_hangs(self):
        env = dict(os.environ); env.pop("OPS_REPORT_ONLY", None)
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch.object(m, "check_clocked_in", return_value=True), \
             mock.patch.object(m.gmail_client, "is_configured", return_value=False), \
             mock.patch.object(m, "budget_guard", side_effect=RuntimeError("no model")), \
             mock.patch.object(m, "write_local_digest", return_value=""), \
             mock.patch.object(m, "file_digest_record", return_value={"status": "report_only"}):
            out = m.graph.invoke({})
        self.assertEqual(out["report"]["sent"], 0)
        self.assertTrue(out["report"]["report_only"])

    def test_clocked_out_graph_ends_without_reading_inbox(self):
        with mock.patch.object(m, "check_clocked_in", return_value=False), \
             mock.patch.object(m.gmail_client, "list_inbox") as li, \
             mock.patch.object(m.gmail_client, "create_draft") as cd, \
             mock.patch.object(m, "file_digest_record") as fd:
            out = m.graph.invoke({})
        li.assert_not_called()    # no inbox read on the clocked-out path
        cd.assert_not_called()    # no drafts on the clocked-out path
        fd.assert_not_called()    # no delivery on the clocked-out path
        self.assertEqual(out["report"]["severity"], "skipped")


# --- Onboarding: roster + capability + langgraph all include email_triage ---------------
class OnboardingTests(unittest.TestCase):
    def test_graph_is_in_langgraph_json(self):
        graphs = json.loads((ROOT / "langgraph.json").read_text())["graphs"]
        self.assertIn("email_triage", graphs)
        self.assertEqual(graphs["email_triage"], "./graphs/ops/email_triage.py:graph")

    def test_roster_row_exists_with_required_fields(self):
        roster = yaml.safe_load((ROOT / "roster.yaml").read_text())
        agent = roster["agents"]["email_triage"]
        self.assertEqual(agent["name"], "Posey")
        self.assertIn("Inbox", agent["role"])
        self.assertEqual(agent["status"], "probation")
        self.assertEqual(agent["hire"], "pending_hr_approval")
        self.assertIn("salary_tokens_per_week", agent)
        self.assertIn("scorecard", agent)
        self.assertIn("email_triage", roster["org"]["ops"])

    def test_capability_grant_is_draft_only_plus_one_allowlisted_send(self):
        manifest = yaml.safe_load((ROOT / "docs" / "governance" / "capabilities.yaml").read_text())
        grant = manifest["grants"]["email_triage"]
        self.assertEqual(grant["posture"], "report_only")
        self.assertIs(grant["can_buy"], False)
        self.assertIn("gmail_oauth", grant["identities"])
        verbs = {c["capability"].split(":", 1)[0] for c in grant["capabilities"]}
        # read / propose / message / post / write — PLUS the single narrow allowlist-scoped 'send'.
        self.assertTrue(verbs <= {"read", "propose", "message", "post", "write", "send"}, verbs)
        caps = {c["capability"] for c in grant["capabilities"]}
        self.assertIn("read:gmail", caps)
        self.assertIn("propose:email_reply", caps)
        self.assertIn("propose:unsubscribe", caps)
        # The ONLY 'send' is the allowlist-pinned invoice→Morning forward — never a general send.
        send_caps = {c for c in caps if c.split(":", 1)[0] == "send"}
        self.assertEqual(send_caps, {"send:invoice_to_morning"}, send_caps)
        # No GENERAL email-send capability (post:email / write:email_send / propose:send_email / send:email).
        self.assertFalse(any(
            c.split(":", 1)[0] in {"post", "write"} and "email" in c.split(":", 1)[-1].lower()
            for c in caps), caps)
        self.assertFalse(any("send:email" in c.lower() or "send:gmail" in c.lower() for c in caps), caps)

    def test_coverage_gates_pass_with_new_agent(self):
        import importlib.util

        def _run(script):
            path = ROOT / "scripts" / script
            spec = importlib.util.spec_from_file_location(script.replace(".py", ""), path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod.main()

        self.assertEqual(_run("check_roster_coverage.py"), 0)
        self.assertEqual(_run("check_capability_coverage.py"), 0)


if __name__ == "__main__":
    unittest.main()
