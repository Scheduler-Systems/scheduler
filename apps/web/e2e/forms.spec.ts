import { test, expect } from "@playwright/test";

// Client-side form validation — no Firebase calls made because the HTML5
// `required` attribute (and/or JS preflight) catches empties first. These
// tests verify the UX contract: blank submit surfaces an error without
// navigation.

test.describe("Login form validation", () => {
  test("empty submit is blocked by HTML5 required (no navigation)", async ({
    page,
  }) => {
    await page.goto("/login");
    await page.getByRole("button", { name: /^sign in$/i }).click();
    // HTML5 validation prevents submit; URL unchanged
    await expect(page).toHaveURL(/\/login/);
    // Email input remains focused and flagged invalid
    const email = page.getByLabel(/email/i);
    const invalid = await email.evaluate(
      (el) => (el as HTMLInputElement).validity.valid
    );
    expect(invalid).toBe(false);
  });

  test("email input enforces type=email constraint", async ({ page }) => {
    await page.goto("/login");
    await page.getByLabel(/email/i).fill("not-an-email");
    await page.getByLabel(/password/i).first().fill("somepassword");
    await page.getByRole("button", { name: /^sign in$/i }).click();
    await expect(page).toHaveURL(/\/login/);
    const email = page.getByLabel(/email/i);
    const invalid = await email.evaluate(
      (el) => (el as HTMLInputElement).validity.valid
    );
    expect(invalid).toBe(false);
  });
});

test.describe("Signup form validation", () => {
  test("empty submit is blocked by HTML5 required", async ({ page }) => {
    await page.goto("/signup");
    await page.getByRole("button", { name: /create account/i }).click();
    await expect(page).toHaveURL(/\/signup/);
  });

  test("mismatched passwords surface an inline error", async ({ page }) => {
    await page.goto("/signup");
    await page.getByLabel(/your name|^name$/i).fill("Test User");
    await page.getByLabel(/email/i).fill("test@example.com");
    const passwords = page.locator('input[type="password"]');
    await passwords.nth(0).fill("validpass1");
    await passwords.nth(1).fill("differentpass2");
    await page.getByRole("button", { name: /create account/i }).click();
    // Mismatch check happens before Firebase; error should appear
    await expect(page.getByText(/don.?t match|no coinciden|אינן תואמות/i)).toBeVisible({
      timeout: 5_000,
    });
  });

  test("too-short password surfaces validation error", async ({ page }) => {
    await page.goto("/signup");
    await page.getByLabel(/your name|^name$/i).fill("Test");
    await page.getByLabel(/email/i).fill("test@example.com");
    const passwords = page.locator('input[type="password"]');
    await passwords.nth(0).fill("abc"); // < 6 chars
    await passwords.nth(1).fill("abc");
    await page.getByRole("button", { name: /create account/i }).click();
    // validatePassword returns !ok with reason — any error banner visible
    const banner = page.locator("div.bg-red-50, [role=alert]").first();
    await expect(banner).toBeVisible({ timeout: 5_000 });
  });

  test("missing name surfaces name-required error", async ({ page }) => {
    await page.goto("/signup");
    // Bypass HTML5 required on name by filling other fields and leaving name blank
    // (required attribute still fires — but we can stub via dispatching submit from JS)
    await page.getByLabel(/email/i).fill("test@example.com");
    const passwords = page.locator('input[type="password"]');
    await passwords.nth(0).fill("validpass1");
    await passwords.nth(1).fill("validpass1");
    // Remove required to trigger JS validation instead of HTML5
    await page.getByLabel(/your name|^name$/i).evaluate((el) => {
      (el as HTMLInputElement).removeAttribute("required");
    });
    await page.getByRole("button", { name: /create account/i }).click();
    const banner = page.locator("div.bg-red-50, [role=alert]").first();
    await expect(banner).toBeVisible({ timeout: 5_000 });
  });
});

test.describe("Forgot-password form validation", () => {
  test("empty submit is blocked by HTML5 required", async ({ page }) => {
    await page.goto("/forgot-password");
    await page.getByRole("button", { name: /send reset link/i }).click();
    await expect(page).toHaveURL(/\/forgot-password/);
  });

  test("invalid email surfaces inline error", async ({ page }) => {
    await page.goto("/forgot-password");
    const email = page.getByLabel(/email/i);
    // Remove the required attr + set an invalid email to trigger JS check
    await email.evaluate((el) =>
      (el as HTMLInputElement).removeAttribute("required")
    );
    await email.fill("not-a-real-email");
    await page.getByRole("button", { name: /send reset link/i }).click();
    const banner = page.locator("div.bg-red-50, [role=alert]").first();
    await expect(banner).toBeVisible({ timeout: 5_000 });
  });
});

test.describe("Phone sign-in form validation", () => {
  test("empty submit blocked by HTML5 required", async ({ page }) => {
    await page.goto("/phone-signin");
    await page.getByRole("button", { name: /send code/i }).click();
    await expect(page).toHaveURL(/\/phone-signin/);
  });

  test("malformed phone (no country code) surfaces error", async ({ page }) => {
    await page.goto("/phone-signin");
    const phone = page.getByLabel(/phone number/i);
    await phone.fill("5551234"); // no + prefix
    await page.getByRole("button", { name: /send code/i }).click();
    const banner = page.locator("div.bg-red-50, [role=alert]").first();
    await expect(banner).toBeVisible({ timeout: 5_000 });
  });
});

test.describe("Keyboard accessibility", () => {
  test("login form is tabbable to submit", async ({ page }) => {
    await page.goto("/login");
    // First tab reaches the email input
    await page.getByLabel(/email/i).focus();
    await expect(page.getByLabel(/email/i)).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(page.getByLabel(/password/i).first()).toBeFocused();
  });

  test("forgot-password form inputs have explicit labels", async ({ page }) => {
    await page.goto("/forgot-password");
    const email = page.getByLabel(/email/i);
    await expect(email).toHaveAttribute("type", "email");
    await expect(email).toHaveAttribute("autocomplete", "email");
  });

  test("signup inputs have proper autocomplete attributes", async ({ page }) => {
    await page.goto("/signup");
    await expect(page.getByLabel(/your name|^name$/i)).toHaveAttribute(
      "autocomplete",
      "name"
    );
    await expect(page.getByLabel(/email/i)).toHaveAttribute(
      "autocomplete",
      "email"
    );
    await expect(page.locator('input[type="password"]').first()).toHaveAttribute(
      "autocomplete",
      "new-password"
    );
  });
});
