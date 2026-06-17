import assert from "node:assert/strict";
import test from "node:test";

// Test credentials — set these env vars to run authenticated E2E tests.
// See TODO below for instructions on provisioning a test account.
const TEST_USER_EMAIL = process.env.TEST_USER_EMAIL;
const TEST_USER_PASSWORD = process.env.TEST_USER_PASSWORD;

// =========================================================================
// Authenticated user flows
// =========================================================================
//
// These tests require a real test account. When no credentials are available
// the entire suite is skipped with a clear diagnostic message.
//
// TODO: Authenticated E2E coverage — what needs to happen
// -------------------------------------------------------
// 1. Provision a dedicated test account in the Firebase project
//    (or enable the Firebase Auth emulator and seed a test user).
// 2. Set TEST_USER_EMAIL / TEST_USER_PASSWORD in .env.local (do not commit).
// 3. Remove the skip condition and implement the tests below using
//    Playwright (not node:test) because browser-based Firebase Auth
//    signInWithEmailAndPassword requires a real DOM environment.
//
//    A Playwright equivalent belongs in e2e/authenticated.spec.ts and
//    would look like:
//
//      import { test, expect } from "@playwright/test";
//
//      test("logs in and sees the dashboard", async ({ page }) => {
//        await page.goto("/login");
//        await page.getByLabel(/email/i).fill(TEST_USER_EMAIL);
//        await page.getByLabel(/password/i).fill(TEST_USER_PASSWORD);
//        await page.getByRole("button", { name: /^sign in$/i }).click();
//        // After login, the SPA should redirect to the dashboard.
//        await expect(page.getByText(/schedules/i)).toBeVisible({ timeout: 10_000 });
//        // Verify schedule list renders
//        await expect(page.getByRole("table")).toBeVisible();
//        // Navigate to schedule detail
//        await page.getByRole("link", { name: /first schedule/i }).click();
//        await expect(page.getByRole("heading", { name: /schedule detail/i })).toBeVisible();
//        // Verify CRUD UI elements
//        await expect(page.getByRole("button", { name: /edit|delete|create/i })).toBeVisible();
//      });

test("authenticated user: dashboard loads after login", {
  skip: !TEST_USER_EMAIL || !TEST_USER_PASSWORD
    ? "Set TEST_USER_EMAIL and TEST_USER_PASSWORD env vars to run authenticated E2E tests"
    : false,
}, async () => {
  // Sanity check: if skip resolves to false the test should actually try to
  // authenticate against the running app. Because node:test has no browser
  // environment for Firebase Auth's signInWithEmailAndPassword, this assertion
  // is deliberately written to fail with a clear message directing developers
  // to the Playwright equivalent in e2e/authenticated.spec.ts.
  assert.fail(
    "node:test cannot run browser-based Firebase Auth login. " +
    "Remove the skip above and implement this as a Playwright test in " +
    "e2e/authenticated.spec.ts instead (see the TODO block in the " +
    "comment at the top of this file)."
  );
});
