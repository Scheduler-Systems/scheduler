# Scheduler

[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-blue.svg)](LICENSE)
[![CI](https://github.com/Scheduler-Systems/scheduler/actions/workflows/ci.yml/badge.svg)](https://github.com/Scheduler-Systems/scheduler/actions/workflows/ci.yml)
[![Stars](https://img.shields.io/github/stars/Scheduler-Systems/scheduler?style=social)](https://github.com/Scheduler-Systems/scheduler/stargazers)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

**Open-source shift & workforce scheduling for small teams.** Build rosters, manage
employees and shifts, and run the whole thing yourself — a Go API, a Next.js web app,
and native iOS/Android clients, powered by a billing-free scheduling engine.
Licensed under **AGPL-3.0**.

> ☁️ **Don't want to self-host?** **[Start free on Scheduler Cloud →](https://app.scheduler-systems.com/?utm_source=github&utm_medium=readme&utm_campaign=oss-launch)**
> — the fully managed version, zero setup. Learn more at
> [scheduler-systems.com](https://scheduler-systems.com/?utm_source=github&utm_medium=readme&utm_campaign=oss-launch).

## Features

- 🗓️ Shift & roster scheduling on a dependency-free engine (`packages/core`)
- 👥 Employee & tenant management with auth
- 📱 Native iOS (SwiftUI) and Android (Kotlin/Compose) clients, plus a Next.js web app
- 🔌 **BYO billing** — a pluggable seam; the open build is fully functional and **unmetered** (everyone is the free tier)
- 🔓 100% open source (AGPL-3.0) — self-host anywhere

## Quickstart (self-host)

```sh
# API — Go HTTP API, in-memory store
cd services/api && make test && make dev          # :8080

# Web — Next.js app
cd apps/web && cp .env.local.example .env.local   # set your Firebase config
npm install && npm run dev
```

Mobile: `apps/android` (`make run`) and `apps/ios` — see each app's README.

## Project layout

```
services/api/      Go HTTP API (tenant auth, schedules, employees, WhatsApp webhook)
apps/web/          Next.js web app (Firebase auth/Firestore; billing STUBBED)
apps/android/      Native Android client (Kotlin/Compose)
apps/ios/          Native iOS client (Swift/SwiftUI)
packages/core/     Billing-free scheduling engine (no-dependency Node)
```

- API — [`services/api/api-boundaries.md`](services/api/api-boundaries.md) · env: [`services/api/.env.example`](services/api/.env.example)
- Web — [`apps/web/README.md`](apps/web/README.md) · Android — [`apps/android/README.md`](apps/android/README.md) · iOS — [`apps/ios/README.md`](apps/ios/README.md)

## Open core & BYO billing

This is the **open core**, and it runs fully functional and **unmetered**. Monetization
(the RevenueCat seat-band catalog, entitlement sync, paywall control-plane) is
intentionally **not** in this repository — it powers the hosted
[Scheduler Cloud](https://app.scheduler-systems.com/?utm_source=github&utm_medium=readme&utm_campaign=oss-launch).
Billing is a pluggable seam, not a hard dependency:

- **Engine** (`packages/core`): `createSchedulerApi({ store, billing })` takes a
  `BillingProvider`; the default is a no-op (`src/billing-stub.mjs`) — free tier for everyone.
- **Web** (`apps/web/lib/billing/*`): stubs resolve every user to the free tier. Set
  `NEXT_PUBLIC_CHECKOUT_BASE_URL` and swap in your own provider (RevenueCat, Stripe, …).

Out of the box, no external billing API is contacted and no charge can occur.

## Configuration

Everything project-specific comes from env — there are **no** baked-in project ids,
keys, or checkout URLs. See `apps/web/.env.local.example` and the `*_PROJECT_ID` /
`NEXT_PUBLIC_FIREBASE_*` variables.

## Contributing & security

- [CONTRIBUTING.md](CONTRIBUTING.md) · [Code of Conduct](CODE_OF_CONDUCT.md)
- Found a vulnerability? See [SECURITY.md](SECURITY.md) — please do not open public issues for security reports.

## License

[AGPL-3.0](LICENSE) · © Scheduler Systems Ltd.
