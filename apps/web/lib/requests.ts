"use client";

import {
  arrayUnion,
  collection,
  collectionGroup,
  doc,
  DocumentReference,
  addDoc,
  setDoc,
  updateDoc,
  deleteDoc,
  getDoc,
  getDocs,
  query,
  where,
  orderBy,
  limit,
  serverTimestamp,
  Timestamp,
  writeBatch,
} from "firebase/firestore";
import { getFirebaseDb } from "./firebase";
import type {
  ScheduleRequest,
  ScheduleRequestStatus,
  ShiftRequest,
  ShiftRequestStatus,
  ScheduleChangeRequest,
} from "./requests-types";

function db() {
  return getFirebaseDb();
}

// ============================================================================
// ScheduleRequest — `schedule_requests/{id}` (top-level)
// ============================================================================

/**
 * List all schedule-level requests that target a given schedule, newest
 * first. Mirrors Flutter's `queryScheduleRequestsRecordOnce` with a
 * `schedule_ref` filter (see lib/backend/backend.dart:369).
 */
export async function getScheduleRequestsForSchedule(
  scheduleId: string
): Promise<ScheduleRequest[]> {
  const scheduleRef = doc(db(), "schedules", scheduleId);
  const snap = await getDocs(
    query(
      collection(db(), "schedule_requests"),
      where("schedule_ref", "==", scheduleRef),
      orderBy("created_time", "desc")
    )
  );
  return snap.docs.map((d) => ({ id: d.id, ...(d.data() as Omit<ScheduleRequest, "id">) }));
}

/**
 * List all schedule-level requests authored by OR targeting a given user.
 * Fans out two queries (from_user, to_user) and merges. Mirrors the
 * Flutter `debug_schedule_requests.dart` scan pattern.
 */
export async function getScheduleRequestsForUser(
  uid: string
): Promise<ScheduleRequest[]> {
  const userRef = doc(db(), "users", uid);
  const [fromSnap, toSnap] = await Promise.all([
    getDocs(
      query(
        collection(db(), "schedule_requests"),
        where("from_user", "==", userRef),
        orderBy("created_time", "desc")
      )
    ),
    getDocs(
      query(
        collection(db(), "schedule_requests"),
        where("to_user", "==", userRef),
        orderBy("created_time", "desc")
      )
    ),
  ]);

  // Merge + dedupe by doc id (a request can't be both from+to the same
  // user in practice, but be defensive).
  const byId = new Map<string, ScheduleRequest>();
  for (const d of [...fromSnap.docs, ...toSnap.docs]) {
    byId.set(d.id, { id: d.id, ...(d.data() as Omit<ScheduleRequest, "id">) });
  }
  return Array.from(byId.values());
}

export interface CreateScheduleRequestInput {
  isAddRequest: boolean;
  isJoinRequest: boolean;
  scheduleName: string;
  requestStatus: ScheduleRequestStatus;
  fromUserUid: string;
  toUserUid?: string | null;
  toUserIdentification: string;
  scheduleId: string;
}

/**
 * Create a schedule-level request. Mirrors Flutter's
 * `createScheduleRequestsRecordData` path in `add_employee_widget.dart`
 * (lines 168-182): single write to `schedule_requests/{newId}` with
 * `created_time: serverTimestamp()`, `is_read: false`.
 */
export async function createScheduleRequest(
  input: CreateScheduleRequestInput
): Promise<string> {
  const fromUser = doc(db(), "users", input.fromUserUid);
  const toUser: DocumentReference | null = input.toUserUid
    ? doc(db(), "users", input.toUserUid)
    : null;
  const scheduleRef = doc(db(), "schedules", input.scheduleId);

  const ref = await addDoc(collection(db(), "schedule_requests"), {
    is_add_request: input.isAddRequest,
    is_join_request: input.isJoinRequest,
    schedule_name: input.scheduleName,
    request_status: input.requestStatus,
    from_user: fromUser,
    to_user: toUser,
    to_user_identification: input.toUserIdentification,
    created_time: serverTimestamp(),
    schedule_ref: scheduleRef,
    is_read: false,
  });
  return ref.id;
}

/**
 * Update a schedule-level request's status (accept/decline). Mirrors
 * Flutter's update in `schedule_request_widget.dart` lines 681-700.
 * Also records the reviewer uid + timestamp as audit fields (these are
 * web-only enhancements; Flutter will ignore them).
 */
export async function updateScheduleRequestStatus(
  id: string,
  status: ScheduleRequestStatus,
  reviewerUid: string
): Promise<void> {
  await updateDoc(doc(db(), "schedule_requests", id), {
    request_status: status,
    reviewer_uid: reviewerUid,
    reviewed_at: serverTimestamp(),
  });
}

/**
 * The invitee's profile fields needed to build the schedule's `employees[]`
 * entry — passed by the caller from the authenticated user + their
 * `users/{uid}` profile doc (Flutter uses currentUserDisplayName /
 * currentPhoneNumber / currentUserEmail / currentUserReference).
 */
export interface AcceptingUserProfile {
  uid: string;
  displayName: string;
  email: string;
  phone: string;
}

/**
 * Accept a schedule ADD invitation — the FULL Flutter parity contract, as one
 * atomic `writeBatch`. Mirrors `schedule_request_widget.dart` ~880-1010, which
 * performs FOUR writes (status alone is NOT membership — that was the P0 bug
 * QA found on 2026-06-11: accept flipped the status and nothing else, so the
 * employee never became a member):
 *
 *   1. schedule_requests/{id} → request_status: ADD_REQUEST_ACCEPTED
 *   2. CREATE users/{uid}/schedules_involved/{auto} with
 *      { schedules_collection_ref, schedule_name, priorities_private: bool[21] all-false }
 *   3. schedules/{sid} → employees arrayUnion({ employee_name, role:{is_worker:true},
 *      employee_phone, user_ref, employee_email })  — exact Flutter field names
 *   4. the schedule's chat doc (chats where schedule_ref == scheduleRef, single)
 *      → users arrayUnion(users/{uid} REFERENCE). NOTE: Flutter-created schedule
 *      chats store `users` as DocumentReferences (web-created threads use uid
 *      strings — a separate, pre-existing mediums mismatch); parity requires
 *      the reference here.
 *
 * The chat lookup is a pre-batch read (exactly like Flutter's
 * `queryChatsRecordOnce` before `firestoreBatch.commit`). A schedule with no
 * chat doc skips write 4 rather than failing membership.
 */
export async function acceptScheduleInvite(
  req: ScheduleRequest,
  profile: AcceptingUserProfile
): Promise<void> {
  const scheduleRef = req.schedule_ref;
  if (!scheduleRef) {
    throw new Error("invite has no schedule_ref — cannot create membership");
  }
  const userRef = doc(db(), "users", profile.uid);

  // Pre-batch read: the schedule's chat thread (may legitimately not exist).
  const chatSnap = await getDocs(
    query(
      collection(db(), "chats"),
      where("schedule_ref", "==", scheduleRef),
      limit(1)
    )
  );
  const chatRef = chatSnap.docs[0]?.ref ?? null;

  const batch = writeBatch(db());

  // (1) status — plus the web-only audit fields updateScheduleRequestStatus records.
  batch.update(doc(db(), "schedule_requests", req.id), {
    request_status: "ADD_REQUEST_ACCEPTED" satisfies ScheduleRequestStatus,
    reviewer_uid: profile.uid,
    reviewed_at: serverTimestamp(),
  });

  // (2) membership doc under the user — priorities_private is the 21-slot
  // all-false array Flutter seeds (List.filled(21, false)).
  batch.set(doc(collection(db(), "users", profile.uid, "schedules_involved")), {
    schedules_collection_ref: scheduleRef,
    schedule_name: req.schedule_name,
    priorities_private: Array(21).fill(false),
  });

  // (3) the schedule's employees[] entry — exact Flutter struct field names.
  batch.update(scheduleRef, {
    employees: arrayUnion({
      employee_name: profile.displayName,
      role: { is_worker: true },
      employee_phone: profile.phone,
      user_ref: userRef,
      employee_email: profile.email,
    }),
  });

  // (4) join the schedule chat (when one exists).
  if (chatRef) {
    batch.update(chatRef, { users: arrayUnion(userRef) });
  }

  await batch.commit();
}

/**
 * Delete (withdraw) a schedule-level request. Mirrors Flutter's
 * `employee_list_widget.dart:568-570`:
 *   await columnScheduleRequestsRecord.reference.delete();
 *
 * Used by the manager-side "Withdraw add request" action — the manager
 * cancels an invitation they sent before the invitee accepts/declines.
 */
export async function deleteScheduleRequest(id: string): Promise<void> {
  await deleteDoc(doc(db(), "schedule_requests", id));
}

/**
 * The pending add-request invitations a manager has sent for a schedule.
 * Filters the schedule's `schedule_requests` to add-requests that are still
 * `ADD_RQUEST_PENDING` (Flutter preserves that typo — see requests-types.ts).
 *
 * Mirrors Flutter's `employee_list_widget.dart:331-347` stream:
 *   queryScheduleRequestsRecord(... where schedule_ref == ref
 *     && is_add_request == true
 *     && request_status == ADD_RQUEST_PENDING)
 *
 * We post-filter in the client (rather than a compound Firestore query) so we
 * don't require a composite index, and to reuse the existing
 * `getScheduleRequestsForSchedule` read path (which is already test-covered).
 */
export async function getPendingAddRequestsForSchedule(
  scheduleId: string
): Promise<ScheduleRequest[]> {
  const all = await getScheduleRequestsForSchedule(scheduleId);
  return all.filter(
    (r) => r.is_add_request && r.request_status === "ADD_RQUEST_PENDING"
  );
}

/**
 * The incoming add-request invitations sent TO a given user that are still
 * pending. The invitee-side read path for the accept/decline screen — mirrors
 * Flutter's `schedule_request_widget.dart` which loads the
 * `ScheduleRequestsRecord` whose `to_user` is the current user and whose
 * `request_status` is `ADD_RQUEST_PENDING` / `JOIN_REQUEST_PENDING`.
 *
 * Reuses the existing test-covered `getScheduleRequestsForUser` read path
 * (from_user + to_user fan-out) and post-filters to the requests the user must
 * action: targeted at them (`to_user`), add-request, still pending.
 */
export async function getPendingInvitesForUser(
  uid: string
): Promise<ScheduleRequest[]> {
  const userPath = `users/${uid}`;
  const all = await getScheduleRequestsForUser(uid);
  return all.filter(
    (r) =>
      r.is_add_request &&
      r.request_status === "ADD_RQUEST_PENDING" &&
      // only requests TARGETING this user (to_user), not ones they authored
      r.to_user != null &&
      r.to_user.path === userPath
  );
}

// ============================================================================
// User lookup — resolve an invitee email to a `users/{uid}` ref
// ============================================================================

export interface InviteeUser {
  uid: string;
  ref: DocumentReference;
  email: string;
  display_name: string;
}

/**
 * Look up a registered user by exact email. Mirrors Flutter's
 * `queryUsersRecordOnce(... where('email', isEqualTo: ...), singleRecord)` in
 * `add_employee_widget.dart:795-804`. Returns null when no account exists yet
 * (the invitee hasn't signed up) — the caller then creates an email-only
 * invitation with `to_user: null` and skips the push notification, exactly as
 * Flutter does.
 */
export async function getUserByEmail(
  email: string
): Promise<InviteeUser | null> {
  const snap = await getDocs(
    query(collection(db(), "users"), where("email", "==", email), limit(1))
  );
  const d = snap.docs[0];
  if (!d) return null;
  const data = d.data() as { email?: string; display_name?: string };
  return {
    uid: d.id,
    ref: doc(db(), "users", d.id),
    email: data.email ?? email,
    display_name: data.display_name ?? "",
  };
}

// ============================================================================
// Push notification trigger — `ff_user_push_notifications/{id}`
// ============================================================================

/**
 * Collection consumed by the Flutter Cloud Function `sendUserPushNotification`.
 * Writing a doc here fans the message out to every FCM token registered on the
 * target users. Source of truth:
 * lib/backend/push_notifications/push_notifications_util.dart:17.
 */
const PUSH_NOTIFICATIONS_COLLECTION = "ff_user_push_notifications";

export interface TriggerPushNotificationInput {
  notificationTitle: string;
  notificationText: string;
  /** uids of the users to notify — converted to `users/{uid}` doc paths. */
  toUserUids: string[];
  /** uid of the sender (the manager). Stored as a `users/{uid}` ref. */
  fromUserUid: string;
  /** Deep-link target screen. Defaults to Flutter's `'Home'`. */
  initialPageName?: string;
  /** Extra payload merged into `parameter_data`. */
  parameterData?: Record<string, unknown>;
}

/**
 * Mirror of Flutter's `triggerPushNotification`
 * (push_notifications_util.dart:67-98): writes one doc to
 * `ff_user_push_notifications` with the title/body, a comma-joined list of
 * recipient user doc paths, the deep-link target, serialized parameter data,
 * the sender ref, and a timestamp. The Cloud Function does the actual FCM send.
 *
 * No-ops when title or body is empty, or when there are no recipients — same
 * guard as Flutter (line 77-79) and consistent with skipping the push for
 * email-only invitees who have no account yet.
 *
 * Best-effort: this is NOT critical to the invite. Callers should not let a
 * notification failure roll back the `schedule_requests` write (Flutter docs
 * this explicitly at add_employee_widget.dart:227-229).
 */
export async function triggerPushNotification(
  input: TriggerPushNotificationInput
): Promise<void> {
  if (!input.notificationTitle || !input.notificationText) return;
  if (input.toUserUids.length === 0) return;

  await addDoc(collection(db(), PUSH_NOTIFICATIONS_COLLECTION), {
    notification_title: input.notificationTitle,
    notification_text: input.notificationText,
    notification_sound: "default",
    user_refs: input.toUserUids.map((uid) => `users/${uid}`).join(","),
    initial_page_name: input.initialPageName ?? "Home",
    parameter_data: JSON.stringify(input.parameterData ?? {}),
    sender: doc(db(), "users", input.fromUserUid),
    timestamp: serverTimestamp(),
  });
}

// ============================================================================
// ShiftRequest — `<parent>/shift_requests/{id}` (subcollection)
// ============================================================================
//
// Flutter's `ShiftRequestsRecord.collection(parent?)` (schema line 60-63)
// supports both a parented query and a collection-group scan. We use the
// collection-group scan when reading per-schedule / per-user because the
// parent path (`schedules/{sid}/built_schedules/{bid}`) is not always on
// hand at call time — we filter by `built_schedule_ref` /
// `reuqesting_employee` instead. When a caller does know the parent
// (write side), they pass the built-schedule id explicitly.

/**
 * Load every shift-swap request whose `built_schedule_ref` points inside
 * the given schedule. Uses a `collectionGroup` query (Flutter's
 * `collectionGroup('shift_requests')`, line 63 of the record schema).
 */
export async function getShiftRequestsForSchedule(
  scheduleId: string
): Promise<ShiftRequest[]> {
  // We filter via the schedule's built_schedules — fetch all built ids
  // for the schedule first, then query by `built_schedule_ref in [...]`.
  // (`in` tops out at 30 per Firestore; scheduling UIs rarely have that
  // many generations, and we fall back to post-filter when exceeded.)
  const builtSnap = await getDocs(
    collection(db(), "schedules", scheduleId, "built_schedules")
  );
  const builtRefs = builtSnap.docs.map((d) => d.ref);
  if (builtRefs.length === 0) return [];

  // Firestore `in` limit is 30; chunk if needed.
  const chunks: DocumentReference[][] = [];
  for (let i = 0; i < builtRefs.length; i += 30) {
    chunks.push(builtRefs.slice(i, i + 30));
  }

  const results: ShiftRequest[] = [];
  for (const chunk of chunks) {
    const snap = await getDocs(
      query(
        collectionGroup(db(), "shift_requests"),
        where("built_schedule_ref", "in", chunk)
      )
    );
    for (const d of snap.docs) {
      results.push({
        id: d.id,
        path: d.ref.path,
        ...(d.data() as Omit<ShiftRequest, "id" | "path">),
      });
    }
  }
  return results;
}

/**
 * Load every shift-swap request authored by the given user. Uses a
 * `collectionGroup` query filtered by `reuqesting_employee` (Flutter
 * typo preserved — see schema line 48).
 */
export async function getShiftRequestsForUser(
  uid: string
): Promise<ShiftRequest[]> {
  const userRef = doc(db(), "users", uid);
  const snap = await getDocs(
    query(
      collectionGroup(db(), "shift_requests"),
      where("reuqesting_employee", "==", userRef)
    )
  );
  return snap.docs.map((d) => ({
    id: d.id,
    path: d.ref.path,
    ...(d.data() as Omit<ShiftRequest, "id" | "path">),
  }));
}

export interface CreateShiftRequestInput {
  scheduleId: string;
  builtScheduleId: string;
  requestingEmployeeUid: string;
  shiftToChangeFrom: Date;
  shiftToChangeTo: Date;
}

/**
 * Create a new shift-swap request. Mirrors Flutter's
 * `createShiftRequestsRecordData` shape (schema lines 99-117). Writes
 * under the built_schedule subcollection:
 * `schedules/{sid}/built_schedules/{bid}/shift_requests/{new}`. Starts
 * in status `PENDING`. Returns the new doc id.
 */
export async function createShiftRequest(
  input: CreateShiftRequestInput
): Promise<string> {
  const parent = doc(
    db(),
    "schedules",
    input.scheduleId,
    "built_schedules",
    input.builtScheduleId
  );
  const requester = doc(db(), "users", input.requestingEmployeeUid);
  const ref = await addDoc(
    collection(parent, "shift_requests"),
    {
      reuqesting_employee: requester,
      shift_to_change_from: Timestamp.fromDate(input.shiftToChangeFrom),
      shift_to_change_to: Timestamp.fromDate(input.shiftToChangeTo),
      built_schedule_ref: parent,
      shift_request_status: "PENDING" as ShiftRequestStatus,
    }
  );
  return ref.id;
}

/**
 * Internal helper: resolve a ShiftRequest doc ref from either an id+parent
 * path OR a full doc path. Because reads come via `collectionGroup`, the
 * caller usually passes the full path (available on each returned
 * `ShiftRequest.path`).
 */
function shiftRequestDocRef(pathOrId: string): DocumentReference {
  // If the string looks like a full path (contains 'shift_requests/'),
  // honour it verbatim.
  if (pathOrId.includes("/shift_requests/")) {
    const segments = pathOrId.split("/");
    // segments come in pairs of collection/doc; pass to doc() as rest
    // args so Firestore resolves the whole path.
    return doc(db(), segments[0], ...segments.slice(1));
  }
  // Fallback: assume it's a top-level `shift_requests/{id}` (some older
  // data may live there; tests cover this case).
  return doc(db(), "shift_requests", pathOrId);
}

/**
 * Update a shift-swap request's status. Records the reviewer uid +
 * server timestamp for audit (web-only fields; Flutter ignores them).
 */
export async function updateShiftRequestStatus(
  pathOrId: string,
  status: ShiftRequestStatus,
  reviewerUid: string
): Promise<void> {
  await updateDoc(shiftRequestDocRef(pathOrId), {
    shift_request_status: status,
    reviewer_uid: reviewerUid,
    reviewed_at: serverTimestamp(),
  });
}

/**
 * Delete a shift-swap request. Only permitted while the request is
 * still `PENDING` — once a manager has accepted/rejected, deletion is
 * destructive of audit trail. Throws when called on non-PENDING docs.
 */
export async function deleteShiftRequest(pathOrId: string): Promise<void> {
  const ref = shiftRequestDocRef(pathOrId);
  const snap = await getDoc(ref);
  if (!snap.exists()) {
    throw new Error(`Shift request not found: ${pathOrId}`);
  }
  const data = snap.data() as Partial<ShiftRequest>;
  if (data.shift_request_status !== "PENDING") {
    throw new Error(
      `Cannot delete shift request with status "${
        data.shift_request_status ?? "unknown"
      }" — only PENDING requests may be deleted.`
    );
  }
  await deleteDoc(ref);
}

// ============================================================================
// ScheduleChangeRequest — `scheduleChangeRequest/{id}` (top-level, camelCase)
// ============================================================================

/**
 * List all schedule-change requests for a given schedule. Since
 * Flutter's `ScheduleChangeRequestRecord` does NOT have a
 * schedule_ref / scheduleId field (see schema), we query by the web-app
 * `scheduleId` field that `createScheduleChangeRequest` attaches. If
 * no docs have that field (pure Flutter-written data), returns [].
 */
export async function getScheduleChangeRequestsForSchedule(
  scheduleId: string
): Promise<ScheduleChangeRequest[]> {
  const snap = await getDocs(
    query(
      collection(db(), "scheduleChangeRequest"),
      where("scheduleId", "==", scheduleId)
    )
  );
  return snap.docs.map((d) => ({
    id: d.id,
    ...(d.data() as Omit<ScheduleChangeRequest, "id">),
  }));
}

export interface CreateScheduleChangeRequestInput {
  scheduleId: string;
  userId: string;
  reason: string;
  dateTime: Date;
  /** Defaults to `'sent'` (matches `shift_change_requests_widget.dart:360`). */
  status?: string;
}

/**
 * Create a schedule-change request. Mirrors Flutter's
 * `shift_change_requests_widget.dart:354-361`:
 *   ScheduleChangeRequestRecord.collection.doc().set(
 *     createScheduleChangeRequestRecordData(
 *       dateTime: _model.datePicked,
 *       reason: _model.resionTextController.text,
 *       userId: currentUserUid,
 *       status: 'sent',
 *     ));
 *
 * We add `scheduleId` so the per-schedule reader can filter — see
 * `getScheduleChangeRequestsForSchedule`.
 */
export async function createScheduleChangeRequest(
  input: CreateScheduleChangeRequestInput
): Promise<string> {
  const ref = doc(collection(db(), "scheduleChangeRequest"));
  await setDoc(ref, {
    DateTime: Timestamp.fromDate(input.dateTime),
    Reason: input.reason,
    userId: input.userId,
    status: input.status ?? "sent",
    scheduleId: input.scheduleId,
  });
  return ref.id;
}

/**
 * Load a single schedule-change request by id.
 */
export async function getScheduleChangeRequest(
  id: string
): Promise<ScheduleChangeRequest | null> {
  const snap = await getDoc(doc(db(), "scheduleChangeRequest", id));
  if (!snap.exists()) return null;
  return { id: snap.id, ...(snap.data() as Omit<ScheduleChangeRequest, "id">) };
}

/**
 * Update a schedule-change request's status. Mirrors Flutter's
 * `show_request_widget.dart` approve/decline flow: sets `status` to
 * `'accepted'` or `'declined'` (or any other string the caller supplies).
 *
 * Also writes `resolved_at: serverTimestamp()` so downstream Cloud
 * Functions can trigger FCM on this write. Tracks the reviewer uid
 * for audit. These extra fields are web-only; Flutter ignores them.
 */
export async function updateScheduleChangeRequestStatus(
  id: string,
  status: string,
  reviewerUid: string
): Promise<void> {
  await updateDoc(doc(db(), "scheduleChangeRequest", id), {
    status,
    reviewer_uid: reviewerUid,
    resolved_at: serverTimestamp(),
  });
}
