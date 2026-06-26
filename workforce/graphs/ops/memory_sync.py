"""memory_sync — the LOCAL memory-sync agent (launchd).

Runs ON the Mac (via launchd), NOT on LangGraph Platform: it needs the local memory
stores on disk (claude-mem sqlite/chroma, the project-memory `.md` trees, the workspace
`data/memory.db`, Dispatch + Codex memory), which a cloud container can't see. Like
git_local_maintainer it is still a LangGraph graph, so running it locally with
LANGSMITH_TRACING=true emits full traces to the SAME LangSmith project as the deployed
fleet — observability is met even though execution is local.

THE DESIGN TARGET (do not reinvent): this is the SKELETON for "Pipeline C — Memory →
LangChain stack" from .tmp/remote-first-migration/INVENTORY-AND-PLAN.md. Pipeline C keeps
local memory as a *cache* by syncing it to a remote target as namespaced records. The remote
target is NOT yet decided (candidates: a self-hosted LangGraph Store, Litestream→GCS for the
SQLite stores, a private `claude-memory` git repo for the markdown trees), so this graph wires
the discover -> plan -> sync -> report shape against a PLUGGABLE backend and ships only the
DryRunBackend live. The real adapters are stubs until Pipeline C's open decisions are made.

LOAD-BEARING SAFETY (mirrors the maintainer model):
  - PROBATION / DRY-RUN by default: nothing is ever uploaded/written remotely unless armed
    with MEMORY_SYNC_APPLY=1. On probation the backend ALWAYS runs dry_run=True.
  - REPORT-ONLY: governance is captured with report_only=True; the run produces a local digest
    and never performs an outward mutation without a human arming the apply switch.
  - NEVER HANGS UNATTENDED: there is NO approval interrupt and NO LLM — every node is
    deterministic and finishes. A scheduled run with zero remote config still completes.
  - FAIL-SAFE: every store stat, state-file read/write, and backend call is wrapped so a
    missing path / locked DB / SDK drift returns a structured result and the run completes.
  - SECRET SAFETY (Gate B — load-bearing): credential files and any record that matches a
    secret pattern are BLOCKED — excluded from the manifest, counted, and NEVER uploaded or
    logged by value. Secret file CONTENTS are never read into state.
  - ML BOUNDARY: any path containing 'gal-model' is skipped, and every store name we act on is
    run through ``assert_not_model_work`` (Anthropic-terms guardrail).
"""
from __future__ import annotations

import glob
import json
import os
import re
import sqlite3
import time
from typing import Optional, Protocol

from typing_extensions import TypedDict

from langgraph.graph import StateGraph, START, END

from agent_toolkit import (
    span,
    governance_capture,
    assert_not_model_work,
    write_local_digest,
)

DEFAULT_ROOT = "/Users/scheduler-systems/Documents/scheduler-systems-ltd"

# ML boundary: never touch the model repo or its artifacts (matches the workspace guardrail).
_MODEL_PATH_MARKER = "gal-model"

# ---------------------------------------------------------------------------
# Gate B — secret safety
# ---------------------------------------------------------------------------
# Credential files / patterns excluded by PATH (never uploaded, contents never read).
_SECRET_FILENAME_PATTERNS = (
    ".credentials.json",
    "config.json",
)
_SECRET_PATH_SEGMENTS = ("/credentials/", "/secrets/")
_SECRET_PATH_SUFFIXES = (".pem", ".key", ".env")
# Secret value patterns scanned inside any text record (a hit BLOCKS the store/record).
_SECRET_VALUE_PATTERNS = (
    re.compile(r"gho_[A-Za-z0-9]{20,}"),          # GitHub OAuth token
    re.compile(r"sk-ant-[A-Za-z0-9-]{20,}"),       # Anthropic API key
    re.compile(r"AKIA[0-9A-Z]{16}"),               # AWS access key id
    re.compile(r"AIza[0-9A-Za-z_-]{20,}"),         # Google API key
)


def _is_secret_path(path: str) -> bool:
    """True if ``path`` looks like a credential file we must NEVER upload. Fail-safe."""
    p = (path or "")
    low = p.lower()
    base = os.path.basename(p)
    if any(seg in low for seg in _SECRET_PATH_SEGMENTS):
        return True
    if any(low.endswith(suf) for suf in _SECRET_PATH_SUFFIXES):
        return True
    for pat in _SECRET_FILENAME_PATTERNS:
        # Match the exact filename or a dotted suffix like "foo.config.json".
        if base == pat or base.endswith(pat):
            return True
    return False


def _contains_secret(text: str) -> bool:
    """True if ``text`` contains a known secret pattern. The matched value is NEVER returned."""
    if not text:
        return False
    for pat in _SECRET_VALUE_PATTERNS:
        if pat.search(text):
            return True
    return False


# ---------------------------------------------------------------------------
# STORES — the local memory stores from Pipeline C (1c). Module-level + overridable
# (tests point these at a tmp layout). Paths are expanduser-d at discover time.
# ---------------------------------------------------------------------------
STORES: list[dict] = [
    {"name": "claude-mem sqlite", "path": "~/.claude-mem/claude-mem.db",
     "kind": "sqlite", "scope": "claude-mem"},
    {"name": "claude-mem chroma", "path": "~/.claude-mem/chroma",
     "kind": "dir", "scope": "claude-mem"},
    {"name": "project memory", "path": "~/.claude/projects",
     "kind": "markdown_tree", "scope": "projects"},
    {"name": "workspace memory", "path": os.path.join(DEFAULT_ROOT, "data", "memory", "memory.db"),
     "kind": "sqlite", "scope": "workspace"},
    {"name": "dispatch memory",
     "path": "~/Library/Application Support/*/local-agent-mode-sessions",
     "kind": "dir", "scope": "dispatch"},
    {"name": "codex memory", "path": "~/.codex",
     "kind": "markdown_tree", "scope": "codex"},
]


def _state_file(root: str) -> str:
    return os.path.join(root, ".tmp", "memory-sync", "state.json")


# ---------------------------------------------------------------------------
# Pluggable backend — the Pipeline C seam. DryRunBackend is the only LIVE one; the
# others are skeletons until Pipeline C's remote target is decided.
# ---------------------------------------------------------------------------
class SyncBackend(Protocol):
    name: str

    def health(self) -> dict: ...

    def sync(self, manifest: list[dict], *, dry_run: bool) -> dict: ...


class DryRunBackend:
    """Default backend: uploads/writes NOTHING, ever. Reports what a real backend WOULD do."""

    name = "dryrun"

    def health(self) -> dict:
        return {"backend": self.name, "ok": True, "configured": True, "note": "dry-run only"}

    def sync(self, manifest: list[dict], *, dry_run: bool) -> dict:
        # By contract this backend never uploads — `dry_run` is irrelevant to it.
        return {
            "backend": self.name,
            "ok": True,
            "uploaded": 0,
            "would_upload": len(manifest or []),
            "dry_run": True,
        }


class _StubBackend:
    """Base for the not-yet-configured Pipeline C adapters. On a real (armed) sync it returns a
    structured 'not configured' result — it NEVER performs an upload. In dry-run it behaves like
    the dry-run backend (reports would_upload, uploads nothing)."""

    name = "stub"

    def health(self) -> dict:
        return {"backend": self.name, "ok": False, "configured": False,
                "error": f"{self.name} backend not configured"}

    def sync(self, manifest: list[dict], *, dry_run: bool) -> dict:
        if dry_run:
            return {
                "backend": self.name,
                "ok": True,
                "uploaded": 0,
                "would_upload": len(manifest or []),
                "dry_run": True,
            }
        # Armed but the real remote is not wired yet — skeleton, no upload.
        return {"ok": False, "error": f"{self.name} backend not configured"}


class LangGraphStoreBackend(_StubBackend):
    """Pipeline C candidate: a periodic exporter feeding namespaced records into a LangGraph
    Store. STUB — no real Store write yet."""

    name = "langgraph_store"


class LitestreamBackend(_StubBackend):
    """Pipeline C candidate: Litestream WAL replication of the SQLite stores to GCS. STUB — no
    real replication configured here (Litestream runs as its own daemon)."""

    name = "litestream"


class ClaudeMemoryGitBackend(_StubBackend):
    """Pipeline C candidate: a private `claude-memory` git repo auto-committed+pushed for the
    markdown memory trees. STUB — no real git push yet."""

    name = "claude_memory_git"


BACKENDS: dict[str, type] = {
    "dryrun": DryRunBackend,
    "langgraph_store": LangGraphStoreBackend,
    "litestream": LitestreamBackend,
    "claude_memory_git": ClaudeMemoryGitBackend,
}


def get_backend(name: Optional[str] = None) -> SyncBackend:
    """Resolve a backend instance by name (env ``MEMORY_SYNC_BACKEND``, default 'dryrun').

    Unknown names fall back to the dry-run backend — never fail open into a live uploader.
    """
    key = (name or os.environ.get("MEMORY_SYNC_BACKEND") or "dryrun").strip().lower()
    cls = BACKENDS.get(key, DryRunBackend)
    return cls()  # type: ignore[call-arg]


def _apply_enabled() -> bool:
    """Armed only when MEMORY_SYNC_APPLY=1 (truthy). Default OFF (probation => dry-run)."""
    return os.environ.get("MEMORY_SYNC_APPLY", "").lower() in ("1", "true", "yes")


def _report_only_default() -> bool:
    """OPS_REPORT_ONLY truthy/unset => True; only an explicit '0'/'false' disables it."""
    raw = os.environ.get("OPS_REPORT_ONLY")
    if raw is None:
        return True
    return raw.strip().lower() not in ("0", "false", "no")


class State(TypedDict, total=False):
    root: str
    store_paths: list[dict]   # optional override of STORES (e.g. for tests)
    stores: list[dict]        # discovered store stats
    manifest: list[dict]      # changed stores to sync
    blocked: list[dict]       # secret/ML-boundary exclusions (counted, never uploaded)
    backend: str
    dry_run: bool
    sync_result: dict
    report: dict


# ---------------------------------------------------------------------------
# Store stat helpers (read-only; never read secret file CONTENTS into state)
# ---------------------------------------------------------------------------
def _sqlite_count(path: str) -> Optional[int]:
    """Best-effort row count over the largest user table. Read-only, fail-safe -> None."""
    try:
        # immutable=1 opens read-only without touching the WAL or locking the live DB.
        uri = f"file:{path}?mode=ro&immutable=1"
        conn = sqlite3.connect(uri, uri=True, timeout=2.0)
        try:
            cur = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%'"
            )
            tables = [r[0] for r in cur.fetchall()]
            total = 0
            for t in tables:
                try:
                    # Table names come from sqlite_master (not user input); quote defensively.
                    c = conn.execute(f'SELECT count(*) FROM "{t}"').fetchone()
                    total += int(c[0]) if c and c[0] is not None else 0
                except sqlite3.Error:
                    continue
            return total
        finally:
            conn.close()
    except (sqlite3.Error, OSError):
        return None


def _tree_file_count(path: str) -> Optional[int]:
    """Count regular files under a directory tree. Read-only, fail-safe -> None."""
    try:
        n = 0
        for _dirpath, _dirnames, filenames in os.walk(path):
            n += len(filenames)
        return n
    except OSError:
        return None


def _stat_store(store: dict) -> dict:
    """Read-only stat of one store: existence, size, mtime, cheap count. Never reads contents
    of a secret file; never raises."""
    name = store.get("name", "")
    kind = store.get("kind", "")
    scope = store.get("scope", "")
    raw_path = store.get("path", "")
    path = os.path.expanduser(raw_path)

    rec: dict = {
        "name": name,
        "kind": kind,
        "scope": scope,
        "path": path,
        "exists": False,
        "size_bytes": 0,
        "mtime": 0.0,
        "count": None,
        "skipped": None,
    }

    # ML boundary first — never even stat a model path.
    if _MODEL_PATH_MARKER in path.lower():
        rec["skipped"] = "ml-boundary"
        return rec

    # A 'dir' store path may be a glob (dispatch memory) — resolve best-effort.
    resolved = path
    if kind == "dir" and any(ch in path for ch in "*?["):
        try:
            matches = sorted(glob.glob(path))
        except OSError:
            matches = []
        if not matches:
            rec["count"] = 0
            return rec  # exists stays False — nothing matched the glob
        resolved = matches[0]
        rec["path"] = resolved

    try:
        st = os.stat(resolved)
    except OSError:
        return rec  # missing / unreadable — exists stays False (fail-safe)

    rec["exists"] = True
    rec["mtime"] = float(st.st_mtime)
    try:
        if os.path.isdir(resolved):
            rec["size_bytes"] = 0  # directory size is not load-bearing; count is the signal
            rec["count"] = _tree_file_count(resolved)
        else:
            rec["size_bytes"] = int(st.st_size)
            if kind == "sqlite":
                rec["count"] = _sqlite_count(resolved)
    except OSError:
        pass
    return rec


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------
def discover_stores(state: State) -> dict:
    """Read-only stat each store (exists/size/mtime/cheap count). Never reads secret contents."""
    root = state.get("root") or os.environ.get("WORKSPACE_ROOT") or DEFAULT_ROOT
    stores_in = state.get("store_paths") or STORES
    discovered: list[dict] = []
    with span("memory_sync.discover_stores", stores=len(stores_in)):
        for store in stores_in:
            # Guard every store identity we act on (Anthropic-terms denylist).
            try:
                assert_not_model_work(store.get("name", ""))
                assert_not_model_work(store.get("scope", ""))
            except Exception:
                # A store whose very name trips the denylist is skipped, not uploaded.
                discovered.append({
                    "name": store.get("name", ""), "kind": store.get("kind", ""),
                    "scope": store.get("scope", ""), "path": "",
                    "exists": False, "size_bytes": 0, "mtime": 0.0,
                    "count": None, "skipped": "ml-boundary",
                })
                continue
            discovered.append(_stat_store(store))
    return {"root": root, "stores": discovered}


def _load_last_state(root: str) -> dict:
    """Read the per-store last-sync state file (mtime/size). Fail-safe -> {}."""
    try:
        with open(_state_file(root), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def plan_sync(state: State) -> dict:
    """Diff each store vs the last-sync state file; changed stores -> manifest, with the secret
    exclusion applied -> blocked. Read-only; uploads nothing."""
    root = state.get("root") or DEFAULT_ROOT
    stores = state.get("stores", []) or []
    manifest: list[dict] = []
    blocked: list[dict] = []
    with span("memory_sync.plan_sync", stores=len(stores)):
        last = _load_last_state(root)
        for rec in stores:
            name = rec.get("name", "")
            path = rec.get("path", "")
            kind = rec.get("kind", "")

            # ML boundary / pre-skipped stores never enter the manifest.
            if rec.get("skipped"):
                blocked.append({"store": name, "path": path,
                                "reason": rec.get("skipped") or "skipped"})
                continue
            if path and _MODEL_PATH_MARKER in path.lower():
                blocked.append({"store": name, "path": path, "reason": "ml-boundary"})
                continue
            # The PATH is the most authoritative identifier of what would be uploaded, so run
            # it through the FULL model-development denylist (not just the 'gal-model' marker).
            # A store whose path embeds e.g. 'eval-worker'/'model-training'/'distill' is blocked
            # even when its name/scope look clean. assert_not_model_work raises on a hit.
            try:
                assert_not_model_work(path)
            except Exception:
                blocked.append({"store": name, "path": path, "reason": "ml-boundary"})
                continue
            if not rec.get("exists"):
                continue  # nothing on disk yet — not a change to sync

            # Gate B: a credential file is BLOCKED — counted, never uploaded, value never read.
            if _is_secret_path(path):
                blocked.append({"store": name, "path": path, "reason": "credential-file"})
                continue
            # Gate B: scan the store NAME (cheap, no contents) for a leaked secret pattern.
            # If the identifier ITSELF embeds a secret, REDACT it — the blocked record must
            # never carry the matched value (the whole point of blocking it).
            if _contains_secret(name) or _contains_secret(path):
                blocked.append({"store": "<redacted>", "path": "<redacted>",
                                "reason": "secret-pattern"})
                continue

            prev = last.get(path) or last.get(name) or {}
            changed = not (
                prev
                and float(prev.get("mtime", -1)) == float(rec.get("mtime", 0))
                and int(prev.get("size_bytes", -1)) == int(rec.get("size_bytes", 0))
            )
            if not changed:
                continue
            manifest.append({
                "store": name,
                "kind": kind,
                "path": path,
                "scope": rec.get("scope", ""),
                "size_bytes": rec.get("size_bytes", 0),
                "mtime": rec.get("mtime", 0.0),
                "changed": True,
            })
    return {"manifest": manifest, "blocked": blocked}


def sync(state: State) -> dict:
    """Hand the manifest to the selected backend. On probation (default) dry_run=True, so the
    backend uploads NOTHING — we assert that contract on the result. Fail-safe."""
    manifest = state.get("manifest", []) or []
    backend = get_backend()
    dry_run = not _apply_enabled()  # armed only by MEMORY_SYNC_APPLY=1
    with span("memory_sync.sync", backend=backend.name, dry_run=dry_run, manifest=len(manifest)):
        try:
            res = backend.sync(manifest, dry_run=dry_run)
            if not isinstance(res, dict):
                res = {"ok": False, "error": "backend returned non-dict"}
        except Exception as exc:  # a backend/SDK problem must never crash the run
            res = {"ok": False, "error": type(exc).__name__}
        # DRY-RUN INVARIANT: nothing may have been uploaded. If a backend ever claims an
        # upload on a dry run, neutralize the claim so downstream accounting stays honest.
        if dry_run and int(res.get("uploaded", 0) or 0) != 0:
            res = {**res, "uploaded": 0, "dry_run_violation": True}
        res.setdefault("backend", backend.name)
        res.setdefault("dry_run", dry_run)
        return {"backend": backend.name, "dry_run": dry_run, "sync_result": res}


def report(state: State) -> dict:
    """Write the local digest, capture governance (report_only=True), return a summary.

    Deterministic terminal node — no LLM, no approval interrupt, always finishes.
    """
    root = state.get("root") or DEFAULT_ROOT
    stores = state.get("stores", []) or []
    manifest = state.get("manifest", []) or []
    blocked = state.get("blocked", []) or []
    sync_result = state.get("sync_result", {}) or {}
    backend = state.get("backend", "dryrun")
    dry_run = state.get("dry_run", True)
    would_upload = int(sync_result.get("would_upload", len(manifest)) or 0)

    with span("memory_sync.report", stores=len(stores), changed=len(manifest),
              blocked=len(blocked), backend=backend, dry_run=dry_run):
        existing = sum(1 for s in stores if s.get("exists"))
        sec = lambda items, fmt: [fmt(i) for i in items] or ["_none_"]
        # Defense-in-depth: plan_sync is the gate that redacts secret-bearing identifiers, but
        # the digest is the only thing this terminal node writes to DISK — never echo a value
        # that matches a secret pattern, even if one slipped past upstream.
        _safe = lambda v: "<redacted>" if _contains_secret(str(v or "")) else v
        lines = [
            "scanned local memory stores for Pipeline C sync (skeleton)",
            f"\nbackend `{backend}` — dry_run={dry_run} "
            f"(arm with MEMORY_SYNC_APPLY=1; default OFF on probation)",
            f"\n## 🗂️ Stores ({existing}/{len(stores)} present)",
            *sec(stores, lambda s: (
                f"- `{_safe(s.get('name'))}` [{s.get('kind')}] "
                + ("present" if s.get('exists') else (s.get('skipped') or 'missing'))
                + (f" — count={s.get('count')}" if s.get('count') is not None else "")
            )),
            f"\n## 🔄 Changed → manifest ({len(manifest)}) — would_upload={would_upload}",
            *sec(manifest, lambda m: f"- `{_safe(m.get('store'))}` [{m.get('kind')}] changed"),
            f"\n## 🔒 Blocked ({len(blocked)}) — secret / ML-boundary; NEVER uploaded",
            # Reason + store name only — NEVER the matched secret value.
            *sec(blocked, lambda b: f"- `{_safe(b.get('store'))}` — {b.get('reason')}"),
        ]
        body = "\n".join(lines) + "\n"
        digest = write_local_digest("memory-sync", "Memory sync", body, root=root)

        governance_capture(
            "memory_sync",
            {
                "stores": len(stores),
                "changed": len(manifest),
                "would_upload": would_upload,
                "blocked": len(blocked),
                "backend": backend,
                "dry_run": True,        # probation: never a real upload
                "report_only": _report_only_default(),
            },
        )
        return {"report": {
            "stores": len(stores),
            "present": existing,
            "changed": len(manifest),
            "would_upload": would_upload,
            "blocked": len(blocked),
            "backend": backend,
            "dry_run": dry_run,
            "uploaded": int(sync_result.get("uploaded", 0) or 0),
            "digest": digest,
        }}


builder = StateGraph(State)
builder.add_node("discover_stores", discover_stores)
builder.add_node("plan_sync", plan_sync)
builder.add_node("sync", sync)
builder.add_node("report", report)
builder.add_edge(START, "discover_stores")
builder.add_edge("discover_stores", "plan_sync")
builder.add_edge("plan_sync", "sync")
builder.add_edge("sync", "report")
builder.add_edge("report", END)

graph = builder.compile()  # NO checkpointer/store — injected by the platform
