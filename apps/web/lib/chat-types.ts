import type { Timestamp } from "firebase/firestore";

/**
 * Types for the chat data layer.
 *
 * Flutter references (for cross-platform parity on field *names*):
 * - lib/backend/schema/chats_record.dart (`chats` top-level collection)
 * - lib/backend/schema/chat_messages_record.dart (messages schema)
 * - lib/chat_group_threads/chat_2_main/chat2_main_widget.dart — the Flutter
 *   thread list query uses `.where('users', arrayContains: currentUserRef)`
 *   and `.orderBy('last_message_time', descending: true)`.
 *
 * Firestore keys follow the Flutter snake_case convention exactly so docs
 * written from web are indistinguishable from docs written from Flutter.
 */

// -----------------------------------------------------------------------
// ChatThread — `chats/{threadId}` (top-level collection)
// -----------------------------------------------------------------------

/**
 * Embedded preview of the most recent message on a thread, denormalised onto
 * the parent thread doc so the thread-list view can render a one-line
 * preview without hitting the messages subcollection. Written by
 * `sendChatMessage` alongside the actual message write.
 */
export interface ChatThreadLastMessage {
  /** Text of the last message. Empty string if the last message was media-only. */
  text: string;
  /** Server timestamp when the message was written. */
  timestamp: Timestamp;
  /** `uid` of the sender — matches `ChatMessage.sender_uid`. */
  sender: string;
}

/**
 * A chat thread (1:1 DM or group). Stored at `chats/{threadId}`.
 *
 * `users` is an array of participant uids — queried via `arrayContains`
 * for the per-user thread list. Keeping it as `string[]` (rather than
 * `DocumentReference[]`) lets the thread-list render without an extra
 * join for display names — the UI resolves the user profile on demand.
 *
 * `is_group` is derived at create time from `users.length > 2` (per the
 * existing Flutter chat UI's convention). We store it explicitly so the
 * thread-list can filter groups vs DMs without counting participants.
 */
export interface ChatThread {
  /** Doc id, populated on read. */
  id: string;
  /** Display name for group chats; optional for 1:1s (UI falls back to
   * the other participant's display name). */
  name?: string;
  /** True iff this is a group chat (users.length > 2). */
  is_group: boolean;
  /** Participant uids. Includes the owner (and every invited user for groups). */
  users: string[];
  /** Denormalised preview of the most recent message. Absent until the
   * first message is sent. */
  last_message?: ChatThreadLastMessage;
  /** Server timestamp at create time. */
  created_at: Timestamp;
  /** `uid` of the user who created the thread. Optional because legacy
   * Flutter-written threads may predate this field. */
  owner?: string;
}

// -----------------------------------------------------------------------
// ChatMessage — `chats/{threadId}/messages/{messageId}` (subcollection)
// -----------------------------------------------------------------------

/**
 * A single chat message. Stored at `chats/{threadId}/messages/{messageId}`.
 *
 * Field names are snake_case to match the Flutter schema convention (see
 * `chat_messages_record.dart` fields: `user`, `text`, `timestamp`,
 * `image`). The web app uses the more specific `sender_uid` / `image_url`
 * / `seen_by` names so the shape is self-documenting — the Flutter mobile
 * app and web app both write into this subcollection; the only mobile
 * fan-in we care about is the notification function on create.
 */
export interface ChatMessage {
  /** Doc id, populated on read. */
  id: string;
  /** Message body. Empty string for image-only messages. */
  text: string;
  /** `uid` of the user who sent the message. */
  sender_uid: string;
  /** Server timestamp when the message was written. */
  timestamp: Timestamp;
  /** Optional image URL (Firebase Storage or otherwise). */
  image_url?: string;
  /** `uid`s of members who have marked this message as seen. */
  seen_by?: string[];
}
