"use client";

import {
  collection,
  doc,
  addDoc,
  updateDoc,
  arrayUnion,
  arrayRemove,
  serverTimestamp,
  setDoc,
  deleteDoc,
  getDoc,
  getDocs,
  writeBatch,
  increment,
  runTransaction,
  Timestamp,
} from "firebase/firestore";
import { getFirebaseDb } from "./firebase";
import type {
  EmployeeDetails,
  RoleStruct,
  ScheduleRow,
  ScheduleSettings,
} from "./types";
import { cellKeysToBoolArray } from "./priorities-mapping";
import * as api from "./api/client";

// -----------------------------------------------------------------------
// Chat writes — messages + thread creation + seen-receipts
//
// Reads for chat live in `chat.ts` (realtime onSnapshot subscribers).
// Writes stay here so they share the same `writeBatch` helper used for
// other multi-doc operations (schedule delete, etc.). The schema is
// defined in `chat-types.ts`.
// -----------------------------------------------------------------------

function db() {
  return getFirebaseDb();
}

function apiEnabled(): boolean {
  return Boolean(process.env.NEXT_PUBLIC_SCHEDULER_API_URL);
}

export interface CreateScheduleInput {
  scheduleName: string;
  numOfStations: number;
  enabledShifts: string[];
  ownerUid: string;
  ownerEmail: string;
  ownerName: string;
}

/**
 * Thrown when a schedule name already exists for the owner. The UI maps this to
 * the duplicate-name message. Distinct from a generic create failure so the
 * form can show the right guidance.
 */
export class ScheduleNameTakenError extends Error {
  constructor(public readonly scheduleName: string) {
    super(`A schedule named "${scheduleName}" already exists`);
    this.name = "ScheduleNameTakenError";
  }
}

/**
 * Deterministic, Firestore-safe document id for the per-owner uniqueness
 * marker. Trimmed + lowercased so "Clinic", "clinic", and " clinic " collide,
 * URL-encoded so it never contains "/" and the "n_" prefix keeps it clear of
 * the reserved "." / ".." ids and the empty string.
 */
function scheduleNameMarkerId(name: string): string {
  return "n_" + encodeURIComponent(name.trim().toLowerCase());
}

export async function createSchedule(
  input: CreateScheduleInput,
): Promise<string> {
  if (apiEnabled()) {
    try {
      const shifts: Record<string, boolean> = {
        morning: input.enabledShifts.includes("morning"),
        afternoon: input.enabledShifts.includes("afternoon"),
        night: input.enabledShifts.includes("night"),
      };
      const ownerEmployee: EmployeeDetails = {
        employee_name: input.ownerName,
        employee_email: input.ownerEmail,
        employee_phone: "",
        role: { is_creator: true, is_admin: true, is_worker: false },
        user_ref: null,
      };
      const result = await api.createSchedule({
        name: input.scheduleName,
        settings: {
          employees: [ownerEmployee],
          current_priorities: new Array(21).fill(""),
          schedule_settings: {
            enabled_shifts: {
              ...shifts,
              morning_hours: "",
              noon_hours: "",
              night_hours: "",
            },
            num_of_stations: input.numOfStations,
            submission_deadline: {
              time: null,
              is_activated: false,
              weekday: "SUNDAY",
            },
          },
        },
      });
      return result.id;
    } catch {
      // Fall through to Firestore
    }
  }

  const ownerRole: RoleStruct = {
    is_creator: true,
    is_admin: true,
    is_worker: false,
  };
  const ownerEmployee: EmployeeDetails = {
    employee_name: input.ownerName,
    employee_email: input.ownerEmail,
    employee_phone: "",
    role: ownerRole,
    user_ref: null,
  };

  const scheduleData = {
    schedule_name: input.scheduleName,
    employees: [ownerEmployee],
    current_priorities: new Array(21).fill(""),
    next_schedule: [],
    schedule_settings: {
      enabled_shifts: {
        morning: input.enabledShifts.includes("morning"),
        afternoon: input.enabledShifts.includes("afternoon"),
        night: input.enabledShifts.includes("night"),
        morning_hours: "",
        noon_hours: "",
        night_hours: "",
      },
      num_of_stations: input.numOfStations,
      submission_deadline: {
        time: null,
        is_activated: false,
        weekday: "SUNDAY",
      },
    },
    sid: "",
    created_at: serverTimestamp(),
    created_by: input.ownerUid,
  };

  // Enforce per-owner name uniqueness atomically. A marker doc keyed by the
  // normalized name is read-then-written inside the transaction, so two
  // concurrent creates of the same name cannot both succeed (the loser's
  // transaction sees the marker / a write conflict and aborts). This closes the
  // read-then-write race the bare client-side check could not, and makes the
  // Firestore path agree with the Go API's server-side 409.
  const markerRef = doc(
    db(),
    "users",
    input.ownerUid,
    "schedule_names",
    scheduleNameMarkerId(input.scheduleName),
  );

  return runTransaction(db(), async (tx) => {
    const markerSnap = await tx.get(markerRef);
    if (markerSnap.exists()) {
      throw new ScheduleNameTakenError(input.scheduleName);
    }

    // Pre-generate the schedule id so the schedule doc, the per-user index, and
    // the uniqueness marker are all written in the same atomic transaction.
    const scheduleRef = doc(collection(db(), "schedules"));
    tx.set(scheduleRef, scheduleData);
    tx.set(
      doc(db(), "users", input.ownerUid, "schedules_involved", scheduleRef.id),
      {
        schedules_collection_ref: scheduleRef,
        schedule_name: input.scheduleName,
        priorities_private: new Array(21).fill(false),
      },
    );
    tx.set(markerRef, {
      schedule_id: scheduleRef.id,
      schedule_name: input.scheduleName,
    });

    return scheduleRef.id;
  });
}

export async function updateScheduleName(
  scheduleId: string,
  scheduleName: string,
  allInvolvedUids: string[],
): Promise<void> {
  if (apiEnabled()) {
    try {
      await api.updateSchedule(scheduleId, { name: scheduleName });
      return;
    } catch {
      // Fall through to Firestore
    }
  }

  const scheduleRef = doc(db(), "schedules", scheduleId);

  // Capture the owner + old name first so we can migrate the uniqueness marker
  // (see createSchedule). Without this, a rename would orphan the old marker and
  // permanently block re-using the old name.
  const snap = await getDoc(scheduleRef);
  const data = snap.exists() ? (snap.data() as Record<string, unknown>) : null;
  const ownerUid = data?.created_by as string | undefined;
  const oldName = data?.schedule_name as string | undefined;

  await updateDoc(scheduleRef, { schedule_name: scheduleName });

  await Promise.all(
    allInvolvedUids.map((uid) =>
      updateDoc(doc(db(), "users", uid, "schedules_involved", scheduleId), {
        schedule_name: scheduleName,
      }).catch(() => {
        // Best-effort — involved doc may not exist for every employee
      }),
    ),
  );

  // Migrate the per-owner uniqueness marker (best-effort): drop the old-name
  // marker and write the new one so the old name becomes reusable and the new
  // name is protected. Legacy schedules with no prior marker simply gain one.
  if (ownerUid) {
    const newMarkerId = scheduleNameMarkerId(scheduleName);
    const oldMarkerId = oldName ? scheduleNameMarkerId(oldName) : null;
    if (oldMarkerId && oldMarkerId !== newMarkerId) {
      await deleteDoc(
        doc(db(), "users", ownerUid, "schedule_names", oldMarkerId),
      ).catch(() => undefined);
    }
    await setDoc(
      doc(db(), "users", ownerUid, "schedule_names", newMarkerId),
      { schedule_id: scheduleId, schedule_name: scheduleName },
    ).catch(() => undefined);
  }
}

export async function addEmployee(
  scheduleId: string,
  employee: Omit<EmployeeDetails, "user_ref">,
): Promise<void> {
  await updateDoc(doc(db(), "schedules", scheduleId), {
    employees: arrayUnion({ ...employee, user_ref: null }),
  });
}

export async function addEmployeesBulk(
  scheduleId: string,
  employees: readonly Omit<EmployeeDetails, "user_ref">[],
): Promise<void> {
  if (employees.length === 0) return;
  const payload = employees.map((e) => ({ ...e, user_ref: null }));
  await updateDoc(doc(db(), "schedules", scheduleId), {
    employees: arrayUnion(...payload),
  });
}

export async function removeEmployee(
  scheduleId: string,
  employee: EmployeeDetails,
): Promise<void> {
  await updateDoc(doc(db(), "schedules", scheduleId), {
    employees: arrayRemove(employee),
  });
}

export async function deleteSchedule(
  scheduleId: string,
  involvedUids: string[],
): Promise<void> {
  if (apiEnabled()) {
    try {
      await api.deleteSchedule(scheduleId);
      // Clean up firestore back-references
      await Promise.all(
        involvedUids.map((uid) =>
          deleteDoc(
            doc(db(), "users", uid, "schedules_involved", scheduleId),
          ).catch(() => undefined),
        ),
      );
      return;
    } catch {
      // Fall through to Firestore
    }
  }

  const scheduleRef = doc(db(), "schedules", scheduleId);

  // Capture owner + name before deletion so we can free the uniqueness marker
  // (see createSchedule). Without this, a deleted name stays permanently
  // un-creatable because its marker would never be removed.
  const snap = await getDoc(scheduleRef);
  const data = snap.exists() ? (snap.data() as Record<string, unknown>) : null;
  const ownerUid = data?.created_by as string | undefined;
  const scheduleName = data?.schedule_name as string | undefined;

  const builtSnap = await getDocs(
    collection(db(), "schedules", scheduleId, "built_schedules"),
  );
  const prioSnap = await getDocs(
    collection(db(), "schedules", scheduleId, "priorities_submissions"),
  );

  const batch = writeBatch(db());
  for (const d of builtSnap.docs) batch.delete(d.ref);
  for (const d of prioSnap.docs) batch.delete(d.ref);
  await batch.commit();

  await Promise.all(
    involvedUids.map((uid) =>
      deleteDoc(
        doc(db(), "users", uid, "schedules_involved", scheduleId),
      ).catch(() => undefined),
    ),
  );

  await deleteDoc(scheduleRef);

  // Free the uniqueness marker so the name can be reused (best-effort).
  if (ownerUid && scheduleName) {
    await deleteDoc(
      doc(
        db(),
        "users",
        ownerUid,
        "schedule_names",
        scheduleNameMarkerId(scheduleName),
      ),
    ).catch(() => undefined);
  }
}

export interface UserProfileInput {
  display_name: string;
  title: string;
  // Optional: in the Flutter-aligned flow the role is chosen on the separate
  // Choose-Role screen (see upsertUserRole) BEFORE the name step, so the
  // name/title write must not clobber it.
  role?: RoleStruct;
}

function roleStructToFlutterString(role: RoleStruct): "employer" | "employee" {
  return role.is_admin || role.is_creator ? "employer" : "employee";
}

export async function upsertUserProfile(
  uid: string,
  email: string,
  input: UserProfileInput,
): Promise<void> {
  const doc_: Record<string, unknown> = {
    uid,
    email,
    display_name: input.display_name,
    title: input.title,
    last_active_time: serverTimestamp(),
  };
  if (input.role) doc_.role = roleStructToFlutterString(input.role);
  await setDoc(doc(db(), "users", uid), doc_, { merge: true });
}

/**
 * Persists just the user's role (employer/employee), matching the Flutter
 * Choose-Role screen which sets the role as its own step after email
 * verification and before the name step.
 */
export async function upsertUserRole(
  uid: string,
  email: string,
  role: RoleStruct,
): Promise<void> {
  await setDoc(
    doc(db(), "users", uid),
    {
      uid,
      email,
      role: roleStructToFlutterString(role),
      last_active_time: serverTimestamp(),
    },
    { merge: true },
  );
}

export async function registerFcmToken(
  uid: string,
  token: string,
): Promise<void> {
  await updateDoc(doc(db(), "users", uid), {
    fcm_tokens: arrayUnion(token),
  });
}

export type ScheduleSettingsInput = Pick<
  ScheduleSettings,
  "enabled_shifts" | "num_of_stations"
> & {
  morning_hours?: string;
  noon_hours?: string;
  night_hours?: string;
  submission_deadline?: {
    is_activated: boolean;
    weekday:
      | "SUNDAY"
      | "MONDAY"
      | "TUESDAY"
      | "WEDNESDAY"
      | "THURSDAY"
      | "FRIDAY"
      | "SATURDAY";
    time: string | null;
  };
};

export interface PublishBuiltScheduleInput {
  rows: ScheduleRow[];
  firstWeekday: string | null;
  lastWeekday: string | null;
  currentPriorities?: string[];
  startDate?: Date;
  endDate?: Date;
}

export async function submitPriorities(
  scheduleId: string,
  uid: string,
  displayName: string,
  priorities: string[],
): Promise<void> {
  const priorityBools = cellKeysToBoolArray(priorities);

  await Promise.all([
    setDoc(
      doc(db(), "users", uid, "schedules_involved", scheduleId),
      {
        priorities_private: priorityBools,
      },
      { merge: true },
    ),
    setDoc(
      doc(db(), "schedules", scheduleId, "priorities_submissions", uid),
      {
        uid,
        display_name: displayName,
        priorities,
        submitted_at: serverTimestamp(),
      },
      { merge: true },
    ),
  ]);
}

export async function publishBuiltSchedule(
  scheduleId: string,
  input: PublishBuiltScheduleInput,
): Promise<string> {
  if (apiEnabled()) {
    try {
      const draft = await api.createDraft(scheduleId, input.rows);
      await api.publishDraft(scheduleId, draft.id);
      // Also write to Firestore for the read side (built_schedules), since
      // the API doesn't persist built schedules for reading later.
    } catch {
      // Fall through to Firestore
    }
  }

  const payload: Record<string, unknown> = {
    schedule: input.rows,
    first_weekday: input.firstWeekday ?? "",
    last_weekday: input.lastWeekday ?? "",
    first_weekday_datetime: input.startDate
      ? Timestamp.fromDate(input.startDate)
      : null,
    last_weekday_datetime: input.endDate
      ? Timestamp.fromDate(input.endDate)
      : null,
    current_priorities: input.currentPriorities ?? [],
    time_created: serverTimestamp(),
  };
  const ref = await addDoc(
    collection(db(), "schedules", scheduleId, "built_schedules"),
    payload,
  );
  return ref.id;
}

export async function updateScheduleSettings(
  scheduleId: string,
  settings: ScheduleSettingsInput,
): Promise<void> {
  if (apiEnabled()) {
    try {
      const shifts: Record<string, boolean> = {
        morning: settings.enabled_shifts.includes("morning"),
        afternoon: settings.enabled_shifts.includes("afternoon"),
        night: settings.enabled_shifts.includes("night"),
      };
      const updates: Record<string, unknown> = {
        "schedule_settings.enabled_shifts": {
          ...shifts,
          morning_hours: settings.morning_hours ?? "",
          noon_hours: settings.noon_hours ?? "",
          night_hours: settings.night_hours ?? "",
        },
        "schedule_settings.num_of_stations": settings.num_of_stations,
      };
      if (settings.submission_deadline) {
        updates["schedule_settings.submission_deadline"] =
          settings.submission_deadline;
      }
      await api.updateSchedule(scheduleId, updates);
      return;
    } catch {
      // Fall through to Firestore
    }
  }

  const flat = settings.enabled_shifts;
  const payload: Record<string, unknown> = {
    "schedule_settings.enabled_shifts": {
      morning: flat.includes("morning"),
      afternoon: flat.includes("afternoon"),
      night: flat.includes("night"),
      morning_hours: settings.morning_hours ?? "",
      noon_hours: settings.noon_hours ?? "",
      night_hours: settings.night_hours ?? "",
    },
    "schedule_settings.num_of_stations": settings.num_of_stations,
  };
  if (settings.morning_hours !== undefined)
    payload["schedule_settings.morning_hours"] = settings.morning_hours;
  if (settings.noon_hours !== undefined)
    payload["schedule_settings.noon_hours"] = settings.noon_hours;
  if (settings.night_hours !== undefined)
    payload["schedule_settings.night_hours"] = settings.night_hours;

  if (settings.submission_deadline) {
    const d = settings.submission_deadline;
    payload["schedule_settings.submission_deadline"] = {
      time: d.time ? Timestamp.fromDate(new Date(d.time)) : null,
      is_activated: d.is_activated,
      weekday: d.weekday,
    };
  }

  await updateDoc(doc(db(), "schedules", scheduleId), payload);
}

// =========================================================================
// Chat — message send, thread create, seen-receipt
// =========================================================================

export interface SendChatMessageInput {
  text: string;
  sender_uid: string;
  image_url?: string;
}

export async function sendChatMessage(
  threadId: string,
  message: SendChatMessageInput,
): Promise<string> {
  const threadRef = doc(db(), "chats", threadId);
  const messageRef = doc(collection(threadRef, "messages"));
  const ts = serverTimestamp();

  const messagePayload: Record<string, unknown> = {
    text: message.text,
    sender_uid: message.sender_uid,
    timestamp: ts,
  };
  if (message.image_url !== undefined) {
    messagePayload.image_url = message.image_url;
  }

  const previewPayload = {
    last_message: {
      text: message.text,
      timestamp: ts,
      sender: message.sender_uid,
    },
  };

  const batch = writeBatch(db());
  batch.set(messageRef, messagePayload);
  batch.update(threadRef, previewPayload);
  await batch.commit();

  return messageRef.id;
}

export async function createChatThread(
  users: string[],
  name?: string,
): Promise<string> {
  if (users.length === 0) {
    throw new Error("createChatThread requires at least one participant uid");
  }
  const payload: Record<string, unknown> = {
    users,
    is_group: users.length > 2,
    created_at: serverTimestamp(),
    owner: users[0],
  };
  if (name !== undefined) {
    payload.name = name;
  }
  const ref = await addDoc(collection(db(), "chats"), payload);
  return ref.id;
}

export async function markMessageSeen(
  threadId: string,
  messageId: string,
  uid: string,
): Promise<void> {
  await updateDoc(doc(db(), "chats", threadId, "messages", messageId), {
    seen_by: arrayUnion(uid),
  });
}

function monthKey(now: Date): string {
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, "0");
  return `${y}-${m}`;
}

export async function incrementMonthlyBuildCount(
  uid: string,
  now: Date = new Date(),
): Promise<void> {
  const key = monthKey(now);
  await setDoc(
    doc(db(), "users", uid),
    {
      monthly_builds: {
        [key]: increment(1),
      },
      total_builds: increment(1),
    },
    { merge: true },
  );
}
