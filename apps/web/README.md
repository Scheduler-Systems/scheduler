# Scheduler Web (Next.js)

Next.js 16 web app for Scheduler. Replaces the Flutter web surface. Lives at
`apps/web/` in the Scheduler repo.

**Status:** 21 / 31 Flutter routes ported (~68%). Full dogfood loop working.
Migration tracked in [#1728](https://github.com/Scheduler-Systems/Scheduler/issues/1728).

Flutter web still serves `your-firebase-project-id.web.app` until DNS cutover.

## Stack

- **Next.js 16** (App Router, static export)
- **React 19** — client components for anything that touches Firebase
- **Tailwind CSS 4** — utility-first styling
- **TypeScript 5**
- **Firebase 12** — Auth, Firestore (same `your-firebase-project-id` project as Flutter)
- **Vitest + jsdom** — unit tests for pure logic

## Local dev

```bash
cd apps/web
cp .env.local.example .env.local
# Fill in NEXT_PUBLIC_FIREBASE_API_KEY from your own Firebase web app config
# (Firebase Console -> Project settings -> your web app). If you keep it in a
# secret manager, fetch it from there — e.g. with gcloud:
#   gcloud secrets versions access latest --secret=YOUR_FIREBASE_API_KEY_SECRET \
#     --project=YOUR_GCP_PROJECT_ID

npm install
npm run dev           # → http://localhost:3000
npm test              # Vitest (unit tests)
npm run build         # Static export → ./out/
```

## Routes

**Auth / marketing (public)**

| Route               | Purpose                                   |
|---------------------|-------------------------------------------|
| `/`                 | Public landing (redirects to `/dashboard` if signed in) |
| `/login`            | Email + Google sign-in                    |
| `/signup`           | Create account                            |
| `/verify-email`     | "Check your inbox" with auto-poll + resend |
| `/phone-signin`     | Phone OTP (pending Firebase console flag) |
| `/forgot-password`  | Password reset                            |

**App (authenticated)**

| Route                                 | Purpose                                      |
|---------------------------------------|----------------------------------------------|
| `/dashboard`                          | Landing for signed-in users                  |
| `/onboarding`                         | First-login name + role setup                |
| `/profile`                            | Edit display name + title                    |
| `/settings`                           | Account / sign-out                           |
| `/employees`                          | All employees across all schedules           |
| `/schedules`                          | My schedules                                 |
| `/schedules/new`                      | Create a schedule                            |
| `/schedules/[id]`                     | Schedule detail — build, publish, CSV export |
| `/schedules/[id]/settings`            | Enabled shifts, num stations, deadline       |
| `/schedules/[id]/import`              | CSV employee import                          |
| `/schedules/[id]/priorities`          | Employee priority submission / view all      |
| `/schedules/[id]/archived`            | Past built schedules                         |

**SEO / PWA (generated)**

| Route                   | Purpose             |
|-------------------------|---------------------|
| `/robots.txt`           | Crawl rules         |
| `/sitemap.xml`          | Crawlable URLs      |
| `/manifest.webmanifest` | PWA manifest        |

## Schedule builder

`lib/schedule-builder.ts`:

1. **Priority-aware pick** — workers who marked the exact `<weekday>|<shift>`
   cell as a priority in `/schedules/[id]/priorities` win first, tie-break on
   fewest current assignments.
2. **Fairness fallback** — no priority match → least-assigned eligible worker.
3. **Same-day conflict avoidance** (toggle on detail page) — worker already on
   the day is skipped for later shifts.

Full coverage in `lib/schedule-builder.test.ts`.

## Firebase

- **Project:** `your-firebase-project-id` (shared with Flutter mobile app)
- **Config:** `lib/firebase.ts` — lazy browser-only init; pulls
  `NEXT_PUBLIC_FIREBASE_API_KEY` from build env.
- **Static export gotcha:** the API key must be baked in at build time via a
  build-env secret (e.g. a `FIREBASE_WEB_API_KEY` GitHub Actions secret) —
  missing key ⇒ `auth/invalid-api-key` infinite loop ⇒ Chrome shows "This page
  couldn't load" while `curl` returns 200. Make sure your deploy pipeline injects
  `NEXT_PUBLIC_FIREBASE_API_KEY` into the build step.

## Deployment

Deploys to a Firebase Hosting site of your choosing. The shipped CI does
`next build` (static export → `./out/`) and `firebase deploy --only hosting`.

- **PR / push to `main`:** `.github/workflows/ci.yml` runs typecheck, lint,
  test, and build for `apps/web/**` (no deploy).
- **Release:** `apps/web/.github/workflows/release.yml` (tag push `v*`) builds
  and deploys to Firebase Hosting using your own GCP/Firebase credentials
  (`GCP_WORKLOAD_IDENTITY_PROVIDER` / `GCP_SERVICE_ACCOUNT` secrets and the
  `FIREBASE_PROJECT` env). Point these at your own project.

Set your hosting target and project in the release workflow before enabling it.

## Source layout

```
app/
  layout.tsx              Root layout, metadata, OG/Twitter tags
  page.tsx                Public landing (with client-side redirect for auth'd users)
  manifest.ts             PWA manifest generator
  robots.ts               robots.txt generator
  sitemap.ts              sitemap.xml generator
  (auth)/                 Auth flows (public)
    login/ signup/ forgot-password/ phone-signin/ onboarding/ verify-email/
  (app)/                  Protected layout + routes
    dashboard/
    profile/
    settings/
    employees/
    schedules/
      [id]/
        page.tsx          Shell (Suspense wrapper)
        schedule-detail-client.tsx
        settings/ import/ priorities/ archived/
      new/
components/
  nav.tsx                 Top nav with avatar-link to /settings
  built-schedule-grid.tsx
  shift-grid/             Cell-grid for priorities + settings
lib/
  firebase.ts             Lazy Firebase init
  auth-context.tsx        useAuth() — email, Google, phone, verify, reload, sign-out
  auth-validation.ts      Pure: email regex, password strength, friendly auth errors
  verify-email.ts         Pure: rate-limit window for resend
  types.ts                Firestore document types (shared with Flutter shape)
  firestore.ts            Typed read wrappers
  firestore-write.ts      Typed write wrappers (incl. deleteSchedule batch)
  schedule-builder.ts     Priority-aware builder (pure)
  csv-employees.ts        CSV import parse + validation
  csv-export.ts           Schedule → CSV download
  shifts.ts               Parse + normalize enabled_shifts (handles both schema shapes)
```

## Testing

- Unit tests: `npm test` (Vitest + jsdom)
- Type check: `npx tsc --noEmit`
- Lint: `npm run lint`
- Build sanity: `npm run build`

All three run on every PR via the root `.github/workflows/ci.yml` (web job).

E2E / Playwright is planned but not yet wired; see #1728 Phase 5.
