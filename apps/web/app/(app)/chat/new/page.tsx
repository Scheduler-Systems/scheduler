"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/lib/auth-context";
import { useI18n } from "@/lib/i18n-context";
import {
  fetchChatContacts,
  subscribeToChatThreads,
  findExistingThread,
  type ChatPickerUser,
} from "@/lib/chat";
import { createChatThread } from "@/lib/firestore-write";
import type { ChatThread } from "@/lib/chat-types";

/**
 * New-chat participant picker — `/chat/new`.
 *
 * Fixes the dead `/chat/new` link the chat list ("+ New chat" button) points
 * at. Faithful web port of the Flutter create-thread flow
 * (`chat_2_invite_users_widget.dart`):
 *
 *   1. Load the caller's chat contacts from `GET /api/chat/contacts` — a
 *      server-scoped set of only the users the caller shares a schedule with
 *      (NOT the global directory; see #51 item 8). The current user's row is
 *      excluded server-side.
 *   2. Select one or more other users (multi-select → a group chat when >1,
 *      mirroring Flutter's `is_group = users.length > 2` convention on the
 *      web `ChatThread`).
 *   3. On "Start chat": look for an existing thread with exactly this
 *      participant set (Flutter's `findChatWithUsersList`); if found, open it.
 *      Otherwise create a new `chats` doc (Flutter's `newChat` branch via
 *      `createChatThread`) and open it.
 *
 * The participant set written to `users[]` is `[currentUid, ...selected]` —
 * the full set, so the thread appears in every member's list (the thread-list
 * query is `where('users', 'array-contains', uid)`). This matches the web
 * `createChatThread` contract (`owner = users[0]`).
 *
 * Static route (no dynamic segment), so it's a single `"use client"` page —
 * same shape as `schedules/new/page.tsx`.
 */
export default function NewChatPage() {
  const router = useRouter();
  const { user } = useAuth();
  const { t } = useI18n();

  const [users, setUsers] = useState<ChatPickerUser[]>([]);
  const [usersLoading, setUsersLoading] = useState(true);
  // Live snapshot of the current user's threads — used to dedupe so we never
  // spawn a second thread for an existing participant set.
  const [threads, setThreads] = useState<ChatThread[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [filter, setFilter] = useState("");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    // One-shot scoped contact load (replaces the former global users stream).
    // `usersLoading` already initialises to true, so the spinner shows until
    // this resolves without a synchronous setState in the effect body.
    fetchChatContacts().then((next) => {
      if (cancelled) return;
      setUsers(next);
      setUsersLoading(false);
    });
    const unsubThreads = subscribeToChatThreads(user.uid, setThreads);
    return () => {
      cancelled = true;
      unsubThreads();
    };
  }, [user]);

  const visibleUsers = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return users;
    return users.filter((u) => {
      const name = u.display_name.toLowerCase();
      const email = (u.email ?? "").toLowerCase();
      return name.includes(q) || email.includes(q);
    });
  }, [users, filter]);

  if (!user) return null;

  function toggle(uid: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(uid)) next.delete(uid);
      else next.add(uid);
      return next;
    });
  }

  async function handleStart() {
    if (!user) return;
    // Flutter guard: must select at least one OTHER user
    // ("You must select at least one other user to start a chat.").
    if (selected.size === 0) {
      setError(t("chatNew.errorSelectUser"));
      return;
    }
    setCreating(true);
    setError(null);
    try {
      // Full participant set: current user + every selected user.
      const participants = Array.from(new Set([user.uid, ...selected]));

      // Dedupe against existing threads (Flutter `findChatWithUsersList`).
      const existing = findExistingThread(threads, participants);
      if (existing) {
        router.push(`/chat/${existing.id}`);
        return;
      }

      // Group chats carry a name (display label for >1:1). Single DMs leave
      // `name` unset so the thread view falls back to the other participant.
      const isGroup = participants.length > 2;
      const id = isGroup
        ? await createChatThread(participants, defaultGroupName(selected, users))
        : await createChatThread(participants);
      router.push(`/chat/${id}`);
    } catch {
      setError(t("chatNew.errorCreate"));
      setCreating(false);
    }
  }

  const selectedCount = selected.size;

  return (
    <div className="space-y-6 max-w-2xl">
      <div className="flex items-center gap-3">
        <Link
          href="/chat"
          aria-label={t("chat.backToList")}
          className="text-sm text-purple-600 hover:underline font-medium"
        >
          {t("chat.backToList")}
        </Link>
        <h1 className="text-2xl font-semibold">{t("chatNew.title")}</h1>
      </div>

      <p className="text-sm text-gray-500">{t("chatNew.subtitle")}</p>

      <input
        type="text"
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        placeholder={t("chatNew.searchPlaceholder")}
        data-testid="chat-new-search"
        className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
      />

      {usersLoading ? (
        <div className="flex items-center justify-center py-16">
          <div className="w-6 h-6 border-2 border-purple-600 border-t-transparent rounded-full animate-spin" />
        </div>
      ) : visibleUsers.length === 0 ? (
        <div className="rounded-lg border border-gray-200 bg-gray-50 p-8 text-center">
          <p className="text-gray-500">{t("chatNew.emptyUsers")}</p>
        </div>
      ) : (
        <ul className="divide-y divide-gray-100 rounded-lg border border-gray-200 bg-white overflow-hidden">
          {visibleUsers.map((u) => {
            const isSelected = selected.has(u.uid);
            const label =
              u.display_name.trim().length > 0
                ? u.display_name
                : u.email ?? u.uid;
            return (
              <li key={u.uid}>
                <button
                  type="button"
                  onClick={() => toggle(u.uid)}
                  data-testid={`chat-new-user-${u.uid}`}
                  aria-pressed={isSelected}
                  className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-gray-50 transition-colors"
                >
                  <div
                    aria-hidden="true"
                    className="flex-shrink-0 w-10 h-10 rounded-full bg-purple-600 flex items-center justify-center text-white font-semibold"
                  >
                    {avatarInitial(label)}
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-medium text-gray-800">
                      {label}
                    </p>
                    {u.email && u.display_name.trim().length > 0 && (
                      <p className="truncate text-xs text-gray-400">
                        {u.email}
                      </p>
                    )}
                  </div>
                  <span
                    aria-hidden="true"
                    className={`flex-shrink-0 w-5 h-5 rounded-md border flex items-center justify-center ${
                      isSelected
                        ? "bg-purple-600 border-purple-600 text-white"
                        : "border-gray-300 bg-white"
                    }`}
                  >
                    {isSelected ? "✓" : ""}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}

      {error && (
        <div
          role="alert"
          className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700"
        >
          {error}
        </div>
      )}

      <div className="flex items-center gap-3 pt-2">
        <button
          type="button"
          onClick={handleStart}
          disabled={creating || selectedCount === 0}
          data-testid="chat-new-start"
          className="rounded-lg bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {creating
            ? t("chatNew.starting")
            : selectedCount > 1
              ? t("chatNew.startGroup", { count: selectedCount })
              : t("chatNew.startChat")}
        </button>
        <Link
          href="/chat"
          className="rounded-lg border border-gray-200 px-4 py-2 text-sm text-gray-600 hover:bg-gray-50"
        >
          {t("chatNew.cancel")}
        </Link>
      </div>
    </div>
  );
}

function avatarInitial(label: string): string {
  const c = label?.trim?.()?.[0];
  return (c ?? "?").toUpperCase();
}

/**
 * Build a default label for a group thread from the selected participants —
 * a comma-joined list of display names (truncated). Flutter shows the group
 * by its `name`/participants; we seed a sensible default so the thread header
 * isn't blank for groups. 1:1 DMs pass no name (handled by the caller).
 */
function defaultGroupName(
  selectedUids: Set<string>,
  users: ChatPickerUser[]
): string {
  const names = users
    .filter((u) => selectedUids.has(u.uid))
    .map((u) =>
      u.display_name.trim().length > 0 ? u.display_name : (u.email ?? u.uid)
    );
  const joined = names.join(", ");
  return joined.length > 60 ? `${joined.slice(0, 59)}…` : joined;
}
