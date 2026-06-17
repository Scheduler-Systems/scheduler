import { describe, it, expect } from "vitest";
import {
  PRIORITIES_ARRAY_LENGTH,
  cellKeyToArrayIndex,
  arrayIndexToCellKey,
  cellKeysToBoolArray,
  boolArrayToCellKeys,
} from "./priorities-mapping";

describe("priorities array ↔ cell-key mapping", () => {
  it("has canonical length 21 (7 days × 3 shifts)", () => {
    expect(PRIORITIES_ARRAY_LENGTH).toBe(21);
  });

  it("cellKeyToArrayIndex maps the 3 morning cells", () => {
    expect(cellKeyToArrayIndex("Sun|morning")).toBe(0);
    expect(cellKeyToArrayIndex("Mon|morning")).toBe(3);
    expect(cellKeyToArrayIndex("Sat|morning")).toBe(18);
  });

  it("cellKeyToArrayIndex handles noon + night for each day", () => {
    expect(cellKeyToArrayIndex("Sun|noon")).toBe(1);
    expect(cellKeyToArrayIndex("Sun|night")).toBe(2);
    expect(cellKeyToArrayIndex("Sat|night")).toBe(20);
  });

  it("also accepts 'afternoon' as an alias for 'noon'", () => {
    expect(cellKeyToArrayIndex("Sun|afternoon")).toBe(1);
    expect(cellKeyToArrayIndex("Wed|afternoon")).toBe(10);
  });

  it("returns -1 for unrecognized cell keys", () => {
    expect(cellKeyToArrayIndex("XYZ|morning")).toBe(-1);
    expect(cellKeyToArrayIndex("Mon|brunch")).toBe(-1);
    expect(cellKeyToArrayIndex("malformed")).toBe(-1);
  });

  it("arrayIndexToCellKey round-trips", () => {
    for (let i = 0; i < PRIORITIES_ARRAY_LENGTH; i++) {
      const key = arrayIndexToCellKey(i);
      expect(cellKeyToArrayIndex(key)).toBe(i);
    }
  });

  it("returns 'morning'/'noon'/'night' (not afternoon) from index", () => {
    expect(arrayIndexToCellKey(0)).toBe("Sun|morning");
    expect(arrayIndexToCellKey(1)).toBe("Sun|noon");
    expect(arrayIndexToCellKey(2)).toBe("Sun|night");
  });

  it("cellKeysToBoolArray produces a 21-bool array with matching positions true", () => {
    const arr = cellKeysToBoolArray(["Sun|morning", "Mon|night"]);
    expect(arr).toHaveLength(21);
    expect(arr[0]).toBe(true);
    expect(arr[5]).toBe(true);
    // Rest should be false
    expect(arr.filter((b) => b).length).toBe(2);
  });

  it("cellKeysToBoolArray ignores unknown keys", () => {
    const arr = cellKeysToBoolArray(["Sun|morning", "XYZ|morning"]);
    expect(arr[0]).toBe(true);
    expect(arr.filter((b) => b).length).toBe(1);
  });

  it("boolArrayToCellKeys is the inverse", () => {
    const arr = new Array(21).fill(false);
    arr[0] = true; // Sun|morning
    arr[5] = true; // Mon|night
    expect(boolArrayToCellKeys(arr)).toEqual(["Sun|morning", "Mon|night"]);
  });

  it("boolArrayToCellKeys tolerates short or long arrays", () => {
    expect(boolArrayToCellKeys([true])).toEqual(["Sun|morning"]);
    const tooLong = new Array(50).fill(false);
    tooLong[25] = true;
    expect(boolArrayToCellKeys(tooLong)).toEqual([]);
  });
});
