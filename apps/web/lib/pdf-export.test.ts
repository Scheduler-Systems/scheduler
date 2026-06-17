import { describe, it, expect, vi, beforeEach } from "vitest";
import type { BuiltSchedule, Schedule } from "./types";

// Capture the options jspdf-autotable is called with so we can assert on them.
// We mock both jspdf (the class) and jspdf-autotable (default fn). Keep
// hoisted mocks so the dynamic-imports inside the export helper land on them.
const autoTableMock = vi.fn();

const setFontSize = vi.fn();
const text = vi.fn();
const output = vi.fn(() => new Blob(["%PDF-1.7"], { type: "application/pdf" }));
const getNumberOfPages = vi.fn(() => 1);
const setPage = vi.fn();
const internal = { pageSize: { getWidth: () => 595, getHeight: () => 842 } };

const jsPDFInstance = {
  setFontSize,
  text,
  output,
  getNumberOfPages,
  setPage,
  internal,
};

// jsPDF is used as `new JsPDF(...)` — provide a plain-function class so the
// `new` call returns our shared instance. vi.fn() mocks can't be used with
// `new` (internal spy object).
function JsPDFMock(this: typeof jsPDFInstance) {
  Object.assign(this, jsPDFInstance);
}
vi.mock("jspdf", () => ({
  default: JsPDFMock,
  jsPDF: JsPDFMock,
}));

vi.mock("jspdf-autotable", () => ({
  default: (...args: unknown[]) => autoTableMock(...args),
}));

// Import AFTER mocks are registered so the lazy dynamic-import inside
// exportBuiltScheduleToPdf picks them up.
const { exportBuiltScheduleToPdf, getPdfFilename, getPdfTitle } = await import("./pdf-export");

function makeSchedule(overrides: Partial<Schedule> = {}): Schedule {
  return {
    id: "sid1",
    schedule_name: "Q2 Roster",
    employees: [],
    current_priorities: [],
    sid: "",
    next_schedule: [],
    schedule_settings: {
      enabled_shifts: ["morning", "night"],
      num_of_stations: 1,
      submission_deadline: null,
    },
    ...overrides,
  };
}

function makeBuilt(overrides: Partial<BuiltSchedule> = {}): BuiltSchedule {
  return {
    id: "b1",
    schedule: [
      { stringList: ["Alice"] },
      { stringList: ["Bob"] },
      { stringList: ["Carol"] },
      { stringList: ["Dave"] },
    ],
    first_weekday: "2026-05-03",
    last_weekday: "2026-05-04",
    first_weekday_datetime: null,
    last_weekday_datetime: null,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    time_created: null as any,
    current_priorities: [],
    ...overrides,
  };
}

describe("exportBuiltScheduleToPdf", () => {
  beforeEach(() => {
    autoTableMock.mockReset();
    setFontSize.mockClear();
    text.mockClear();
    output.mockClear();
    getNumberOfPages.mockClear();
    setPage.mockClear();
    output.mockReturnValue(
      new Blob(["%PDF-1.7"], { type: "application/pdf" }),
    );
    getNumberOfPages.mockReturnValue(1);
  });

  it("returns a Blob of application/pdf type", async () => {
    const blob = await exportBuiltScheduleToPdf(makeSchedule(), makeBuilt());
    expect(blob).toBeInstanceOf(Blob);
    expect(blob.type).toBe("application/pdf");
  });

  it("passes the canonical header row to autoTable", async () => {
    await exportBuiltScheduleToPdf(makeSchedule(), makeBuilt());
    expect(autoTableMock).toHaveBeenCalledTimes(1);
    const [, options] = autoTableMock.mock.calls.at(-1) as [
      unknown,
      { head: unknown[][] },
    ];
    // Expected column order: Shift, Day, Employee, Start, End, Priority
    expect(options.head).toEqual([
      ["Shift", "Day", "Employee", "Start", "End", "Priority"],
    ]);
  });

  it("does not throw when the built schedule is empty", async () => {
    const built = makeBuilt({ schedule: [] });
    await expect(
      exportBuiltScheduleToPdf(makeSchedule(), built),
    ).resolves.toBeInstanceOf(Blob);
    // autoTable still called, just with an empty body
    expect(autoTableMock).toHaveBeenCalledTimes(1);
    const [, options] = autoTableMock.mock.calls.at(-1) as [
      unknown,
      { body: unknown[] },
    ];
    expect(options.body).toEqual([]);
  });

  it("writes the schedule name + date range into the title", async () => {
    await exportBuiltScheduleToPdf(
      makeSchedule({ schedule_name: "Summer Team" }),
      makeBuilt({ first_weekday: "2026-05-03", last_weekday: "2026-05-09" }),
    );
    const titleCall = text.mock.calls.find(
      (call) =>
        typeof call[0] === "string" && (call[0] as string).includes("Summer Team"),
    );
    expect(titleCall).toBeDefined();
    expect(titleCall![0]).toContain("Summer Team");
    expect(titleCall![0]).toContain("Schedule");
    expect(titleCall![0]).toContain("2026-05-03");
    expect(titleCall![0]).toContain("2026-05-09");
  });

  it("renders a page-number + generation-timestamp footer on each page", async () => {
    getNumberOfPages.mockReturnValue(2);
    await exportBuiltScheduleToPdf(makeSchedule(), makeBuilt());
    // setPage called for each page to draw the footer
    expect(setPage).toHaveBeenCalledWith(1);
    expect(setPage).toHaveBeenCalledWith(2);
    const footerCalls = text.mock.calls.filter(
      (call) =>
        typeof call[0] === "string" &&
        /Page\s+\d+\s+of\s+\d+/i.test(call[0] as string),
    );
    expect(footerCalls.length).toBeGreaterThanOrEqual(2);
    // Must also render the generated-at timestamp string somewhere
    const genCall = text.mock.calls.find(
      (call) =>
        typeof call[0] === "string" &&
        /Generated/i.test(call[0] as string),
    );
    expect(genCall).toBeDefined();
  });
});

describe("getPdfFilename", () => {
  it("uses the schedule name in the filename", () => {
    const name = getPdfFilename(
      // Partial is fine — only schedule_name is read.
      { schedule_name: "Q2 Roster" } as Schedule,
    );
    expect(name).toMatch(/^Q2_Roster.*\.pdf$/);
  });

  it("sanitizes unsafe characters", () => {
    const name = getPdfFilename(
      { schedule_name: "Team / Week: 21?" } as Schedule,
    );
    // Forward-slashes, colons, question marks replaced with underscores
    expect(name).not.toMatch(/[\\/:?]/);
    expect(name.endsWith(".pdf")).toBe(true);
  });

  it("falls back when schedule_name is blank", () => {
    const name = getPdfFilename({ schedule_name: "" } as Schedule);
    expect(name).toMatch(/schedule.*\.pdf$/i);
  });

  it("trims leading and trailing whitespace from schedule_name", () => {
    const name = getPdfFilename({ schedule_name: "  My Roster  " } as Schedule);
    expect(name.startsWith("My_Roster")).toBe(true);
  });

  it("falls back to 'schedule' when only special characters remain after sanitization", () => {
    const name = getPdfFilename({ schedule_name: "___" } as Schedule);
    expect(name.startsWith("schedule")).toBe(true);
  });
});

describe("getPdfTitle", () => {
  it("defaults to 'Untitled Schedule' when schedule_name is blank", () => {
    const title = getPdfTitle(
      makeSchedule({ schedule_name: "" }),
      makeBuilt(),
    );
    expect(title).toContain("Untitled");
    expect(title).toContain("Schedule");
  });

  it("omits date range when neither first nor last weekday is set", () => {
    const title = getPdfTitle(
      makeSchedule({ schedule_name: "My Roster" }),
      makeBuilt({ first_weekday: "", last_weekday: "" }),
    );
    expect(title).toBe("My Roster Schedule");
    expect(title).not.toContain("·");
  });

  it("includes only first weekday when last is blank", () => {
    const title = getPdfTitle(
      makeSchedule(),
      makeBuilt({ first_weekday: "2026-05-03", last_weekday: "" }),
    );
    expect(title).toContain("2026-05-03");
  });

  it("includes only last weekday when first is blank", () => {
    const title = getPdfTitle(
      makeSchedule(),
      makeBuilt({ first_weekday: "", last_weekday: "2026-05-09" }),
    );
    expect(title).toContain("2026-05-09");
  });
});

describe("formatDay (via exportBuiltScheduleToPdf)", () => {
  it("uses ISO date format when first_weekday_datetime has a valid toDate()", async () => {
    const built = makeBuilt({
      first_weekday_datetime: {
        toDate: () => new Date("2026-05-03T00:00:00Z"),
      } as never,
    });
    await exportBuiltScheduleToPdf(makeSchedule(), built);
    const [, opts] = autoTableMock.mock.calls.at(-1) as [
      unknown,
      { body: string[][] },
    ];
    // Day column of first row should be ISO date from toDate()
    expect(opts.body[0][1]).toBe("2026-05-03");
    expect(opts.body[2][1]).toBe("2026-05-04"); // second day
  });
});

describe("buildPdfRows edge cases (via exportBuiltScheduleToPdf)", () => {
  it("handles null schedule_settings (no enabled_shifts)", async () => {
    const schedule = makeSchedule({ schedule_settings: null });
    await exportBuiltScheduleToPdf(schedule, makeBuilt());
    const [, opts] = autoTableMock.mock.calls.at(-1) as [
      unknown,
      { body: string[][] },
    ];
    // numShifts = Math.max(0, 1) = 1 — rows still render
    expect(opts.body.length).toBeGreaterThan(0);
  });

  it("renders empty placeholder row when no employees assigned to a cell", async () => {
    const built = makeBuilt({
      schedule: [
        { stringList: [] },
        { stringList: ["Bob"] },
        { stringList: [] },
        { stringList: ["Dave"] },
      ],
    });
    await exportBuiltScheduleToPdf(makeSchedule(), built);
    const [, opts] = autoTableMock.mock.calls.at(-1) as [
      unknown,
      { body: string[][] },
    ];
    // First row has empty employee name (placeholder row)
    expect(opts.body[0][2]).toBe("");
    // Second row has Bob
    expect(opts.body[1][2]).toBe("Bob");
  });

  it("produces multiple rows per cell when multiple workers are assigned", async () => {
    const built = makeBuilt({
      schedule: [
        { stringList: ["Alice", "Bob"] },
        { stringList: ["Carol"] },
      ],
    });
    const schedule = makeSchedule({
      schedule_settings: {
        enabled_shifts: ["morning"],
        num_of_stations: 1,
        submission_deadline: null,
      },
    });
    await exportBuiltScheduleToPdf(schedule, built);
    const [, opts] = autoTableMock.mock.calls.at(-1) as [
      unknown,
      { body: string[][] },
    ];
    // 2 days x 1 shift = 2*1=2 schedule cells, first cell has 2 workers
    // Day 0: Alice (row 0), Bob (row 1) — same shift, same day
    expect(opts.body[0][2]).toBe("Alice");
    expect(opts.body[1][2]).toBe("Bob");
    expect(opts.body[0][0]).toBe("morning");
    expect(opts.body[1][0]).toBe("morning");
    expect(opts.body[0][1]).toBe(opts.body[1][1]); // same day label
  });

  it("parses morning_hours, noon_hours, and night_hours from settings", async () => {
    const schedule = makeSchedule({
      schedule_settings: {
        enabled_shifts: ["morning", "afternoon", "night"],
        num_of_stations: 1,
        submission_deadline: null,
        morning_hours: "06:00-14:00",
        noon_hours: "14:00-22:00",
        night_hours: "22:00-06:00",
      },
    });
    await exportBuiltScheduleToPdf(schedule, makeBuilt());
    const [, opts] = autoTableMock.mock.calls.at(-1) as [
      unknown,
      { body: string[][] },
    ];
    // 2 days x 3 shifts = 6 rows. First 3 = day 0 shifts
    expect(opts.body[0][3]).toBe("06:00"); // morning start
    expect(opts.body[0][4]).toBe("14:00"); // morning end
    expect(opts.body[1][3]).toBe("14:00"); // afternoon start
    expect(opts.body[1][4]).toBe("22:00"); // afternoon end
    expect(opts.body[2][3]).toBe("22:00"); // night start
    expect(opts.body[2][4]).toBe("06:00"); // night end
  });

  it("parses noon/afternoon hours from noon_hours key", async () => {
    const schedule = makeSchedule({
      schedule_settings: {
        enabled_shifts: ["afternoon"],
        num_of_stations: 1,
        submission_deadline: null,
        noon_hours: "12:00-20:00",
      },
    });
    await exportBuiltScheduleToPdf(schedule, makeBuilt());
    const [, opts] = autoTableMock.mock.calls.at(-1) as [
      unknown,
      { body: string[][] },
    ];
    expect(opts.body[0][3]).toBe("12:00");
    expect(opts.body[0][4]).toBe("20:00");
  });

  it("handles em-dash in hour range formatting", async () => {
    const schedule = makeSchedule({
      schedule_settings: {
        enabled_shifts: ["morning"],
        num_of_stations: 1,
        submission_deadline: null,
        morning_hours: "06:00–14:00", // em dash, not hyphen
      },
    });
    await exportBuiltScheduleToPdf(schedule, makeBuilt());
    const [, opts] = autoTableMock.mock.calls.at(-1) as [
      unknown,
      { body: string[][] },
    ];
    expect(opts.body[0][3]).toBe("06:00");
    expect(opts.body[0][4]).toBe("14:00");
  });

  it("handles custom shift names without matching hours config", async () => {
    const schedule = makeSchedule({
      schedule_settings: {
        enabled_shifts: ["custom_shift"],
        num_of_stations: 1,
        submission_deadline: null,
      },
    });
    await exportBuiltScheduleToPdf(schedule, makeBuilt());
    const [, opts] = autoTableMock.mock.calls.at(-1) as [
      unknown,
      { body: string[][] },
    ];
    // Unknown shift name should have empty start/end
    expect(opts.body[0][3]).toBe("");
    expect(opts.body[0][4]).toBe("");
  });
});

describe("exportBuiltScheduleToPdf Blob type handling", () => {
  it("creates new Blob with correct MIME type when output returns non-Blob", async () => {
    output.mockReturnValue("raw string output" as unknown as Blob); // not a Blob
    const blob = await exportBuiltScheduleToPdf(makeSchedule(), makeBuilt());
    expect(blob).toBeInstanceOf(Blob);
    expect(blob.type).toBe("application/pdf");
  });
});
