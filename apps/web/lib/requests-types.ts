import type { DocumentReference, Timestamp } from "firebase/firestore";

/**
 * Types mirroring the Flutter shift-change request data layer.
 *
 * Flutter sources:
 * - lib/backend/schema/schedule_requests_record.dart
 * - lib/backend/schema/shift_requests_record.dart
 * - lib/backend/schema/schedule_change_request_record.dart
 * - lib/backend/schema/enums/enums.dart
 *
 * Firestore keys are snake_case (Flutter convention). DocumentReference
 * fields are stored as live refs in Flutter; in the TS layer we surface
 * them as `DocumentReference` where it's helpful and as doc-path `string`
 * when the caller only needs an identifier. Timestamps round-trip via
 * Firebase's `Timestamp` class.
 */

// -----------------------------------------------------------------------
// Enums (exact string values from Flutter's enum .name serialisation)
// -----------------------------------------------------------------------

/**
 * Mirrors Flutter `ScheduleRequestStatus` enum
 * (lib/backend/schema/enums/enums.dart:28-35).
 *
 * NOTE: `ADD_RQUEST_PENDING` is misspelled in Flutter (missing 'E').
 * We preserve the typo for data compatibility — any renaming would
 * break existing Firestore docs written by Flutter.
 */
export type ScheduleRequestStatus =
  | "ADD_RQUEST_PENDING"
  | "JOIN_REQUEST_PENDING"
  | "ADD_REQUEST_ACCEPTED"
  | "JOIN_REQUEST_ACCEPTED"
  | "ADD_REQUEST_DECLINED"
  | "JOIN_REQUEST_DECLINED";

/**
 * Mirrors Flutter `ShiftRequestStatus` enum
 * (lib/backend/schema/enums/enums.dart:3-7).
 *
 * NOTE: `REJECETED` is misspelled in Flutter (metathesis of C/E).
 * We preserve the typo for data compatibility.
 */
export type ShiftRequestStatus = "PENDING" | "ACCEPTED" | "REJECETED";

// -----------------------------------------------------------------------
// ScheduleRequest — schedule-level requests (join, add-employee)
// -----------------------------------------------------------------------

/**
 * Mirrors Flutter `ScheduleRequestsRecord`
 * (lib/backend/schema/schedule_requests_record.dart).
 *
 * Stored at Firestore collection: `schedule_requests/{requestId}`.
 * Top-level collection (see line 86 of the Flutter file:
 * `FirebaseFirestore.instance.collection('schedule_requests')`).
 */
export interface ScheduleRequest {
  /** Firestore doc id (populated when fetched). */
  id: string;

  /**
   * `is_add_request` — true when a manager invites an employee.
   * Flutter line 19-22.
   */
  is_add_request: boolean;

  /**
   * `is_join_request` — true when an employee asks to join a schedule.
   * Flutter line 24-27.
   */
  is_join_request: boolean;

  /**
   * `schedule_name` — denormalised display name for the list UI.
   * Flutter line 29-32.
   */
  schedule_name: string;

  /**
   * `request_status` — lifecycle state. Stored as the enum `.name` string.
   * Flutter line 34-37.
   */
  request_status: ScheduleRequestStatus | null;

  /**
   * `from_user` — DocumentReference to `users/{uid}` of the author.
   * Flutter line 39-42.
   */
  from_user: DocumentReference | null;

  /**
   * `to_user` — DocumentReference to `users/{uid}` of the target user
   * (null when the target hasn't signed up yet — see
   * `to_user_identification`).
   * Flutter line 44-47.
   */
  to_user: DocumentReference | null;

  /**
   * `to_user_identification` — email of the target user when `to_user`
   * is null. Flutter line 49-52.
   */
  to_user_identification: string;

  /**
   * `created_time` — when the request was written. Flutter line 54-57.
   * Flutter stores as `DateTime`; Firestore serialises to `Timestamp`.
   */
  created_time: Timestamp | null;

  /**
   * `schedule_ref` — DocumentReference to `schedules/{sid}`.
   * Flutter line 59-62.
   */
  schedule_ref: DocumentReference | null;

  /**
   * `is_read` — has the target user seen the request yet.
   * Flutter line 64-67.
   */
  is_read: boolean;
}

// -----------------------------------------------------------------------
// ShiftRequest — individual shift-swap requests
// -----------------------------------------------------------------------

/**
 * Mirrors Flutter `ShiftRequestsRecord`
 * (lib/backend/schema/shift_requests_record.dart).
 *
 * Stored at Firestore subcollection: `<parent>/shift_requests/{requestId}`.
 * Flutter uses either:
 *  - `parent.collection('shift_requests')` for a specific parent
 *  - `collectionGroup('shift_requests')` for schedule-wide reads
 * (Flutter lines 60-63).
 *
 * The parent is typically a `built_schedules/{bid}` doc under a schedule
 * (derived from the presence of `built_schedule_ref` — the Flutter
 * `parentReference` getter resolves to `reference.parent.parent!` which
 * is the built_schedule doc).
 */
export interface ShiftRequest {
  /** Firestore doc id (populated when fetched). */
  id: string;

  /**
   * Full Firestore doc path
   * (e.g. `schedules/sid/built_schedules/bid/shift_requests/rid`).
   * Needed for targeted updates when reads come via `collectionGroup`.
   */
  path: string;

  /**
   * `reuqesting_employee` — DocumentReference to `users/{uid}`.
   *
   * NOTE: Flutter preserves the typo `reuqesting_employee` (should be
   * `requesting_employee`). We mirror the typo for data compatibility.
   * Flutter line 19-22, storage key line 48.
   */
  reuqesting_employee: DocumentReference | null;

  /**
   * `shift_to_change_from` — timestamp of the shift the employee
   * currently owns. Flutter line 24-27.
   */
  shift_to_change_from: Timestamp | null;

  /**
   * `shift_to_change_to` — timestamp of the desired shift.
   * Flutter line 29-32.
   */
  shift_to_change_to: Timestamp | null;

  /**
   * `built_schedule_ref` — DocumentReference to the built_schedules doc
   * this request targets. Flutter line 34-37.
   */
  built_schedule_ref: DocumentReference | null;

  /**
   * `shift_request_status` — lifecycle state. Stored as the enum
   * `.name` string. Flutter line 39-42.
   */
  shift_request_status: ShiftRequestStatus | null;

  // Fields the TS layer adds for the manager-inbox UI in P3-3 but not
  // present in Flutter's schema. These are OPTIONAL — the web helpers
  // populate them on write (via serverTimestamp + current uid) so a
  // manager can audit who reviewed what, but Flutter reads will simply
  // ignore them. See `updateShiftRequestStatus` in `requests.ts`.
  /**
   * `reviewer_uid` — uid of the manager who accepted/rejected the
   * request. Written by `updateShiftRequestStatus`.
   */
  reviewer_uid?: string;

  /**
   * `reviewed_at` — when the status was changed. Written by
   * `updateShiftRequestStatus` via `serverTimestamp()`.
   */
  reviewed_at?: Timestamp | null;
}

// -----------------------------------------------------------------------
// ScheduleChangeRequest — schedule-structure change requests
// -----------------------------------------------------------------------

/**
 * Mirrors Flutter `ScheduleChangeRequestRecord`
 * (lib/backend/schema/schedule_change_request_record.dart).
 *
 * Stored at Firestore collection: `scheduleChangeRequest/{requestId}`
 * (note camelCase, line 46 of Flutter file).
 *
 * Flutter field names are CAPITALISED here
 * (`DateTime`, `Reason`) — unusual for this codebase but faithful to
 * the FlutterFlow-generated field keys. We mirror them exactly.
 */
export interface ScheduleChangeRequest {
  /** Firestore doc id (populated when fetched). */
  id: string;

  /**
   * `DateTime` (sic — capitalised) — the date the change should apply.
   * Flutter line 18-21, storage key line 39.
   */
  DateTime: Timestamp | null;

  /**
   * `Reason` (sic — capitalised) — free-text justification.
   * Flutter line 23-26, storage key line 40.
   */
  Reason: string;

  /**
   * `userId` — uid of the author. Stored as a plain string (not a ref),
   * per Flutter line 28-31.
   */
  userId: string;

  /**
   * `status` — plain string with values `'sent'` | `'accepted'` |
   * `'declined'`. Flutter does NOT use a typed enum here (line 33-36).
   * The widget `shift_change_requests_widget.dart` writes `'sent'` on
   * create; `show_request_widget.dart` writes `'accepted'` / `'declined'`
   * on review.
   */
  status: string;

  /**
   * `scheduleId` — id of the schedule this change targets. NOT in the
   * Flutter record schema (no `scheduleId` field there), but required
   * for the web app's `getScheduleChangeRequestsForSchedule` helper.
   *
   * TODO (P3-2/P3-3): when Flutter adds a `schedule_ref` or `scheduleId`
   * field to this record, align on it. Until then the web app writes
   * it as an extra field; Flutter ignores unknown fields.
   */
  scheduleId?: string;
}
