"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { getSchedule } from "@/lib/firestore";
import { updateScheduleSettings } from "@/lib/firestore-write";
import { ShiftGrid } from "@/components/shift-grid";
import type { Schedule, SubmissionDeadline } from "@/lib/types";

const AVAILABLE_SHIFTS = ["morning", "afternoon", "night"] as const;
type ShiftKey = (typeof AVAILABLE_SHIFTS)[number];

const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

type DeadlineWeekday =
  | "SUNDAY"
  | "MONDAY"
  | "TUESDAY"
  | "WEDNESDAY"
  | "THURSDAY"
  | "FRIDAY"
  | "SATURDAY";

const DEADLINE_WEEKDAYS: { value: DeadlineWeekday; label: string }[] = [
  { value: "SUNDAY", label: "Sunday" },
  { value: "MONDAY", label: "Monday" },
  { value: "TUESDAY", label: "Tuesday" },
  { value: "WEDNESDAY", label: "Wednesday" },
  { value: "THURSDAY", label: "Thursday" },
  { value: "FRIDAY", label: "Friday" },
  { value: "SATURDAY", label: "Saturday" },
];

function readDeadline(d: unknown): SubmissionDeadline {
  const empty: SubmissionDeadline = {
    time: null,
    is_activated: false,
    weekday: "SUNDAY",
  };
  if (!d || typeof d !== "object") return empty;
  const asStruct = d as Partial<SubmissionDeadline>;
  if ("is_activated" in asStruct || "weekday" in asStruct) {
    return {
      time: asStruct.time ?? null,
      is_activated: asStruct.is_activated === true,
      weekday: asStruct.weekday ?? "SUNDAY",
    };
  }
  // Legacy: bare Timestamp stored directly
  return { ...empty, time: d as SubmissionDeadline["time"] };
}

// enabled_shifts is stored as a boolean struct { morning, afternoon, night,
// *_hours } (see createSchedule / updateScheduleSettings), matching the Flutter
// schema. Older data may carry a bare array of enabled keys. Normalize both to
// the set of enabled ShiftKeys so the settings page never crashes on load.
function readEnabledShifts(es: unknown): Set<ShiftKey> {
  const out = new Set<ShiftKey>();
  if (Array.isArray(es)) {
    es.forEach((k) => {
      if ((AVAILABLE_SHIFTS as readonly string[]).includes(k)) out.add(k as ShiftKey);
    });
    return out;
  }
  if (es && typeof es === "object") {
    const struct = es as Record<string, unknown>;
    for (const k of AVAILABLE_SHIFTS) {
      if (struct[k] === true) out.add(k);
    }
  }
  return out;
}

// Shift hours canonically live inside the enabled_shifts struct (morning_hours,
// noon_hours, night_hours), matching createSchedule/updateScheduleSettings.
// Fall back to the top level of schedule_settings for resilience to older data.
function readShiftHours(settings: unknown): {
  morning: string;
  noon: string;
  night: string;
} {
  const s =
    settings && typeof settings === "object"
      ? (settings as Record<string, unknown>)
      : {};
  const es =
    s.enabled_shifts && typeof s.enabled_shifts === "object" && !Array.isArray(s.enabled_shifts)
      ? (s.enabled_shifts as Record<string, unknown>)
      : {};
  const str = (v: unknown) => (typeof v === "string" ? v : "");
  const pick = (k: string) => str(es[k]) || str(s[k]);
  return {
    morning: pick("morning_hours"),
    noon: pick("noon_hours"),
    night: pick("night_hours"),
  };
}

function deadlineTimeToInputValue(
  t: SubmissionDeadline["time"]
): string {
  if (!t) return "";
  // Firestore Timestamp has .toDate(); ISO strings fall back to Date(str).
  const d =
    typeof (t as { toDate?: () => Date }).toDate === "function"
      ? (t as { toDate: () => Date }).toDate()
      : new Date(String(t));
  if (isNaN(d.getTime())) return "";
  // datetime-local expects "YYYY-MM-DDTHH:mm"
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export default function ScheduleSettingsClient() {
  const { id } = useParams<{ id: string }>();
  const [schedule, setSchedule] = useState<Schedule | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [enabledShifts, setEnabledShifts] = useState<Set<ShiftKey>>(new Set());
  const [numOfStations, setNumOfStations] = useState(1);
  const [morningHours, setMorningHours] = useState("");
  const [noonHours, setNoonHours] = useState("");
  const [nightHours, setNightHours] = useState("");

  const [deadlineActive, setDeadlineActive] = useState(false);
  const [deadlineWeekday, setDeadlineWeekday] =
    useState<DeadlineWeekday>("SUNDAY");
  const [deadlineTimeInput, setDeadlineTimeInput] = useState("");

  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!id) return;
    try {
      const s = await getSchedule(id);
      if (!s) {
        setError("Schedule not found.");
        return;
      }
      setSchedule(s);
      const settings = s.schedule_settings;
      setEnabledShifts(readEnabledShifts(settings?.enabled_shifts));
      setNumOfStations(settings?.num_of_stations ?? 1);
      const hours = readShiftHours(settings);
      setMorningHours(hours.morning);
      setNoonHours(hours.noon);
      setNightHours(hours.night);
      const deadline = readDeadline(settings?.submission_deadline);
      setDeadlineActive(deadline.is_activated);
      setDeadlineWeekday(
        (deadline.weekday as DeadlineWeekday) || "SUNDAY"
      );
      setDeadlineTimeInput(deadlineTimeToInputValue(deadline.time));
    } catch {
      setError("Failed to load schedule.");
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  function toggleShift(shift: ShiftKey) {
    setEnabledShifts((prev) => {
      const next = new Set(prev);
      if (next.has(shift)) next.delete(shift);
      else next.add(shift);
      return next;
    });
  }

  async function handleSave() {
    if (!schedule) return;
    setSaving(true);
    setSaveMsg(null);
    try {
      await updateScheduleSettings(schedule.id, {
        enabled_shifts: Array.from(enabledShifts),
        num_of_stations: numOfStations,
        morning_hours: morningHours,
        noon_hours: noonHours,
        night_hours: nightHours,
        submission_deadline: {
          is_activated: deadlineActive,
          weekday: deadlineWeekday,
          time: deadlineTimeInput
            ? new Date(deadlineTimeInput).toISOString()
            : null,
        },
      });
      setSaveMsg("Saved.");
    } catch {
      setSaveMsg("Failed to save. Please try again.");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="w-6 h-6 border-2 border-purple-600 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (error || !schedule) {
    return (
      <div className="space-y-4">
        <Link href="/schedules" className="text-sm text-purple-600 hover:underline">
          ← Back to Schedules
        </Link>
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {error ?? "Schedule not found."}
        </div>
      </div>
    );
  }

  const activeShifts = AVAILABLE_SHIFTS.filter((s) => enabledShifts.has(s));

  return (
    <div className="space-y-6">
      <Link
        href={`/schedules/${schedule.id}`}
        className="text-sm text-purple-600 hover:underline"
      >
        ← {schedule.schedule_name || "Schedule"}
      </Link>

      <header>
        <h1 className="text-2xl font-semibold text-gray-900">Schedule settings</h1>
        <p className="text-sm text-gray-500">
          Configure enabled shifts, station count, and shift hours for{" "}
          <span className="font-medium text-gray-700">
            {schedule.schedule_name}
          </span>
          .
        </p>
      </header>

      <section className="rounded-lg border border-gray-200 bg-white p-5 space-y-4">
        <h2 className="text-sm font-semibold text-gray-900">Enabled shifts</h2>
        <div className="flex flex-wrap gap-2">
          {AVAILABLE_SHIFTS.map((shift) => {
            const active = enabledShifts.has(shift);
            return (
              <button
                key={shift}
                type="button"
                onClick={() => toggleShift(shift)}
                className={[
                  "rounded-full border px-3 py-1 text-sm capitalize transition",
                  active
                    ? "border-purple-600 bg-purple-600 text-white"
                    : "border-gray-300 bg-white text-gray-700 hover:bg-gray-50",
                ].join(" ")}
              >
                {shift}
              </button>
            );
          })}
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 pt-2">
          <label className="space-y-1 text-sm">
            <span className="text-gray-700">Morning hours</span>
            <input
              value={morningHours}
              onChange={(e) => setMorningHours(e.target.value)}
              placeholder="e.g. 06:00–14:00"
              className="w-full rounded-lg border border-gray-300 px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
            />
          </label>
          <label className="space-y-1 text-sm">
            <span className="text-gray-700">Noon / afternoon hours</span>
            <input
              value={noonHours}
              onChange={(e) => setNoonHours(e.target.value)}
              placeholder="e.g. 14:00–22:00"
              className="w-full rounded-lg border border-gray-300 px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
            />
          </label>
          <label className="space-y-1 text-sm">
            <span className="text-gray-700">Night hours</span>
            <input
              value={nightHours}
              onChange={(e) => setNightHours(e.target.value)}
              placeholder="e.g. 22:00–06:00"
              className="w-full rounded-lg border border-gray-300 px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
            />
          </label>
        </div>
      </section>

      <section className="rounded-lg border border-gray-200 bg-white p-5 space-y-3">
        <h2 className="text-sm font-semibold text-gray-900">Stations</h2>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => setNumOfStations((n) => Math.max(1, n - 1))}
            className="rounded-lg border border-gray-300 px-3 py-1 text-sm hover:bg-gray-50"
          >
            −
          </button>
          <span className="min-w-[2ch] text-center text-lg font-medium text-gray-900">
            {numOfStations}
          </span>
          <button
            type="button"
            onClick={() => setNumOfStations((n) => n + 1)}
            className="rounded-lg border border-gray-300 px-3 py-1 text-sm hover:bg-gray-50"
          >
            +
          </button>
          <span className="text-sm text-gray-500">concurrent station(s) per shift</span>
        </div>
      </section>

      <section className="rounded-lg border border-gray-200 bg-white p-5 space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-900">
            Priority submission deadline
          </h2>
          <label className="inline-flex items-center gap-2 text-sm text-gray-700">
            <input
              type="checkbox"
              checked={deadlineActive}
              onChange={(e) => setDeadlineActive(e.target.checked)}
            />
            Enforce
          </label>
        </div>
        <p className="text-xs text-gray-500">
          Block employees from submitting priorities once the selected weekday
          + time has passed. Matches the Flutter app&apos;s submission_deadline
          struct.
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-1">
          <label className="space-y-1 text-sm">
            <span className="text-gray-700">Weekday</span>
            <select
              value={deadlineWeekday}
              onChange={(e) =>
                setDeadlineWeekday(e.target.value as DeadlineWeekday)
              }
              disabled={!deadlineActive}
              className="w-full rounded-lg border border-gray-300 px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500 disabled:opacity-50"
            >
              {DEADLINE_WEEKDAYS.map((w) => (
                <option key={w.value} value={w.value}>
                  {w.label}
                </option>
              ))}
            </select>
          </label>
          <label className="space-y-1 text-sm">
            <span className="text-gray-700">Time</span>
            <input
              type="datetime-local"
              value={deadlineTimeInput}
              onChange={(e) => setDeadlineTimeInput(e.target.value)}
              disabled={!deadlineActive}
              className="w-full rounded-lg border border-gray-300 px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500 disabled:opacity-50"
            />
          </label>
        </div>
      </section>

      <section className="rounded-lg border border-gray-200 bg-white p-5 space-y-3">
        <h2 className="text-sm font-semibold text-gray-900">Preview</h2>
        <ShiftGrid days={DAYS} shifts={activeShifts} readOnly />
      </section>

      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={handleSave}
          disabled={saving}
          className="rounded-lg bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50"
        >
          {saving ? "Saving…" : "Save settings"}
        </button>
        {saveMsg && <span className="text-sm text-gray-600">{saveMsg}</span>}
      </div>
    </div>
  );
}
