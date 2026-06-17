import { test, expect } from "@playwright/test";

// LocaleSwitcher lives in the app Nav (auth-gated). On public auth pages,
// locale is driven by localStorage["scheduler.locale"] + navigator.language
// via I18nProvider. We simulate the switch by priming localStorage before
// navigation and asserting that the translated heading + <html dir> flip.

async function primeLocale(page: import("@playwright/test").Page, locale: string) {
  // Visit the origin first so localStorage is same-origin writable, then set.
  await page.goto("/login");
  await page.evaluate((l) => {
    localStorage.setItem("scheduler.locale", l);
  }, locale);
}

test.describe("Locale persistence via localStorage", () => {
  test("default locale is en; <html lang> is en; <html dir> is ltr", async ({
    page,
  }) => {
    await page.goto("/login");
    // Allow I18nProvider's useEffect to settle
    await page.waitForLoadState("networkidle");
    await expect(page.locator("html")).toHaveAttribute("lang", "en");
    await expect(page.locator("html")).toHaveAttribute("dir", "ltr");
  });

  test("setting he flips <html dir> to rtl on reload", async ({ page }) => {
    await primeLocale(page, "he");
    await page.reload();
    await page.waitForLoadState("networkidle");
    await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
    await expect(page.locator("html")).toHaveAttribute("lang", "he");
  });

  test("setting es keeps <html dir> ltr but lang switches to es", async ({
    page,
  }) => {
    await primeLocale(page, "es");
    await page.reload();
    await page.waitForLoadState("networkidle");
    await expect(page.locator("html")).toHaveAttribute("lang", "es");
    await expect(page.locator("html")).toHaveAttribute("dir", "ltr");
  });

  test("login subheading is translated in he", async ({ page }) => {
    await primeLocale(page, "he");
    await page.reload();
    await page.waitForLoadState("networkidle");
    // Hebrew subheading copy from i18n-dict.ts
    await expect(page.getByText("התחברו לחשבון שלכם")).toBeVisible();
  });

  test("login subheading is translated in es", async ({ page }) => {
    await primeLocale(page, "es");
    await page.reload();
    await page.waitForLoadState("networkidle");
    await expect(page.getByText(/inicia sesión en tu cuenta/i)).toBeVisible();
  });

  test("signup heading localized in he", async ({ page }) => {
    await page.goto("/signup");
    await page.evaluate(() => {
      localStorage.setItem("scheduler.locale", "he");
    });
    await page.reload();
    await page.waitForLoadState("networkidle");
    await expect(
      page.getByRole("heading", { name: /צור את החשבון שלך/ })
    ).toBeVisible();
  });

  test("signup heading localized in es", async ({ page }) => {
    await page.goto("/signup");
    await page.evaluate(() => {
      localStorage.setItem("scheduler.locale", "es");
    });
    await page.reload();
    await page.waitForLoadState("networkidle");
    await expect(
      page.getByRole("heading", { name: /crea tu cuenta/i })
    ).toBeVisible();
  });

  test("forgot-password heading localized in he", async ({ page }) => {
    await page.goto("/forgot-password");
    await page.evaluate(() => {
      localStorage.setItem("scheduler.locale", "he");
    });
    await page.reload();
    await page.waitForLoadState("networkidle");
    await expect(
      page.getByRole("heading", { name: /איפוס סיסמה/ })
    ).toBeVisible();
  });

  test("forgot-password heading localized in es", async ({ page }) => {
    await page.goto("/forgot-password");
    await page.evaluate(() => {
      localStorage.setItem("scheduler.locale", "es");
    });
    await page.reload();
    await page.waitForLoadState("networkidle");
    await expect(
      page.getByRole("heading", { name: /restablecer contraseña/i })
    ).toBeVisible();
  });

  test("login CTA Spanish copy is applied", async ({ page }) => {
    await primeLocale(page, "es");
    await page.reload();
    await page.waitForLoadState("networkidle");
    await expect(
      page.getByRole("button", { name: /^iniciar sesión$/i })
    ).toBeVisible();
  });
});

test.describe("Locale resolution fallbacks", () => {
  test("unsupported locale falls back to en", async ({ page }) => {
    await page.goto("/login");
    await page.evaluate(() => {
      localStorage.setItem("scheduler.locale", "fr");
    });
    await page.reload();
    await page.waitForLoadState("networkidle");
    // "fr" isn't supported, resolver returns DEFAULT_LOCALE (en)
    await expect(page.locator("html")).toHaveAttribute("lang", "en");
  });

  test("empty locale value falls back to en", async ({ page }) => {
    await page.goto("/login");
    await page.evaluate(() => {
      localStorage.removeItem("scheduler.locale");
    });
    await page.reload();
    await page.waitForLoadState("networkidle");
    await expect(page.locator("html")).toHaveAttribute("lang", "en");
  });
});
