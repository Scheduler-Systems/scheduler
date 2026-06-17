"use client";

// Notifications bell (M23) — the AppBar trailing action that opens the
// notifications center. Faithful port of Flutter's home-bell
// (`lib/features/home/view/home_widget.dart` lines 444-588): a bell icon with
// an orange (#EE8B60) count badge summing the unread schedule_requests +
// unread notifications; tapping opens the notifications dialog
// (`NotificationsWidget`).
//
// Gated to the INTERNAL audience tier via `scheduler.web-notifications-center`
// — renders nothing for paying customers (synchronous false), so the bell
// never appears for them during the parity pilot.

import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth-context";
import { useI18n } from "@/lib/i18n-context";
import {
  useFeatureFlag,
  WEB_NOTIFICATIONS_CENTER_FLAG,
} from "@/lib/feature-flags/use-feature-flag";
import {
  subscribeToNotifications,
  subscribeToScheduleRequests,
} from "@/lib/notifications";
import NotificationsPanel from "./notifications-panel";

export function NotificationsBell() {
  const enabled = useFeatureFlag(WEB_NOTIFICATIONS_CENTER_FLAG);
  const { user } = useAuth();
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [unreadRequests, setUnreadRequests] = useState(0);
  const [unreadOther, setUnreadOther] = useState(0);

  useEffect(() => {
    if (!enabled || !user) return;
    const unsubReq = subscribeToScheduleRequests(user.email, (rs) =>
      setUnreadRequests(rs.filter((r) => !r.is_read).length)
    );
    const unsubOther = subscribeToNotifications(user.uid, (ns) =>
      setUnreadOther(ns.filter((n) => !n.is_read).length)
    );
    return () => {
      unsubReq();
      unsubOther();
    };
  }, [enabled, user]);

  // Customer-dark: synchronous false → nothing renders (after hooks).
  if (!enabled || !user) return null;

  const total = unreadRequests + unreadOther;

  return (
    <>
      <button
        type="button"
        aria-label={t("notifications.title")}
        data-testid="notifications-bell"
        onClick={() => setOpen(true)}
        className="relative flex h-8 w-8 items-center justify-center rounded-full text-white transition-colors hover:bg-white/10"
      >
        <svg viewBox="0 0 24 24" className="h-6 w-6" fill="currentColor" aria-hidden="true">
          <path d="M12 22a2.5 2.5 0 0 0 2.45-2h-4.9A2.5 2.5 0 0 0 12 22Zm6-6V11a6 6 0 0 0-4.5-5.8V4.5a1.5 1.5 0 0 0-3 0v.7A6 6 0 0 0 6 11v5l-1.6 1.6a1 1 0 0 0 .7 1.7h13.8a1 1 0 0 0 .7-1.7L18 16Z" />
        </svg>
        {total > 0 && (
          <span
            data-testid="notifications-bell-badge"
            className="absolute -right-1 -top-1 inline-flex min-w-[1.1rem] items-center justify-center rounded-[10px] bg-[#EE8B60] px-1 text-[10px] font-semibold leading-4 text-white"
          >
            {total}
          </span>
        )}
      </button>

      {open && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
          role="dialog"
          aria-modal="true"
          data-testid="notifications-dialog"
          onClick={(e) => {
            if (e.target === e.currentTarget) setOpen(false);
          }}
        >
          <div className="h-[70vh] w-full max-w-md">
            <NotificationsPanel onClose={() => setOpen(false)} />
          </div>
        </div>
      )}
    </>
  );
}
