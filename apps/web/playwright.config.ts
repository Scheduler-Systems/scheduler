import { defineConfig, devices } from "@playwright/test";

// Smoke-test config. Runs against the deployed scheduler-web-next.web.app
// by default (so CI doesn't need to spin up a dev server). Override with
// `E2E_BASE_URL=http://localhost:3000 npx playwright test` when iterating.
const BASE_URL =
  process.env.E2E_BASE_URL ?? "https://scheduler-web-next.web.app";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? "dot" : "list",
  use: {
    baseURL: BASE_URL,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      // The default project excludes accessibility.spec.ts so the smoke
      // suite stays fast — a11y has its own project below.
      testIgnore: /accessibility\.spec\.ts$/,
      use: { ...devices["Desktop Chrome"] },
    },
    {
      // Dedicated a11y project: runs ONLY e2e/accessibility.spec.ts so it
      // can be scheduled independently in CI via
      //   npx playwright test --project=accessibility
      name: "accessibility",
      testMatch: /accessibility\.spec\.ts$/,
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  // Intentionally no webServer — smoke tests hit the live deploy.
});
