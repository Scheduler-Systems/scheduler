import { test, expect } from "@playwright/test";
import { onEmulators, signUpFreshCreator, createSchedule } from "./helpers/emulator";

// =========================================================================
// Full employer journey — runs against the LOCAL Firebase emulators.
// =========================================================================
//
// Unlike authenticated.spec.ts (which needs a pre-provisioned account on the
// live deploy), this suite signs up a FRESH user on the Auth emulator each
// run, so it can exercise the complete authenticated flow end-to-end with no
// shared state and no risk to production data.
//
// To run:
//   1. firebase emulators:start --only auth,firestore --project your-firebase-project-id   (make emulators)
//   2. NEXT_PUBLIC_USE_FIREBASE_EMULATORS=true npm run dev                        (make dev)
//   3. E2E_BASE_URL=http://localhost:3000 E2E_USE_EMULATORS=1 \
//        npx playwright test --project=chromium e2e/emulator-employer-journey.spec.ts

test.describe("Employer journey (Firebase emulators)", () => {
  test.skip(!onEmulators, "Set E2E_USE_EMULATORS=1 and E2E_BASE_URL=http://localhost:3000 to run the emulator journey");

  test("signup → onboarding → dashboard", async ({ page }) => {
    await signUpFreshCreator(page);
    await expect(page.getByText(/your workforce planning overview/i)).toBeVisible();
    await expect(page.getByText(/no schedules yet/i)).toBeVisible();
  });

  test("creates a schedule and lands on its detail page", async ({ page }) => {
    await signUpFreshCreator(page);
    await createSchedule(page, "Clinic Rota");
    await expect(page).toHaveURL(/\/schedules\/[^/]+\/?$/, { timeout: 15_000 });
    await expect(page.getByRole("heading", { name: /clinic rota/i })).toBeVisible({ timeout: 10_000 });
    // The creator is auto-added as an employee.
    await expect(page.getByText(/employees \(1\)/i)).toBeVisible();
  });

  test("rejects a duplicate schedule name with a clear error", async ({ page }) => {
    await signUpFreshCreator(page);
    await createSchedule(page, "Clinic Rota");
    await expect(page.getByRole("heading", { name: /clinic rota/i })).toBeVisible({ timeout: 10_000 });

    // Second create with the same name must surface the duplicate error.
    await createSchedule(page, "Clinic Rota");
    await expect(
      page.getByText(/a schedule with this name already exists/i),
    ).toBeVisible({ timeout: 10_000 });
  });

  test("adds an employee to a schedule", async ({ page }) => {
    await signUpFreshCreator(page);
    await createSchedule(page, "Clinic Rota");
    await expect(page.getByRole("heading", { name: /clinic rota/i })).toBeVisible({ timeout: 10_000 });

    await page.getByRole("button", { name: /add employee/i }).click();
    await page.getByPlaceholder(/full name/i).fill("Alice Worker");
    await page.getByPlaceholder(/^email$/i).fill("alice@example.com");
    await page.getByRole("button", { name: /^add employee$/i }).click();

    await expect(page.getByText(/employees \(2\)/i)).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/alice worker/i)).toBeVisible();
  });

  test("builds and publishes a schedule", async ({ page }) => {
    await signUpFreshCreator(page);
    await createSchedule(page, "Clinic Rota");
    await expect(page.getByRole("heading", { name: /clinic rota/i })).toBeVisible({ timeout: 10_000 });

    await page.getByRole("button", { name: /build schedule/i }).click();
    await page.getByRole("button", { name: /^publish$/i }).click();
    await expect(page.getByText(/published new schedule/i)).toBeVisible({ timeout: 15_000 });
  });

  test("premium: free-tier station limit triggers the paywall on a 2nd schedule", async ({ page }) => {
    await signUpFreshCreator(page);
    await createSchedule(page, "Clinic Rota");
    await expect(page.getByRole("heading", { name: /clinic rota/i })).toBeVisible({ timeout: 10_000 });

    // A unique second name passes the dup check but hits the free-tier limit.
    await createSchedule(page, "Night Rota");
    await expect(page.getByText(/choose your plan/i)).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/your current plan allows 1 station/i)).toBeVisible();
    // All four tiers are offered (assert via the tier-card headings).
    await expect(page.getByRole("heading", { name: "Free", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Essentials", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Pro", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Enterprise", exact: true })).toBeVisible();
  });
});
