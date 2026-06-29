# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims to
follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

_Nothing yet._

## [1.0.0] - 2026-06-20

First semver-tagged release. Self-host in under a minute
(`./examples/create-a-schedule.sh`) — verified from a clean clone.

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
- Removed the agent-dispatch / LangSmith surface from the open core (SSRF +
  key-exfiltration risk); that functionality belongs in the hosted control plane.
- Cleared web dependency vulnerabilities (Dependabot alerts → 0).

## Project history

The open core was first published on **2026-06-17** under **AGPL-3.0**: the Go HTTP
API (`services/api`), the Next.js web app (`apps/web`), native iOS (SwiftUI) and
Android (Kotlin/Compose) clients, and the dependency-free scheduling engine
(`packages/core`) — with a BYO-billing seam so the open build runs fully functional
and unmetered.
