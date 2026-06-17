"use client";

// P3-2 — employee-side shift-change request submission form.
//
// Wraps the helper `createScheduleChangeRequest` in `lib/requests.ts`.
// Authentication is enforced by the surrounding `(app)` layout — no
// explicit `<RequireAuth>` component exists; the layout redirects
// unauthenticated users to `/login` before this page renders.

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/lib/auth-context";
import { useI18n } from "@/lib/i18n-context";
import { getSchedule, getLatestBuiltSchedule } from "@/lib/firestore";
import { createScheduleChangeRequest } from "@/lib/requests";
import { parseEnabledShifts } from "@/lib/shifts";
import type { Schedule, BuiltSchedule } from "@/lib/types";

const DAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

// Helper: turn a row index into a human-readable "Day Shift" label plus
// the Date (used as the payload's `dateTime`). Mirrors the layout used
// by BuiltScheduleGrid — rows are laid out as (day * numShifts + shift).
interface ShiftSlot {
  key: string;           // stable option value
  label: string;         // "Mon · Morning"
  dateTime: Date;        // what we persist in `DateTime`
}

function computeShiftSlots(
  built: BuiltSchedule | null,
  enabledShifts: string[]
): ShiftSlot[] {
  if (!built || enabledShifts.length === 0) return [];
  const numShifts = enabledShifts.length;
  const numDays = Math.ceil((built.schedule?.length ?? 0) / numShifts);
  const startTs = built.first_weekday_datetime;
  const startDate: Date | null = startTs
    ? // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (startTs as any).toDate?.() ?? null
    : null;

  const slots: ShiftSlot[] = [];
  for (let d = 0; d < numDays; d++) {
    for (let s = 0; s < numShifts; s++) {
      const shiftName = enabledShifts[s];
      let label: string;
      let dt: Date;
      if (startDate instanceof Date) {
        dt = new Date(startDate);
        dt.setDate(startDate.getDate() + d);
        const day = DAY_LABELS[dt.getDay()];
        const date = dt.toISOString().slice(0, 10);
        label = `${day} ${date} · ${shiftName}`;
      } else {
        // No start timestamp yet — fall back to generic labels, use "now"
        // as the Date so we always have a valid value to persist.
        dt = new Date();
        label = `${DAY_LABELS[d % 7]} #${d + 1} · ${shiftName}`;
      }
      slots.push({ key: `${d}-${s}`, label, dateTime: dt });
    }
  }
  return slots;
}

export default function NewRequestClient() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { user } = useAuth();
  const { t } = useI18n();

  const [schedule, setSchedule] = useState<Schedule | null>(null);
  const [built, setBuilt] = useState<BuiltSchedule | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [targetUid, setTargetUid] = useState("");
  const [shiftKey, setShiftKey] = useState("");
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!id) return;
    try {
      const [s, b] = await Promise.all([
        getSchedule(id),
        getLatestBuiltSchedule(id),
      ]);
      if (!s) {
        setLoadError(t("requests.errorLoad"));
      } else {
        setSchedule(s);
        setBuilt(b);
      }
    } catch {
      setLoadError(t("requests.errorLoad"));
    } finally {
      setLoading(false);
    }
  }, [id, t]);

  useEffect(() => {
    load();
  }, [load]);

  const enabledShifts = parseEnabledShifts(
    schedule?.schedule_settings?.enabled_shifts
  );
  const shiftSlots = computeShiftSlots(built, enabledShifts);

  // Employees minus the current user — you can't swap with yourself.
  const swapCandidates = (schedule?.employees ?? []).filter((e) => {
    const uid = (e.user_ref as { id?: string } | null)?.id;
    const email = e.employee_email?.toLowerCase();
    if (uid && user?.uid && uid === user.uid) return false;
    if (email && user?.email && email === user.email.toLowerCase()) return false;
    return true;
  });

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!schedule || !user) return;
    if (!targetUid) {
      setFormError(t("requests.submitErrorTargetRequired"));
      return;
    }
    if (!shiftKey) {
      setFormError(t("requests.submitErrorShiftRequired"));
      return;
    }
    if (!reason.trim()) {
      setFormError(t("requests.submitErrorReasonRequired"));
      return;
    }
    const slot = shiftSlots.find((s) => s.key === shiftKey);
    if (!slot) {
      setFormError(t("requests.submitErrorShiftRequired"));
      return;
    }
    setSubmitting(true);
    setFormError(null);
    try {
      // The shift-change record carries the DateTime of the shift plus a
      // free-text Reason — we embed the target employee selection in the
      // reason so it surfaces in the inbox (the Flutter schema has no
      // target field). The structured target is stored via the
      // (existing) userId field.
      const targetEmp = swapCandidates.find((emp) => {
        const uid = (emp.user_ref as { id?: string } | null)?.id;
        return uid === targetUid || emp.employee_email === targetUid;
      });
      const reasonWithTarget =
        targetEmp
          ? `Swap with ${targetEmp.employee_name || targetEmp.employee_email}: ${reason.trim()}`
          : reason.trim();
      await createScheduleChangeRequest({
        scheduleId: schedule.id,
        userId: user.uid,
        reason: reasonWithTarget,
        dateTime: slot.dateTime,
      });
      router.push(`/schedules/${schedule.id}`);
    } catch {
      setFormError(t("requests.submitErrorGeneric"));
      setSubmitting(false);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="w-6 h-6 border-2 border-purple-600 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (loadError || !schedule) {
    return (
      <div className="space-y-4">
        <Link
          href={`/schedules/${id}`}
          className="text-sm text-purple-600 hover:underline"
        >
          {t("requests.backToInbox")}
        </Link>
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {loadError ?? t("requests.errorLoad")}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-lg">
      <Link
        href={`/schedules/${schedule.id}/requests`}
        className="text-sm text-purple-600 hover:underline"
      >
        {t("requests.backToInbox")}
      </Link>

      <div>
        <h1 className="text-2xl font-semibold">{t("requests.submitTitle")}</h1>
        <p className="text-sm text-gray-500 mt-1">
          {schedule.schedule_name}
        </p>
      </div>

      {swapCandidates.length === 0 ? (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
          {t("requests.submitNoEmployees")}
        </div>
      ) : shiftSlots.length === 0 ? (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
          {t("requests.submitNoShifts")}
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="space-y-5">
          <div>
            <label
              htmlFor="target"
              className="block text-sm font-medium text-gray-700 mb-1"
            >
              {t("requests.submitTarget")}
              <span className="text-red-500"> *</span>
            </label>
            <select
              id="target"
              value={targetUid}
              onChange={(e) => setTargetUid(e.target.value)}
              className="w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
            >
              <option value="">—</option>
              {swapCandidates.map((emp, idx) => {
                const uid =
                  (emp.user_ref as { id?: string } | null)?.id ??
                  emp.employee_email;
                return (
                  <option key={`${uid}-${idx}`} value={uid}>
                    {emp.employee_name || emp.employee_email || "(unnamed)"}
                  </option>
                );
              })}
            </select>
          </div>

          <div>
            <label
              htmlFor="shift"
              className="block text-sm font-medium text-gray-700 mb-1"
            >
              {t("requests.submitShift")}
              <span className="text-red-500"> *</span>
            </label>
            <select
              id="shift"
              value={shiftKey}
              onChange={(e) => setShiftKey(e.target.value)}
              className="w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
            >
              <option value="">—</option>
              {shiftSlots.map((slot) => (
                <option key={slot.key} value={slot.key}>
                  {slot.label}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label
              htmlFor="reason"
              className="block text-sm font-medium text-gray-700 mb-1"
            >
              {t("requests.submitReason")}
              <span className="text-red-500"> *</span>
            </label>
            <textarea
              id="reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={3}
              placeholder=""
              className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
            />
          </div>

          {formError && (
            <div
              role="alert"
              className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700"
            >
              {formError}
            </div>
          )}

          <div className="flex gap-3 pt-2">
            <button
              type="submit"
              disabled={submitting}
              className="rounded-lg bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {submitting
                ? t("requests.submitSubmitting")
                : t("requests.submitButton")}
            </button>
            <Link
              href={`/schedules/${schedule.id}`}
              className="rounded-lg border border-gray-200 px-4 py-2 text-sm text-gray-600 hover:bg-gray-50"
            >
              {t("requests.backToInbox")}
            </Link>
          </div>
        </form>
      )}
    </div>
  );
}

