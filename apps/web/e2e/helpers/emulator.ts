import { expect, type Page } from "@playwright/test";

// Shared helpers for the emulator-backed e2e suites. These only make sense
// against the local Firebase emulators (fresh Auth users per run), so callers
// gate with `onEmulators`.

export const onEmulators =
  !!process.env.E2E_USE_EMULATORS &&
  (process.env.E2E_BASE_URL ?? "").includes("localhost");

export function uniqueEmail(): string {
  // Tests run in node, so Date.now()/Math.random() are fine here.
  return `e2e-${Date.now()}-${Math.random().toString(36).slice(2, 8)}@example.com`;
}

/**
 * Signs up a brand-new employer (Creator role) on the Auth emulator and lands
 * on the dashboard. Returns the email used.
 */
export async function signUpFreshCreator(page: Page, name = "E2E Creator"): Promise<string> {
  const email = uniqueEmail();
  await page.goto("/signup");

  await page.getByLabel(/your name/i).fill(name);
  await page.getByLabel(/^email$/i).fill(email);
  await page.getByLabel(/^password$/i).fill("123456");
  await page.getByLabel(/confirm password/i).fill("123456");
  await page.getByRole("button", { name: /create account/i }).click();

  await page.getByRole("button", { name: /continue anyway/i }).click();

  // Choose-Role screen (Flutter-aligned): pick Manager (employer) so the
  // account can create schedules.
  await expect(page.getByRole("heading", { name: /choose role/i })).toBeVisible({ timeout: 15_000 });
  await page.getByRole("button", { name: /log in as manager/i }).click();

  // Onboarding name step (role already set on Choose-Role).
  await expect(page.getByText(/welcome to scheduler/i)).toBeVisible({ timeout: 15_000 });
  const nameField = page.getByLabel(/display name/i);
  if ((await nameField.inputValue()) === "") await nameField.fill(name);
  await page.getByRole("button", { name: /^continue$/i }).click();

  await expect(page.getByRole("link", { name: /^dashboard$/i })).toBeVisible({ timeout: 15_000 });
  return email;
}

/**
 * Grants a subscription tier for the rest of the session by setting the
 * dev-only billing override (honored only under the emulator flag — see
 * lib/billing/client.ts). Must be called BEFORE the first navigation so the
 * init script is in place when the app reads it.
 */
export async function grantTier(
  page: Page,
  tier: "free" | "essentials" | "pro" | "enterprise",
): Promise<void> {
  await page.addInitScript((t) => {
    try {
      window.localStorage.setItem("dev_billing_tier", t as string);
    } catch {
      /* ignore */
    }
  }, tier);
}

/** Creates a schedule from the New Schedule form. */
export async function createSchedule(page: Page, name: string): Promise<void> {
  await page.goto("/schedules/new");
  await page.getByPlaceholder(/weekly clinic rota/i).fill(name);
  await page.getByRole("button", { name: /create schedule/i }).click();
}

/** Signs up, creates one schedule, and returns its detail-page URL. */
export async function signUpAndCreateSchedule(page: Page, name = "Clinic Rota"): Promise<string> {
  await signUpFreshCreator(page);
  await createSchedule(page, name);
  await expect(page.getByRole("heading", { name: new RegExp(name, "i") })).toBeVisible({ timeout: 15_000 });
  return page.url();
}
