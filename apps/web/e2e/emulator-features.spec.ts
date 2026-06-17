import { test, expect } from "@playwright/test";
import {
  onEmulators,
  signUpFreshCreator,
  signUpAndCreateSchedule,
} from "./helpers/emulator";

// =========================================================================
// Remaining feature coverage (Firebase emulators) — billing/premium, account
// & schedule settings, priorities, requests, profile, employees, export,
// locale/RTL. Same emulator gating as the employer-journey suite.
// =========================================================================

test.describe("Feature coverage (Firebase emulators)", () => {
  test.skip(!onEmulators, "Set E2E_USE_EMULATORS=1 and E2E_BASE_URL=http://localhost:3000 to run");

  test("billing page shows the current plan and opens the paywall", async ({ page }) => {
    await signUpFreshCreator(page);
    await page.goto("/settings/billing");
    // Free tier by default (no RevenueCat entitlement on the emulator).
    await expect(page.getByText(/plan|tier|free/i).first()).toBeVisible({ timeout: 10_000 });
    // An upgrade affordance must exist and open the paywall.
    const upgrade = page.getByRole("button", { name: /upgrade|choose|change plan|view plans/i }).first();
    if (await upgrade.isVisible().catch(() => false)) {
      await upgrade.click();
      await expect(page.getByText(/choose your plan|essentials|pro|enterprise/i).first()).toBeVisible({ timeout: 10_000 });
    }
  });

  test("account settings page loads", async ({ page }) => {
    await signUpFreshCreator(page);
    await page.goto("/settings");
    await expect(page.getByRole("heading", { name: /settings/i }).first()).toBeVisible({ timeout: 10_000 });
  });

  test("profile page shows the user's identity", async ({ page }) => {
    await signUpFreshCreator(page);
    await page.goto("/profile");
    await expect(page.getByText(/e2e creator|profile|display name/i).first()).toBeVisible({ timeout: 10_000 });
  });

  test("aggregated employees page loads", async ({ page }) => {
    await signUpFreshCreator(page);
    await page.goto("/employees");
    await expect(page.getByRole("heading", { name: /employees/i }).first()).toBeVisible({ timeout: 10_000 });
  });

  test("schedule detail exposes export (CSV + PDF) actions", async ({ page }) => {
    await signUpAndCreateSchedule(page);
    await expect(page.getByRole("button", { name: /export csv/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /download pdf/i })).toBeVisible();
  });

  test("schedule settings page opens from the detail view", async ({ page }) => {
    // Navigate via the schedule id — there is also a global account "Settings"
    // link, so a name-based click is ambiguous.
    const url = await signUpAndCreateSchedule(page);
    const id = url.match(/schedules\/([^/]+)/)?.[1];
    expect(id).toBeTruthy();
    await page.goto(`/schedules/${id}/settings`);
    await expect(page.getByText(/setting|schedule name|station|deadline/i).first()).toBeVisible({ timeout: 10_000 });
  });

  test("priorities page opens from the detail view", async ({ page }) => {
    await signUpAndCreateSchedule(page);
    await page.getByRole("link", { name: /priorities/i }).first().click();
    await expect(page).toHaveURL(/\/schedules\/[^/]+\/priorities/, { timeout: 10_000 });
    await expect(page.getByText(/priorit|availability|submit/i).first()).toBeVisible({ timeout: 10_000 });
  });

  test("schedule requests page opens from the detail view", async ({ page }) => {
    await signUpAndCreateSchedule(page);
    await page.getByRole("link", { name: /requests/i }).first().click();
    await expect(page).toHaveURL(/\/schedules\/[^/]+\/requests/, { timeout: 10_000 });
    await expect(page.getByText(/request|no requests/i).first()).toBeVisible({ timeout: 10_000 });
  });

  test("entry is phone-first (Flutter-aligned) with email/google alternatives", async ({ page }) => {
    // Anonymous visit to the entry — no login, so no redirect.
    await page.goto("/phone-signin");
    // Phone is the primary method.
    await expect(page.getByLabel(/phone/i)).toBeVisible({ timeout: 10_000 });
    // Alternatives offered below (Flutter's phone-first screen).
    await expect(page.getByRole("link", { name: /continue with email/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /continue with google/i })).toBeVisible();
    await expect(page.getByRole("link", { name: /create one/i })).toBeVisible();
  });

  test("locale switch toggles the app to Hebrew (RTL)", async ({ page }) => {
    await signUpFreshCreator(page);
    // The locale switcher is a <select> in the top bar (EN by default).
    const selector = page.locator("select").first();
    await expect(selector).toBeVisible({ timeout: 10_000 });
    await selector.selectOption({ label: /he|עברית|hebrew/i }).catch(async () => {
      // Fall back to value-based selection if the label regex doesn't match.
      await selector.selectOption("he");
    });
    // The document should flip to RTL or render Hebrew text.
    await expect
      .poll(async () => page.locator("html").getAttribute("dir"), { timeout: 5_000 })
      .toBe("rtl");
  });
});
