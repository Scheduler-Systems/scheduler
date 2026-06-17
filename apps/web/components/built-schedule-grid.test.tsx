import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

// Mock getLatestBuiltSchedule before importing the component so we control
// loading → loaded transitions deterministically.
const mockGet = vi.fn<() => Promise<unknown>>();
vi.mock("@/lib/firestore", () => ({
  getLatestBuiltSchedule: () => mockGet(),
}));

const { BuiltScheduleGrid } = await import("./built-schedule-grid");

function schedule(overrides = {}) {
  return {
    id: "sid1",
    schedule_name: "Test",
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

describe("<BuiltScheduleGrid>", () => {
  it("renders a loading spinner while the fetch is pending", () => {
    mockGet.mockReturnValueOnce(new Promise(() => undefined));
    // (schedule is typed loosely for test — intentionally partial)
    render(<BuiltScheduleGrid schedule={schedule()} />);
    expect(screen.getByText(/Loading published schedule/i)).toBeTruthy();
  });

  it("renders the empty-state when no built schedule exists", async () => {
    mockGet.mockResolvedValueOnce(null);
    // (schedule is typed loosely for test — intentionally partial)
    render(<BuiltScheduleGrid schedule={schedule()} />);
    await waitFor(() =>
      expect(screen.getByText(/No published schedule yet/i)).toBeTruthy()
    );
  });

  it("renders the grid with day labels + shift columns when data is present", async () => {
    mockGet.mockResolvedValueOnce({
      id: "b1",
      schedule: [
        { stringList: ["Alice"] },
        { stringList: ["Bob"] },
        { stringList: ["Carol"] },
        { stringList: ["Dave"] },
      ],
      first_weekday: "",
      last_weekday: "",
      current_priorities: [],
      first_weekday_datetime: null,
      last_weekday_datetime: null,
      time_created: null,
    });
    // (schedule is typed loosely for test — intentionally partial)
    render(<BuiltScheduleGrid schedule={schedule()} />);
    await waitFor(() => expect(screen.getByText("Alice")).toBeTruthy());
    expect(screen.getByText("Bob")).toBeTruthy();
    expect(screen.getByText("Carol")).toBeTruthy();
    expect(screen.getByText("Dave")).toBeTruthy();
    // Fallback "Day 1", "Day 2" labels when no first_weekday_datetime
    expect(screen.getByText("Day 1")).toBeTruthy();
    expect(screen.getByText("Day 2")).toBeTruthy();
  });

  it("labels rows with concrete weekdays when first_weekday_datetime is provided", async () => {
    // 2025-01-05 is a Sunday — supply it as the start date so day labels
    // are the localised weekday/month/day form rather than "Day 1".
    const start = new Date("2025-01-05T00:00:00Z");
    mockGet.mockResolvedValueOnce({
      id: "b1",
      // Two enabled shifts × two days = 4 rows
      schedule: [
        { stringList: ["A"] },
        { stringList: ["B"] },
        { stringList: ["C"] },
        { stringList: ["D"] },
      ],
      // A non-ISO-but-parseable date on first_weekday / last_weekday triggers
      // the `weekLabel` branch (formatDate -> locale string). Using raw
      // `yyyy-mm-dd` here stays deterministic and avoids locale drift.
      first_weekday: "2025-01-05",
      last_weekday: "2025-01-06",
      current_priorities: [],
      first_weekday_datetime: { toDate: () => start },
      last_weekday_datetime: { toDate: () => new Date("2025-01-06T00:00:00Z") },
      time_created: null,
    });
    render(<BuiltScheduleGrid schedule={schedule()} />);
    await waitFor(() => expect(screen.getByText("A")).toBeTruthy());
    // Week-of label rendered (exact format depends on locale, but it
    // must contain an en-dash separator and both formatted dates).
    const weekOfText = screen.getByText(/Week of/i);
    expect(weekOfText.textContent).toMatch(/–/);
    // Day labels no longer use "Day 1" fallback.
    expect(screen.queryByText("Day 1")).toBeNull();
  });

  it("renders an empty first_weekday gracefully (formatDate empty-string branch)", async () => {
    mockGet.mockResolvedValueOnce({
      id: "b1",
      schedule: [{ stringList: ["X"] }],
      first_weekday: "",
      last_weekday: "",
      current_priorities: [],
      first_weekday_datetime: null,
      last_weekday_datetime: null,
      time_created: null,
    });
    render(<BuiltScheduleGrid schedule={schedule()} />);
    await waitFor(() => expect(screen.getByText("X")).toBeTruthy());
    // With no first_weekday / last_weekday, the "Week of ..." line must NOT
    // render (weekLabel is an empty string and the component suppresses it).
    expect(screen.queryByText(/Week of/i)).toBeNull();
  });

  it("shows an em-dash for empty slots", async () => {
    mockGet.mockResolvedValueOnce({
      id: "b1",
      schedule: [{ stringList: [] }, { stringList: ["Bob"] }],
      first_weekday: "",
      last_weekday: "",
      current_priorities: [],
      first_weekday_datetime: null,
      last_weekday_datetime: null,
      time_created: null,
    });
    // (schedule is typed loosely for test — intentionally partial)
    render(<BuiltScheduleGrid schedule={schedule()} />);
    await waitFor(() => expect(screen.getByText("Bob")).toBeTruthy());
    // At least one em-dash for the empty cell
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });
});
