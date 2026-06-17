import type { MetadataRoute } from "next";

// Required for `output: export` static builds (Firebase Hosting target).
export const dynamic = "force-static";

const SITE_URL = "https://scheduler-web-next.web.app";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: "/",
        // Don't index authenticated pages or schedule details that require
        // sign-in anyway; they're static SPA shells with no useful content
        // for crawlers.
        disallow: [
          "/dashboard",
          "/employees",
          "/profile",
          "/settings",
          "/schedules",
          "/onboarding",
          "/verify-email",
        ],
      },
    ],
    sitemap: `${SITE_URL}/sitemap.xml`,
    host: SITE_URL,
  };
}
