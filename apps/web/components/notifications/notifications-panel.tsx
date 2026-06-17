"use client";

// Notifications center (M23) — faithful web port of Flutter's
// `lib/production_components/notifications/notifications_widget.dart`.
//
// Structure mirrored from the Flutter widget:
//  - header row: "Mark All as Read" switch + label (widget lines 122-237),
//    "Notifications" title + subtitle (lines 240-306), close button (307-326)
//  - 2 tabs: "Schedule Requests" / "Other" (TabBar lines 335-381)
//  - tab 1 list: schedule_requests rows (lines 463-1168)
//  - tab 2 list: notifications rows ("X sent you a message", lines 1213-1596)
//  - each row: unread → accent3 bg + purple shadow; read → plain bg + a
//    24px check circle (lines 531-558 / 1108-1157, 1231-1255 / 1543-1587)
//  - empty state: NotAvailableTemplate "No notifications at this time"
//    (lines 454-461 / 1203-1211)
//
// This is the entry component for the feature and is gated to the INTERNAL
// audience tier — it returns null SYNCHRONOUSLY for paying customers (see
// `useFeatureFlag`), so the module never flashes for them.

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { useI18n } from "@/lib/i18n-context";
import {
  useFeatureFlag,
  WEB_NOTIFICATIONS_CENTER_FLAG,
} from "@/lib/feature-flags/use-feature-flag";
import {
  markAllRead,
  markNotificationRead,
  markScheduleRequestRead,
  subscribeToNotifications,
  subscribeToScheduleRequests,
} from "@/lib/notifications";
import { getUserProfile } from "@/lib/firestore";
import type {
  NotificationRecord,
  ScheduleRequest,
} from "@/lib/notifications-types";

type Tab = "requests" | "other";

// Firestore timestamps arrive as `Timestamp | null | FieldValue`. Normalise to
// `Date | null` without importing the Timestamp type — keeps this unit-testable
// against plain mock objects (same helper shape as chat/page.tsx).
function timestampToDate(ts: unknown): Date | null {
  if (!ts) return null;
  if (ts instanceof Date) return ts;
  if (typeof ts === "object" && ts !== null) {
    const maybe = ts as { toDate?: () => Date; seconds?: number };
    if (typeof maybe.toDate === "function") {
      try {
        return maybe.toDate();
      } catch {
        return null;
      }
    }
    if (typeof maybe.seconds === "number") return new Date(maybe.seconds * 1000);
  }
  return null;
}

// Relative-time bucket → i18n string. Matches chat/page.tsx's helper so the
// two surfaces read identically. Flutter uses `dateTimeFormat("relative", …)`.
function relativeTimeLabel(
  t: (key: string, params?: Record<string, string | number>) => string,
  when: Date | null,
  now: Date
): string {
  if (!when) return "";
  const diffSec = Math.max(0, Math.floor((now.getTime() - when.getTime()) / 1000));
  if (diffSec < 60) return t("chat.relativeNow");
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return t("chat.relativeMinutes", { count: diffMin });
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return t("chat.relativeHours", { count: diffHr });
  const diffDay = Math.floor(diffHr / 24);
  if (diffDay < 7) return t("chat.relativeDays", { count: diffDay });
  return when.toISOString().slice(0, 10);
}

function refId(ref: unknown): string | undefined {
  return (ref as { id?: string } | null)?.id;
}

// A 24×24 read-state pip: filled-purple-bordered circle showing a check when
// the row has been read; light border when unread. Mirrors the Flutter
// `Container(width:24,height:24, shape:circle, …, child: Visibility(isRead → check))`.
function ReadPip({ read }: { read: boolean }) {
  return (
    <span
      aria-hidden="true"
      className={`flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full border-2 ${
        read ? "border-purple-600 bg-purple-50" : "border-gray-200 bg-purple-50"
      }`}
    >
      {read && (
        <svg viewBox="0 0 24 24" className="h-4 w-4 text-purple-600" fill="none">
          <path
            d="M5 13l4 4L19 7"
            stroke="currentColor"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      )}
    </span>
  );
}

// Resolve `from_user` → display name, cached per-uid. Flutter resolves the
// actor via a UsersRecord stream; we one-shot `getUserProfile` and fall back
// to the localized "Deleted user" string.
function useDisplayNames(uids: string[]): Record<string, string> {
  const [names, setNames] = useState<Record<string, string>>({});
  const key = uids.slice().sort().join(",");
  useEffect(() => {
    let active = true;
    const missing = uids.filter((u) => u && names[u] === undefined);
    if (missing.length === 0) return;
    Promise.all(
      missing.map(async (u) => {
        try {
          const p = await getUserProfile(u);
          return [u, p?.display_name ?? ""] as const;
        } catch {
          return [u, ""] as const;
        }
      })
    ).then((pairs) => {
      if (!active) return;
      setNames((prev) => {
        const next = { ...prev };
        for (const [u, n] of pairs) next[u] = n;
        return next;
      });
    });
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return names;
}

interface NotificationsPanelProps {
  /** Optional close handler — rendered as a header ✕ when supplied (dialog mode). */
  onClose?: () => void;
}

/**
 * The notifications panel. Internal-only/OFF-for-customers via the
 * `scheduler.web-notifications-center` flag. Used both as a standalone
 * `/notifications` route and as a dialog body (pass `onClose`).
 */
export default function NotificationsPanel({ onClose }: NotificationsPanelProps) {
  const enabled = useFeatureFlag(WEB_NOTIFICATIONS_CENTER_FLAG);
  const { user } = useAuth();
  const { t } = useI18n();
  const router = useRouter();

  const [tab, setTab] = useState<Tab>("requests");
  const [requests, setRequests] = useState<ScheduleRequest[]>([]);
  const [notifications, setNotifications] = useState<NotificationRecord[]>([]);
  const [loadingReq, setLoadingReq] = useState(true);
  const [loadingOther, setLoadingOther] = useState(true);
  const [markingAll, setMarkingAll] = useState(false);

  const now = useMemo(
    () => new Date(),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [requests, notifications]
  );

  useEffect(() => {
    if (!enabled || !user) return;
    const unsubReq = subscribeToScheduleRequests(user.email, (next) => {
      setRequests(next);
      setLoadingReq(false);
    });
    const unsubOther = subscribeToNotifications(user.uid, (next) => {
      setNotifications(next);
      setLoadingOther(false);
    });
    return () => {
      unsubReq();
      unsubOther();
    };
  }, [enabled, user]);

  const actorUids = useMemo(() => {
    const out: string[] = [];
    for (const r of requests) {
      const id = refId(r.from_user);
      if (id) out.push(id);
    }
    for (const n of notifications) {
      const id = refId(n.from_user);
      if (id) out.push(id);
    }
    return Array.from(new Set(out));
  }, [requests, notifications]);
  const names = useDisplayNames(actorUids);

  // Customer-dark: synchronous false → nothing renders. Must come AFTER hooks
  // so hook order stays stable across the enabled/disabled transition.
  if (!enabled) return null;
  if (!user) return null;

  const unreadRequests = requests.filter((r) => !r.is_read);
  const unreadOther = notifications.filter((n) => !n.is_read);
  const anyUnread =
    tab === "requests" ? unreadRequests.length > 0 : unreadOther.length > 0;

  async function handleMarkAll() {
    if (markingAll) return;
    setMarkingAll(true);
    try {
      if (tab === "requests") {
        await markAllRead(unreadRequests.map((r) => r.id), "schedule_requests");
      } else {
        await markAllRead(unreadOther.map((n) => n.id), "notifications");
      }
    } finally {
      setMarkingAll(false);
    }
  }

  function actorName(uid: string | undefined): string {
    const n = uid ? names[uid] : "";
    return n && n.trim().length > 0 ? n : t("notifications.deletedUser");
  }

  function requestTitle(r: ScheduleRequest): string {
    if (r.is_add_request) return t("notifications.scheduleAddRequest");
    if (r.is_join_request) return t("notifications.scheduleJoinRequest");
    return " ";
  }

  return (
    <div
      data-testid="notifications-panel"
      className="flex h-full max-h-[80vh] w-full flex-col overflow-hidden rounded-xl bg-white shadow-[0_2px_4px_rgba(0,0,0,0.2)]"
    >
      {/* Header — switch + title/subtitle + close. */}
      <div className="flex items-start justify-between gap-3 px-4 pt-4">
        <div className="flex flex-col items-center">
          <button
            type="button"
            role="switch"
            aria-checked={false}
            aria-label={t("notifications.markAllAsRead")}
            disabled={markingAll || !anyUnread}
            onClick={handleMarkAll}
            data-testid="notifications-mark-all"
            className={`relative inline-flex h-6 w-11 flex-shrink-0 items-center rounded-full transition-colors disabled:opacity-40 ${
              anyUnread ? "bg-gray-300" : "bg-gray-200"
            }`}
          >
            <span className="inline-block h-5 w-5 translate-x-0.5 rounded-full bg-white shadow transition-transform" />
          </button>
          <span className="mt-1 text-[10px] text-gray-600">
            {t("notifications.markAllAsRead")}
          </span>
        </div>

        <div className="min-w-0 flex-1">
          <h2
            className={`text-xl font-semibold ${
              anyUnread ? "text-gray-900" : "text-purple-600"
            }`}
          >
            {t("notifications.title")}
          </h2>
          <p className="mt-1 line-clamp-2 text-sm text-gray-500">
            {t("notifications.subtitle")}
          </p>
        </div>

        {onClose && (
          <button
            type="button"
            aria-label={t("common.close")}
            onClick={onClose}
            data-testid="notifications-close"
            className="flex h-11 w-11 flex-shrink-0 items-center justify-center rounded-xl border border-purple-600 text-gray-700 transition-colors hover:bg-purple-50"
          >
            <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none">
              <path
                d="M6 6l12 12M18 6L6 18"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
              />
            </svg>
          </button>
        )}
      </div>

      {/* Tabs. */}
      <div className="mt-3 flex items-center justify-center gap-8 border-b border-gray-100 px-4">
        {(
          [
            ["requests", "notifications.tabScheduleRequests"],
            ["other", "notifications.tabOther"],
          ] as const
        ).map(([key, label]) => {
          const active = tab === key;
          return (
            <button
              key={key}
              type="button"
              onClick={() => setTab(key)}
              data-testid={`notifications-tab-${key}`}
              className={`-mb-px border-b-4 px-2 pb-1 text-base transition-colors ${
                active
                  ? "border-purple-600 text-gray-900"
                  : "border-transparent text-gray-500 hover:text-gray-700"
              }`}
            >
              {t(label)}
            </button>
          );
        })}
      </div>

      {/* Lists. */}
      <div className="min-h-0 flex-1 overflow-y-auto">
        {tab === "requests" ? (
          <RequestsList
            loading={loadingReq}
            requests={requests}
            now={now}
            t={t}
            actorName={actorName}
            title={requestTitle}
            onTap={async (r) => {
              if (!r.is_read) await markScheduleRequestRead(r.id);
              // An ADD invitation TARGETING me → I'm the invitee: the accept
              // screen is /invites. (QA 2026-06-11: routing invitees to the
              // schedule's shift-change inbox dead-ended — a non-member can't
              // see it and bounced to /dashboard.)
              const targetsMe =
                r.request_status === "ADD_RQUEST_PENDING" &&
                ((user && r.to_user?.path === `users/${user.uid}`) ||
                  (!r.to_user &&
                    !!user?.email &&
                    r.to_user_identification === user.email));
              if (targetsMe) {
                router.push("/invites");
                onClose?.();
                return;
              }
              // Otherwise (join requests to my schedule / invites I sent as
              // manager) → the schedule's requests inbox, as before.
              const sid = refId(r.schedule_ref);
              if (
                (r.request_status === "ADD_RQUEST_PENDING" ||
                  r.request_status === "JOIN_REQUEST_PENDING") &&
                sid
              ) {
                router.push(`/schedules/${sid}/requests`);
                onClose?.();
              }
            }}
          />
        ) : (
          <OtherList
            loading={loadingOther}
            notifications={notifications}
            now={now}
            t={t}
            actorName={actorName}
            onTap={async (n) => {
              if (!n.is_read) await markNotificationRead(n.id);
              const cid = refId(n.chat_ref_id);
              if (cid) {
                router.push(`/chat/${cid}`);
                onClose?.();
              }
            }}
          />
        )}
      </div>
    </div>
  );
}

function Spinner() {
  return (
    <div className="flex items-center justify-center py-16">
      <div className="h-10 w-10 animate-spin rounded-full border-4 border-purple-600 border-t-transparent" />
    </div>
  );
}

function EmptyState({ text }: { text: string }) {
  return (
    <div className="px-4 py-16 text-center">
      <p className="text-sm text-gray-500">{text}</p>
    </div>
  );
}

// A single notification tile — shared shell for both tabs. Read rows are plain;
// unread rows get the accent3 (light purple) background + the AE88C3 shadow.
function Tile({
  read,
  onTap,
  testid,
  children,
}: {
  read: boolean;
  onTap: () => void;
  testid: string;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onTap}
      data-testid={testid}
      data-read={read}
      className={`flex w-full items-center justify-between gap-3 px-3 py-2 text-start transition-colors ${
        read
          ? "bg-white hover:bg-gray-50"
          : "bg-purple-50 shadow-[0_2px_4px_rgba(174,136,195,0.6)] hover:bg-purple-100"
      }`}
    >
      <div className="min-w-0 flex-1 ps-1 pe-3">{children}</div>
      <ReadPip read={read} />
    </button>
  );
}

function RequestsList({
  loading,
  requests,
  now,
  t,
  actorName,
  title,
  onTap,
}: {
  loading: boolean;
  requests: ScheduleRequest[];
  now: Date;
  t: (k: string, p?: Record<string, string | number>) => string;
  actorName: (uid: string | undefined) => string;
  title: (r: ScheduleRequest) => string;
  onTap: (r: ScheduleRequest) => void;
}) {
  if (loading) return <Spinner />;
  if (requests.length === 0)
    return <EmptyState text={t("notifications.empty")} />;
  return (
    <ul className="divide-y divide-gray-100">
      {requests.map((r) => {
        const when = timestampToDate(r.created_time);
        return (
          <li key={r.id}>
            <Tile
              read={r.is_read}
              onTap={() => onTap(r)}
              testid={`notification-request-${r.id}`}
            >
              <p className="truncate text-base font-bold text-gray-900">
                {title(r)}
              </p>
              <p className="mt-1 truncate text-sm text-gray-600">
                {t("notifications.requestJoinBody", {
                  name: actorName(refId(r.from_user)),
                })}
              </p>
              <p className="mt-1 truncate text-xs text-gray-700">
                {relativeTimeLabel(t, when, now)}
              </p>
            </Tile>
          </li>
        );
      })}
    </ul>
  );
}

function OtherList({
  loading,
  notifications,
  now,
  t,
  actorName,
  onTap,
}: {
  loading: boolean;
  notifications: NotificationRecord[];
  now: Date;
  t: (k: string, p?: Record<string, string | number>) => string;
  actorName: (uid: string | undefined) => string;
  onTap: (n: NotificationRecord) => void;
}) {
  if (loading) return <Spinner />;
  if (notifications.length === 0)
    return <EmptyState text={t("notifications.empty")} />;
  return (
    <ul className="divide-y divide-gray-100">
      {notifications.map((n) => {
        const when = timestampToDate(n.time_created);
        return (
          <li key={n.id}>
            <Tile
              read={n.is_read}
              onTap={() => onTap(n)}
              testid={`notification-other-${n.id}`}
            >
              <p className="truncate text-sm">
                <span className="font-semibold text-gray-900">
                  {actorName(refId(n.from_user))}
                </span>
                <span className="text-gray-700">
                  {t("notifications.sentYouAMessage")}
                </span>
              </p>
              <p className="mt-1 truncate text-sm text-gray-600">{n.content}</p>
              <p className="mt-1 truncate text-xs text-gray-500">
                {relativeTimeLabel(t, when, now)}
              </p>
            </Tile>
          </li>
        );
      })}
    </ul>
  );
}
