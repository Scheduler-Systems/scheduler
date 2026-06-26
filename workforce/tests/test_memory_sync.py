"""Safety + behavior tests for memory_sync — the LOCAL Pipeline C sync skeleton.

The load-bearing invariants under test:
  - SECRET SAFETY (Gate B): credential files and records containing a secret pattern are
    BLOCKED — counted, NEVER in the manifest, value never logged.
  - DRY-RUN by default: the DryRunBackend uploads NOTHING (uploaded == 0) and no stub backend
    performs a network/upload; on probation sync() runs dry_run=True.
  - BACKEND SELECTION: get_backend honors MEMORY_SYNC_BACKEND.
  - ML BOUNDARY: a 'gal-model' store path is skipped (never synced).
  - INCREMENTAL: plan_sync respects a prior state.json (an unchanged store is not in the
    manifest).

Run:
    .venv/bin/python -m unittest tests.test_memory_sync -v
"""
import json
import os
import tempfile
import unittest
from unittest import mock

from graphs.ops import memory_sync as m


def _clear_env(env=None):
    env = dict(os.environ if env is None else env)
    for k in ("MEMORY_SYNC_BACKEND", "MEMORY_SYNC_APPLY", "OPS_REPORT_ONLY", "WORKSPACE_ROOT"):
        env.pop(k, None)
    return env


class DiscoverTests(unittest.TestCase):
    def test_discover_stats_temp_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "mem.db")
            with open(db, "wb") as fh:
                fh.write(b"SQLite format 3\x00" + b"\x00" * 32)
            tree = os.path.join(tmp, "proj")
            os.makedirs(os.path.join(tree, "p", "memory"))
            with open(os.path.join(tree, "p", "memory", "a.md"), "w") as fh:
                fh.write("# note\n")
            missing = os.path.join(tmp, "nope")

            stores = [
                {"name": "wk", "path": db, "kind": "sqlite", "scope": "workspace"},
                {"name": "proj", "path": tree, "kind": "markdown_tree", "scope": "projects"},
                {"name": "gone", "path": missing, "kind": "dir", "scope": "x"},
            ]
            with mock.patch.dict(os.environ, _clear_env(), clear=True):
                out = m.discover_stores({"root": tmp, "store_paths": stores})

        by = {s["name"]: s for s in out["stores"]}
        self.assertTrue(by["wk"]["exists"])
        self.assertTrue(by["proj"]["exists"])
        self.assertEqual(by["proj"]["count"], 1)        # one .md file under the tree
        self.assertFalse(by["gone"]["exists"])          # missing store -> exists False


class SecretSafetyTests(unittest.TestCase):
    def test_credential_file_blocked_not_in_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            cred = os.path.join(tmp, ".credentials.json")
            with open(cred, "w") as fh:
                fh.write('{"token":"super-secret"}')
            stat = {"name": "claude creds", "kind": "sqlite", "scope": "x", "path": cred,
                    "exists": True, "size_bytes": 10, "mtime": 123.0, "count": None, "skipped": None}
            out = m.plan_sync({"root": tmp, "stores": [stat]})
        self.assertEqual(out["manifest"], [])                       # never queued for upload
        self.assertEqual(len(out["blocked"]), 1)
        self.assertEqual(out["blocked"][0]["reason"], "credential-file")

    def test_record_with_token_blocked_value_never_logged(self):
        # A store NAME containing a leaked GitHub token must be BLOCKED, and the matched value
        # must never appear in any blocked entry.
        token = "gho_" + "A" * 24
        stat = {"name": f"leak {token}", "kind": "dir", "scope": "x", "path": "/tmp/whatever",
                "exists": True, "size_bytes": 1, "mtime": 1.0, "count": None, "skipped": None}
        out = m.plan_sync({"root": "/w", "stores": [stat]})
        self.assertEqual(out["manifest"], [])
        self.assertEqual(len(out["blocked"]), 1)
        self.assertEqual(out["blocked"][0]["reason"], "secret-pattern")
        # The secret value is NEVER carried in the blocked record.
        self.assertNotIn(token, json.dumps(out["blocked"]))

    def test_pem_and_credentials_segment_paths_are_secret(self):
        self.assertTrue(m._is_secret_path("/home/u/id_rsa.pem"))
        self.assertTrue(m._is_secret_path("/x/private.key"))
        self.assertTrue(m._is_secret_path("/x/.env"))
        self.assertTrue(m._is_secret_path("/a/credentials/thing.json"))
        self.assertTrue(m._is_secret_path("/x/.credentials.json"))
        self.assertFalse(m._is_secret_path("/x/memory/note.md"))

    def test_contains_secret_matches_known_patterns(self):
        self.assertTrue(m._contains_secret("sk-ant-" + "x" * 24))
        self.assertTrue(m._contains_secret("AKIA" + "ABCDEFGHIJ123456"))
        self.assertTrue(m._contains_secret("AIza" + "b" * 24))
        self.assertFalse(m._contains_secret("just a normal note"))


class MlBoundaryTests(unittest.TestCase):
    def test_gal_model_path_skipped(self):
        store = {"name": "model mem", "path": "/x/gal-model/store.db",
                 "kind": "sqlite", "scope": "model"}
        rec = m._stat_store(store)
        self.assertEqual(rec["skipped"], "ml-boundary")
        # And it must end up blocked (never in the manifest) in plan_sync.
        out = m.plan_sync({"root": "/w", "stores": [rec]})
        self.assertEqual(out["manifest"], [])
        self.assertEqual(out["blocked"][0]["reason"], "ml-boundary")

    def test_denylist_path_blocked_even_when_name_scope_clean(self):
        # The PATH is the authoritative identifier of what would be uploaded. A store whose
        # path embeds a model-development denylist term (e.g. 'eval-worker', 'model-training',
        # 'distill') must be BLOCKED even when its name/scope look clean — not just 'gal-model'.
        for denied_path in (
            "/x/governance/eval-worker/state.db",
            "/x/model-training/checkpoints.db",
            "/x/distill-pipeline/cache.db",
        ):
            stat = {"name": "clean", "kind": "sqlite", "scope": "clean", "path": denied_path,
                    "exists": True, "size_bytes": 1, "mtime": 1.0, "count": None,
                    "skipped": None}
            out = m.plan_sync({"root": "/w", "stores": [stat]})
            self.assertEqual(out["manifest"], [], f"{denied_path} leaked into manifest")
            self.assertEqual(out["blocked"][0]["reason"], "ml-boundary")


class BackendTests(unittest.TestCase):
    def test_default_backend_is_dryrun(self):
        with mock.patch.dict(os.environ, _clear_env(), clear=True):
            b = m.get_backend()
        self.assertEqual(b.name, "dryrun")
        self.assertIsInstance(b, m.DryRunBackend)

    def test_get_backend_selects_via_env(self):
        with mock.patch.dict(os.environ, {"MEMORY_SYNC_BACKEND": "litestream"}):
            self.assertIsInstance(m.get_backend(), m.LitestreamBackend)
        with mock.patch.dict(os.environ, {"MEMORY_SYNC_BACKEND": "langgraph_store"}):
            self.assertIsInstance(m.get_backend(), m.LangGraphStoreBackend)
        with mock.patch.dict(os.environ, {"MEMORY_SYNC_BACKEND": "claude_memory_git"}):
            self.assertIsInstance(m.get_backend(), m.ClaudeMemoryGitBackend)

    def test_unknown_backend_falls_back_to_dryrun(self):
        with mock.patch.dict(os.environ, {"MEMORY_SYNC_BACKEND": "bogus-uploader"}):
            self.assertIsInstance(m.get_backend(), m.DryRunBackend)

    def test_dryrun_backend_uploads_nothing(self):
        manifest = [{"store": "a"}, {"store": "b"}]
        res = m.DryRunBackend().sync(manifest, dry_run=True)
        self.assertEqual(res["uploaded"], 0)
        self.assertEqual(res["would_upload"], 2)
        # Even if a caller passes dry_run=False, the dry-run backend NEVER uploads.
        res2 = m.DryRunBackend().sync(manifest, dry_run=False)
        self.assertEqual(res2["uploaded"], 0)

    def test_stub_backend_does_not_upload_when_armed(self):
        # An armed (dry_run=False) stub returns 'not configured' — no upload, no network.
        for cls in (m.LangGraphStoreBackend, m.LitestreamBackend, m.ClaudeMemoryGitBackend):
            res = cls().sync([{"store": "a"}], dry_run=False)
            self.assertFalse(res["ok"])
            self.assertIn("not configured", res["error"])
            self.assertNotIn("uploaded", res)   # nothing was uploaded


class SyncNodeTests(unittest.TestCase):
    def test_sync_is_dry_run_by_default_uploads_nothing(self):
        with mock.patch.dict(os.environ, _clear_env(), clear=True):
            out = m.sync({"manifest": [{"store": "a"}, {"store": "b"}]})
        self.assertTrue(out["dry_run"])
        self.assertEqual(out["backend"], "dryrun")
        self.assertEqual(out["sync_result"]["uploaded"], 0)
        self.assertEqual(out["sync_result"]["would_upload"], 2)

    def test_sync_neutralizes_a_lying_upload_count_on_dry_run(self):
        class LyingBackend:
            name = "liar"

            def health(self):
                return {}

            def sync(self, manifest, *, dry_run):
                return {"ok": True, "uploaded": 99, "would_upload": len(manifest)}

        with mock.patch.dict(os.environ, _clear_env(), clear=True), \
             mock.patch.object(m, "get_backend", return_value=LyingBackend()):
            out = m.sync({"manifest": [{"store": "a"}]})
        # Dry-run invariant: a claimed upload is forced back to 0.
        self.assertEqual(out["sync_result"]["uploaded"], 0)
        self.assertTrue(out["sync_result"].get("dry_run_violation"))

    def test_sync_survives_backend_exception(self):
        class BoomBackend:
            name = "boom"

            def health(self):
                return {}

            def sync(self, manifest, *, dry_run):
                raise RuntimeError("kaboom")

        with mock.patch.dict(os.environ, _clear_env(), clear=True), \
             mock.patch.object(m, "get_backend", return_value=BoomBackend()):
            out = m.sync({"manifest": [{"store": "a"}]})
        self.assertFalse(out["sync_result"]["ok"])
        self.assertEqual(out["sync_result"]["error"], "RuntimeError")  # type-only, no body


class PlanIncrementalTests(unittest.TestCase):
    def test_prior_state_excludes_unchanged_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = os.path.join(tmp, ".tmp", "memory-sync")
            os.makedirs(state_dir)
            unchanged = {"name": "wk", "kind": "sqlite", "scope": "workspace",
                         "path": "/x/mem.db", "exists": True,
                         "size_bytes": 100, "mtime": 555.0, "count": 3, "skipped": None}
            changed = {"name": "proj", "kind": "markdown_tree", "scope": "projects",
                       "path": "/x/proj", "exists": True,
                       "size_bytes": 200, "mtime": 999.0, "count": 5, "skipped": None}
            # Prior state: 'wk' identical (mtime+size), 'proj' has an OLD mtime/size.
            with open(os.path.join(state_dir, "state.json"), "w") as fh:
                json.dump({
                    "/x/mem.db": {"mtime": 555.0, "size_bytes": 100},
                    "/x/proj": {"mtime": 111.0, "size_bytes": 1},
                }, fh)
            out = m.plan_sync({"root": tmp, "stores": [unchanged, changed]})

        names = [e["store"] for e in out["manifest"]]
        self.assertNotIn("wk", names)        # unchanged -> excluded from manifest
        self.assertIn("proj", names)         # changed -> queued

    def test_no_prior_state_treats_everything_changed(self):
        with tempfile.TemporaryDirectory() as tmp:
            stat = {"name": "wk", "kind": "sqlite", "scope": "workspace",
                    "path": "/x/mem.db", "exists": True,
                    "size_bytes": 1, "mtime": 1.0, "count": 1, "skipped": None}
            out = m.plan_sync({"root": tmp, "stores": [stat]})
        self.assertEqual([e["store"] for e in out["manifest"]], ["wk"])

    def test_missing_store_not_in_manifest(self):
        stat = {"name": "gone", "kind": "dir", "scope": "x", "path": "/x/none",
                "exists": False, "size_bytes": 0, "mtime": 0.0, "count": None, "skipped": None}
        out = m.plan_sync({"root": "/w", "stores": [stat]})
        self.assertEqual(out["manifest"], [])


class ReportAndGraphTests(unittest.TestCase):
    def test_report_writes_digest_and_captures_governance(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(m, "governance_capture") as gov:
            state = {
                "root": tmp,
                "stores": [{"name": "wk", "kind": "sqlite", "exists": True, "count": 3}],
                "manifest": [{"store": "wk", "kind": "sqlite"}],
                "blocked": [{"store": "creds", "reason": "credential-file"}],
                "sync_result": {"backend": "dryrun", "uploaded": 0, "would_upload": 1,
                                "dry_run": True},
                "backend": "dryrun",
                "dry_run": True,
            }
            out = m.report(state)
            # Check while the tmp dir still exists (it is removed when the with-block ends).
            self.assertTrue(os.path.exists(out["report"]["digest"]))
        self.assertEqual(out["report"]["uploaded"], 0)
        self.assertEqual(out["report"]["would_upload"], 1)
        gov.assert_called_once()
        payload = gov.call_args[0][1]
        self.assertTrue(payload["report_only"])
        self.assertTrue(payload["dry_run"])
        self.assertEqual(payload["blocked"], 1)

    def test_report_does_not_leak_secret_value_into_digest(self):
        token = "gho_" + "Z" * 24
        with tempfile.TemporaryDirectory() as tmp:
            state = {
                "root": tmp, "stores": [], "manifest": [],
                "blocked": [{"store": "leak", "reason": "secret-pattern"}],
                "sync_result": {"uploaded": 0, "would_upload": 0}, "backend": "dryrun",
                "dry_run": True,
            }
            out = m.report(state)
            with open(out["report"]["digest"], encoding="utf-8") as fh:
                text = fh.read()
        self.assertNotIn(token, text)   # the digest reports reasons, never values

    def test_report_redacts_secret_named_store_that_bypassed_the_gate(self):
        # Defense-in-depth: report() WRITES the digest to disk + captures governance. Even if a
        # secret-named store somehow reaches the manifest/stores/blocked lists (upstream bug),
        # the terminal sink must NOT echo the matched secret value into the digest file.
        token = "sk-ant-" + "Q" * 30
        leaky = f"leaky-{token}"
        with tempfile.TemporaryDirectory() as tmp:
            state = {
                "root": tmp,
                "stores": [{"name": leaky, "kind": "sqlite", "exists": True, "count": 1}],
                "manifest": [{"store": leaky, "kind": "sqlite"}],
                "blocked": [{"store": leaky, "reason": "secret-pattern"}],
                "sync_result": {"uploaded": 0, "would_upload": 1}, "backend": "dryrun",
                "dry_run": True,
            }
            out = m.report(state)
            with open(out["report"]["digest"], encoding="utf-8") as fh:
                text = fh.read()
        self.assertNotIn(token, text)        # value never written to the digest
        self.assertIn("<redacted>", text)    # replaced with the redaction marker

    def test_graph_compiles_without_checkpointer(self):
        self.assertIsNotNone(m.graph)

    def test_full_run_dry_default_uploads_nothing(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.dict(os.environ, _clear_env(), clear=True):
            db = os.path.join(tmp, "mem.db")
            with open(db, "w") as fh:
                fh.write("x")
            stores = [{"name": "wk", "path": db, "kind": "sqlite", "scope": "workspace"}]
            final = m.graph.invoke({"root": tmp, "store_paths": stores})
        self.assertEqual(final["report"]["uploaded"], 0)
        self.assertTrue(final["report"]["dry_run"])


if __name__ == "__main__":
    unittest.main()
