"""Tests for the event-driven webhook RECEIVER + the event->agent routing table.

All MOCKED — no real network, no real fire. The ``fire`` callable is a recording stub injected
into ``EventReceiver``; ``runs.create`` / ``a2a_client.fire_run`` are never reached. We assert
the SECURITY properties the audit fix turns on:

  * a valid GitHub-signed PR event fires the right agent(s) with the deterministic per-PR
    thread_id, and ONLY then;
  * an UNSIGNED or WRONG-signature request is rejected (401) and fires NOTHING;
  * a replayed (already-seen delivery id) request is rejected and fires nothing;
  * a verified Sentry issue alert routes to the bug-triage agent (web_qa_regression);
  * firing is FAIL-SAFE — a fire that raises yields a per-agent "error" status, never a crash.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import sys
import types
import unittest
from unittest import mock

from agent_toolkit import event_routing
from scripts import event_receiver as er

_GH_SECRET = "gh-test-secret"
_SENTRY_SECRET = "sentry-test-secret"


def _sign_github(secret: str, raw: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


def _sign_sentry(secret: str, raw: bytes) -> str:
    return hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


class _Recorder:
    """A fire stub that records (agent, thread_id, input) calls; optionally raises for an agent."""

    def __init__(self, raise_for: set[str] | None = None):
        self.calls: list[tuple[str, str, dict]] = []
        self.raise_for = raise_for or set()

    def __call__(self, agent, thread_id, agent_input):
        self.calls.append((agent, thread_id, dict(agent_input)))
        if agent in self.raise_for:
            raise RuntimeError("simulated fire failure")
        return {"run_id": "stub"}


def _make(fire, **kw):
    return er.EventReceiver(github_secret=_GH_SECRET, sentry_secret=_SENTRY_SECRET, fire=fire, **kw)


# Minimal-but-realistic webhook bodies.
def _pr_body(action="opened", merged=False, number=1487, node="PR_node_abc",
             repo="Scheduler-Systems/scheduler-web", branch="feat/x", sha="deadbeef"):
    return {
        "action": action,
        "number": number,
        "pull_request": {"number": number, "node_id": node, "merged": merged,
                         "head": {"ref": branch, "sha": sha}},
        "repository": {"full_name": repo},
    }


def _push_body(repo="Scheduler-Systems/scheduler-web", ref="refs/heads/main", after="cafef00d"):
    return {"ref": ref, "after": after, "repository": {"full_name": repo}}


def _sentry_body(issue_id="ISSUE-42"):
    return {"action": "triggered", "data": {"issue": {"id": issue_id, "title": "TypeError"}}}


def _gh_headers(event, raw, *, secret=_GH_SECRET, delivery="d-1", sign=True):
    h = {"X-GitHub-Event": event, "X-GitHub-Delivery": delivery}
    if sign:
        h["X-Hub-Signature-256"] = _sign_github(secret, raw)
    return h


# ── routing table (pure data) ────────────────────────────────────────────────────

class RoutingTable(unittest.TestCase):
    def test_pr_opened_routes_to_qa_chain(self):
        # A PR open fires the QA chain AND the board's PR-review agent (additive — the board
        # "decide on PRs" step rides alongside QA; see agent_toolkit.pr_eval / board.pr_review).
        self.assertEqual(event_routing.agents_for("github", "pr_opened"),
                         ["qa_lead_aggregator", "board_pr_review"])
        self.assertEqual(event_routing.agents_for("github", "pr_synchronize"),
                         ["qa_lead_aggregator", "board_pr_review"])

    def test_pr_merged_routes_to_qa_chain_and_regression(self):
        self.assertEqual(event_routing.agents_for("github", "pr_merged"),
                         ["qa_lead_aggregator", "web_qa_regression"])

    def test_sentry_routes_to_bug_agent(self):
        self.assertEqual(event_routing.agents_for("sentry", "issue_alert"), ["web_qa_regression"])

    def test_unknown_event_routes_to_nothing(self):
        self.assertEqual(event_routing.agents_for("github", "labeled"), [])
        self.assertEqual(event_routing.agents_for("bogus", "whatever"), [])

    def test_every_fireable_agent_is_a_real_graph(self):
        # Guard against routing to a graph that doesn't exist in langgraph.json.
        import os
        with open(os.path.join(er._REPO_ROOT, "langgraph.json")) as fh:
            cfg = json.load(fh)
        graphs = set(cfg["graphs"])
        self.assertTrue(event_routing.FIREABLE_AGENTS)
        for agent in event_routing.FIREABLE_AGENTS:
            self.assertIn(agent, graphs, f"{agent} routed but not a deployed graph")

    def test_normalize_github(self):
        self.assertEqual(event_routing.normalize_github("pull_request", _pr_body("opened")), "pr_opened")
        self.assertEqual(event_routing.normalize_github("pull_request", _pr_body("synchronize")), "pr_synchronize")
        self.assertEqual(event_routing.normalize_github("pull_request",
                         _pr_body("closed", merged=True)), "pr_merged")
        # a non-merge close is ignored
        self.assertIsNone(event_routing.normalize_github("pull_request", _pr_body("closed", merged=False)))
        self.assertEqual(event_routing.normalize_github("push", _push_body()), "push")
        self.assertIsNone(event_routing.normalize_github("ping", {}))


# ── deterministic thread id ──────────────────────────────────────────────────────

class ThreadId(unittest.TestCase):
    def test_stable_per_subject(self):
        a = er.thread_id_for("github", "PR_node_abc")
        b = er.thread_id_for("github", "PR_node_abc")
        self.assertEqual(a, b)

    def test_differs_per_subject(self):
        self.assertNotEqual(er.thread_id_for("github", "PR_1"), er.thread_id_for("github", "PR_2"))

    def test_is_uuid5_of_subject(self):
        import uuid
        expected = str(uuid.uuid5(er._THREAD_NS, "github:PR_node_abc"))
        self.assertEqual(er.thread_id_for("github", "PR_node_abc"), expected)


# ── happy path: a verified PR open fires the QA chain ─────────────────────────────

class GithubHappyPath(unittest.TestCase):
    def test_pr_opened_fires_qa_lead_with_deterministic_thread(self):
        rec = _Recorder()
        r = _make(rec)
        body = _pr_body("opened", node="PR_xyz")
        raw = json.dumps(body).encode()
        status, out = r.handle("github", _gh_headers("pull_request", raw), raw)
        self.assertEqual(status, 202)
        # A PR open fires the QA chain AND the board PR-review agent (both on the SAME per-PR
        # deterministic thread). The QA lead is fired first; board_pr_review rides alongside.
        self.assertEqual([c[0] for c in rec.calls], ["qa_lead_aggregator", "board_pr_review"])
        expected_thread = er.thread_id_for("github", "PR_xyz")
        self.assertEqual(rec.calls[0][1], expected_thread)
        self.assertEqual(out["thread_id"], expected_thread)
        self.assertEqual(out["fired"][0]["status"], "fired")
        # the structured input carries useful, non-secret context
        inp = rec.calls[0][2]
        self.assertEqual(inp["target"], "Scheduler-Systems/scheduler-web")
        self.assertEqual(inp["pr_number"], 1487)
        # the thread_id is passed to fire() as its own arg (the firer threads the run); the
        # input dict carries the event context, not the thread id.
        self.assertEqual(inp["event"], "github:pr_opened")

    def test_pr_merged_fires_both_agents_same_thread(self):
        rec = _Recorder()
        r = _make(rec)
        body = _pr_body("closed", merged=True, node="PR_merge")
        raw = json.dumps(body).encode()
        status, out = r.handle("github", _gh_headers("pull_request", raw), raw)
        self.assertEqual(status, 202)
        self.assertEqual([c[0] for c in rec.calls], ["qa_lead_aggregator", "web_qa_regression"])
        # both fired on the SAME per-PR thread (continuity)
        self.assertEqual(rec.calls[0][1], rec.calls[1][1])

    def test_push_fires_regression_watcher(self):
        rec = _Recorder()
        r = _make(rec)
        body = _push_body()
        raw = json.dumps(body).encode()
        status, out = r.handle("github", _gh_headers("push", raw), raw)
        self.assertEqual(status, 202)
        self.assertEqual([c[0] for c in rec.calls], ["web_qa_regression"])

    def test_ping_is_accepted_but_fires_nothing(self):
        rec = _Recorder()
        r = _make(rec)
        raw = json.dumps({"zen": "hi"}).encode()
        status, out = r.handle("github", _gh_headers("ping", raw), raw)
        self.assertEqual(status, 200)
        self.assertEqual(rec.calls, [])

    def test_ignored_pr_action_fires_nothing(self):
        rec = _Recorder()
        r = _make(rec)
        body = _pr_body("labeled")
        raw = json.dumps(body).encode()
        status, out = r.handle("github", _gh_headers("pull_request", raw), raw)
        self.assertEqual(status, 200)
        self.assertEqual(rec.calls, [])


# ── rejection: unsigned / wrong signature -> 401, fire NOTHING ────────────────────

class GithubRejection(unittest.TestCase):
    def test_missing_signature_rejected_no_fire(self):
        rec = _Recorder()
        r = _make(rec)
        body = _pr_body("opened")
        raw = json.dumps(body).encode()
        headers = _gh_headers("pull_request", raw, sign=False)  # no signature header
        status, out = r.handle("github", headers, raw)
        self.assertEqual(status, 401)
        self.assertEqual(rec.calls, [])
        self.assertEqual(out["fired"], [])

    def test_wrong_signature_rejected_no_fire(self):
        rec = _Recorder()
        r = _make(rec)
        body = _pr_body("opened")
        raw = json.dumps(body).encode()
        headers = _gh_headers("pull_request", raw, secret="WRONG-SECRET")
        status, out = r.handle("github", headers, raw)
        self.assertEqual(status, 401)
        self.assertEqual(rec.calls, [])

    def test_tampered_body_rejected_no_fire(self):
        # sign the original, then tamper the body -> HMAC no longer matches
        rec = _Recorder()
        r = _make(rec)
        body = _pr_body("opened")
        raw = json.dumps(body).encode()
        headers = _gh_headers("pull_request", raw)  # signed over `raw`
        tampered = raw + b'  '  # different bytes
        status, out = r.handle("github", headers, tampered)
        self.assertEqual(status, 401)
        self.assertEqual(rec.calls, [])

    def test_malformed_signature_header_rejected(self):
        rec = _Recorder()
        r = _make(rec)
        raw = json.dumps(_pr_body()).encode()
        headers = {"X-GitHub-Event": "pull_request", "X-GitHub-Delivery": "d-x",
                   "X-Hub-Signature-256": "not-a-sha256-header"}
        status, out = r.handle("github", headers, raw)
        self.assertEqual(status, 401)
        self.assertEqual(rec.calls, [])

    def test_valid_signature_but_malformed_json_rejected_no_fire(self):
        rec = _Recorder()
        r = _make(rec)
        raw = b"{not json"
        headers = _gh_headers("pull_request", raw)  # correctly signs the (garbage) bytes
        status, out = r.handle("github", headers, raw)
        self.assertEqual(status, 401)
        self.assertEqual(rec.calls, [])


# ── replay defense ────────────────────────────────────────────────────────────────

class ReplayDefense(unittest.TestCase):
    def test_same_delivery_id_replayed_is_rejected(self):
        rec = _Recorder()
        r = _make(rec)
        body = _pr_body("opened")
        raw = json.dumps(body).encode()
        headers = _gh_headers("pull_request", raw, delivery="dup-1")
        s1, _ = r.handle("github", headers, raw)
        self.assertEqual(s1, 202)
        # one PR-open delivery fans out to the QA chain + the board PR-review agent (2 fires)
        self.assertEqual(len(rec.calls), 2)
        # exact same signed request again -> replay -> rejected, NO new fire
        s2, out2 = r.handle("github", headers, raw)
        self.assertEqual(s2, 401)
        self.assertEqual(out2["rejected"], "github-replay")
        self.assertEqual(len(rec.calls), 2)

    def test_missing_delivery_id_still_dedups_on_signed_body(self):
        # The replay key is derived from SIGNED material (the body hash), NOT the unsigned
        # X-GitHub-Delivery header. So a missing delivery id no longer matters for replay safety:
        # the FIRST delivery of a signed body is accepted, and an identical replay is rejected
        # purely on the body hash — the unsigned header is irrelevant to dedup. (See the
        # ReplayBypass regression tests: mutating the unsigned header can never re-fire a body.)
        rec = _Recorder()
        r = _make(rec)
        body = _pr_body("opened")
        raw = json.dumps(body).encode()
        headers = {"X-GitHub-Event": "pull_request",
                   "X-Hub-Signature-256": _sign_github(_GH_SECRET, raw)}  # no delivery id
        s1, _ = r.handle("github", headers, raw)
        self.assertEqual(s1, 202)
        # one PR-open delivery fans out to the QA chain + the board PR-review agent (2 fires)
        self.assertEqual(len(rec.calls), 2)
        # an identical signed body replayed (still no delivery id) is rejected on the body hash
        s2, out2 = r.handle("github", headers, raw)
        self.assertEqual(s2, 401)
        self.assertEqual(out2["rejected"], "github-replay")
        self.assertEqual(len(rec.calls), 2)


# ── Sentry path ───────────────────────────────────────────────────────────────────

class SentryPath(unittest.TestCase):
    def _headers(self, raw, *, secret=_SENTRY_SECRET, resource="issue", sign=True):
        h = {"Sentry-Hook-Resource": resource}
        if sign:
            h["Sentry-Hook-Signature"] = _sign_sentry(secret, raw)
        return h

    def test_verified_issue_alert_routes_to_bug_agent(self):
        rec = _Recorder()
        r = _make(rec)
        body = _sentry_body("ISSUE-77")
        raw = json.dumps(body).encode()
        status, out = r.handle("sentry", self._headers(raw), raw)
        self.assertEqual(status, 202)
        self.assertEqual([c[0] for c in rec.calls], ["web_qa_regression"])
        # deterministic per-issue thread
        self.assertEqual(rec.calls[0][1], er.thread_id_for("sentry", "ISSUE-77"))
        self.assertEqual(rec.calls[0][2]["sentry_issue"], "ISSUE-77")

    def test_unsigned_sentry_rejected_no_fire(self):
        rec = _Recorder()
        r = _make(rec)
        raw = json.dumps(_sentry_body()).encode()
        status, out = r.handle("sentry", self._headers(raw, sign=False), raw)
        self.assertEqual(status, 401)
        self.assertEqual(rec.calls, [])

    def test_wrong_secret_sentry_rejected(self):
        rec = _Recorder()
        r = _make(rec)
        raw = json.dumps(_sentry_body()).encode()
        status, out = r.handle("sentry", self._headers(raw, secret="nope"), raw)
        self.assertEqual(status, 401)
        self.assertEqual(rec.calls, [])

    def test_sentry_replay_rejected(self):
        rec = _Recorder()
        r = _make(rec)
        raw = json.dumps(_sentry_body("ISSUE-A")).encode()
        headers = self._headers(raw, resource="issue")
        s1, _ = r.handle("sentry", headers, raw)
        self.assertEqual(s1, 202)
        s2, out2 = r.handle("sentry", headers, raw)
        self.assertEqual(s2, 401)
        self.assertEqual(out2["rejected"], "sentry-replay")
        self.assertEqual(len(rec.calls), 1)


# ── fail-safe firing ──────────────────────────────────────────────────────────────

class FailSafe(unittest.TestCase):
    def test_fire_error_does_not_crash_and_reports_status(self):
        # qa_lead fails, web_qa_regression succeeds -> 202, per-agent statuses, no exception
        rec = _Recorder(raise_for={"qa_lead_aggregator"})
        r = _make(rec)
        body = _pr_body("closed", merged=True)
        raw = json.dumps(body).encode()
        status, out = r.handle("github", _gh_headers("pull_request", raw), raw)
        self.assertEqual(status, 202)
        statuses = {f["agent"]: f["status"] for f in out["fired"]}
        self.assertEqual(statuses["qa_lead_aggregator"], "error")
        self.assertEqual(statuses["web_qa_regression"], "fired")
        # both were attempted (the error did not abort the loop)
        self.assertEqual(len(rec.calls), 2)

    def test_unknown_source_is_404(self):
        rec = _Recorder()
        r = _make(rec)
        status, out = r.handle("bitbucket", {}, b"{}")
        self.assertEqual(status, 404)
        self.assertEqual(rec.calls, [])


# ── signature helpers are constant-time + correct ─────────────────────────────────

class SignatureUnits(unittest.TestCase):
    def test_github_roundtrip(self):
        raw = b'{"a":1}'
        self.assertTrue(er.verify_github_signature(_GH_SECRET, raw, _sign_github(_GH_SECRET, raw)))

    def test_github_empty_secret_denies(self):
        raw = b'{"a":1}'
        self.assertFalse(er.verify_github_signature("", raw, _sign_github(_GH_SECRET, raw)))

    def test_github_none_header_denies(self):
        self.assertFalse(er.verify_github_signature(_GH_SECRET, b"{}", None))

    def test_sentry_roundtrip(self):
        raw = b'{"x":2}'
        self.assertTrue(er.verify_sentry_signature(_SENTRY_SECRET, raw, _sign_sentry(_SENTRY_SECRET, raw)))


# ── SSRF / injection: the (signed-but-attacker-controlled) body must not steer the run ──
#
# A GitHub org configures ONE webhook secret, so EVERY repo in the org — and every PR a
# low-privilege actor opens (including from a fork) — produces a VALIDLY-SIGNED webhook whose
# ``repository.full_name`` and ``pull_request.head.ref`` are attacker-influenced. Signature
# verification proves the bytes came from GitHub; it does NOT prove the named repo/branch is one
# the fleet is allowed to act on. The receiver is the trust boundary (it does the sig-verify +
# replay + agent allow-list), yet today it copies ``repository.full_name`` straight into the run
# input as ``target``/``repo`` with ZERO validation against ``ALLOWED_REPOS`` — relying entirely
# on each downstream agent re-checking ``assert_allowed_repo``. That is exactly the SSRF/SSRF-
# adjacent injection hole: a crafted-but-signed payload makes the receiver fire an agent pointed
# at an arbitrary, non-allow-listed repo (and ships shell-metachar branch text into the input).
class TargetValidation(unittest.TestCase):
    def _allowed_repos(self):
        # Pull the canonical allow-list the agents enforce, so this test tracks the real list.
        from agent_toolkit.github_ops import ALLOWED_REPOS
        return ALLOWED_REPOS

    def test_signed_event_for_unlisted_repo_does_not_fire_that_repo(self):
        """A verified webhook naming a repo OUTSIDE the allow-list must not fire an agent that
        is targeted at that repo. The receiver should reject it (or refuse to route), NOT pass
        the attacker repo through to ``runs.create``. FAILS today: the receiver fires with
        ``target``/``repo`` == the attacker-chosen, non-allow-listed repo."""
        rec = _Recorder()
        r = _make(rec)
        evil_repo = "evil-attacker/exfil-target"  # not in ALLOWED_REPOS
        self.assertNotIn(evil_repo, self._allowed_repos())
        body = _pr_body("opened", node="PR_evil", repo=evil_repo)
        raw = json.dumps(body).encode()
        status, out = r.handle("github", _gh_headers("pull_request", raw, delivery="evil-1"), raw)

        # Property: no agent may be fired with a non-allow-listed repo as its target/repo.
        for agent, _thread, agent_input in rec.calls:
            for key in ("target", "repo"):
                self.assertIn(
                    agent_input.get(key, next(iter(self._allowed_repos()))),
                    self._allowed_repos(),
                    f"{agent} fired with {key}={agent_input.get(key)!r} — an unvalidated, "
                    f"non-allow-listed repo from the webhook body reached the run input",
                )

    def test_signed_push_for_unlisted_repo_does_not_fire_that_repo(self):
        """Same hole on the push path (fires ``web_qa_regression`` which reads ``state['target']``
        and hits the GitHub API with it)."""
        rec = _Recorder()
        r = _make(rec)
        evil_repo = "evil-attacker/exfil-target"
        body = _push_body(repo=evil_repo)
        raw = json.dumps(body).encode()
        status, out = r.handle("github", _gh_headers("push", raw, delivery="evil-push-1"), raw)
        for agent, _thread, agent_input in rec.calls:
            self.assertIn(
                agent_input.get("target", next(iter(self._allowed_repos()))),
                self._allowed_repos(),
                f"{agent} fired with target={agent_input.get('target')!r} from an unvalidated "
                f"push body",
            )


# ── production fire path: the deterministic thread must reach runs.create ──────────
#
# Every test above injects a RECORDER stub for ``fire`` and asserts the receiver HANDS it the
# deterministic thread_id. But the receiver's *production* firer is ``er._default_fire`` ->
# ``a2a_client.fire_run`` -> ``client.runs.create(...)``. The whole point of the feature is
# per-PR / per-issue THREAD CONTINUITY: a PR's repeated pushes must append to ONE LangSmith
# thread, not spawn a fresh stateless run each time. In the LangGraph SDK that continuity is
# expressed ONLY by the FIRST POSITIONAL arg of ``runs.create`` (``thread_id``); a key named
# "thread_id" inside ``input`` is just opaque graph state and does NOT thread the run.
#
# These tests drive the REAL ``_default_fire`` with a fake ``langgraph_sdk`` that captures what
# ``runs.create`` actually receives. They FAIL today: ``fire_run`` calls
# ``client.runs.create(None, target_graph, input=inp)`` — the deterministic thread is passed as
# ``None`` (stateless run) and merely smuggled into ``input``. Continuity is silently lost: the
# fleet opens a brand-new thread on every push instead of continuing the PR's thread.
class ProductionThreadContinuity(unittest.TestCase):
    def _install_fake_sdk(self):
        """Install a fake ``langgraph_sdk`` whose ``runs.create`` records its positional args."""
        captured: dict = {}

        class _FakeRuns:
            async def create(self, thread_id, assistant_id, input=None, **kw):  # SDK signature
                captured["thread_id_positional"] = thread_id
                captured["assistant_id"] = assistant_id
                captured["input"] = input
                return {"run_id": "stub", "thread_id": thread_id}

            async def wait(self, thread_id, assistant_id, input=None, **kw):
                captured["thread_id_positional"] = thread_id
                return {"run_id": "stub"}

        class _FakeThreads:
            async def create(self, *, thread_id=None, if_exists=None, **kw):  # SDK signature
                # The firer must ENSURE the deterministic thread exists (idempotently) before
                # threading a run onto it. Record the requested id + conflict behavior.
                captured["thread_create_id"] = thread_id
                captured["thread_create_if_exists"] = if_exists
                return {"thread_id": thread_id}

        class _FakeClient:
            runs = _FakeRuns()
            threads = _FakeThreads()

        fake_sdk = types.ModuleType("langgraph_sdk")
        fake_sdk.get_client = lambda **kw: _FakeClient()
        return fake_sdk, captured

    def test_default_fire_passes_thread_id_as_runs_create_thread(self):
        fake_sdk, captured = self._install_fake_sdk()
        det_thread = er.thread_id_for("github", "PR_node_abc")
        env = {"LANGGRAPH_DEPLOYMENT_URL": "https://example.test",
               "LANGSMITH_API_KEY": "k", "LANGSMITH_TENANT_ID": "t"}
        with mock.patch.dict(sys.modules, {"langgraph_sdk": fake_sdk}), \
             mock.patch.dict("os.environ", env, clear=False):
            er._default_fire("qa_lead_aggregator", det_thread,
                             {"event": "github:pr_opened", "subject_id": "PR_node_abc"})

        # The deterministic thread MUST be the run's thread (positional arg) for continuity.
        self.assertEqual(
            captured.get("thread_id_positional"), det_thread,
            "runs.create was called with thread_id=%r, not the deterministic per-PR thread %r "
            "-> every push opens a NEW stateless thread; the smuggled input['thread_id']=%r does "
            "NOT thread the run." % (captured.get("thread_id_positional"), det_thread,
                                     (captured.get("input") or {}).get("thread_id")),
        )

    def test_two_fires_for_same_pr_reuse_one_thread(self):
        """A PR's first push and a later push (same subject) must land on the SAME run thread."""
        fake_sdk, captured = self._install_fake_sdk()
        det_thread = er.thread_id_for("github", "PR_same")
        env = {"LANGGRAPH_DEPLOYMENT_URL": "https://example.test",
               "LANGSMITH_API_KEY": "k", "LANGSMITH_TENANT_ID": "t"}
        seen: list = []
        with mock.patch.dict(sys.modules, {"langgraph_sdk": fake_sdk}), \
             mock.patch.dict("os.environ", env, clear=False):
            er._default_fire("qa_lead_aggregator", det_thread, {"event": "github:pr_synchronize"})
            seen.append(captured.get("thread_id_positional"))
            er._default_fire("qa_lead_aggregator", det_thread, {"event": "github:pr_synchronize"})
            seen.append(captured.get("thread_id_positional"))
        # both runs must share the deterministic, non-None thread (continuity, not fresh threads)
        self.assertEqual(seen, [det_thread, det_thread],
                         "the two pushes did not reuse the PR's thread: %r" % (seen,))
        self.assertIsNotNone(seen[0], "thread_id was None -> a fresh stateless thread per push")


if __name__ == "__main__":
    unittest.main()
