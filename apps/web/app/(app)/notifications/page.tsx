"use client";

// Notifications center route (M23) — `/notifications`.
//
// Faithful standalone surface for Flutter's notifications panel
// (`lib/production_components/notifications/notifications_widget.dart`). The
// Flutter app opens this as a dialog from the home-bell; on web it is both a
// dialog (via `NotificationsBell`) and this addressable route, so a deep link
// / refresh lands on the same content.
//
// Gated to the INTERNAL audience tier via `scheduler.web-notifications-center`.
// Two layers keep it dark for paying customers:
//   1. The page redirects a non-internal user to /dashboard (a route is
//      publicly addressable, so we guard the navigation, not just the render).
//   2. `NotificationsPanel` itself returns null for non-internal users.
// A customer can therefore never see notifications-center content, even by
// typing the URL directly.

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import {
  useFeatureFlag,
  WEB_NOTIFICATIONS_CENTER_FLAG,
} from "@/lib/feature-flags/use-feature-flag";
import NotificationsPanel from "@/components/notifications/notifications-panel";

export default function NotificationsPage() {
  const enabled = useFeatureFlag(WEB_NOTIFICATIONS_CENTER_FLAG);
  const router = useRouter();

  useEffect(() => {
    if (!enabled) router.replace("/dashboard");
  }, [enabled, router]);

  if (!enabled) return null;

  return (
    <div className="mx-auto max-w-md">
      <NotificationsPanel />
    </div>
  );
}
