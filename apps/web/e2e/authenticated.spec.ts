import { test, expect } from "@playwright/test";

const TEST_USER_EMAIL = process.env.TEST_USER_EMAIL;
const TEST_USER_PASSWORD = process.env.TEST_USER_PASSWORD;

// =========================================================================
// Authenticated user flows
// =========================================================================
//
// These tests require a real test account. When no credentials are available
// the entire suite is skipped with a clear diagnostic message.
//
// To run locally:
//   1. Provision a test account in the Firebase project.
//   2. Set TEST_USER_EMAIL / TEST_USER_PASSWORD in .env.local (do not commit).
//   3. Start the dev server: npm run dev
//   4. Run: E2E_BASE_URL=http://localhost:3000 npx playwright test --project=chromium e2e/authenticated.spec.ts

test.describe("Authenticated user flows", () => {
  test.skip(!TEST_USER_EMAIL || !TEST_USER_PASSWORD, "Set TEST_USER_EMAIL and TEST_USER_PASSWORD env vars to run authenticated E2E tests");

  test("logs in and navigates to the dashboard", async ({ page }) => {
    // Navigate to login page
    await page.goto("/login");

    // Fill in credentials
    await page.getByLabel(/email/i).fill(TEST_USER_EMAIL!);
    await page.getByLabel(/password/i).fill(TEST_USER_PASSWORD!);

    // Submit the sign-in form
    await page.getByRole("button", { name: /^sign in$/i }).click();

    // After login the SPA should redirect to the dashboard.
    // Wait for a heading or link that confirms we're on the dashboard.
    await expect(page.getByText(/dashboard/i)).toBeVisible({ timeout: 15_000 });

    // Verify the dashboard shows schedule-related content or quick actions.
    await expect(page.getByText(/schedules|quick actions/i)).toBeVisible({ timeout: 10_000 });
  });

  test("dashboard shows schedule list", async ({ page }) => {
    await page.goto("/login");
    await page.getByLabel(/email/i).fill(TEST_USER_EMAIL!);
    await page.getByLabel(/password/i).fill(TEST_USER_PASSWORD!);
    await page.getByRole("button", { name: /^sign in$/i }).click();

    // Wait for dashboard to render after login redirect.
    await expect(page.getByText(/dashboard/i)).toBeVisible({ timeout: 15_000 });

    // Navigate to the schedules list page via dashboard links or nav.
    await page.goto("/dashboard");
    await page.waitForLoadState("networkidle");

    // The dashboard should render schedule rows or an empty-state message.
    // Either is acceptable — we just need to verify the page loaded.
    const scheduleList = page.locator("table, [role='table'], [data-testid='schedule-list']");
    const emptyState = page.getByText(/no schedules yet/i);

    // If the user has schedules, verify they render. If not, verify the empty state.
    if (await scheduleList.isVisible()) {
      await expect(scheduleList).toBeVisible();
      // Verify at least one schedule row or link is present
      await expect(page.getByText(/schedule/i).first()).toBeVisible();
    } else if (await emptyState.isVisible()) {
      await expect(emptyState).toBeVisible();
    }
    // If neither is visible yet, wait briefly for content to render
    await expect(
      page.getByText(/schedules|quick actions|no schedules/i),
    ).toBeVisible({ timeout: 10_000 });
  });

  test("navigates to a schedule detail from the dashboard", async ({ page }) => {
    await page.goto("/login");
    await page.getByLabel(/email/i).fill(TEST_USER_EMAIL!);
    await page.getByLabel(/password/i).fill(TEST_USER_PASSWORD!);
    await page.getByRole("button", { name: /^sign in$/i }).click();

    // Wait for dashboard to load
    await expect(page.getByText(/dashboard/i)).toBeVisible({ timeout: 15_000 });

    // Navigate to the schedules listing page
    await page.goto("/schedules");
    await page.waitForLoadState("networkidle");

    // Wait for the page to load — either schedules or empty state
    await page.waitForTimeout(2000);

    // Look for a clickable schedule link or row (anchor tags, buttons, or table rows).
    const scheduleLink = page.locator(
      'a[href*="/schedules/"]:not([href*="/schedules$"]), [role="link"][href*="/schedules/"]',
    ).first();

    if (await scheduleLink.isVisible({ timeout: 3000 }).catch(() => false)) {
      await scheduleLink.click();
      // After clicking a schedule link, we should land on the schedule detail page.
      await expect(page).toHaveURL(/\/schedules\//, { timeout: 10_000 });

      // The schedule detail should show PDF download button or schedule name.
      const downloadBtn = page.getByRole("button", { name: /download pdf/i });
      const scheduleHeading = page.locator("h1, h2").filter({ hasText: /schedule|roster/i }).first();
      await expect(
        downloadBtn.or(scheduleHeading).first(),
      ).toBeVisible({ timeout: 10_000 });
    } else {
      // No schedules exist — assert empty state message.
      await expect(
        page.getByText(/no schedules/i),
      ).toBeVisible({ timeout: 10_000 });
    }
  });
});
