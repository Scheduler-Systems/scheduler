"use client";

import {
  collection,
  doc,
  getDoc,
  onSnapshot,
  orderBy,
  query,
  where,
  type Unsubscribe,
} from "firebase/firestore";
import { getFirebaseDb } from "./firebase";
import type { ChatMessage, ChatThread } from "./chat-types";

/**
 * A user as surfaced in the new-chat participant picker. Mirrors the subset
 * of the Flutter `UsersRecord` the invite-users screen reads
 * (`chat_2_invite_users_widget.dart` streams `queryUsersRecord(orderBy:
 * 'display_name')` and renders `display_name`). We keep only the fields the
 * picker needs so the list stays cheap and SSR-safe.
 */
export interface ChatPickerUser {
  /** `uid` field on the user doc — the value stored in a thread's `users[]`. */
  uid: string;
  /** Display name; empty string when the profile hasn't set one. */
  display_name: string;
  /** Optional email, used as a secondary label when display_name is blank. */
  email?: string;
}

/**
 * Chat data-layer read operations. Writes live in `firestore-write.ts`
 * alongside the rest of the Firestore mutation helpers (co-located so
 * batched thread+message writes can share the batch helper).
 *
 * All subscribers swallow missing-auth/missing-doc errors by delivering
 * an empty payload — callers render an empty state rather than throwing,
 * matching the pattern in `requests.ts`.
 */

function db() {
  return getFirebaseDb();
}

/**
 * Subscribe to the list of chat threads the given user participates in.
 * Mirrors Flutter's `chat2_main_widget.dart` query (lines 143-146, 773-774):
 *
 *   .where('users', arrayContains: currentUserReference)
 *   .orderBy('last_message_time', descending: true)
 *
 * The web app stores `users` as a `string[]` of uids (not DocumentReferences
 * like Flutter) — see `chat-types.ts`. To stay queryable from the Flutter
 * UI as well, creates must write the DocumentReferences in the existing
 * Flutter path; the web ordering column here uses `last_message.timestamp`
 * because our denormalised preview is a struct (Flutter's scalar column is
 * `last_message_time`).
 *
 * Returns the `Unsubscribe` handle from `onSnapshot` — callers must call
 * it in their cleanup effect.
 */
export function subscribeToChatThreads(
  uid: string,
  cb: (threads: ChatThread[]) => void
): Unsubscribe {
  const q = query(
    collection(db(), "chats"),
    where("users", "array-contains", uid),
    orderBy("last_message.timestamp", "desc")
  );
  return onSnapshot(
    q,
    (snap) => {
      const threads: ChatThread[] = snap.docs.map((d) => ({
        id: d.id,
        ...(d.data() as Omit<ChatThread, "id">),
      }));
      cb(threads);
    },
    () => {
      // Swallow permission/auth errors by reporting an empty list — the UI
      // renders an empty state. The original error lands in the Firestore
      // SDK's internal logger, which is the pattern we use elsewhere.
      cb([]);
    }
  );
}

/**
 * Subscribe to the messages in a thread, ordered oldest-first so the UI
 * can append to the bottom of a scroll view without needing to reverse.
 * The message subcollection lives at `chats/{threadId}/messages`.
 */
export function subscribeToChatMessages(
  threadId: string,
  cb: (messages: ChatMessage[]) => void
): Unsubscribe {
  const q = query(
    collection(db(), "chats", threadId, "messages"),
    orderBy("timestamp", "asc")
  );
  return onSnapshot(
    q,
    (snap) => {
      const messages: ChatMessage[] = snap.docs.map((d) => ({
        id: d.id,
        ...(d.data() as Omit<ChatMessage, "id">),
      }));
      cb(messages);
    },
    () => {
      cb([]);
    }
  );
}

/**
 * Single-shot read of a thread doc. Returns `null` when the thread
 * doesn't exist (or the caller lacks permission) rather than throwing —
 * matches the `getSchedule` / `getUserProfile` convention in
 * `firestore.ts` so callers can pattern-match a missing thread the same
 * way they handle a missing schedule.
 */
export async function getChatThread(
  threadId: string
): Promise<ChatThread | null> {
  const snap = await getDoc(doc(db(), "chats", threadId));
  if (!snap.exists()) return null;
  return { id: snap.id, ...(snap.data() as Omit<ChatThread, "id">) };
}

/**
 * Fetch the directory of users that can be invited to a new chat.
 *
 * SECURITY (#51 item 8 — cross-org user enumeration). This REPLACES the former
 * `subscribeToUsers`, which streamed `collection('users') orderBy('display_name')`
 * straight from the client — i.e. the ENTIRE user directory (every name + email,
 * across every org) to any signed-in browser. The picker now reads a
 * server-scoped endpoint (`GET /api/chat/contacts`) that returns only the users
 * the caller shares a schedule with, computed from the caller's verified uid.
 * The matching Firestore rule denies client `list` on `users`, so the directory
 * cannot be enumerated via the SDK either.
 *
 * One-shot (contacts don't change mid-picker) rather than a live subscription;
 * the caller manages its own loading state. Like the other readers in this
 * module, any failure resolves to an empty list so the UI renders an empty
 * state rather than throwing. The current user is already excluded server-side.
 */
export async function fetchChatContacts(): Promise<ChatPickerUser[]> {
  try {
    const res = await fetch("/api/chat/contacts", {
      method: "GET",
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    });
    if (!res.ok) return [];
    const body = (await res.json()) as { items?: ChatPickerUser[] };
    return Array.isArray(body.items) ? body.items : [];
  } catch {
    return [];
  }
}

/**
 * Find an existing thread whose participant set is exactly `selectedUids`
 * (order-independent). Pure helper — the React port of Flutter's
 * `findChatWithUsersList` custom action (`custom_code/actions/
 * find_chat_with_users_list.dart`), which sorts both id lists and compares
 * them with `listEquals`. Returns the first matching thread, or `null`.
 *
 * Dedupe is by SET, so duplicate uids in either input are collapsed before
 * comparison — this guards the create path from spawning a second 1:1 thread
 * for the same pair, exactly like the Flutter flow (it only creates a new
 * `chats` doc when this returns null).
 */
export function findExistingThread(
  threads: ChatThread[],
  selectedUids: string[]
): ChatThread | null {
  const wanted = Array.from(new Set(selectedUids)).sort();
  const key = wanted.join(",");
  for (const thread of threads) {
    const have = Array.from(new Set(thread.users)).sort();
    if (have.join(",") === key) return thread;
  }
  return null;
}
