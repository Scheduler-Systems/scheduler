# Firestore / Storage security-rules tests

Emulator-backed tests for [`apps/web/firestore.rules`](../../firestore.rules) and
[`apps/web/storage.rules`](../../storage.rules), using
[`@firebase/rules-unit-testing`](https://firebase.google.com/docs/rules/unit-tests).
They assert both that **legitimate access works** and that the **IDOR /
privilege-escalation surfaces are denied**.

This package is intentionally separate from the Next.js app so `firebase-tools`
(large) does not bloat the web build.

## Run

```bash
cd apps/web/test/firestore-rules
npm install
npm test          # firebase emulators:exec --only firestore  ->  node --test
```

Requires **Java 11+** (the Firestore emulator is a JVM process). The emulator
port (`8088`) comes from [`apps/web/firebase.json`](../../firebase.json).

## What is covered

| Area | Asserted |
|------|----------|
| Auth gate | unauthenticated access denied |
| `users` | own-profile write only; `role` immutable once set; build counters un-tamperable; profiles readable for email lookup |
| `schedules` | create stamps `created_by`; owner-only update/delete; `created_by` immutable |
| `built_schedules` / `priorities_submissions` | owner writes; user writes only own slot |
| `shift_requests` / `schedule_requests` | author-only create |
| `notifications` | recipient-scoped read/update; no client create |
| `chats` / messages | participant gate (uid **and** reference forms); sender must be self |
| `ff_user_push_notifications` | enqueue allowed; token doc owner-only |
| `webhook_events` | no client access |

> Not deployed by these tests — a production rules deploy is a founder hard gate
> (credentialed prod-snapshot replay + sign-off).
