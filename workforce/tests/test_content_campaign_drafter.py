"""Safety tests for the cloud content_campaign_drafter agent.

It drafts content + campaigns (email / social / blog) for the Scheduler repositioning, as
DRAFTS ONLY for human review. The tests prove the load-bearing invariants on the pure node
cores (no checkpointer, no network):
  (1) NO SEND PATH — the module imports no email/social send client and calls no send/publish
      API; the only outward delivery is ``file_digest_issue`` (report-only);
  (2) the do_not_claim ``compliance_scan`` flags a draft that mentions a forbidden feature;
  (3) ``draft_content`` always produces a non-empty draft via the deterministic fallback when
      the model is unavailable;
  (4) ``deliver`` stays REPORT-ONLY (no GitHub write, no approval interrupt);
  (5) the clock-in gate routes a clocked-out run straight to END without drafting.
Run:
    .venv/bin/python -m unittest tests.test_content_campaign_drafter -v
"""
import ast
import os
import unittest
from unittest import mock

from graphs.marketing import content_campaign_drafter as m


def _strip_strings_and_comments(src: str) -> str:
    """Return the module source with all string literals + comments removed (tokenize-based).

    Lets the no-send-path test scan only real CODE tokens — so documentation prose that names
    a send client as a counter-example ("there is no Brevo path") doesn't false-positive.
    """
    import io
    import tokenize

    out: list[str] = []
    try:
        toks = tokenize.generate_tokens(io.StringIO(src).readline)
        for tok in toks:
            if tok.type in (tokenize.STRING, tokenize.COMMENT):
                continue
            out.append(tok.string)
    except Exception:
        return src  # fail-safe: if tokenizing breaks, fall back to raw source
    return " ".join(out)


# --- (1) NO SEND PATH -------------------------------------------------------------------
class NoSendPathTests(unittest.TestCase):
    """The agent must NEVER send: no Brevo/email/social send client, only digest delivery."""

    # Substrings that would betray an outward send path sneaking into the module.
    _FORBIDDEN_IMPORTS = (
        "brevo", "sib_api", "sendgrid", "mailchimp", "smtplib", "tweepy",
        "linkedin_api", "facebook", "buffer", "hootsuite", "postmark", "mailgun",
    )
    _FORBIDDEN_CALLS = ("send_email", "send_message", "send_campaign", "publish", ".send(")

    def test_module_source_has_no_send_client_or_call(self):
        """Scan the CODE (docstrings/comments stripped) for any send client or send/publish call.

        Documentation prose legitimately names Brevo as the thing the agent does NOT use, so we
        strip all string literals + comments first and only assert against real code tokens.
        """
        with open(m.__file__, "r", encoding="utf-8") as fh:
            src = fh.read()
        code = _strip_strings_and_comments(src).lower()
        for needle in self._FORBIDDEN_IMPORTS:
            self.assertNotIn(needle, code, f"module must not reference a send client: {needle}")
        for needle in self._FORBIDDEN_CALLS:
            self.assertNotIn(needle, code, f"module must not call a send/publish API: {needle}")

    def test_imports_no_send_modules(self):
        """Statically: the module imports nothing that looks like an email/social SDK."""
        with open(m.__file__, "r", encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported += [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                imported.append(node.module or "")
        joined = " ".join(imported).lower()
        for needle in self._FORBIDDEN_IMPORTS:
            self.assertNotIn(needle, joined)

    def test_deliver_outward_call_is_only_file_digest_issue(self):
        """The ONLY outward delivery in deliver() is file_digest_issue (report-only)."""
        calls = {"file_digest_issue": 0}

        def fake_file(repo, title, body, *, labels=None, report_only=None, **kwargs):
            calls["file_digest_issue"] += 1
            assert report_only is True, "deliver must stay report-only"
            return {"status": "report_only", "repo": repo}

        env = {k: v for k, v in os.environ.items() if k != "OPS_REPORT_ONLY"}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(m, "write_local_digest", return_value="/tmp/x/latest.md"), \
                mock.patch.object(m, "file_digest_issue", side_effect=fake_file):
            m.deliver({
                "brief": "b",
                "content": m._deterministic_content("b", {}),
                "compliance": {"flags": [], "clean": True},
            })
        self.assertEqual(calls["file_digest_issue"], 1)  # exactly one outward delivery


# --- (2) do_not_claim compliance scan ---------------------------------------------------
class ComplianceScanTests(unittest.TestCase):
    def test_flags_a_do_not_claim_term(self):
        """A draft that mentions a forbidden feature is flagged, clean=False."""
        positioning = {"product": {"do_not_claim": ["time tracking", "AI scheduling"]}}
        content = {
            "email_subject": "Now with time tracking!",  # forbidden
            "email_body": "Schedule shifts in one click.",
            "social_posts": ["One-click rosters."],
            "blog_outline": "Outline.",
        }
        out = m.compliance_scan({"content": content, "positioning": positioning})
        self.assertFalse(out["compliance"]["clean"])
        terms = [f["term"] for f in out["compliance"]["flags"]]
        self.assertIn("time tracking", terms)
        # The flag points at the offending field.
        flag = next(f for f in out["compliance"]["flags"] if f["term"] == "time tracking")
        self.assertEqual(flag["field"], "email_subject")

    def test_flags_term_in_social_posts(self):
        """The scan covers social_posts entries too (not just email/blog)."""
        positioning = {"product": {"do_not_claim": ["offline"]}}
        content = {
            "email_subject": "Schedule shifts",
            "email_body": "Body.",
            "social_posts": ["Works great", "Now with offline mode"],
            "blog_outline": "Outline.",
        }
        out = m.compliance_scan({"content": content, "positioning": positioning})
        self.assertFalse(out["compliance"]["clean"])
        fields = [f["field"] for f in out["compliance"]["flags"]]
        self.assertIn("social_posts[1]", fields)

    def test_clean_when_no_forbidden_terms(self):
        positioning = {"product": {"do_not_claim": ["time tracking", "AI scheduling"]}}
        content = m._deterministic_content("Reposition to shift scheduling", positioning)
        out = m.compliance_scan({"content": content, "positioning": positioning})
        self.assertTrue(out["compliance"]["clean"])
        self.assertEqual(out["compliance"]["flags"], [])

    def test_scan_never_raises_on_malformed_content(self):
        out = m.compliance_scan({"content": None, "positioning": {}})
        self.assertTrue(out["compliance"]["clean"])

    def test_deterministic_draft_is_compliance_clean(self):
        """The deterministic fallback must itself pass the guardrail (no forbidden terms)."""
        positioning = m._load_positioning()  # real positioning doc
        content = m._deterministic_content(m.DEFAULT_BRIEF, positioning)
        out = m.compliance_scan({"content": content, "positioning": positioning})
        self.assertTrue(out["compliance"]["clean"], out["compliance"]["flags"])


# --- (3) deterministic fallback ---------------------------------------------------------
class DraftFallbackTests(unittest.TestCase):
    def test_draft_deterministic_when_model_raises(self):
        """budget_guard raising must NOT crash draft_content — a full draft is still produced."""
        with mock.patch.object(m, "budget_guard", side_effect=RuntimeError("no API key")):
            out = m.draft_content({"brief": "Reposition to shift scheduling", "positioning": {}})
        content = out["content"]
        self.assertTrue(content["email_subject"].strip())     # never empty
        self.assertTrue(content["email_body"].strip())
        self.assertTrue(content["social_posts"])
        self.assertTrue(content["blog_outline"].strip())
        self.assertIn("RuntimeError", content.get("_note", ""))  # labelled, not faked

    def test_draft_uses_model_output_when_available(self):
        fake_model = mock.MagicMock()
        fake_model.invoke.return_value = mock.MagicMock(content=(
            '{"email_subject": "S", "email_body": "B", '
            '"social_posts": ["p1", "p2"], "blog_outline": "O"}'
        ))
        with mock.patch.object(m, "budget_guard", return_value=fake_model):
            out = m.draft_content({"brief": "b", "positioning": {}})
        self.assertEqual(out["content"]["email_subject"], "S")
        self.assertEqual(out["content"]["social_posts"], ["p1", "p2"])

    def test_draft_falls_back_when_model_returns_garbage(self):
        """Unparseable model output still yields a non-empty deterministic draft."""
        fake_model = mock.MagicMock()
        fake_model.invoke.return_value = mock.MagicMock(content="not json at all")
        with mock.patch.object(m, "budget_guard", return_value=fake_model):
            out = m.draft_content({"brief": "b", "positioning": {}})
        self.assertTrue(out["content"]["email_subject"].strip())
        self.assertTrue(out["content"]["social_posts"])

    def test_draft_falls_back_when_model_returns_empty_skeleton(self):
        """A valid-shape but ALL-EMPTY model object must NOT override the deterministic draft.

        Regression: a model that echoes a hollow JSON skeleton (one expected key, no usable
        copy) previously overrode the good fallback with an empty draft — the 'never empty'
        invariant. The normalized empty object must be treated as unusable.
        """
        fake_model = mock.MagicMock()
        fake_model.invoke.return_value = mock.MagicMock(
            content='{"email_subject": "", "social_posts": []}'
        )
        with mock.patch.object(m, "budget_guard", return_value=fake_model):
            out = m.draft_content({"brief": "Reposition to shift scheduling", "positioning": {}})
        content = out["content"]
        self.assertTrue(content["email_subject"].strip())   # deterministic fallback won
        self.assertTrue(content["email_body"].strip())
        self.assertTrue(content["social_posts"])
        self.assertTrue(content["blog_outline"].strip())

    def test_normalize_content_rejects_all_empty_object(self):
        """_normalize_content returns {} for an all-empty (but valid-shape) object."""
        self.assertEqual(
            m._normalize_content({"email_subject": "", "email_body": "", "social_posts": [],
                                  "blog_outline": ""}),
            {},
        )
        # A single real field is still usable.
        self.assertTrue(m._normalize_content({"email_subject": "Hi"}))

    def test_brief_precedence_env_then_default(self):
        env = {k: v for k, v in os.environ.items() if k != "CONTENT_BRIEF"}
        with mock.patch.dict(os.environ, env, clear=True):
            out = m.gather({})
            self.assertEqual(out["brief"], m.DEFAULT_BRIEF)
        with mock.patch.dict(os.environ, {"CONTENT_BRIEF": "from-env"}):
            out = m.gather({})
            self.assertEqual(out["brief"], "from-env")
        # state.brief wins over env.
        with mock.patch.dict(os.environ, {"CONTENT_BRIEF": "from-env"}):
            out = m.gather({"brief": "from-state"})
            self.assertEqual(out["brief"], "from-state")


# --- (4) deliver report-only ------------------------------------------------------------
class DeliverReportOnlyTests(unittest.TestCase):
    def test_deliver_is_report_only_and_never_writes(self):
        captured = {}

        def fake_file(repo, title, body, *, labels=None, report_only=None, **kwargs):
            captured.update(repo=repo, title=title, labels=labels, report_only=report_only)
            assert report_only is True, "deliver must stay report-only on probation"
            return {"status": "report_only", "repo": repo}

        env = {k: v for k, v in os.environ.items() if k != "OPS_REPORT_ONLY"}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(m, "write_local_digest", return_value="/tmp/x/latest.md") as wd, \
                mock.patch.object(m, "file_digest_issue", side_effect=fake_file):
            out = m.deliver({
                "brief": "b",
                "content": m._deterministic_content("b", {}),
                "compliance": {"flags": [], "clean": True},
            })
        self.assertTrue(captured["report_only"])
        self.assertEqual(captured["repo"], m.DIGEST_REPO)
        self.assertEqual(captured["title"], "Campaign content (draft)")
        self.assertIn("growth:content", captured["labels"])
        self.assertNotIn("gate:human-required", captured["labels"])  # clean => no gate label
        self.assertEqual(out["report"]["delivery"], "report_only")
        self.assertTrue(out["report_only"])
        wd.assert_called_once()

    def test_flagged_draft_adds_human_gate_label(self):
        captured = {}

        def fake_file(repo, title, body, *, labels=None, report_only=None, **kwargs):
            captured.update(labels=labels)
            return {"status": "report_only"}

        with mock.patch.object(m, "_report_only", return_value=True), \
                mock.patch.object(m, "write_local_digest", return_value=""), \
                mock.patch.object(m, "file_digest_issue", side_effect=fake_file):
            m.deliver({
                "brief": "b",
                "content": m._deterministic_content("b", {}),
                "compliance": {"flags": [{"term": "offline", "field": "email_body",
                                          "detail": "x"}], "clean": False},
            })
        self.assertIn("growth:content", captured["labels"])
        self.assertIn("gate:human-required", captured["labels"])

    def test_report_only_env_contract(self):
        with mock.patch.dict(os.environ, {"OPS_REPORT_ONLY": "0"}):
            self.assertFalse(m._report_only())
        with mock.patch.dict(os.environ, {"OPS_REPORT_ONLY": "false"}):
            self.assertFalse(m._report_only())
        with mock.patch.dict(os.environ, {"OPS_REPORT_ONLY": "1"}):
            self.assertTrue(m._report_only())
        env = {k: v for k, v in os.environ.items() if k != "OPS_REPORT_ONLY"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertTrue(m._report_only())  # unset => report-only


# --- (5) budget gate / clock-in ---------------------------------------------------------
class BudgetGateTests(unittest.TestCase):
    def test_clocked_out_ends_without_drafting(self):
        """Clocked out: budget_gate reports + governance, route goes to END (not gather)."""
        with mock.patch.object(m, "check_clocked_in", return_value=False), \
                mock.patch.object(m, "governance_capture") as gov:
            out = m.budget_gate({})
            route = m._budget_route({})
        self.assertEqual(out["report"]["delivery"], "skipped")
        self.assertTrue(out["report_only"])
        self.assertEqual(route, "clocked_out")
        gov.assert_called_once()
        self.assertTrue(gov.call_args[0][1]["report_only"])

    def test_clocked_in_proceeds_to_gather(self):
        with mock.patch.object(m, "check_clocked_in", return_value=True):
            out = m.budget_gate({})
            route = m._budget_route({})
        self.assertEqual(out, {})
        self.assertEqual(route, "gather")


# --- finalize + graph -------------------------------------------------------------------
class FinalizeTests(unittest.TestCase):
    def test_finalize_captures_report_only_governance(self):
        with mock.patch.object(m, "governance_capture") as gov:
            out = m.finalize({
                "compliance": {"flags": [], "clean": True},
                "report": {"delivery": "report_only", "digest": "/tmp/d"},
            })
        self.assertTrue(out["report"]["report_only"])
        self.assertEqual(out["report"]["delivery"], "report_only")
        gov.assert_called_once()
        self.assertTrue(gov.call_args[0][1]["report_only"])


class GraphInvokeTests(unittest.TestCase):
    def test_full_run_report_only_no_creds(self):
        """Unattended, no model/creds: full graph runs, delivers report-only, never hangs."""
        env = {k: v for k, v in os.environ.items() if k != "OPS_REPORT_ONLY"}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(m, "check_clocked_in", return_value=True), \
                mock.patch.object(m, "budget_guard", side_effect=RuntimeError("no model")), \
                mock.patch.object(m, "write_local_digest", return_value=""), \
                mock.patch.object(m, "file_digest_issue",
                                  return_value={"status": "report_only"}) as fd:
            out = m.graph.invoke({})
        self.assertTrue(out["report"]["report_only"])
        self.assertTrue(fd.call_args.kwargs["report_only"])  # no GitHub call, no approval hang

    def test_clocked_out_graph_ends_without_delivery(self):
        with mock.patch.object(m, "check_clocked_in", return_value=False), \
                mock.patch.object(m, "budget_guard") as bg, \
                mock.patch.object(m, "file_digest_issue") as fd:
            out = m.graph.invoke({})
        bg.assert_not_called()   # no model spend on the clocked-out path
        fd.assert_not_called()   # no delivery on the clocked-out path
        self.assertEqual(out["report"]["delivery"], "skipped")

    def test_graph_compiles_without_checkpointer(self):
        self.assertIsNotNone(m.graph)


if __name__ == "__main__":
    unittest.main()
