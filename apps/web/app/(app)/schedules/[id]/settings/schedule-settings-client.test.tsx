import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const paramsMock = { id: "sid1" };
vi.mock("next/navigation", () => ({
  useParams: () => paramsMock,
}));

vi.mock("next/link", () => ({
  default: ({
    children,
    href,
    ...rest
  }: {
    children: React.ReactNode;
    href: string;
  } & React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

const getSchedule = vi.fn();
vi.mock("@/lib/firestore", () => ({
  getSchedule: (id: string) => getSchedule(id),
}));

const updateScheduleSettings = vi.fn();
vi.mock("@/lib/firestore-write", () => ({
  updateScheduleSettings: (...args: unknown[]) => updateScheduleSettings(...args),
}));

vi.mock("@/components/shift-grid", () => ({
  ShiftGrid: () => <div data-testid="shift-grid" />,
}));

const ScheduleSettingsClient = (await import("./schedule-settings-client")).default;

describe("ScheduleSettingsClient", () => {
  beforeEach(() => {
    getSchedule.mockReset();
    updateScheduleSettings.mockReset();
  });

  it("loads settings and renders shift toggles + hour inputs", async () => {
    getSchedule.mockResolvedValueOnce({
      id: "sid1",
      schedule_name: "Clinic",
      schedule_settings: {
        enabled_shifts: ["morning"],
        num_of_stations: 3,
        morning_hours: "06–14",
        noon_hours: "",
        night_hours: "",
        submission_deadline: {
          is_activated: true,
          weekday: "MONDAY",
          time: null,
        },
      },
    });
    render(<ScheduleSettingsClient />);
    await waitFor(() =>
      expect(
        screen.getByRole("heading", { name: /Schedule settings/i }),
      ).toBeInTheDocument(),
    );
    expect(screen.getByLabelText(/Morning hours/i)).toHaveValue("06–14");
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByLabelText(/Weekday/i)).toHaveValue("MONDAY");
  });

  it("renders error when schedule not found", async () => {
    getSchedule.mockResolvedValueOnce(null);
    render(<ScheduleSettingsClient />);
    await waitFor(() =>
      expect(screen.getByText(/Schedule not found/i)).toBeInTheDocument(),
    );
  });

  it("saves settings and shows the success message", async () => {
    getSchedule.mockResolvedValueOnce({
      id: "sid1",
      schedule_name: "Clinic",
      schedule_settings: {
        enabled_shifts: [],
        num_of_stations: 1,
        submission_deadline: null,
      },
    });
    updateScheduleSettings.mockResolvedValueOnce(undefined);
    const user = userEvent.setup();
    render(<ScheduleSettingsClient />);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Save settings/i }))
        .toBeInTheDocument(),
    );
    // Toggle a shift + change stations count
    await user.click(screen.getByRole("button", { name: /morning/i }));
    await user.click(screen.getByRole("button", { name: /^\+$/ }));
    await user.click(screen.getByRole("button", { name: /Save settings/i }));
    await waitFor(() =>
      expect(updateScheduleSettings).toHaveBeenCalledWith(
        "sid1",
        expect.objectContaining({
          enabled_shifts: ["morning"],
          num_of_stations: 2,
        }),
      ),
    );
    await waitFor(() =>
      expect(screen.getByText(/^Saved\.$/)).toBeInTheDocument(),
    );
  });

  it("shows a failure message when updateScheduleSettings rejects", async () => {
    getSchedule.mockResolvedValueOnce({
      id: "sid1",
      schedule_name: "Clinic",
      schedule_settings: {
        enabled_shifts: [],
        num_of_stations: 1,
      },
    });
    updateScheduleSettings.mockRejectedValueOnce(new Error("boom"));
    const user = userEvent.setup();
    render(<ScheduleSettingsClient />);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Save settings/i }))
        .toBeInTheDocument(),
    );
    await user.click(screen.getByRole("button", { name: /Save settings/i }));
    await waitFor(() =>
      expect(screen.getByText(/Failed to save/i)).toBeInTheDocument(),
    );
  });

  it("decrements stations but clamps at 1", async () => {
    getSchedule.mockResolvedValueOnce({
      id: "sid1",
      schedule_name: "Clinic",
      schedule_settings: { enabled_shifts: [], num_of_stations: 2 },
    });
    const user = userEvent.setup();
    render(<ScheduleSettingsClient />);
    await waitFor(() => expect(screen.getByText("2")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: /^−$/ }));
    expect(screen.getByText("1")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^−$/ }));
    // stays at 1 (clamp)
    expect(screen.getByText("1")).toBeInTheDocument();
  });

  it("renders error when getSchedule rejects (catch branch)", async () => {
    getSchedule.mockRejectedValueOnce(new Error("network error"));
    render(<ScheduleSettingsClient />);
    await waitFor(() =>
      expect(screen.getByText(/Failed to load schedule/i)).toBeInTheDocument(),
    );
  });

  it("toggles a shift off (delete from set)", async () => {
    getSchedule.mockResolvedValueOnce({
      id: "sid1",
      schedule_name: "Clinic",
      schedule_settings: {
        enabled_shifts: ["morning"],
        num_of_stations: 1,
      },
    });
    const user = userEvent.setup();
    render(<ScheduleSettingsClient />);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Save settings/i }))
        .toBeInTheDocument(),
    );
    // morning is active by default from loaded data; click to deactivate
    await user.click(screen.getByRole("button", { name: /^morning$/i }));
    await user.click(screen.getByRole("button", { name: /Save settings/i }));
    await waitFor(() =>
      expect(updateScheduleSettings).toHaveBeenCalledWith(
        "sid1",
        expect.objectContaining({ enabled_shifts: [] }),
      ),
    );
  });

  it("saves with enforceable submission deadline and multiple hours", async () => {
    getSchedule.mockResolvedValueOnce({
      id: "sid1",
      schedule_name: "Clinic",
      schedule_settings: {
        enabled_shifts: [],
        num_of_stations: 1,
        morning_hours: "06–14",
        noon_hours: "14–22",
        night_hours: "22–06",
        submission_deadline: null,
      },
    });
    updateScheduleSettings.mockResolvedValueOnce(undefined);
    const user = userEvent.setup();
    render(<ScheduleSettingsClient />);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Save settings/i }))
        .toBeInTheDocument(),
    );
    // Toggle deadline enforce on
    await user.click(screen.getByLabelText(/Enforce/i));
    // Change the weekday
    await user.selectOptions(screen.getByLabelText(/Weekday/i), "FRIDAY");
    await user.click(screen.getByRole("button", { name: /Save settings/i }));
    await waitFor(() =>
      expect(updateScheduleSettings).toHaveBeenCalledWith(
        "sid1",
        expect.objectContaining({
          enabled_shifts: [],
          morning_hours: "06–14",
          noon_hours: "14–22",
          night_hours: "22–06",
          submission_deadline: expect.objectContaining({
            is_activated: true,
            weekday: "FRIDAY",
          }),
        }),
      ),
    );
  });

  it("handles missing schedule_settings fields gracefully (null deadlines)", async () => {
    getSchedule.mockResolvedValueOnce({
      id: "sid1",
      schedule_name: "Clinic",
      schedule_settings: {
        enabled_shifts: [],
        num_of_stations: 1,
        submission_deadline: null,
      },
    });
    render(<ScheduleSettingsClient />);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Save settings/i }))
        .toBeInTheDocument(),
    );
    // Enforce checkbox should be unchecked since deadline is null
    const enforceCheckbox = screen.getByLabelText(/Enforce/i) as HTMLInputElement;
    expect(enforceCheckbox.checked).toBe(false);
  });

  it("reads a legacy bare Timestamp as submission_deadline (readDeadline legacy branch)", async () => {
    // Legacy format: submission_deadline is a bare Timestamp-like object
    // (no is_activated or weekday keys — treated as direct time value)
    const legacyTimestamp = { toDate: () => new Date("2025-06-01T08:00:00") };
    getSchedule.mockResolvedValueOnce({
      id: "sid1",
      schedule_name: "Clinic",
      schedule_settings: {
        enabled_shifts: ["morning"],
        num_of_stations: 2,
        submission_deadline: legacyTimestamp,
      },
    });
    render(<ScheduleSettingsClient />);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Save settings/i }))
        .toBeInTheDocument(),
    );
    // The legacy Timestamp should result in deadlineActive = true (since the
    // is_activated check from readDeadline won't find the key, but the legacy
    // path returns empty + time — time is the Timestamp).
    // In the Flutter model a bare timestamp was treated as "enforced"
    // implicitly via the caller. Save payload should reflect the time.
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /Save settings/i }));
    await waitFor(() =>
      expect(updateScheduleSettings).toHaveBeenCalledWith(
        "sid1",
        expect.objectContaining({
          enabled_shifts: ["morning"],
          num_of_stations: 2,
          submission_deadline: expect.objectContaining({
            is_activated: false,
            weekday: "SUNDAY",
          }),
        }),
      ),
    );
  });

  it("saves with a deadline time value (deadlineTimeInput truthy branch)", async () => {
    getSchedule.mockResolvedValueOnce({
      id: "sid1",
      schedule_name: "Clinic",
      schedule_settings: {
        enabled_shifts: [],
        num_of_stations: 1,
        submission_deadline: {
          is_activated: true,
          weekday: "WEDNESDAY",
          time: new Date("2025-07-15T17:00:00"),
        },
      },
    });
    updateScheduleSettings.mockResolvedValueOnce(undefined);
    const user = userEvent.setup();
    render(<ScheduleSettingsClient />);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Save settings/i }))
        .toBeInTheDocument(),
    );
    await user.click(screen.getByRole("button", { name: /Save settings/i }));
    await waitFor(() =>
      expect(updateScheduleSettings).toHaveBeenCalledWith(
        "sid1",
        expect.objectContaining({
          submission_deadline: expect.objectContaining({
            is_activated: true,
            weekday: "WEDNESDAY",
          }),
        }),
      ),
    );
  });

  it("falls back to 'Schedule' label when schedule_name is empty", async () => {
    getSchedule.mockResolvedValueOnce({
      id: "sid1",
      schedule_name: "",
      schedule_settings: {
        enabled_shifts: [],
        num_of_stations: 1,
      },
    });
    render(<ScheduleSettingsClient />);
    await waitFor(() =>
      expect(screen.getByText(/Schedule$/)).toBeInTheDocument(),
    );
  });
});
