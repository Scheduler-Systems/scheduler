"use client";

import {
  collection,
  doc,
  getDoc,
  getDocs,
  query,
  orderBy,
  limit,
} from "firebase/firestore";
import { getFirebaseDb } from "./firebase";
import type { Schedule, ScheduleInvolved, BuiltSchedule } from "./types";
import { boolArrayToCellKeys } from "./priorities-mapping";
import * as api from "./api/client";

function db() {
  return getFirebaseDb();
}

// ---------------------------------------------------------------------------
// Schedule reads — forwarded to scheduler-api REST when configured.
// Falls back to direct Firestore when NEXT_PUBLIC_SCHEDULER_API_URL is unset.
// ---------------------------------------------------------------------------

function apiEnabled(): boolean {
  return Boolean(process.env.NEXT_PUBLIC_SCHEDULER_API_URL);
}

function apiScheduleToLegacy(a: api.ApiSchedule): Schedule {
  const settings = a.settings ?? {};
  return {
    id: a.id,
    schedule_name: a.name,
    employees:
      (settings as { employees?: Schedule["employees"] }).employees ?? [],
    current_priorities:
      (settings as { current_priorities?: string[] }).current_priorities ?? [],
    schedule_settings:
      (settings as { schedule_settings?: Schedule["schedule_settings"] })
        .schedule_settings ?? null,
    sid: "",
    next_schedule: [],
  };
}

export async function getUserSchedules(_uid: string): Promise<Schedule[]> {
  if (apiEnabled()) {
    try {
      const res = await api.listSchedules();
      return res.items.map(apiScheduleToLegacy);
    } catch {
      // Fall through to Firestore
    }
  }

  const involvedSnap = await getDocs(
    collection(db(), "users", _uid, "schedules_involved"),
  );

  const refs = involvedSnap.docs.map((d) => {
    const data = d.data() as ScheduleInvolved;
    return data.schedules_collection_ref;
  });

  const schedules = await Promise.all(
    refs.map(async (ref) => {
      const snap = await getDoc(ref);
      if (!snap.exists()) return null;
      return { id: snap.id, ...snap.data() } as Schedule;
    }),
  );

  return schedules.filter(Boolean) as Schedule[];
}

export async function getSchedule(
  scheduleId: string,
): Promise<Schedule | null> {
  if (apiEnabled()) {
    try {
      const a = await api.getSchedule(scheduleId);
      return apiScheduleToLegacy(a);
    } catch {
      // Fall through to Firestore
    }
  }

  const snap = await getDoc(doc(db(), "schedules", scheduleId));
  if (!snap.exists()) return null;
  return { id: snap.id, ...snap.data() } as Schedule;
}

export async function getBuiltSchedules(
  scheduleId: string,
): Promise<BuiltSchedule[]> {
  const snap = await getDocs(
    query(
      collection(db(), "schedules", scheduleId, "built_schedules"),
      orderBy("time_created", "desc"),
    ),
  );
  return snap.docs.map((d) => ({ id: d.id, ...d.data() }) as BuiltSchedule);
}

export interface UserProfile {
  uid: string;
  email: string;
  display_name: string;
  title?: string;
  role?:
    | "employer"
    | "employee"
    | { is_creator?: boolean; is_admin?: boolean; is_worker?: boolean };
}

export async function getUserProfile(uid: string): Promise<UserProfile | null> {
  const snap = await getDoc(doc(db(), "users", uid));
  return snap.exists() ? ({ uid, ...snap.data() } as UserProfile) : null;
}

export function isEmployerRole(role: UserProfile["role"] | undefined): boolean {
  if (!role) return false;
  if (typeof role === "string") return role === "employer";
  return role.is_admin === true || role.is_creator === true;
}

export interface PrioritySubmission {
  uid: string;
  display_name: string;
  priorities: string[];
  submitted_at: { seconds: number } | null;
}

export async function getPrioritySubmission(
  scheduleId: string,
  uid: string,
): Promise<PrioritySubmission | null> {
  const [involvedSnap, subSnap] = await Promise.all([
    getDoc(doc(db(), "users", uid, "schedules_involved", scheduleId)),
    getDoc(doc(db(), "schedules", scheduleId, "priorities_submissions", uid)),
  ]);

  const flutterBools = involvedSnap.exists()
    ? ((involvedSnap.data().priorities_private as boolean[] | undefined) ??
      null)
    : null;

  const sub = subSnap.exists() ? (subSnap.data() as PrioritySubmission) : null;

  if (flutterBools && flutterBools.some((b) => b)) {
    return {
      uid,
      display_name: sub?.display_name ?? "",
      priorities: boolArrayToCellKeys(flutterBools),
      submitted_at: sub?.submitted_at ?? null,
    };
  }

  return sub;
}

export async function getAllPrioritySubmissions(
  scheduleId: string,
): Promise<PrioritySubmission[]> {
  const subSnap = await getDocs(
    collection(db(), "schedules", scheduleId, "priorities_submissions"),
  );
  const byUid = new Map<string, PrioritySubmission>();
  for (const d of subSnap.docs) {
    const data = d.data() as PrioritySubmission;
    byUid.set(d.id, { ...data, uid: d.id });
  }

  const schedule = await getSchedule(scheduleId);
  const uids = new Set<string>();
  for (const emp of schedule?.employees ?? []) {
    const uid = (emp.user_ref as { id?: string } | null)?.id;
    if (uid) uids.add(uid);
  }
  for (const uid of byUid.keys()) uids.add(uid);

  const involvedDocs = await Promise.all(
    Array.from(uids).map(async (uid) => {
      const snap = await getDoc(
        doc(db(), "users", uid, "schedules_involved", scheduleId),
      );
      if (!snap.exists()) return null;
      const bools = snap.data().priorities_private as boolean[] | undefined;
      if (!bools || !bools.some((b) => b)) return null;
      return { uid, bools };
    }),
  );

  for (const entry of involvedDocs) {
    if (!entry) continue;
    const existing = byUid.get(entry.uid);
    byUid.set(entry.uid, {
      uid: entry.uid,
      display_name: existing?.display_name ?? "",
      priorities: boolArrayToCellKeys(entry.bools),
      submitted_at: existing?.submitted_at ?? null,
    });
  }

  return Array.from(byUid.values());
}

export async function getLatestBuiltSchedule(
  scheduleId: string,
): Promise<BuiltSchedule | null> {
  const snap = await getDocs(
    query(
      collection(db(), "schedules", scheduleId, "built_schedules"),
      orderBy("time_created", "desc"),
      limit(1),
    ),
  );
  if (snap.empty) return null;
  const d = snap.docs[0];
  return { id: d.id, ...d.data() } as BuiltSchedule;
}

export interface DashboardSummary {
  scheduleCount: number;
  employeeCount: number;
  schedules: { id: string; name: string; employeeCount: number }[];
}

export async function getDashboardSummary(
  uid: string,
): Promise<DashboardSummary> {
  const schedules = await getUserSchedules(uid);
  const uniqueEmails = new Set<string>();
  for (const s of schedules) {
    for (const e of s.employees ?? []) {
      if (e.employee_email) uniqueEmails.add(e.employee_email);
    }
  }
  return {
    scheduleCount: schedules.length,
    employeeCount: uniqueEmails.size,
    schedules: schedules.map((s) => ({
      id: s.id,
      name: s.schedule_name,
      employeeCount: s.employees?.length ?? 0,
    })),
  };
}

export function buildCountMonthKey(now: Date = new Date()): string {
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, "0");
  return `${y}-${m}`;
}

export async function getMonthlyBuildCount(
  uid: string,
  now: Date = new Date(),
): Promise<number> {
  const snap = await getDoc(doc(db(), "users", uid));
  if (!snap.exists()) return 0;
  const data = snap.data() as { monthly_builds?: Record<string, unknown> };
  const map = data.monthly_builds;
  if (!map || typeof map !== "object") return 0;
  const key = buildCountMonthKey(now);
  const raw = (map as Record<string, unknown>)[key];
  return typeof raw === "number" && Number.isFinite(raw) && raw >= 0 ? raw : 0;
}
