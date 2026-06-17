import type { MetadataRoute } from "next";

export const dynamic = "force-static";

const SITE_URL = "https://scheduler-web-next.web.app";

// Only crawlable marketing/auth surfaces. Authenticated pages are excluded
// via robots.ts — they're gated by Firebase Auth anyway.
const PUBLIC_ROUTES = [
  { path: "/", priority: 1, changeFrequency: "monthly" as const },
  { path: "/login", priority: 0.8, changeFrequency: "yearly" as const },
  { path: "/signup", priority: 0.9, changeFrequency: "yearly" as const },
  {
    path: "/forgot-password",
    priority: 0.4,
    changeFrequency: "yearly" as const,
  },
  {
    path: "/phone-signin",
    priority: 0.4,
    changeFrequency: "yearly" as const,
  },
];

export default function sitemap(): MetadataRoute.Sitemap {
  const now = new Date().toISOString();
  return PUBLIC_ROUTES.map(({ path, priority, changeFrequency }) => ({
    url: `${SITE_URL}${path}`,
    lastModified: now,
    changeFrequency,
    priority,
  }));
}
