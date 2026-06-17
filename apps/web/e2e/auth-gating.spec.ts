import { test, expect } from "@playwright/test";

// Every app route should redirect anonymous visitors to /login. The static
// export uses a client-side effect in AppLayout, so we allow up to 10s for
// the useEffect to fire on slow network.

const GATED_ROUTES: { path: string; label: string }[] = [
  { path: "/dashboard", label: "dashboard" },
  { path: "/profile", label: "profile" },
  { path: "/settings", label: "settings" },
  { path: "/employees", label: "employees" },
  { path: "/schedules", label: "schedules index" },
  { path: "/schedules/new", label: "new schedule" },
  { path: "/schedules/testid", label: "schedule detail (testid)" },
  { path: "/schedules/testid/settings", label: "schedule settings" },
  { path: "/schedules/testid/archived", label: "schedule archived" },
  { path: "/schedules/testid/priorities", label: "schedule priorities" },
  { path: "/schedules/testid/import", label: "schedule import" },
];

test.describe("Auth gating — anonymous visitor is redirected to /login", () => {
  for (const { path, label } of GATED_ROUTES) {
    test(`${label} (${path}) redirects to /login within 10s`, async ({
      page,
    }) => {
      await page.goto(path);
      await page.waitForURL(/\/login/, { timeout: 10_000 });
      await expect(page).toHaveURL(/\/login/);
    });
  }
});

test.describe("Auth gating — post-redirect landing is usable", () => {
  test("after redirect from /dashboard, login form renders", async ({
    page,
  }) => {
    await page.goto("/dashboard");
    await page.waitForURL(/\/login/, { timeout: 10_000 });
    await expect(page.getByLabel(/email/i)).toBeVisible();
    await expect(page.getByLabel(/password/i).first()).toBeVisible();
  });

  test("after redirect from /employees, Sign in CTA is present", async ({
    page,
  }) => {
    await page.goto("/employees");
    await page.waitForURL(/\/login/, { timeout: 10_000 });
    await expect(
      page.getByRole("button", { name: /^sign in$/i })
    ).toBeVisible();
  });

  test("after redirect from /schedules/anything/settings, login renders", async ({
    page,
  }) => {
    await page.goto("/schedules/anything/settings");
    await page.waitForURL(/\/login/, { timeout: 10_000 });
    await expect(
      page.getByRole("heading", { name: /scheduler/i })
    ).toBeVisible();
  });
});

test.describe("Auth gating — public routes stay public", () => {
  const PUBLIC_ROUTES = [
    "/login",
    "/signup",
    "/forgot-password",
    "/phone-signin",
    "/verify-email",
  ];

  for (const path of PUBLIC_ROUTES) {
    test(`${path} does NOT redirect away from itself`, async ({ page }) => {
      await page.goto(path);
      // Wait briefly to ensure no redirect kicks in
      await page.waitForLoadState("networkidle");
      // Allow the URL to keep trailing slash tolerantly
      expect(page.url()).toContain(path);
    });
  }
});
