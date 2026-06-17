"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import {
  useFeatureFlag,
  WEB_EMPLOYEE_INVITE_FLAG,
} from "@/lib/feature-flags/use-feature-flag";
import { useI18n } from "@/lib/i18n-context";
import { LocaleSwitcher } from "./locale-switcher";
import { NotificationsBell } from "./notifications/notifications-bell";

const NAV_LINKS: { href: string; key: string }[] = [
  { href: "/dashboard", key: "nav.dashboard" },
  { href: "/schedules", key: "nav.schedules" },
  { href: "/employees", key: "nav.employees" },
];

export function Nav() {
  const pathname = usePathname();
  const { user } = useAuth();
  const { t } = useI18n();
  // /invites was an orphaned page (QA 2026-06-11): reachable only by typed
  // URL. Same internal flag as the page itself — customers never see it.
  const invitesEnabled = useFeatureFlag(WEB_EMPLOYEE_INVITE_FLAG);
  const links = invitesEnabled
    ? [...NAV_LINKS, { href: "/invites", key: "nav.invites" }]
    : NAV_LINKS;

  const initial = (user?.displayName ?? user?.email ?? "?")[0].toUpperCase();

  return (
    // Flutter AppBar parity: solid brand purple (#6A0DAD) with white content and
    // a subtle elevation, replacing the plain white starter bar. Structure is
    // unchanged (same links, locale switcher, settings avatar) to preserve
    // functionality and e2e selectors — only the colors are re-themed.
    <header className="bg-purple-600 text-white shadow-sm">
      <div className="container mx-auto px-4 max-w-6xl flex items-center justify-between h-14">
        <div className="flex items-center gap-6">
          <Link href="/dashboard" className="font-semibold text-white">
            Scheduler
          </Link>
          <nav className="hidden sm:flex items-center gap-1">
            {links.map(({ href, key }) => (
              <Link
                key={href}
                href={href}
                className={`px-3 py-1.5 rounded-md text-sm transition-colors ${
                  pathname.startsWith(href)
                    ? "bg-white/15 text-white font-medium"
                    : "text-purple-100 hover:text-white hover:bg-white/10"
                }`}
              >
                {t(key)}
              </Link>
            ))}
          </nav>
        </div>

        <div className="flex items-center gap-2">
          {/* Notifications bell — self-gated to internal tier (M23); renders
              nothing for paying customers. Flutter parity: the home AppBar's
              trailing bell + unread badge. */}
          <NotificationsBell />
          <LocaleSwitcher compact />
          <span className="text-xs text-purple-200 hidden md:block truncate max-w-[160px]">
            {user?.email}
          </span>
          <Link
            href="/settings"
            aria-label={t("nav.settings")}
            title={user?.displayName ?? user?.email ?? t("nav.settings")}
            className={`flex items-center justify-center w-8 h-8 rounded-full text-sm font-semibold transition-colors ${
              pathname.startsWith("/settings")
                ? "bg-white text-purple-700"
                : "bg-white/20 text-white hover:bg-white/30"
            }`}
          >
            {initial}
          </Link>
        </div>
      </div>
    </header>
  );
}
