// enabled_shifts compat shim.
//
// Flutter writes a nested object:   { morning: bool, afternoon: bool, night: bool, *_hours: string }
// Next.js (Phase 5+) writes flat:   string[]  e.g. ["morning", "night"]
//
// Both apps read the same schedules/<id> doc, so the reader has to accept either
// shape. Writes from Next.js stay flat until Phase 8+ can migrate the schema.

export const CANONICAL_SHIFTS = ["morning", "afternoon", "night"] as const;
export type CanonicalShift = (typeof CANONICAL_SHIFTS)[number];

const CANONICAL_SET = new Set<string>(CANONICAL_SHIFTS);

export function parseEnabledShifts(raw: unknown): CanonicalShift[] {
  if (Array.isArray(raw)) {
    const seen = new Set<CanonicalShift>();
    for (const v of raw) {
      if (typeof v === "string" && CANONICAL_SET.has(v)) {
        seen.add(v as CanonicalShift);
      }
    }
    return CANONICAL_SHIFTS.filter((s) => seen.has(s));
  }

  if (raw && typeof raw === "object") {
    const obj = raw as Record<string, unknown>;
    return CANONICAL_SHIFTS.filter((s) => obj[s] === true);
  }

  return [];
}

export function toEnabledShiftsWrite(
  shifts: readonly string[],
): CanonicalShift[] {
  const seen = new Set<CanonicalShift>();
  for (const s of shifts) {
    if (CANONICAL_SET.has(s)) seen.add(s as CanonicalShift);
  }
  return CANONICAL_SHIFTS.filter((s) => seen.has(s));
}
