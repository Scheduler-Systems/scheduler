// Cross-platform priorities schema glue.
//
// Flutter writes `priorities_private: bool[21]` onto
// `users/{uid}/schedules_involved/{scheduleId}` — a fixed-length array where
// each index corresponds to a specific (weekday, shift) cell. The Next.js
// surface uses human-readable cell keys like "Sun|morning". This module is
// the two-way translator so both apps can read each other's writes.
//
// Array index formula: index = dayIndex * 3 + shiftIndex
//   where dayIndex:  Sun=0, Mon=1, Tue=2, Wed=3, Thu=4, Fri=5, Sat=6
//   and   shiftIndex: morning=0, afternoon=1, night=2
//
// The middle shift round-trips back to "afternoon" — the canonical label the
// Next.js surface uses everywhere (`CANONICAL_SHIFTS` in shifts.ts, the
// priorities grid cells, and the schedule builder's cell keys). Emitting "noon"
// here previously broke selected-state restore and priority matching, because a
// user's "Fri|afternoon" pick round-tripped through the bool array as
// "Fri|noon" and no longer matched the grid/builder cell key. "noon" is still
// ACCEPTED on input as an alias (see shiftIndex) for any legacy/Flutter writer
// that uses it.

export const PRIORITIES_ARRAY_LENGTH = 21;

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"] as const;
type Weekday = (typeof WEEKDAYS)[number];

// Canonical shift labels (used when converting index → key). The middle shift is
// "afternoon" to match shifts.ts CANONICAL_SHIFTS, the priorities grid, and the
// schedule builder. "noon" remains an accepted INPUT alias (see shiftIndex).
const SHIFTS = ["morning", "afternoon", "night"] as const;
type Shift = (typeof SHIFTS)[number];

function dayIndex(d: string): number {
  return WEEKDAYS.indexOf(d as Weekday);
}

function shiftIndex(s: string): number {
  if (s === "morning") return 0;
  if (s === "noon" || s === "afternoon") return 1;
  if (s === "night") return 2;
  return -1;
}

export function cellKeyToArrayIndex(cellKey: string): number {
  const parts = cellKey.split("|");
  if (parts.length !== 2) return -1;
  const [day, shift] = parts;
  const di = dayIndex(day);
  const si = shiftIndex(shift);
  if (di < 0 || si < 0) return -1;
  return di * 3 + si;
}

export function arrayIndexToCellKey(index: number): string {
  if (index < 0 || index >= PRIORITIES_ARRAY_LENGTH) return "";
  const day: Weekday = WEEKDAYS[Math.floor(index / 3)];
  const shift: Shift = SHIFTS[index % 3];
  return `${day}|${shift}`;
}

export function cellKeysToBoolArray(cellKeys: readonly string[]): boolean[] {
  const arr = new Array<boolean>(PRIORITIES_ARRAY_LENGTH).fill(false);
  for (const key of cellKeys) {
    const idx = cellKeyToArrayIndex(key);
    if (idx >= 0) arr[idx] = true;
  }
  return arr;
}

export function boolArrayToCellKeys(arr: readonly boolean[]): string[] {
  const out: string[] = [];
  for (let i = 0; i < arr.length; i++) {
    if (i >= PRIORITIES_ARRAY_LENGTH) break;
    if (arr[i]) out.push(arrayIndexToCellKey(i));
  }
  return out;
}
