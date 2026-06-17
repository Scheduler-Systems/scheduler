"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useAuth } from "@/lib/auth-context";
import { useI18n } from "@/lib/i18n-context";
import { subscribeToChatThreads } from "@/lib/chat";
import type { ChatThread } from "@/lib/chat-types";

const PREVIEW_MAX = 60;

function truncate(text: string, max: number): string {
  if (text.length <= max) return text;
  return `${text.slice(0, max - 1)}…`;
}

// Relative-time helper. The i18n dictionary owns the locale-aware strings; we
// just pick the bucket (now / minutes / hours / days). Anything older than 7d
// falls back to an ISO yyyy-mm-dd so the list stays unambiguous without
// needing a full Intl.RelativeTimeFormat polyfill for every supported locale.
function relativeTimeLabel(
  t: (key: string, params?: Record<string, string | number>) => string,
  when: Date,
  now: Date
): string {
  const diffMs = now.getTime() - when.getTime();
  const diffSec = Math.max(0, Math.floor(diffMs / 1000));
  if (diffSec < 60) return t("chat.relativeNow");
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return t("chat.relativeMinutes", { count: diffMin });
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return t("chat.relativeHours", { count: diffHr });
  const diffDay = Math.floor(diffHr / 24);
  if (diffDay < 7) return t("chat.relativeDays", { count: diffDay });
  return when.toISOString().slice(0, 10);
}

function threadDisplayName(thread: ChatThread, uid: string): string {
  if (thread.name && thread.name.trim().length > 0) return thread.name;
  // 1:1 DMs fall back to the other participant's uid as a last resort —
  // the Flutter app dereferences this to displayName via a user lookup; in
  // this phase we surface the uid short form to stay SSR-safe. A follow-up
  // phase will resolve names via a userProfiles cache.
  const other = thread.users.find((u) => u !== uid) ?? thread.users[0] ?? "?";
  return other;
}

function avatarInitial(label: string): string {
  const c = label?.trim?.()?.[0];
  return (c ?? "?").toUpperCase();
}

// Timestamp fields come out of Firestore as `Timestamp | null | FieldValue`
// (serverTimestamp() is a sentinel until server-resolved). Normalise to a
// `Date | null` for the UI without importing the Firestore Timestamp type
// directly — keeps this file unit-testable against plain mock objects.
function timestampToDate(
  ts: unknown
): Date | null {
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
    if (typeof maybe.seconds === "number") {
      return new Date(maybe.seconds * 1000);
    }
  }
  return null;
}

// Has the current user NOT yet seen the latest message?
// We don't have per-message seen state denormalised on the thread doc, so
// the best proxy is: the last message sender is someone other than me, AND
// my uid isn't in the last message's seen_by (which the thread list doesn't
// have — that field lives on the message subdoc). Until we denormalise
// `last_message.seen_by`, we treat any message whose sender isn't me as
// potentially unread. The thread page clears this by marking the latest
// message seen as it renders.
function isUnread(thread: ChatThread, uid: string): boolean {
  const last = thread.last_message;
  if (!last) return false;
  return last.sender !== uid;
}

export default function ChatListPage() {
  const { user } = useAuth();
  const { t } = useI18n();
  const [threads, setThreads] = useState<ChatThread[]>([]);
  const [loading, setLoading] = useState(true);
  // `now` is recomputed every time a new snapshot arrives so relative labels
  // stay fresh without a ticker. Good-enough for a chat list — the list
  // re-renders on every new message anyway. Memo keeps the same Date across
  // child renders of a single update cycle.
  const now = useMemo(
    () => new Date(),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [threads]
  );

  useEffect(() => {
    if (!user) return;
    const unsubscribe = subscribeToChatThreads(user.uid, (next) => {
      setThreads(next);
      setLoading(false);
    });
    return () => unsubscribe();
  }, [user]);

  if (!user) return null;

  const unreadCount = threads.reduce(
    (n, thread) => (isUnread(thread, user.uid) ? n + 1 : n),
    0
  );

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h1 className="text-2xl font-semibold">{t("chat.listTitle")}</h1>
          {unreadCount > 0 && (
            <span
              aria-label={`${unreadCount} unread`}
              data-testid="chat-unread-total"
              className="inline-flex items-center justify-center rounded-full bg-purple-600 px-2 py-0.5 text-xs font-semibold text-white"
            >
              {unreadCount}
            </span>
          )}
        </div>
        <Link
          href="/chat/new"
          className="rounded-lg bg-purple-600 px-3 py-2 text-sm font-medium text-white hover:bg-purple-700 transition-colors"
        >
          {t("chat.newChat")}
        </Link>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-20">
          <div className="w-6 h-6 border-2 border-purple-600 border-t-transparent rounded-full animate-spin" />
        </div>
      ) : threads.length === 0 ? (
        <div className="rounded-lg border border-gray-200 bg-gray-50 p-8 text-center">
          <p className="text-gray-500">{t("chat.emptyMessage")}</p>
        </div>
      ) : (
        <ul className="divide-y divide-gray-100 rounded-lg border border-gray-200 bg-white overflow-hidden">
          {threads.map((thread) => {
            const display = threadDisplayName(thread, user.uid);
            const preview = thread.last_message?.text ?? "";
            const when = timestampToDate(thread.last_message?.timestamp);
            const unread = isUnread(thread, user.uid);
            return (
              <li key={thread.id}>
                <Link
                  href={`/chat/${thread.id}`}
                  className="flex items-center gap-3 px-4 py-3 hover:bg-gray-50 transition-colors"
                  data-testid={`chat-row-${thread.id}`}
                >
                  <div
                    aria-hidden="true"
                    className="flex-shrink-0 w-10 h-10 rounded-full bg-purple-600 flex items-center justify-center text-white font-semibold"
                  >
                    {avatarInitial(display)}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center justify-between gap-2">
                      <p
                        className={`truncate ${
                          unread
                            ? "font-semibold text-gray-900"
                            : "font-medium text-gray-800"
                        }`}
                      >
                        {display}
                      </p>
                      {when && (
                        <span className="flex-shrink-0 text-xs text-gray-400">
                          {relativeTimeLabel(t, when, now)}
                        </span>
                      )}
                    </div>
                    <p
                      className={`truncate text-sm ${
                        unread ? "text-gray-900" : "text-gray-500"
                      }`}
                    >
                      {preview ? truncate(preview, PREVIEW_MAX) : ""}
                    </p>
                  </div>
                  {unread && (
                    <span
                      aria-label="unread"
                      data-testid={`chat-unread-${thread.id}`}
                      className="flex-shrink-0 w-2 h-2 rounded-full bg-purple-600"
                    />
                  )}
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
