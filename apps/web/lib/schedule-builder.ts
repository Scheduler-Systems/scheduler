// Priority-aware schedule builder with same-day conflict avoidance and fairness.
//
// Pick order for each slot:
//   1. Workers who marked this exact (weekday|shift) cell as priority AND
//      (if avoidSameDayConflicts) aren't already on that day. Among these,
//      the one with the fewest assignments so far wins.
//   2. Otherwise, fairness-based round-robin: least-assigned worker who isn't
//      already on the day (when the flag is set), tie-break on cursor order.
//
// Produces a ScheduleRow[] in the day-major layout the Flutter app expects:
// rows[dayIdx * numShifts + shiftIdx].stringList = names assigned to that slot.

import type { ScheduleRow } from "./types";

export interface BuilderEmployee {
  name: string;
}

export type PriorityMap = Record<string, Set<string>>;

export interface BuildScheduleInput {
  employees: readonly BuilderEmployee[];
  enabledShifts: readonly string[];
  numDays: number;
  numStations: number;
  startDate?: Date;
  avoidSameDayConflicts?: boolean;
  priorities?: PriorityMap;
}

export interface ScheduleConflict {
  dayIndex: number;
  worker: string;
  shifts: string[];
}

export interface BuildScheduleOutput {
  rows: ScheduleRow[];
  firstWeekday: string | null;
  lastWeekday: string | null;
  conflicts: ScheduleConflict[];
}

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"] as const;

function isoDate(d: Date): string {
  const y = d.getUTCFullYear();
  const m = String(d.getUTCMonth() + 1).padStart(2, "0");
  const day = String(d.getUTCDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function normName(s: string): string {
  return s.trim().toLowerCase();
}

function normalizePriorities(priorities: PriorityMap | undefined): PriorityMap {
  if (!priorities) return {};
  const out: PriorityMap = {};
  for (const [k, v] of Object.entries(priorities)) {
    out[normName(k)] = v;
  }
  return out;
}

export function buildSchedule(input: BuildScheduleInput): BuildScheduleOutput {
  const {
    employees,
    enabledShifts,
    numDays,
    numStations,
    startDate,
    avoidSameDayConflicts = false,
    priorities,
  } = input;

  if (numDays <= 0 || enabledShifts.length === 0) {
    return { rows: [], firstWeekday: null, lastWeekday: null, conflicts: [] };
  }

  const normalizedPriorities = normalizePriorities(priorities);
  const startWeekday = startDate ? startDate.getUTCDay() : 0;
  const assignments = new Map<number, number>();
  const rows: ScheduleRow[] = [];
  let cursor = 0;

  function relativeOrder(a: number, b: number): number {
    return (
      ((a - cursor + employees.length) % employees.length) -
      ((b - cursor + employees.length) % employees.length)
    );
  }

  function pickIndex(
    cellKey: string,
    dayAssigned: Set<string>
  ): number | null {
    if (employees.length === 0) return null;

    // 1. Priority candidates: workers who marked this cell AND are eligible
    const priorityIdxs: number[] = [];
    for (let i = 0; i < employees.length; i++) {
      const cell = normalizedPriorities[normName(employees[i].name)];
      if (!cell || !cell.has(cellKey)) continue;
      if (avoidSameDayConflicts && dayAssigned.has(employees[i].name)) continue;
      priorityIdxs.push(i);
    }
    if (priorityIdxs.length > 0) {
      priorityIdxs.sort((a, b) => {
        const ca = assignments.get(a) ?? 0;
        const cb = assignments.get(b) ?? 0;
        if (ca !== cb) return ca - cb;
        return relativeOrder(a, b);
      });
      return priorityIdxs[0];
    }

    // 2. Fairness fallback: least-assigned eligible worker,
    // tie-break on cursor-relative order.
    const candidateIdxs: number[] = [];
    for (let offset = 0; offset < employees.length; offset++) {
      const i = (cursor + offset) % employees.length;
      if (avoidSameDayConflicts && dayAssigned.has(employees[i].name)) continue;
      candidateIdxs.push(i);
    }
    if (candidateIdxs.length === 0) return null;
    candidateIdxs.sort((a, b) => {
      const ca = assignments.get(a) ?? 0;
      const cb = assignments.get(b) ?? 0;
      if (ca !== cb) return ca - cb;
      return relativeOrder(a, b);
    });
    return candidateIdxs[0];
  }

  for (let d = 0; d < numDays; d++) {
    const weekday = WEEKDAYS[(startWeekday + d) % 7];
    const dayAssigned = new Set<string>();
    for (let s = 0; s < enabledShifts.length; s++) {
      const cellKey = `${weekday}|${enabledShifts[s]}`;
      const stringList: string[] = [];
      for (let k = 0; k < numStations; k++) {
        const idx = pickIndex(cellKey, dayAssigned);
        if (idx === null) {
          stringList.push("");
          continue;
        }
        const pick = employees[idx].name;
        stringList.push(pick);
        dayAssigned.add(pick);
        assignments.set(idx, (assignments.get(idx) ?? 0) + 1);
        cursor = (idx + 1) % employees.length;
      }
      rows.push({ stringList });
    }
  }

  let first: string | null = null;
  let last: string | null = null;
  if (startDate) {
    first = isoDate(startDate);
    const end = new Date(startDate);
    end.setUTCDate(end.getUTCDate() + (numDays - 1));
    last = isoDate(end);
  }

  const conflicts: ScheduleConflict[] = [];
  const numShifts = enabledShifts.length;
  for (let d = 0; d < numDays; d++) {
    const seen = new Map<string, string[]>();
    for (let s = 0; s < numShifts; s++) {
      const row = rows[d * numShifts + s];
      for (const name of row.stringList) {
        if (!name) continue;
        const shifts = seen.get(name);
        if (shifts) {
          if (!shifts.includes(enabledShifts[s])) shifts.push(enabledShifts[s]);
        } else {
          seen.set(name, [enabledShifts[s]]);
        }
      }
    }
    for (const [worker, shifts] of seen) {
      if (shifts.length > 1) {
        conflicts.push({ dayIndex: d, worker, shifts });
      }
    }
  }

  return { rows, firstWeekday: first, lastWeekday: last, conflicts };
}
