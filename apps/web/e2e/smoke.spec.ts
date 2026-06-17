import { test, expect } from "@playwright/test";

// Smoke tests that run against the live deploy. Each test should:
//   - probe a public surface (no authenticated state required)
//   - assert on meaningful content, not just 200
//   - be fast and deterministic (no Firebase writes)

test.describe("Public surfaces render", () => {
  test("root redirects anonymous users to /login", async ({ page }) => {
    await page.goto("/");
    // Root renders a spinner then client-redirects based on Firebase auth.
    // Anonymous → /login. Matches the legacy Flutter web behavior.
    await expect(page).toHaveURL(/\/login/, { timeout: 10_000 });
  });

  test("login page has email + password fields + submit", async ({ page }) => {
    await page.goto("/login");
    // Login form inputs — match by label or placeholder
    await expect(page.getByLabel(/email/i)).toBeVisible();
    await expect(page.getByLabel(/password/i).first()).toBeVisible();
    await expect(
      page.getByRole("button", { name: /sign in/i })
    ).toBeVisible();
  });

  test("signup page has name, email, password + Create account CTA", async ({
    page,
  }) => {
    await page.goto("/signup");
    await expect(
      page.getByRole("heading", { name: /create your account|sign up/i })
    ).toBeVisible();
    await expect(page.getByLabel(/your name|name/i)).toBeVisible();
    await expect(page.getByLabel(/email/i)).toBeVisible();
    await expect(
      page.getByRole("button", { name: /create account/i })
    ).toBeVisible();
  });

  test("forgot-password page renders the reset form", async ({ page }) => {
    await page.goto("/forgot-password");
    await expect(page.getByLabel(/email/i)).toBeVisible();
  });

  test("phone-signin page renders the phone entry UI", async ({ page }) => {
    await page.goto("/phone-signin");
    // Heading copy from /phone-signin — tolerant of slight copy drift
    await expect(
      page.locator("h1, h2").filter({ hasText: /phone/i }).first()
    ).toBeVisible();
  });
});

test.describe("Auth gating", () => {
  test("/dashboard redirects unauthenticated users to /login", async ({
    page,
  }) => {
    await page.goto("/dashboard");
    // Could end up on /login or /dashboard (the layout renders a spinner
    // before the effect fires); wait for either the login heading or the
    // URL change.
    await page.waitForURL(/\/login|\/dashboard/, { timeout: 10_000 });
    // If we're still on dashboard after 5 s, check the URL flipped to /login
    await expect(page).toHaveURL(/\/login/, { timeout: 10_000 });
  });

  test("/schedules also gates unauthenticated users", async ({ page }) => {
    await page.goto("/schedules");
    await expect(page).toHaveURL(/\/login/, { timeout: 10_000 });
  });
});

test.describe("SEO + PWA artifacts", () => {
  test("robots.txt disallows authenticated routes and points at the sitemap", async ({
    request,
  }) => {
    const res = await request.get("/robots.txt");
    expect(res.status()).toBe(200);
    const body = await res.text();
    expect(body).toContain("Disallow: /dashboard");
    expect(body).toContain("Disallow: /schedules");
    expect(body).toContain("Sitemap:");
  });

  test("sitemap.xml lists the public routes", async ({ request }) => {
    const res = await request.get("/sitemap.xml");
    expect(res.status()).toBe(200);
    const body = await res.text();
    expect(body).toContain("<loc>https://scheduler-web-next.web.app/</loc>");
    expect(body).toContain("/login");
    expect(body).toContain("/signup");
  });

  test("manifest.webmanifest returns valid JSON with the PWA fields", async ({
    request,
  }) => {
    const res = await request.get("/manifest.webmanifest");
    expect(res.status()).toBe(200);
    const json = await res.json();
    expect(json.name).toBe("Scheduler");
    expect(json.display).toBe("standalone");
    expect(json.start_url).toBe("/");
    expect(Array.isArray(json.icons)).toBe(true);
  });
});
