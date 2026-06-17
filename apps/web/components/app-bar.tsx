"use client";

/**
 * AppBar — the shared purple app-shell header primitive.
 *
 * Faithful port of the Flutter FlutterFlow AppBar that defines every screen's
 * identity across the Scheduler app. Spec (Foundation tier F4, from the
 * web-parity audit + lib/flutter_flow/flutter_flow_theme.dart):
 *
 *   - background:   primary  #6A0DAD  (var --color-primary)
 *   - title:        white, Montserrat w600 22px  (== FlutterFlow headlineMedium,
 *                   flutter_flow_theme.dart:196-201 — note that scale is w600 22px)
 *   - back button:  white back-arrow, 30px glyph inside a 60px circular tap
 *                   target (FlutterFlow FlutterFlowIconButton borderRadius 30,
 *                   buttonSize 60, iconSize 30)
 *   - elevation:    2.0  (≈ Tailwind shadow-md)
 *   - actions:      optional right-side slot (e.g. notification bell) with an
 *                   optional unread badge in tertiary #EE8B60 (var --color-tertiary)
 *
 * This is the reusable primitive ONLY. Retrofitting every screen
 * (dashboard / schedules / employees / chat / settings / sub-routes) onto it is
 * a separate, per-screen task — the dashboard reference usage ships alongside.
 */

import { useRouter } from "next/navigation";
import type { ReactNode } from "react";

export interface AppBarProps {
  /** The screen title — rendered white, Montserrat w600 22px (headlineMedium). */
  title: string;
  /**
   * Show the white back-arrow button. When `onBack` is omitted it falls back to
   * `router.back()`. Defaults to false (top-level screens have no back arrow,
   * matching Flutter where automaticallyImplyLeading is false on home/main).
   */
  showBack?: boolean;
  /** Custom back handler; defaults to browser/router history back. */
  onBack?: () => void;
  /** Optional right-side action slot (e.g. a notification bell, overflow menu). */
  actions?: ReactNode;
  /**
   * Unread/notification count. When > 0 a small tertiary (#EE8B60) badge is
   * shown on the trailing edge — mirrors the Flutter notification badge.
   */
  badgeCount?: number;
  /** Center the title (Flutter `centerTitle: true`). Defaults to false (start-aligned). */
  centerTitle?: boolean;
  /** Extra classes for the outer header (rarely needed). */
  className?: string;
}

/** White back-arrow glyph (Flutter Icons.arrow_back_ios_new), 30px. */
function BackArrowIcon() {
  return (
    <svg
      width="30"
      height="30"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.25"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <polyline points="15 18 9 12 15 6" />
    </svg>
  );
}

export function AppBar({
  title,
  showBack = false,
  onBack,
  actions,
  badgeCount = 0,
  centerTitle = false,
  className = "",
}: AppBarProps) {
  const router = useRouter();

  const handleBack = () => {
    if (onBack) onBack();
    else router.back();
  };

  return (
    <header
      // bg-[--color-primary] == Flutter primary #6A0DAD; shadow-md ≈ elevation 2.0
      className={`flex h-14 w-full items-center gap-1 bg-[var(--color-primary)] px-2 text-white shadow-md ${className}`}
      role="banner"
    >
      {showBack ? (
        <button
          type="button"
          onClick={handleBack}
          aria-label="Back"
          // 60px circular tap target (h-15 w-15 == 3.75rem), 30px glyph centered.
          className="flex h-[60px] w-[60px] shrink-0 items-center justify-center rounded-full text-white transition-colors hover:bg-white/10 active:bg-white/20"
        >
          <BackArrowIcon />
        </button>
      ) : (
        // Keep title alignment stable when there is no back button.
        <span aria-hidden="true" className="w-2 shrink-0" />
      )}

      <h1
        className={`min-w-0 flex-1 truncate text-[22px] font-semibold leading-tight text-white ${
          centerTitle ? "text-center" : "text-left"
        }`}
      >
        {title}
      </h1>

      {(actions || badgeCount > 0) && (
        <div className="relative flex shrink-0 items-center gap-1 pr-1">
          {actions}
          {badgeCount > 0 && (
            <span
              // Notification badge — tertiary #EE8B60 per Flutter spec.
              className="absolute -right-0.5 -top-0.5 flex min-w-[18px] items-center justify-center rounded-full bg-[var(--color-tertiary)] px-1 text-[11px] font-semibold leading-none text-white"
              aria-label={`${badgeCount} unread`}
            >
              {badgeCount > 99 ? "99+" : badgeCount}
            </span>
          )}
        </div>
      )}
    </header>
  );
}

export default AppBar;
