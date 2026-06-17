"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { getBuiltSchedules, getSchedule } from "@/lib/firestore";
import type { BuiltSchedule, Schedule } from "@/lib/types";

function formatTimestamp(ts: BuiltSchedule["time_created"]): string {
  if (!ts) return "";
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const maybeDate = (ts as any).toDate?.();
  if (maybeDate instanceof Date && !isNaN(maybeDate.getTime())) {
    return maybeDate.toLocaleString();
  }
  return "";
}

function formatRange(b: BuiltSchedule): string {
  if (b.first_weekday && b.last_weekday) {
    return `${b.first_weekday} – ${b.last_weekday}`;
  }
  return "";
}

export default function ArchivedClient() {
  const { id } = useParams<{ id: string }>();
  const [schedule, setSchedule] = useState<Schedule | null>(null);
  const [builds, setBuilds] = useState<BuiltSchedule[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!id) return;
    try {
      const [s, bs] = await Promise.all([
        getSchedule(id),
        getBuiltSchedules(id),
      ]);
      if (!s) {
        setError("Schedule not found.");
        return;
      }
      setSchedule(s);
      setBuilds(bs);
    } catch {
      setError("Failed to load archived schedules.");
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

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

  return (
    <div className="space-y-6">
      <Link
        href={`/schedules/${schedule.id}`}
        className="text-sm text-purple-600 hover:underline"
      >
        ← {schedule.schedule_name || "Schedule"}
      </Link>

      <header>
        <h1 className="text-2xl font-semibold text-gray-900">
          Archived schedules
        </h1>
        <p className="text-sm text-gray-500">
          All published builds for{" "}
          <span className="font-medium text-gray-700">
            {schedule.schedule_name}
          </span>
          , newest first.
        </p>
      </header>

      {builds.length === 0 ? (
        <div className="rounded-lg border border-gray-200 bg-gray-50 p-6 text-center text-sm text-gray-500">
          No schedules have been built yet.
        </div>
      ) : (
        <div className="rounded-md border border-gray-200 overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-3 py-2 text-left font-medium text-gray-600">
                  Built at
                </th>
                <th className="px-3 py-2 text-left font-medium text-gray-600">
                  Range
                </th>
                <th className="px-3 py-2 text-left font-medium text-gray-600">
                  Slots
                </th>
                <th className="px-3 py-2 text-left font-medium text-gray-600">
                  Priorities snapshot
                </th>
              </tr>
            </thead>
            <tbody>
              {builds.map((b) => (
                <tr key={b.id} className="border-t border-gray-100">
                  <td className="px-3 py-2 text-gray-700">
                    {formatTimestamp(b.time_created)}
                  </td>
                  <td className="px-3 py-2 text-gray-700">
                    {formatRange(b) || "—"}
                  </td>
                  <td className="px-3 py-2 text-gray-500">
                    {b.schedule?.length ?? 0} row{b.schedule?.length === 1 ? "" : "s"}
                  </td>
                  <td className="px-3 py-2 text-gray-500">
                    {b.current_priorities?.length ?? 0}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
