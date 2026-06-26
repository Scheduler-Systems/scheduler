# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims to
follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html). `v1.0.0` will be
the first semver-tagged release.

## [Unreleased]

### Added
- **Persistent storage for the Go API** — a Firestore-backed `Store` selectable via
  `SCHEDULER_STORE=firestore` (default `memory`); data now survives restarts. A boot
  readiness probe fails fast if the backend is unreachable or misconfigured.
- **Firestore + Cloud Storage security rules** (`apps/web/firestore.rules`,
  `apps/web/storage.rules`) with an emulator-backed test suite.
- **Native-app & engine CI** — Android (build + unit tests + lint, then launch on an
  emulator) and iOS (build + unit tests on a simulator, then a launch smoke) jobs that
  actually run the apps, plus an engine (`packages/core`) test job.
- **`examples/create-a-schedule.sh`** — a zero-dependency quickstart that creates a
  schedule against the engine.
- This changelog.

### Security
- Removed the agent-dispatch HTTP route from the **product** engine
  (`packages/core`) — it had an SSRF + key-exfiltration risk and belongs in the
  hosted control plane. (Note: the `workforce/` directory is a separate,
  **development/experimental** LangGraph fleet — not part of the self-hostable
  product; it is not built, run, or supported by this release. See `workforce/README.md`.)
- Cleared web dependency vulnerabilities (Dependabot alerts → 0).

### Known limitations
- The Firestore-backed Go API store (`SCHEDULER_STORE=firestore`, opt-in; the
  default is in-memory) does not yet surface **runtime** write failures to
  callers — only a boot readiness probe is enforced, so a Firestore outage
  *after* startup can drop a write silently. Tracked fix: thread error returns
  through the `Store` interface (services/api/internal/store).

## Project history

The open core was first published on **2026-06-17** under **AGPL-3.0**: the Go HTTP
API (`services/api`), the Next.js web app (`apps/web`), native iOS (SwiftUI) and
Android (Kotlin/Compose) clients, and the dependency-free scheduling engine
(`packages/core`) — with a BYO-billing seam so the open build runs fully functional
and unmetered.
