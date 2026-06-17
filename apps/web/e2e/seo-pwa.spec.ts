import { test, expect } from "@playwright/test";

// Robots + sitemap + manifest assertions. These are static artifacts served
// directly by Firebase Hosting from the Next static export.

test.describe("robots.txt", () => {
  test("returns 200 and plain text", async ({ request }) => {
    const res = await request.get("/robots.txt");
    expect(res.status()).toBe(200);
    const ct = res.headers()["content-type"] ?? "";
    expect(ct).toMatch(/text\/plain/);
  });

  test("allows all by default", async ({ request }) => {
    const body = await (await request.get("/robots.txt")).text();
    expect(body).toContain("User-Agent: *");
    expect(body).toContain("Allow: /");
  });

  test("disallows all auth-gated route roots", async ({ request }) => {
    const body = await (await request.get("/robots.txt")).text();
    for (const path of [
      "/dashboard",
      "/employees",
      "/profile",
      "/settings",
      "/schedules",
      "/onboarding",
      "/verify-email",
    ]) {
      expect(body).toContain(`Disallow: ${path}`);
    }
  });

  test("references the sitemap and host", async ({ request }) => {
    const body = await (await request.get("/robots.txt")).text();
    expect(body).toMatch(/Sitemap:\s*https:\/\/scheduler-web-next\.web\.app\/sitemap\.xml/);
    expect(body).toMatch(/Host:\s*https:\/\/scheduler-web-next\.web\.app/);
  });
});

test.describe("sitemap.xml", () => {
  test("returns 200 with XML content-type", async ({ request }) => {
    const res = await request.get("/sitemap.xml");
    expect(res.status()).toBe(200);
    const ct = res.headers()["content-type"] ?? "";
    expect(ct).toMatch(/xml/);
  });

  test("is a valid <urlset> document", async ({ request }) => {
    const body = await (await request.get("/sitemap.xml")).text();
    expect(body).toContain('<?xml version="1.0"');
    expect(body).toContain(
      '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    );
    expect(body).toContain("</urlset>");
  });

  test("lists every public route", async ({ request }) => {
    const body = await (await request.get("/sitemap.xml")).text();
    for (const path of [
      "/",
      "/login",
      "/signup",
      "/forgot-password",
      "/phone-signin",
    ]) {
      expect(body).toContain(
        `<loc>https://scheduler-web-next.web.app${path === "/" ? "/" : path}</loc>`
      );
    }
  });

  test("does NOT list any auth-gated route", async ({ request }) => {
    const body = await (await request.get("/sitemap.xml")).text();
    for (const path of [
      "/dashboard",
      "/employees",
      "/profile",
      "/settings",
      "/onboarding",
      "/verify-email",
    ]) {
      expect(body).not.toContain(
        `<loc>https://scheduler-web-next.web.app${path}</loc>`
      );
    }
  });

  test("entries carry priority + changefreq metadata", async ({ request }) => {
    const body = await (await request.get("/sitemap.xml")).text();
    expect(body).toContain("<priority>");
    expect(body).toContain("<changefreq>");
    expect(body).toContain("<lastmod>");
  });
});

test.describe("manifest.webmanifest", () => {
  test("returns 200 with manifest content-type", async ({ request }) => {
    const res = await request.get("/manifest.webmanifest");
    expect(res.status()).toBe(200);
    const ct = res.headers()["content-type"] ?? "";
    expect(ct).toMatch(/manifest\+json|application\/json/);
  });

  test("is valid JSON and has required PWA keys", async ({ request }) => {
    const json = await (await request.get("/manifest.webmanifest")).json();
    expect(json.name).toBe("Scheduler");
    expect(json.short_name).toBe("Scheduler");
    expect(json.start_url).toBe("/");
    expect(json.display).toBe("standalone");
    expect(json.orientation).toBe("portrait");
  });

  test("theme + background colors match FlutterFlow purple + white", async ({
    request,
  }) => {
    const json = await (await request.get("/manifest.webmanifest")).json();
    expect(json.theme_color).toBe("#a855f7");
    expect(json.background_color).toBe("#ffffff");
  });

  test("includes at least one icon entry with src + sizes + type", async ({
    request,
  }) => {
    const json = await (await request.get("/manifest.webmanifest")).json();
    expect(Array.isArray(json.icons)).toBe(true);
    expect(json.icons.length).toBeGreaterThan(0);
    const icon = json.icons[0];
    expect(icon.src).toBeTruthy();
    expect(icon.sizes).toBeTruthy();
    expect(icon.type).toBeTruthy();
  });
});

test.describe("Head metadata (served shell HTML)", () => {
  test("login page has expected viewport + theme-color meta", async ({
    page,
  }) => {
    await page.goto("/login");
    const themeColor = await page
      .locator('meta[name="theme-color"]')
      .first()
      .getAttribute("content");
    expect(themeColor).toBe("#a855f7");
    const viewport = await page
      .locator('meta[name="viewport"]')
      .first()
      .getAttribute("content");
    expect(viewport).toMatch(/width=device-width/);
  });

  test("favicon is reachable", async ({ request }) => {
    const res = await request.get("/favicon.ico");
    expect(res.status()).toBe(200);
  });
});
