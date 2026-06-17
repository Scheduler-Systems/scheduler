import { describe, it, expect } from "vitest";
import { parseEnabledShifts, toEnabledShiftsWrite } from "./shifts";

describe("parseEnabledShifts (read compat)", () => {
  it("returns flat string[] when already a string array (Next.js Phase 5 shape)", () => {
    expect(parseEnabledShifts(["morning", "night"])).toEqual([
      "morning",
      "night",
    ]);
  });

  it("returns [] for null / undefined / missing", () => {
    expect(parseEnabledShifts(null)).toEqual([]);
    expect(parseEnabledShifts(undefined)).toEqual([]);
  });

  it("derives the list from Flutter's nested object shape", () => {
    const flutter = {
      morning: true,
      afternoon: false,
      night: true,
      morning_hours: "06-14",
      noon_hours: "",
      night_hours: "22-06",
    };
    // Preserves canonical ordering: morning, afternoon, night
    expect(parseEnabledShifts(flutter)).toEqual(["morning", "night"]);
  });

  it("treats missing booleans as false in Flutter shape", () => {
    expect(parseEnabledShifts({ morning: true })).toEqual(["morning"]);
    expect(parseEnabledShifts({})).toEqual([]);
  });

  it("filters out unknown string keys in the flat array", () => {
    expect(parseEnabledShifts(["morning", "lunch", "night"])).toEqual([
      "morning",
      "night",
    ]);
  });

  it("handles objects with non-boolean truthy values (e.g. strings) conservatively", () => {
    // Only strict `true` counts — avoids interpreting stray strings as enabled
    expect(
      parseEnabledShifts({ morning: "yes", afternoon: 1, night: true }),
    ).toEqual(["night"]);
  });
});

describe("toEnabledShiftsWrite (forward-compat write)", () => {
  it("emits a flat string[] suitable for the Next.js schema", () => {
    expect(toEnabledShiftsWrite(["morning", "night"])).toEqual([
      "morning",
      "night",
    ]);
  });

  it("de-duplicates and preserves canonical order", () => {
    expect(toEnabledShiftsWrite(["night", "morning", "morning"])).toEqual([
      "morning",
      "night",
    ]);
  });

  it("drops unknown shift names", () => {
    expect(toEnabledShiftsWrite(["morning", "lunch"])).toEqual(["morning"]);
  });
});
