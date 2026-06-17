import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    environmentOptions: {
      jsdom: {
        url: "http://localhost:3000",
      },
    },
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    // Playwright specs live in e2e/ and use a different runner
    // Legacy node:test specs live in test/ and use a different runner
    exclude: ["node_modules/**", "e2e/**", "test/**", ".next/**", "out/**"],
    coverage: {
      provider: "v8",
      reporter: ["text", "html", "json-summary"],
      // Coverage is scoped to code we author. `app/**` now covers every page
      // since P0-2 (#1757) landed ~97 unit tests co-located with each page
      // source file — any new page without a test will pull the average
      // below the thresholds below and fail CI.
      include: [
        "lib/**/*.{ts,tsx}",
        "components/**/*.{ts,tsx}",
        "app/**/*.{ts,tsx}",
      ],
      exclude: [
        "**/*.test.{ts,tsx}",
        "**/*.d.ts",
        // Thin SDK bootstrap (browser-only), exercised via integration/E2E
        // or via the public API tests (lib/billing/{client,purchase}.test.ts)
        // that inject their own callable + SDK loader. The uncovered ~30% in
        // each is purely the `await import("firebase/...")` / `await
        // import("@revenuecat/purchases-js")` lazy-SDK bridge — only exercised
        // at runtime in a real browser, not unit-testable. Structurally
        // identical to lib/firebase.ts.
        "lib/firebase.ts",
        "lib/billing/client.ts",
        "lib/billing/purchase.ts",
        // Type-only modules with no runtime code (interfaces/enums only).
        "lib/types.ts",
        "lib/requests-types.ts",
        "lib/chat-types.ts",
        // App Router thin shells — tested via Playwright, not unit.
        "app/**/layout.tsx",
        // Root page.tsx is a metadata + <HomePage/> wrapper — logic lives in
        // home-page.tsx (which IS covered). The wrapper itself is identical
        // to a layout shell.
        "app/page.tsx",
        // Static-export shell pages for dynamic [id] routes. Each one just
        // returns generateStaticParams([{id:"_"}]) + <ClientComponent/>. The
        // real logic is in the co-located *-client.tsx (which IS covered).
        "app/**/schedules/[id]/page.tsx",
        "app/**/schedules/[id]/archived/page.tsx",
        "app/**/schedules/[id]/import/page.tsx",
        "app/**/schedules/[id]/priorities/page.tsx",
        "app/**/schedules/[id]/settings/page.tsx",
        // Same pattern for verify-email: server <Suspense> shell around a
        // client component that's fully covered.
        "app/**/verify-email/page.tsx",
        // Next.js metadata route files — pure static data returned by a
        // single function; no runtime branching to cover.
        "app/manifest.ts",
        "app/robots.ts",
        "app/sitemap.ts",
        // Client-side error boundary — tested via Playwright.
        "app/global-error.tsx",
        // API route handlers — tested via Playwright, not unit.
        // These are Next.js server-side route handlers that require
        // full Firebase Auth / Firestore infrastructure in a real server
        // environment. Playwright E2E tests cover them at the user level.
        "app/api/**/route.ts",
        // Auth form components — client-side forms with Firebase SDK
        // integration. Tested via the page-level tests (login, signup,
        // phone-signin page.test.tsx files) and Playwright E2E.
        "components/auth/*.tsx",
        // Barrel re-exports — no logic to cover.
        "**/index.ts",
      ],
      // P0-1 initial floor: enforces the current baseline after the P0-2
      // page-test landing (#1757) + this PR's targeted gap-fills. The ideal
      // target is 92/82/92/92 — the remaining shortfall lives almost entirely
      // in `schedules/[id]/schedule-detail-client.tsx` (94 uncovered stmts
      // in a 682-line client component) and a handful of SDK bootstrap
      // paths in `lib/billing/client.ts`. Next ticket (P0-3) bumps these
      // to 92/82/92/92 by adding the missing schedule-detail tests and
      // refactoring the billing SDK bridge behind an injectable factory.
      //
      // DO NOT lower these — any new page file without a test, or any
      // regression in an existing one, will drop the average below the
      // floor and fail CI. That is the feature.
      thresholds: {
        statements: 85,
        branches: 75,
        functions: 85,
        lines: 85,
      },
    },
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./"),
    },
  },
});
