import { describe, it, expect, vi } from "vitest";
import { builtScheduleToCsv, escapeCsvField, downloadCsv } from "./csv-export";
import type { BuiltSchedule } from "./types";

function row(names: string[]) {
  return { stringList: names };
}

describe("escapeCsvField", () => {
  it("leaves plain strings alone", () => {
    expect(escapeCsvField("hello")).toBe("hello");
  });
  it("quotes strings containing commas", () => {
    expect(escapeCsvField("a,b")).toBe('"a,b"');
  });
  it("escapes quotes by doubling them", () => {
    expect(escapeCsvField('say "hi"')).toBe('"say ""hi"""');
  });
  it("quotes strings containing newlines", () => {
    expect(escapeCsvField("line1\nline2")).toBe('"line1\nline2"');
  });
});

describe("builtScheduleToCsv", () => {
  it("emits header + rows in day-major order", () => {
    const built: Partial<BuiltSchedule> = {
      schedule: [
        row(["Alice"]),
        row(["Bob"]),
        row(["Carol"]),
        row(["Dave"]),
      ],
    };
    const csv = builtScheduleToCsv(built as BuiltSchedule, {
      days: ["Mon", "Tue"],
      shifts: ["morning", "night"],
    });
    const lines = csv.split("\n");
    expect(lines[0]).toBe("Day,Shift,Assigned");
    expect(lines.length).toBe(5); // header + 4 rows
    expect(lines[1]).toBe("Mon,morning,Alice");
    expect(lines[4]).toBe("Tue,night,Dave");
  });

  it("joins multiple stations with ' & '", () => {
    const built: Partial<BuiltSchedule> = {
      schedule: [row(["Alice", "Bob"])],
    };
    const csv = builtScheduleToCsv(built as BuiltSchedule, {
      days: ["Mon"],
      shifts: ["morning"],
    });
    expect(csv.split("\n")[1]).toBe("Mon,morning,Alice & Bob");
  });

  it("quotes cells with commas", () => {
    const built: Partial<BuiltSchedule> = {
      schedule: [row(["Doe, Jane"])],
    };
    const csv = builtScheduleToCsv(built as BuiltSchedule, {
      days: ["Mon"],
      shifts: ["morning"],
    });
    expect(csv.split("\n")[1]).toBe('Mon,morning,"Doe, Jane"');
  });

  it("emits just the header when the schedule is empty", () => {
    const csv = builtScheduleToCsv({ schedule: [] } as unknown as BuiltSchedule, {
      days: [],
      shifts: [],
    });
    expect(csv).toBe("Day,Shift,Assigned");
  });
});

describe("downloadCsv", () => {
  it("creates a Blob URL, appends+clicks a link, then revokes the URL", () => {
    const createObjectURL = vi.spyOn(URL, "createObjectURL").mockReturnValue(
      "blob:mock-url"
    );
    const revokeObjectURL = vi.spyOn(URL, "revokeObjectURL").mockImplementation(
      () => undefined
    );

    // We can't easily intercept createElement without breaking testing-library;
    // instead we just assert the side effects on URL + that the anchor
    // briefly exists under document.body.
    let seenAnchor: HTMLAnchorElement | null = null;
    const origAppendChild = document.body.appendChild.bind(document.body);
    const spy = vi
      .spyOn(document.body, "appendChild")
      .mockImplementation((node: Node) => {
        if ((node as HTMLElement).tagName === "A") {
          seenAnchor = node as HTMLAnchorElement;
        }
        return origAppendChild(node);
      });

    downloadCsv("roster.csv", "Day,Shift,Assigned\nMon,morning,Alice");

    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:mock-url");
    expect(seenAnchor).not.toBeNull();
    expect(seenAnchor!.download).toBe("roster.csv");
    expect(seenAnchor!.href).toContain("blob:mock-url");

    spy.mockRestore();
    createObjectURL.mockRestore();
    revokeObjectURL.mockRestore();
  });
});
