"use client";

import { useState, useEffect, useCallback } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/lib/auth-context";
import {
  getSchedule,
  getPrioritySubmission,
  getAllPrioritySubmissions,
  type PrioritySubmission,
} from "@/lib/firestore";
import { submitPriorities } from "@/lib/firestore-write";
import { parseEnabledShifts } from "@/lib/shifts";
import { friendlyAuthError } from "@/lib/auth-validation";
import type { Schedule, EmployeeDetails } from "@/lib/types";

const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

function cellKey(day: string, shift: string) {
  return `${day}|${shift}`;
}

function findCurrentUserRole(
  schedule: Schedule,
  email: string | null | undefined
): EmployeeDetails["role"] | null {
  if (!email) return null;
  const match = schedule.employees?.find(
    (e) => e.employee_email?.toLowerCase() === email.toLowerCase()
  );
  return match?.role ?? null;
}

export default function PrioritiesClient() {
  const { id } = useParams<{ id: string }>();
  const { user } = useAuth();

  const [schedule, setSchedule] = useState<Schedule | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [submitting, setSubmitting] = useState(false);
  const [submitMsg, setSubmitMsg] = useState<string | null>(null);

  const [allSubs, setAllSubs] = useState<PrioritySubmission[] | null>(null);

  const load = useCallback(async () => {
    if (!id || !user) return;
    try {
      const s = await getSchedule(id);
      if (!s) {
        setError("Schedule not found.");
        return;
      }
      setSchedule(s);

      const mine = await getPrioritySubmission(id, user.uid);
      if (mine) setSelected(new Set(mine.priorities));

      const role = findCurrentUserRole(s, user.email);
      if (role?.is_admin || role?.is_creator) {
        const all = await getAllPrioritySubmissions(id);
        setAllSubs(all);
      }
    } catch {
      setError("Failed to load priorities.");
    } finally {
      setLoading(false);
    }
  }, [id, user]);

  useEffect(() => {
    load();
  }, [load]);

  function toggle(day: string, shift: string) {
    const key = cellKey(day, shift);
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  async function handleSubmit() {
    if (!schedule || !user) return;
    setSubmitting(true);
    setSubmitMsg(null);
    try {
      await submitPriorities(
        schedule.id,
        user.uid,
        user.displayName ?? user.email ?? "Anonymous",
        Array.from(selected)
      );
      setSubmitMsg("Priorities submitted.");
    } catch (err) {
      setSubmitMsg(friendlyAuthError(err));
    } finally {
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

  const shifts = parseEnabledShifts(schedule.schedule_settings?.enabled_shifts);

  return (
    <div className="space-y-6">
      <Link
        href={`/schedules/${schedule.id}`}
        className="text-sm text-purple-600 hover:underline"
      >
        ← {schedule.schedule_name || "Schedule"}
      </Link>

      <header>
        <h1 className="text-2xl font-semibold text-gray-900">My priorities</h1>
        <p className="text-sm text-gray-500">
          Tap cells to mark shifts you&apos;d prefer to work. The admin uses
          these when building the next schedule.
        </p>
      </header>

      {shifts.length === 0 ? (
        <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          This schedule has no shifts configured yet. An admin needs to enable
          shifts in Settings before priorities can be collected.
        </div>
      ) : (
        <>
          <section className="rounded-lg border border-gray-200 bg-white p-3">
            <div className="overflow-x-auto">
              <table className="w-full border-separate border-spacing-0 text-sm">
                <thead>
                  <tr>
                    <th className="px-2 py-1 text-left font-medium text-gray-500" />
                    {DAYS.map((d) => (
                      <th
                        key={d}
                        className="min-w-[72px] border-b border-gray-200 px-2 py-1 text-center font-medium text-gray-700"
                      >
                        {d}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {shifts.map((s) => (
                    <tr key={s}>
                      <th
                        scope="row"
                        className="border-r border-gray-200 px-2 py-1 text-left font-medium text-gray-600 capitalize"
                      >
                        {s}
                      </th>
                      {DAYS.map((d) => {
                        const key = cellKey(d, s);
                        const picked = selected.has(key);
                        return (
                          <td
                            key={key}
                            onClick={() => toggle(d, s)}
                            className={[
                              "border-b border-r border-gray-100 px-2 py-2 text-center cursor-pointer select-none text-xs transition",
                              picked
                                ? "bg-purple-600 text-white"
                                : "bg-white text-gray-400 hover:bg-purple-50",
                            ].join(" ")}
                          >
                            {picked ? "✓" : "·"}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={handleSubmit}
              disabled={submitting}
              className="rounded-md bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50"
            >
              {submitting ? "Submitting…" : "Submit priorities"}
            </button>
            {submitMsg && (
              <span className="text-sm text-gray-600">{submitMsg}</span>
            )}
            <span className="ml-auto text-xs text-gray-500">
              {selected.size} shift{selected.size === 1 ? "" : "s"} selected
            </span>
          </div>
        </>
      )}

      {allSubs && (
        <section className="space-y-3">
          <h2 className="text-lg font-medium text-gray-900">
            All submissions ({allSubs.length})
          </h2>
          {allSubs.length === 0 ? (
            <p className="text-sm text-gray-500">
              No submissions yet. Share this page with your team.
            </p>
          ) : (
            <div className="rounded-md border border-gray-200 overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-3 py-2 text-left font-medium text-gray-600">
                      Name
                    </th>
                    <th className="px-3 py-2 text-left font-medium text-gray-600">
                      Picked shifts
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {allSubs.map((sub) => (
                    <tr key={sub.uid} className="border-t border-gray-100">
                      <td className="px-3 py-1.5 font-medium text-gray-800">
                        {sub.display_name}
                      </td>
                      <td className="px-3 py-1.5 text-gray-600">
                        {sub.priorities.length === 0
                          ? "—"
                          : sub.priorities.join(", ")}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
