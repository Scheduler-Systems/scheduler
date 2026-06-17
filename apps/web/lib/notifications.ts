"use client";

import {
  collection,
  doc,
  onSnapshot,
  orderBy,
  query,
  updateDoc,
  where,
  type DocumentReference,
  type Unsubscribe,
} from "firebase/firestore";
import { getFirebaseDb } from "./firebase";
import type { NotificationRecord, ScheduleRequest } from "./notifications-types";

/**
 * Notifications-center data layer (M23) — READ + mark-as-read.
 *
 * Mirrors Flutter's `notifications_widget.dart`, which fans two top-level
 * collections into a 2-tab panel:
 *
 *   Tab "Schedule Requests":
 *     queryScheduleRequestsRecord(
 *       .where('to_user_identification', isEqualTo: currentUserEmail)
 *       .orderBy('created_time', descending: true))      // lines 46-57 / 414-431
 *
 *   Tab "Other" (chat-message notifications):
 *     queryNotificationsRecord(
 *       .where('to_user', isEqualTo: currentUserReference)
 *       .orderBy('time_created', descending: true))       // lines 63-68
 *
 * Read subscribers swallow missing-auth / missing-doc errors by delivering an
 * empty payload, so the panel renders an empty state rather than throwing —
 * the same fail-safe convention as `chat.ts` (`subscribeToChatThreads`).
 *
 * Writes in this round are limited to flipping `is_read` (the "Mark All as
 * Read" toggle and the per-row tap), faithful to the Flutter panel which
 * `.update(createScheduleRequestsRecordData(isRead: true))` /
 * `.update(createNotificationsRecordData(isRead: true))`. No new docs are
 * created from the web in this round.
 */

function db() {
  return getFirebaseDb();
}

/** `users/{uid}` DocumentReference — the `notifications.to_user` filter value. */
function userRef(uid: string): DocumentReference {
  return doc(db(), "users", uid);
}

/**
 * Subscribe to the schedule add/join requests addressed to a user (by email).
 *
 * Flutter filters on `to_user_identification == currentUserEmail` (or the phone
 * number when there is no email). The web auth user always has an email in this
 * app's sign-in flows, so we key on email; an empty email yields an empty list
 * (no query) rather than a broken `==''` filter.
 */
export function subscribeToScheduleRequests(
  email: string | null,
  cb: (requests: ScheduleRequest[]) => void
): Unsubscribe {
  const e = (email ?? "").trim();
  if (!e) {
    cb([]);
    return () => {};
  }
  const q = query(
    collection(db(), "schedule_requests"),
    where("to_user_identification", "==", e),
    orderBy("created_time", "desc")
  );
  return onSnapshot(
    q,
    (snap) => {
      const requests: ScheduleRequest[] = snap.docs.map((d) => ({
        id: d.id,
        ...(d.data() as Omit<ScheduleRequest, "id">),
      }));
      cb(requests);
    },
    () => {
      // Permission/auth/index errors → empty list (UI shows empty state).
      cb([]);
    }
  );
}

/**
 * Subscribe to the chat-message notifications addressed to a user.
 *
 * Flutter filters on `to_user == currentUserReference` and orders by
 * `time_created desc`.
 */
export function subscribeToNotifications(
  uid: string | null,
  cb: (notifications: NotificationRecord[]) => void
): Unsubscribe {
  if (!uid) {
    cb([]);
    return () => {};
  }
  const q = query(
    collection(db(), "notifications"),
    where("to_user", "==", userRef(uid)),
    orderBy("time_created", "desc")
  );
  return onSnapshot(
    q,
    (snap) => {
      const notifications: NotificationRecord[] = snap.docs.map((d) => ({
        id: d.id,
        ...(d.data() as Omit<NotificationRecord, "id">),
      }));
      cb(notifications);
    },
    () => {
      cb([]);
    }
  );
}

/**
 * Mark a single `schedule_requests` doc read. Mirrors Flutter's
 * `.update(createScheduleRequestsRecordData(isRead: true))`.
 */
export async function markScheduleRequestRead(id: string): Promise<void> {
  await updateDoc(doc(db(), "schedule_requests", id), { is_read: true });
}

/**
 * Mark a single `notifications` doc read. Mirrors Flutter's
 * `.update(createNotificationsRecordData(isRead: true))`.
 */
export async function markNotificationRead(id: string): Promise<void> {
  await updateDoc(doc(db(), "notifications", id), { is_read: true });
}

/**
 * "Mark All as Read" for the active tab. Flutter's switch walks the in-memory
 * list and updates each unread doc's `is_read` flag (one tab at a time — see
 * `notifications_widget.dart` lines 142-184). We mirror that: flip only the
 * docs that are currently unread, in the collection for the given tab.
 *
 * Returns the number of docs updated (0 when nothing was unread). Failures on
 * an individual doc are swallowed so one permission error can't strand the
 * rest — matching the Flutter loop, which has no per-doc error handling.
 */
export async function markAllRead(
  ids: string[],
  collectionName: "schedule_requests" | "notifications"
): Promise<number> {
  let updated = 0;
  for (const id of ids) {
    try {
      await updateDoc(doc(db(), collectionName, id), { is_read: true });
      updated += 1;
    } catch {
      // Swallow — keep going for the remaining docs (Flutter has no guard).
    }
  }
  return updated;
}
