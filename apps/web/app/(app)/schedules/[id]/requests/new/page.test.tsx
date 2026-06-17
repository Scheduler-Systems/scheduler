import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const pushMock = vi.fn();
const paramsMock: { id: string } = { id: "sid1" };
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock, replace: vi.fn() }),
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

const useAuthMock = vi.fn();
vi.mock("@/lib/auth-context", () => ({
  useAuth: () => useAuthMock(),
}));

const getSchedule = vi.fn();
const getLatestBuiltSchedule = vi.fn();
vi.mock("@/lib/firestore", () => ({
  getSchedule: (id: string) => getSchedule(id),
  getLatestBuiltSchedule: (id: string) => getLatestBuiltSchedule(id),
}));

const createScheduleChangeRequest = vi.fn();
vi.mock("@/lib/requests", () => ({
  createScheduleChangeRequest: (...args: unknown[]) =>
    createScheduleChangeRequest(...args),
}));

vi.mock("@/lib/shifts", () => ({
  parseEnabledShifts: (input: unknown) =>
    Array.isArray(input) ? (input as string[]) : ["morning", "night"],
}));

// Client component imported after mocks register.
const NewRequestPage = (await import("./page")).default;

function baseSchedule() {
  return {
    id: "sid1",
    schedule_name: "Clinic",
    employees: [
      {
        employee_name: "Ada",
        employee_email: "ada@x",
        employee_phone: "",
        role: { is_worker: true, is_admin: true, is_creator: true },
        user_ref: { id: "u1", path: "users/u1" },
      },
      {
        employee_name: "Bob",
        employee_email: "bob@x",
        employee_phone: "",
        role: { is_worker: true, is_admin: false, is_creator: false },
        user_ref: { id: "u2", path: "users/u2" },
      },
    ],
    current_priorities: [],
    next_schedule: [],
    schedule_settings: {
      enabled_shifts: ["morning", "night"],
      num_of_stations: 1,
      submission_deadline: null,
    },
    sid: "",
  };
}

function baseBuilt() {
  return {
    id: "b1",
    // 2 days × 2 shifts = 4 rows
    schedule: [
      { stringList: [""] },
      { stringList: [""] },
      { stringList: [""] },
      { stringList: [""] },
    ],
    first_weekday: "",
    last_weekday: "",
    first_weekday_datetime: {
      toDate: () => new Date("2026-05-03T00:00:00Z"),
    },
    last_weekday_datetime: null,
    time_created: { toDate: () => new Date() },
    current_priorities: [],
  };
}

describe("NewRequestPage", () => {
  beforeEach(() => {
    pushMock.mockReset();
    getSchedule.mockReset();
    getLatestBuiltSchedule.mockReset();
    createScheduleChangeRequest.mockReset();
    useAuthMock.mockReturnValue({
      user: { uid: "u1", email: "ada@x", displayName: "Ada" },
    });
  });

  it("renders target, shift, reason fields once data loads", async () => {
    getSchedule.mockResolvedValueOnce(baseSchedule());
    getLatestBuiltSchedule.mockResolvedValueOnce(baseBuilt());
    render(<NewRequestPage />);
    await waitFor(() =>
      expect(
        screen.getByRole("heading", { name: /Request a shift change/i })
      ).toBeInTheDocument()
    );
    // Select for target employee, select for shift, textarea for reason
    const selects = screen.getAllByRole("combobox");
    expect(selects.length).toBeGreaterThanOrEqual(2);
    // The current user (Ada) should NOT appear in the swap list; Bob should.
    expect(
      screen.getByRole("option", { name: /^Bob$/ })
    ).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /^Ada$/ })).toBeNull();
    // Reason textarea
    expect(screen.getByRole("textbox")).toBeInTheDocument();
    // Submit button
    expect(
      screen.getByRole("button", { name: /Submit request/i })
    ).toBeInTheDocument();
  });

  it("submits with the correct payload and routes to schedule detail", async () => {
    getSchedule.mockResolvedValueOnce(baseSchedule());
    getLatestBuiltSchedule.mockResolvedValueOnce(baseBuilt());
    createScheduleChangeRequest.mockResolvedValueOnce("rc-new");
    const user = userEvent.setup();
    render(<NewRequestPage />);
    await waitFor(() =>
      expect(
        screen.getByRole("heading", { name: /Request a shift change/i })
      ).toBeInTheDocument()
    );
    const selects = screen.getAllByRole("combobox");
    // selects[0] is target, selects[1] is shift
    await user.selectOptions(selects[0], "u2");
    // Pick the first available shift option (index 1 skips the placeholder)
    const shiftOptions = selects[1].querySelectorAll("option");
    await user.selectOptions(selects[1], shiftOptions[1].value);
    await user.type(screen.getByRole("textbox"), "family trip");
    await user.click(screen.getByRole("button", { name: /Submit request/i }));
    await waitFor(() =>
      expect(createScheduleChangeRequest).toHaveBeenCalledWith(
        expect.objectContaining({
          scheduleId: "sid1",
          userId: "u1",
          reason: expect.stringContaining("family trip"),
          dateTime: expect.any(Date),
        })
      )
    );
    // Reason should embed the target name for reviewer visibility.
    const payload = createScheduleChangeRequest.mock.calls[0][0] as {
      reason: string;
    };
    expect(payload.reason).toMatch(/Swap with Bob/);
    await waitFor(() =>
      expect(pushMock).toHaveBeenCalledWith("/schedules/sid1")
    );
  });

  it("shows an error banner when createScheduleChangeRequest rejects", async () => {
    getSchedule.mockResolvedValueOnce(baseSchedule());
    getLatestBuiltSchedule.mockResolvedValueOnce(baseBuilt());
    createScheduleChangeRequest.mockRejectedValueOnce(new Error("boom"));
    const user = userEvent.setup();
    render(<NewRequestPage />);
    await waitFor(() =>
      expect(
        screen.getByRole("heading", { name: /Request a shift change/i })
      ).toBeInTheDocument()
    );
    const selects = screen.getAllByRole("combobox");
    await user.selectOptions(selects[0], "u2");
    const shiftOptions = selects[1].querySelectorAll("option");
    await user.selectOptions(selects[1], shiftOptions[1].value);
    await user.type(screen.getByRole("textbox"), "reason text");
    await user.click(screen.getByRole("button", { name: /Submit request/i }));
    await waitFor(() =>
      expect(
        screen.getByText(/Failed to submit request/i)
      ).toBeInTheDocument()
    );
    expect(pushMock).not.toHaveBeenCalled();
  });

  it("shows target-required error when target is blank", async () => {
    getSchedule.mockResolvedValueOnce(baseSchedule());
    getLatestBuiltSchedule.mockResolvedValueOnce(baseBuilt());
    const user = userEvent.setup();
    render(<NewRequestPage />);
    await waitFor(() =>
      expect(
        screen.getByRole("heading", { name: /Request a shift change/i })
      ).toBeInTheDocument()
    );
    await user.click(screen.getByRole("button", { name: /Submit request/i }));
    await waitFor(() =>
      expect(
        screen.getByText(/Pick an employee to swap with/i)
      ).toBeInTheDocument()
    );
    expect(createScheduleChangeRequest).not.toHaveBeenCalled();
  });

  it("shows the empty-schedule banner when no built schedule exists", async () => {
    getSchedule.mockResolvedValueOnce(baseSchedule());
    getLatestBuiltSchedule.mockResolvedValueOnce(null);
    render(<NewRequestPage />);
    await waitFor(() =>
      expect(
        screen.getByText(/No built schedule yet/i)
      ).toBeInTheDocument()
    );
    expect(
      screen.queryByRole("button", { name: /Submit request/i })
    ).toBeNull();
  });

  it("shows the no-employees banner when the schedule has only the current user", async () => {
    getSchedule.mockResolvedValueOnce({
      ...baseSchedule(),
      employees: [baseSchedule().employees[0]], // just Ada
    });
    getLatestBuiltSchedule.mockResolvedValueOnce(baseBuilt());
    render(<NewRequestPage />);
    await waitFor(() =>
      expect(
        screen.getByText(/No other employees/i)
      ).toBeInTheDocument()
    );
  });

  it("renders the error state when getSchedule returns null", async () => {
    getSchedule.mockResolvedValueOnce(null);
    getLatestBuiltSchedule.mockResolvedValueOnce(null);
    render(<NewRequestPage />);
    await waitFor(() =>
      expect(
        screen.getByText(/Failed to load requests/i)
      ).toBeInTheDocument()
    );
  });
});
