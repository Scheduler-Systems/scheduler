# Scheduler (open core)

Open-source shift-scheduling platform: a Go API, a Next.js web app, and a
billing-free scheduling engine. Licensed under **AGPL-3.0** (see `LICENSE`).

This is the **open core**. Monetization (the RevenueCat seat-band catalog,
entitlement sync, paywall control-plane) is intentionally **not** in this
repository — it lives in a separate private control-plane that powers the
hosted Scheduler Cloud. The open-source build runs fully functional and
**unmetered** (every user is the free tier), and exposes a clean **BYO billing**
seam so you can wire your own provider.

## Layout

```
services/api/      Go HTTP API (tenant auth, schedules, employees, WhatsApp webhook)
apps/web/          Next.js web app (Firebase auth/Firestore; billing STUBBED)
apps/android/      Native Android client (Kotlin/Compose)
apps/ios/          Native iOS client (Swift/SwiftUI)
packages/core/     Billing-free scheduling engine (no-dependency Node)
```

- API — [`services/api/api-boundaries.md`](services/api/api-boundaries.md) ·
  env: [`services/api/.env.example`](services/api/.env.example)
- Web — [`apps/web/README.md`](apps/web/README.md)
- Android — [`apps/android/README.md`](apps/android/README.md)
- iOS — [`apps/ios/README.md`](apps/ios/README.md)

## BYO billing

Billing is a pluggable seam, not a hard dependency:

- **Engine** (`packages/core`): `createSchedulerApi({ store, billing })` takes a
  `BillingProvider`. The default is a no-op (`src/billing-stub.mjs`) — free tier
  for everyone, nothing metered.
- **Web** (`apps/web/lib/billing/*`): ships stubs that resolve every user to the
  free tier. Set `NEXT_PUBLIC_CHECKOUT_BASE_URL` and replace the stubs with your
  own provider client (RevenueCat, Stripe, etc.) to enable real purchases.

Out of the box, no external billing API is contacted and no charge can occur.

## Run

```sh
# API
cd services/api && make test && make dev      # :8080, in-memory store

# Web
cd apps/web && cp .env.local.example .env.local   # set your Firebase config
npm install && npm run dev
```

## Configuration

Everything project-specific comes from env. There are **no** baked-in project
ids, keys, or checkout URLs — see `apps/web/.env.local.example` and the
`*_PROJECT_ID` / `NEXT_PUBLIC_FIREBASE_*` env vars.
