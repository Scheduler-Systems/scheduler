import { test, expect } from "@playwright/test";
import {
  onEmulators,
  grantTier,
  signUpFreshCreator,
  createSchedule,
} from "./helpers/emulator";

// =========================================================================
// Premium / subscription — GRANTED-state behavior (Firebase emulators).
//
// Two complementary layers of premium coverage:
//
//  1. The REAL RevenueCat path (no override): the billing callable is routed to
//     the local Functions emulator (see Makefile `emulators` + connectFunctions-
//     Emulator in lib/billing/client.ts), which calls the real RC *sandbox* API
//     with the dev secret. A brand-new user has no RC customer, so RC returns
//     404 → the function maps that to a clean Free state. This proves the live
//     app→function→RC integration + the 404→free fix.
//
//  2. GRANTED-state behavior (what a *paid* user can do): grantTier() sets the
//     dev billing override (emulator-only), which flows through the real
//     deriveTier → limits → enforcement gates. A real active-entitlement read-
//     back needs a completed sandbox store purchase (or a legacy v1 secret key
//     for a promotional grant) — the one externally-gated step.
// =========================================================================

test.describe("Premium granted-state (Firebase emulators)", () => {
  test.skip(!onEmulators, "Set E2E_USE_EMULATORS=1 and E2E_BASE_URL=http://localhost:3000 to run");

  test("FREE via the REAL RevenueCat path: billing shows Free, no error banner (no override)", async ({ page }) => {
    // Deliberately NO grantTier() — exercises the real callable → Functions
    // emulator → RC sandbox (404 customer-not-found → clean Free).
    await signUpFreshCreator(page);
    await page.goto("/settings/billing");
    await expect(page.getByRole("heading", { level: 1, name: /free/i })).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("billing-error-banner")).toHaveCount(0);
  });

  test("FREE: a 2nd schedule hits the paywall (free station limit = 1)", async ({ page }) => {
    await grantTier(page, "free");
    await signUpFreshCreator(page);
    await createSchedule(page, "Clinic Rota");
    await expect(page.getByRole("heading", { name: /clinic rota/i })).toBeVisible({ timeout: 10_000 });
    await createSchedule(page, "Night Rota");
    await expect(page.getByText(/choose your plan/i)).toBeVisible({ timeout: 10_000 });
  });

  test("PRO: a 2nd schedule is ALLOWED — granted tier unlocks past the free limit", async ({ page }) => {
    await grantTier(page, "pro");
    await signUpFreshCreator(page);
    await createSchedule(page, "Clinic Rota");
    await expect(page.getByRole("heading", { name: /clinic rota/i })).toBeVisible({ timeout: 10_000 });
    // On Pro (5 stations) the 2nd schedule must succeed — no paywall.
    await createSchedule(page, "Night Rota");
    await expect(page.getByRole("heading", { name: /night rota/i })).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/choose your plan/i)).toHaveCount(0);
  });

  test("ENTERPRISE: multiple schedules allowed with no paywall (unlimited)", async ({ page }) => {
    await grantTier(page, "enterprise");
    await signUpFreshCreator(page);
    await createSchedule(page, "Rota A");
    await expect(page.getByRole("heading", { name: /rota a/i })).toBeVisible({ timeout: 10_000 });
    await createSchedule(page, "Rota B");
    await expect(page.getByRole("heading", { name: /rota b/i })).toBeVisible({ timeout: 10_000 });
    await createSchedule(page, "Rota C");
    await expect(page.getByRole("heading", { name: /rota c/i })).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/choose your plan/i)).toHaveCount(0);
  });

  test("billing page reflects the granted tier (Pro), not Free", async ({ page }) => {
    await grantTier(page, "pro");
    await signUpFreshCreator(page);
    await page.goto("/settings/billing");
    // The current-plan area should surface the granted tier.
    await expect(page.getByText(/\bpro\b/i).first()).toBeVisible({ timeout: 10_000 });
  });
});
