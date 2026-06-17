"""OBSERVE / learning mode — shared read-only recon for every QA worker graph.

The defining rule of OBSERVE mode (orchestrate-local, execute-on-cluster still applies):
the worker MUST NOT dispatch CI and MUST NOT propose any outward writes. Instead it READS
what is locally available — the target repo's test setup + recent git history under
``Scheduler-Systems/<repo>`` (strictly READ-ONLY) — and hands those facts to the model so
it can produce an "observations" learning summary of how that platform's QA works and
where it looks fragile. Report-only; there is no approval gate in observe mode.

Activation: ``state.get("mode") == "observe"`` OR the env flag ``LEARN_MODE=1``.

Nothing here executes the suite, boots an emulator/simulator, runs a build, or mutates the
repo. ``git log``/``git status`` are read-only inspections; file reads are read-only. Every
target string is still guarded by ``assert_not_model_work`` in the caller.
"""
import os
import subprocess

# Workspace root that contains the Scheduler-Systems org checkouts. Overridable for tests.
_DEFAULT_ORG_ROOT = "/Users/YOUR_USERNAME/workspace/Scheduler-Systems"

# Test-setup files we look for, per platform flavour. Read-only.
_RECON_FILES = (
    # web (Next.js / Vitest / Playwright)
    "package.json",
    "playwright.config.ts",
    "playwright.config.js",
    "vitest.config.ts",
    "vitest.config.js",
    # android (Gradle / JUnit / Espresso)
    "build.gradle",
    "build.gradle.kts",
    "app/build.gradle",
    "app/build.gradle.kts",
    "gradle.properties",
    # ios (SPM / XCTest)
    "Package.swift",
    "Makefile",
    "fastlane/Fastfile",
    # shared CI surface
    ".github/workflows/gate.yml",
    "README.md",
)

# Cap how much of any one file we feed the model — keep the learning pass cheap.
_MAX_FILE_BYTES = 4000


def is_observe_mode(state: dict) -> bool:
    """OBSERVE/learning mode is on when state.mode == 'observe' OR env LEARN_MODE=1."""
    if (state or {}).get("mode") == "observe":
        return True
    return os.environ.get("LEARN_MODE") == "1"


def _org_root() -> str:
    return os.environ.get("SCHEDULER_ORG_ROOT", _DEFAULT_ORG_ROOT)


def _read_head(path: str, limit: int = _MAX_FILE_BYTES) -> str:
    """Read up to `limit` bytes of a file, read-only. Never raises."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            data = fh.read(limit + 1)
    except Exception:
        return ""
    if len(data) > limit:
        return data[:limit] + "\n…(truncated)…"
    return data


def _git(repo_dir: str, *args: str) -> str:
    """Run a strictly read-only git inspection in repo_dir. Never raises, never mutates."""
    try:
        out = subprocess.run(
            ["git", "-C", repo_dir, *args],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return (out.stdout or out.stderr or "").strip()
    except Exception as exc:  # missing git / not a repo / timeout — degrade, don't crash
        return f"(git {' '.join(args)} unavailable: {exc})"


def read_local_repo_recon(local_repo_dir: str) -> dict:
    """READ-ONLY recon of a local checkout: test-setup files + recent git history.

    `local_repo_dir` is the repo folder name under the Scheduler-Systems org root
    (e.g. "scheduler-web"). Returns a dict of facts for the model. Never dispatches,
    never writes, never runs the suite.
    """
    repo_dir = os.path.join(_org_root(), local_repo_dir)
    facts: dict = {"repo_dir": repo_dir, "exists": os.path.isdir(repo_dir)}
    if not facts["exists"]:
        facts["note"] = f"local checkout not found at {repo_dir}; recon limited"
        facts["test_setup"] = {}
        facts["git_log"] = "(no local checkout)"
        facts["git_status"] = "(no local checkout)"
        return facts

    # Test-setup files that actually exist (read-only).
    test_setup: dict = {}
    for rel in _RECON_FILES:
        full = os.path.join(repo_dir, rel)
        if os.path.isfile(full):
            content = _read_head(full)
            if content:
                test_setup[rel] = content
    facts["test_setup"] = test_setup
    facts["test_setup_files"] = sorted(test_setup.keys())

    # Recent git history (read-only inspections only).
    facts["git_log"] = _git(repo_dir, "log", "-n", "20", "--pretty=format:%h %ad %s", "--date=short")
    facts["git_status"] = _git(repo_dir, "status", "--short", "--branch")
    return facts


def render_recon(facts: dict, max_files: int = 8) -> str:
    """Render recon facts into a compact, model-friendly prompt block (read-only)."""
    lines = [f"LOCAL REPO: {facts.get('repo_dir')}  (exists={facts.get('exists')})"]
    if facts.get("note"):
        lines.append(f"NOTE: {facts['note']}")
    files = facts.get("test_setup_files") or []
    lines.append(f"TEST-SETUP FILES FOUND ({len(files)}): {', '.join(files) or 'none'}")
    lines.append("")
    lines.append("RECENT GIT LOG (last 20, read-only):")
    lines.append(facts.get("git_log") or "(none)")
    lines.append("")
    lines.append("GIT STATUS (read-only):")
    lines.append(facts.get("git_status") or "(clean/unknown)")
    setup = facts.get("test_setup") or {}
    for rel in (facts.get("test_setup_files") or [])[:max_files]:
        lines.append("")
        lines.append(f"----- {rel} -----")
        lines.append(setup.get(rel, ""))
    return "\n".join(lines)
