"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/lib/auth-context";
import { isEmailVerified } from "@/lib/verify-email";
import { useI18n } from "@/lib/i18n-context";

function UserAvatar({ name, email }: { name?: string | null; email?: string | null }) {
  const initial = (name ?? email ?? "?")[0].toUpperCase();
  return (
    <div className="w-14 h-14 rounded-full bg-purple-600 flex items-center justify-center text-white text-xl font-semibold flex-shrink-0">
      {initial}
    </div>
  );
}

interface MenuItemProps {
  href?: string;
  onClick?: () => void;
  icon: React.ReactNode;
  label: string;
  sublabel?: string;
  danger?: boolean;
}

function MenuItem({ href, onClick, icon, label, sublabel, danger }: MenuItemProps) {
  const cls = `flex items-center gap-3 px-4 py-3 text-sm transition-colors hover:bg-gray-50 ${
    danger ? "text-red-600" : "text-gray-700"
  }`;
  const inner = (
    <>
      <span className={`flex-shrink-0 ${danger ? "text-red-500" : "text-gray-400"}`}>
        {icon}
      </span>
      <span className="flex-1">
        <span className="block font-medium">{label}</span>
        {sublabel && (
          <span className="block text-xs text-gray-400 mt-0.5">{sublabel}</span>
        )}
      </span>
      {!danger && (
        <svg className="w-4 h-4 text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
        </svg>
      )}
    </>
  );

  if (href) {
    return (
      <Link href={href} className={cls}>
        {inner}
      </Link>
    );
  }
  return (
    <button type="button" onClick={onClick} className={`w-full text-left ${cls}`}>
      {inner}
    </button>
  );
}

export default function SettingsPage() {
  const { user, signOut } = useAuth();
  const { t } = useI18n();
  const router = useRouter();
  const [signingOut, setSigningOut] = useState(false);

  async function handleSignOut() {
    setSigningOut(true);
    try {
      await signOut();
      router.replace("/login");
    } catch {
      // Swallow — the auth layer already surfaces the error; we just
      // need to release the button's disabled state.
    } finally {
      setSigningOut(false);
    }
  }

  const emailVerified = isEmailVerified(user);

  return (
    <div className="space-y-6 max-w-lg">
      <div>
        <h1 className="text-2xl font-semibold text-gray-900">{t("settings.heading")}</h1>
      </div>

      {/* Profile card */}
      <div className="rounded-xl border border-gray-200 bg-white p-4 flex items-center gap-4">
        <UserAvatar name={user?.displayName} email={user?.email} />
        <div className="min-w-0 flex-1">
          <p className="font-semibold text-gray-900 truncate">
            {user?.displayName || t("settings.unnamedUser")}
          </p>
          <p className="text-sm text-gray-500 truncate">{user?.email}</p>
          {!emailVerified && (
            <Link
              href={`/verify-email?email=${encodeURIComponent(user?.email ?? "")}`}
              className="inline-block mt-1 text-xs text-amber-600 hover:underline"
            >
              {t("settings.emailNotVerified")}
            </Link>
          )}
        </div>
        <Link
          href="/profile"
          className="flex-shrink-0 text-xs text-purple-600 hover:underline font-medium"
        >
          {t("settings.edit")}
        </Link>
      </div>

      {/* Account section */}
      <div className="rounded-xl border border-gray-200 bg-white overflow-hidden">
        <p className="px-4 py-2 text-xs font-semibold uppercase tracking-wider text-gray-400 bg-gray-50">
          {t("settings.sectionAccount")}
        </p>
        <div className="divide-y divide-gray-100">
          <MenuItem
            href="/settings/billing"
            icon={
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3 10h18M7 15h1m4 0h1m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H6a3 3 0 00-3 3v8a3 3 0 003 3z" />
              </svg>
            }
            label={t("settings.menuBilling")}
            sublabel={t("settings.menuBillingSub")}
          />
          <MenuItem
            href="/employees"
            icon={
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" />
              </svg>
            }
            label={t("settings.menuEmployees")}
            sublabel={t("settings.menuEmployeesSub")}
          />
          <MenuItem
            href="/schedules"
            icon={
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
              </svg>
            }
            label={t("settings.menuSchedules")}
            sublabel={t("settings.menuSchedulesSub")}
          />
          <MenuItem
            href="/profile"
            icon={
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
              </svg>
            }
            label={t("settings.menuProfile")}
            sublabel={t("settings.menuProfileSub")}
          />
        </div>
      </div>

      {/* Session section */}
      <div className="rounded-xl border border-gray-200 bg-white overflow-hidden">
        <p className="px-4 py-2 text-xs font-semibold uppercase tracking-wider text-gray-400 bg-gray-50">
          {t("settings.sectionSession")}
        </p>
        <MenuItem
          onClick={handleSignOut}
          danger
          icon={
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
            </svg>
          }
          label={signingOut ? t("settings.signingOut") : t("common.signOut")}
        />
      </div>
    </div>
  );
}
