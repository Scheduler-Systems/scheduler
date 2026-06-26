import { describe, it, expect } from "vitest";
import { buildSchedule } from "./schedule-builder";

const workers = [
  { name: "Alice" },
  { name: "Bob" },
  { name: "Carol" },
  { name: "Dave" },
];

describe("buildSchedule", () => {
  it("returns an empty grid when there are no shifts", () => {
    const out = buildSchedule({
      employees: workers,
      enabledShifts: [],
      numDays: 7,
      numStations: 1,
    });
    expect(out.rows).toHaveLength(0);
  });

  it("returns an empty grid when there are no days", () => {
    const out = buildSchedule({
      employees: workers,
      enabledShifts: ["morning"],
      numDays: 0,
      numStations: 1,
    });
    expect(out.rows).toHaveLength(0);
  });

  it("produces exactly numDays × numShifts rows in day-major order", () => {
    const out = buildSchedule({
      employees: workers,
      enabledShifts: ["morning", "night"],
      numDays: 3,
      numStations: 1,
    });
    expect(out.rows).toHaveLength(3 * 2);
    // Day 0: morning, night | Day 1: morning, night | Day 2: morning, night
    expect(out.rows[0].stringList).toHaveLength(1);
    expect(out.rows[1].stringList).toHaveLength(1);
  });

  it("assigns numStations names per slot", () => {
    const out = buildSchedule({
      employees: workers,
      enabledShifts: ["morning"],
      numDays: 1,
      numStations: 3,
    });
    expect(out.rows).toHaveLength(1);
    expect(out.rows[0].stringList).toHaveLength(3);
  });

  it("cycles employees round-robin so distribution stays balanced", () => {
    const out = buildSchedule({
      employees: [{ name: "A" }, { name: "B" }, { name: "C" }],
      enabledShifts: ["morning", "night"],
      numDays: 2,
      numStations: 1,
    });
    // 4 slots total, 3 workers → A, B, C, A
    expect(out.rows.map((r) => r.stringList[0])).toEqual(["A", "B", "C", "A"]);
  });

  it("falls back to empty string placeholders when there are no employees", () => {
    const out = buildSchedule({
      employees: [],
      enabledShifts: ["morning"],
      numDays: 1,
      numStations: 2,
    });
    expect(out.rows[0].stringList).toEqual(["", ""]);
  });

  it("produces stable first/last weekday labels when start is provided", () => {
    const out = buildSchedule({
      employees: workers,
      enabledShifts: ["morning"],
      numDays: 7,
      numStations: 1,
      startDate: new Date("2026-05-03T00:00:00Z"), // Sunday
    });
    expect(out.firstWeekday).toBe("2026-05-03");
    expect(out.lastWeekday).toBe("2026-05-09");
  });

  it("omits date labels if no start date", () => {
    const out = buildSchedule({
      employees: workers,
      enabledShifts: ["morning"],
      numDays: 7,
      numStations: 1,
    });
    expect(out.firstWeekday).toBeNull();
    expect(out.lastWeekday).toBeNull();
  });

  describe("conflict detection", () => {
    it("reports no conflicts for a well-distributed build", () => {
      const out = buildSchedule({
        employees: workers,
        enabledShifts: ["morning", "night"],
        numDays: 3,
        numStations: 1,
      });
      expect(out.conflicts).toEqual([]);
    });

    it("flags a worker assigned to two shifts the same day", () => {
      // 1 worker, 2 shifts in 1 day → "Solo" lands in both.
      const out = buildSchedule({
        employees: [{ name: "Solo" }],
        enabledShifts: ["morning", "night"],
        numDays: 1,
        numStations: 1,
      });
      expect(out.conflicts).toHaveLength(1);
      expect(out.conflicts[0]).toMatchObject({
        dayIndex: 0,
        worker: "Solo",
      });
      expect(out.conflicts[0].shifts).toEqual(["morning", "night"]);
    });

    it("ignores empty-string placeholders as conflicts", () => {
      const out = buildSchedule({
        employees: [],
        enabledShifts: ["morning", "night"],
        numDays: 2,
        numStations: 1,
      });
      expect(out.conflicts).toEqual([]);
    });

    it("avoidSameDayConflicts skips a worker already on the same day", () => {
      // With [A, B] workers, 2 shifts × 1 day × 1 station:
      // Without the flag: cursor increments → A, B (no conflict, they differ)
      // With 2 workers only 1 shift but 2 stations:
      // Without flag: A, B. With flag: same.
      // Stronger test: 1 worker, 2 shifts → before: Solo, Solo.
      // With flag: Solo, "" (skipped).
      const out = buildSchedule({
        employees: [{ name: "Solo" }],
        enabledShifts: ["morning", "night"],
        numDays: 1,
        numStations: 1,
        avoidSameDayConflicts: true,
      });
      expect(out.rows[0].stringList).toEqual(["Solo"]);
      expect(out.rows[1].stringList).toEqual([""]);
      expect(out.conflicts).toEqual([]);
    });
  });

  describe("priority-aware assignment", () => {
    it("prefers a worker who marked the cell as priority over round-robin", () => {
      // Default round-robin would pick A first, but B priorities Sun|morning
      const out = buildSchedule({
        employees: [{ name: "Alice" }, { name: "Bob" }],
        enabledShifts: ["morning"],
        numDays: 1,
        numStations: 1,
        startDate: new Date("2026-05-03T00:00:00Z"), // Sunday
        priorities: {
          bob: new Set(["Sun|morning"]),
        },
      });
      expect(out.rows[0].stringList[0]).toBe("Bob");
    });

    it("matches priorities case-insensitively by name", () => {
      const out = buildSchedule({
        employees: [{ name: "Alice" }, { name: "Bob" }],
        enabledShifts: ["morning"],
        numDays: 1,
        numStations: 1,
        startDate: new Date("2026-05-03T00:00:00Z"),
        priorities: {
          BOB: new Set(["Sun|morning"]),
        },
      });
      expect(out.rows[0].stringList[0]).toBe("Bob");
    });

    it("among tied priority candidates, picks the one with fewest assignments (fairness)", () => {
      // Both B and C priority Mon|morning.
      // After day 0, one of them is assigned on Sun|morning. The other should be
      // preferred on Mon|morning.
      const out = buildSchedule({
        employees: [{ name: "Alice" }, { name: "Bob" }, { name: "Carol" }],
        enabledShifts: ["morning"],
        numDays: 2,
        numStations: 1,
        startDate: new Date("2026-05-03T00:00:00Z"),
        priorities: {
          bob: new Set(["Sun|morning", "Mon|morning"]),
          carol: new Set(["Mon|morning"]),
        },
      });
      expect(out.rows[0].stringList[0]).toBe("Bob");
      // Bob has 1 assignment, Carol has 0 — Carol wins Mon|morning
      expect(out.rows[1].stringList[0]).toBe("Carol");
    });

    it("falls back to fairness-based round-robin when no priority match", () => {
      // No priorities → pick the least-assigned worker. With all at 0,
      // the cursor order is preserved (same as plain round-robin).
      const out = buildSchedule({
        employees: [{ name: "A" }, { name: "B" }, { name: "C" }],
        enabledShifts: ["morning"],
        numDays: 3,
        numStations: 1,
        priorities: {},
      });
      expect(out.rows.map((r) => r.stringList[0])).toEqual(["A", "B", "C"]);
    });

    it("respects avoidSameDayConflicts for priority picks", () => {
      // Solo priorities both morning and night on Sun. With the flag on,
      // Solo gets morning (first slot), then night slot must be empty.
      const out = buildSchedule({
        employees: [{ name: "Solo" }, { name: "Other" }],
        enabledShifts: ["morning", "night"],
        numDays: 1,
        numStations: 1,
        startDate: new Date("2026-05-03T00:00:00Z"),
        avoidSameDayConflicts: true,
        priorities: {
          solo: new Set(["Sun|morning", "Sun|night"]),
        },
      });
      expect(out.rows[0].stringList[0]).toBe("Solo");
      // night slot: no priority candidate available (Solo is on same day);
      // falls through to Other
      expect(out.rows[1].stringList[0]).toBe("Other");
    });

    it("priorities ignored when the named worker is not on the roster", () => {
      const out = buildSchedule({
        employees: [{ name: "A" }, { name: "B" }],
        enabledShifts: ["morning"],
        numDays: 1,
        numStations: 1,
        startDate: new Date("2026-05-03T00:00:00Z"),
        priorities: {
          ghost: new Set(["Sun|morning"]), // not on roster
        },
      });
      expect(out.rows[0].stringList[0]).toBe("A");
    });

    it("honors a later-shift priority over an earlier-shift fairness fill (same day)", () => {
      // Two workers, 3 shifts/day, conflict-avoidance on. Jordan marked
      // Fri|afternoon as a priority. A naive fairness fill would place Jordan in
      // Fri|morning (least-assigned), then same-day avoidance would block his
      // afternoon priority. The builder must hold Jordan back from morning so
      // his explicit afternoon priority is honored.
      const out = buildSchedule({
        employees: [{ name: "Jordan" }, { name: "Alex" }],
        enabledShifts: ["morning", "afternoon", "night"],
        numDays: 7,
        numStations: 1,
        startDate: new Date("2026-06-28T00:00:00Z"), // Sunday -> Fri = day index 5
        avoidSameDayConflicts: true,
        priorities: {
          jordan: new Set(["Mon|morning", "Wed|morning", "Fri|afternoon"]),
        },
      });
      // Friday is day index 5; rows are day-major with 3 shifts/day.
      const friMorning = out.rows[5 * 3 + 0].stringList[0];
      const friAfternoon = out.rows[5 * 3 + 1].stringList[0];
      expect(friAfternoon).toBe("Jordan");
      expect(friMorning).not.toBe("Jordan");
      // The three explicit priorities are all honored.
      expect(out.rows[1 * 3 + 0].stringList[0]).toBe("Jordan"); // Mon|morning
      expect(out.rows[3 * 3 + 0].stringList[0]).toBe("Jordan"); // Wed|morning
    });

    it("handles trimmed whitespace in priority names", () => {
      const out = buildSchedule({
        employees: [{ name: "Alice" }, { name: "Bob" }],
        enabledShifts: ["morning"],
        numDays: 1,
        numStations: 1,
        startDate: new Date("2026-05-03T00:00:00Z"),
        priorities: {
          "  bob  ": new Set(["Sun|morning"]),
        },
      });
      expect(out.rows[0].stringList[0]).toBe("Bob");
    });
  });
});
