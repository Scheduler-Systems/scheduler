"use client";

import { useEffect, useState } from "react";
import { getLatestBuiltSchedule } from "@/lib/firestore";
import { parseEnabledShifts } from "@/lib/shifts";
import type { BuiltSchedule, Schedule } from "@/lib/types";

interface Props {
  schedule: Schedule;
}

function formatDate(dateStr: string): string {
  if (!dateStr) return "";
  // Firestore stores dates as "dd/mm/yyyy" or similar — attempt ISO parse first
  const d = new Date(dateStr);
  if (!isNaN(d.getTime())) return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  return dateStr;
}

export function BuiltScheduleGrid({ schedule }: Props) {
  const [built, setBuilt] = useState<BuiltSchedule | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getLatestBuiltSchedule(schedule.id)
      .then(setBuilt)
      .finally(() => setLoading(false));
  }, [schedule.id]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-sm text-gray-400 py-4">
        <div className="w-4 h-4 border-2 border-gray-300 border-t-transparent rounded-full animate-spin" />
        Loading published schedule…
      </div>
    );
  }

  if (!built || built.schedule.length === 0) {
    return (
      <div className="rounded-lg border border-gray-200 bg-gray-50 p-6 text-center text-sm text-gray-500">
        No published schedule yet.
      </div>
    );
  }

  // enabled_shifts is persisted as an OBJECT ({morning,afternoon,night}) by the
  // app's own createSchedule (Flutter data model), not the string[] the TS type
  // claims. Use the shared compat shim — treating the object as an array made
  // numShifts NaN → the published roster rendered zero rows.
  const shifts = parseEnabledShifts(schedule.schedule_settings?.enabled_shifts);
  const numShifts = Math.max(shifts.length, 1);
  const numDays = Math.ceil(built.schedule.length / numShifts);

  // Attempt to label rows (days)
  const dayLabels: string[] = [];
  const start = built.first_weekday_datetime?.toDate() ?? null;
  for (let d = 0; d < numDays; d++) {
    if (start) {
      const day = new Date(start);
      day.setDate(start.getDate() + d);
      dayLabels.push(day.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" }));
    } else {
      dayLabels.push(`Day ${d + 1}`);
    }
  }

  const weekLabel =
    built.first_weekday && built.last_weekday
      ? `${formatDate(built.first_weekday)} – ${formatDate(built.last_weekday)}`
      : "";

  return (
    <div className="space-y-2">
      {weekLabel && (
        <p className="text-sm text-gray-500">
          Week of {weekLabel}
        </p>
      )}
      <div className="overflow-x-auto rounded-lg border border-gray-200">
        <table className="min-w-full divide-y divide-gray-200 text-sm">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wide sticky left-0 bg-gray-50 min-w-[100px]">
                Day
              </th>
              {shifts.length > 0
                ? shifts.map((s) => (
                    <th key={s} className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">
                      {s}
                    </th>
                  ))
                : (
                    <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">
                      Assigned
                    </th>
                  )}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200 bg-white">
            {dayLabels.map((dayLabel, dayIdx) => (
              <tr key={dayIdx} className="hover:bg-gray-50">
                <td className="px-3 py-2 font-medium text-gray-700 sticky left-0 bg-white">
                  {dayLabel}
                </td>
                {(shifts.length > 0 ? shifts : [""]).map((_, shiftIdx) => {
                  const slot = built.schedule[dayIdx * numShifts + shiftIdx];
                  const names = slot?.stringList ?? [];
                  return (
                    <td key={shiftIdx} className="px-3 py-2 text-gray-600 align-top">
                      {names.length === 0 ? (
                        <span className="text-gray-300">—</span>
                      ) : (
                        <ul className="space-y-0.5">
                          {names.map((name, i) => (
                            <li key={i} className="text-xs">{name || "—"}</li>
                          ))}
                        </ul>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
