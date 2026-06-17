import type { DocumentReference, Timestamp } from "firebase/firestore";

/**
 * Types for the notifications-center data layer (M23).
 *
 * The Flutter notifications panel (the bell → 2-tab dialog) reads TWO
 * distinct top-level collections, NOT one:
 *
 *  1. `schedule_requests` — schedule add/join invitations. Queried by
 *     `to_user_identification` (the target user's email). This is the
 *     "Schedule Requests" tab. Type already modelled in
 *     `requests-types.ts` as `ScheduleRequest` — re-exported here so the
 *     notifications layer has a single import surface.
 *
 *  2. `notifications` — chat-message alerts ("X sent you a message").
 *     Queried by `to_user` (a `users/{uid}` DocumentReference). This is
 *     the "Other" tab.
 *
 * Flutter sources:
 *  - lib/production_components/notifications/notifications_widget.dart
 *    (the two queries: lines 46-57 schedule_requests; 63-68 notifications)
 *  - lib/backend/schema/notifications_record.dart (the `notifications`
 *    record schema — fields mirrored below)
 *
 * Firestore keys stay snake_case (Flutter convention) so docs written from
 * web are indistinguishable from docs written from Flutter.
 */

// Re-export the schedule-request type so the notifications UI imports from one
// place. The `schedule_requests` collection is shared with the per-schedule
// requests inbox (P3-3) and is already faithfully modelled there.
export type {
  ScheduleRequest,
  ScheduleRequestStatus,
} from "./requests-types";

/**
 * Mirrors Flutter `NotificationsRecord`
 * (lib/backend/schema/notifications_record.dart).
 *
 * Stored at Firestore collection: `notifications/{notificationId}`
 * (top-level collection — see the Flutter record's
 * `collection` getter, line 66-67:
 * `FirebaseFirestore.instance.collection('notifications')`).
 *
 * These are written by the Flutter chat-message flow; the web app only
 * READS them in the notifications center (report-only parity — no web
 * writes to this collection in this round).
 */
export interface NotificationRecord {
  /** Firestore doc id (populated when fetched). */
  id: string;

  /**
   * `is_read` — has the target user seen this notification.
   * Flutter line 18-21. Defaults to false when absent.
   */
  is_read: boolean;

  /**
   * `from_user` — DocumentReference to `users/{uid}` of the sender.
   * Used to resolve the actor's display name in the row.
   * Flutter line 23-26.
   */
  from_user: DocumentReference | null;

  /**
   * `content` — the notification body (e.g. the message preview).
   * Flutter line 28-31.
   */
  content: string;

  /**
   * `time_created` — when the notification was written.
   * Flutter line 33-36 (`DateTime` → Firestore `Timestamp`).
   */
  time_created: Timestamp | null;

  /**
   * `type` — the notification kind (Flutter `NotificationType` enum,
   * stored as the enum `.name` string). Surfaced as a plain string here;
   * the only Flutter row variant currently rendered is the chat-message
   * notification, so the UI does not branch on this yet.
   * Flutter line 38-41.
   */
  type: string | null;

  /**
   * `to_user` — DocumentReference to `users/{uid}` of the recipient.
   * The query filter for this collection. Flutter line 43-46.
   */
  to_user: DocumentReference | null;

  /**
   * `chat_ref_id` — DocumentReference to the `chats/{chatId}` doc this
   * notification points at. Tapping the row navigates to that chat.
   * Flutter line 48-51.
   */
  chat_ref_id: DocumentReference | null;
}
