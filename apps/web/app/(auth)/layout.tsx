import type { ReactNode } from "react";

/**
 * Shared layout for all auth screens (login, signup, forgot-password,
 * phone-signin, choose-role, onboarding, verify-email).
 *
 * Why this exists: the auth cards previously each used
 * `min-h-screen flex items-center justify-center` with no scroll, so on short
 * viewports the card was vertically clipped with no way to reach the bottom.
 *
 * This wrapper makes the auth column at least full-height and scrollable when
 * the content is taller than the viewport (`overflow-y-auto`). It deliberately
 * does NOT impose horizontal padding or width constraints — the card pages
 * center themselves (`flex justify-center` + `max-w-*`) and the full-bleed
 * choose-role screen spans edge to edge. Vertical centering and breathing room
 * for the card pages are provided by the shared `auth-card-shell` class in
 * globals.css (top-aligned + scrollable on short screens, centered from `sm:`).
 */
export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen overflow-y-auto">{children}</div>
  );
}
