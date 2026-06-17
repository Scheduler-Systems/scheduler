import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, act, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const replaceMock = vi.fn();
const pushMock = vi.fn();
const paramsMock = { id: "sid1" };
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock, push: pushMock }),
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

// P1-4 billing context — mocked here so tests can flip tier/limits between
// cases. Defaults set in beforeEach keep the base pre-P1-4 flows green
// (pro/unlimited), and the P1-4 cases override to free-tier limits.
const useBillingMock = vi.fn();
vi.mock("@/lib/billing/billing-context", () => ({
  useBilling: () => useBillingMock(),
}));

// PaywallModal + PDF button use useI18n. We return keys verbatim so paywall
// banner assertions can match by key, with a small override for the PDF
// button so the pre-existing "Download PDF" assertion from P2-2 stays green.
const I18N_OVERRIDES: Record<string, string> = {
  "scheduleDetail.downloadPdf": "Download PDF",
};
vi.mock("@/lib/i18n-context", () => ({
  useI18n: () => ({
    t: (key: string) => I18N_OVERRIDES[key] ?? key,
    locale: "en",
    setLocale: vi.fn(),
  }),
}));

const getSchedule = vi.fn();
const getLatestBuiltSchedule = vi.fn();
const getAllPrioritySubmissions = vi.fn();
const getMonthlyBuildCount = vi.fn();
vi.mock("@/lib/firestore", () => ({
  getSchedule: (id: string) => getSchedule(id),
  getLatestBuiltSchedule: (id: string) => getLatestBuiltSchedule(id),
  getAllPrioritySubmissions: (id: string) => getAllPrioritySubmissions(id),
  getMonthlyBuildCount: (...a: unknown[]) => getMonthlyBuildCount(...a),
}));

const updateScheduleName = vi.fn();
const addEmployee = vi.fn();
const removeEmployee = vi.fn();
const publishBuiltSchedule = vi.fn();
const deleteSchedule = vi.fn();
const incrementMonthlyBuildCount = vi.fn();
vi.mock("@/lib/firestore-write", () => ({
  updateScheduleName: (...a: unknown[]) => updateScheduleName(...a),
  addEmployee: (...a: unknown[]) => addEmployee(...a),
  removeEmployee: (...a: unknown[]) => removeEmployee(...a),
  publishBuiltSchedule: (...a: unknown[]) => publishBuiltSchedule(...a),
  deleteSchedule: (...a: unknown[]) => deleteSchedule(...a),
  incrementMonthlyBuildCount: (...a: unknown[]) => incrementMonthlyBuildCount(...a),
}));

vi.mock("@/components/built-schedule-grid", () => ({
  BuiltScheduleGrid: () => <div data-testid="built-grid" />,
}));

// Controllable mock state so tests can exercise the "no shifts" branch and the
// "builder returned conflicts" path without re-mocking.
let mockShifts: string[] = ["morning", "night"];
let mockBuildResult: {
  rows: { name: string; shifts: string[] }[];
  firstWeekday: string;
  lastWeekday: string;
  conflicts: { dayIndex: number; worker: string; shifts: string[] }[];
} = { rows: [], firstWeekday: "2026-05-03", lastWeekday: "2026-05-09", conflicts: [] };

vi.mock("@/lib/schedule-builder", () => ({
  buildSchedule: () => mockBuildResult,
}));
vi.mock("@/lib/shifts", () => ({
  parseEnabledShifts: () => mockShifts,
}));

const downloadCsvMock = vi.fn();
vi.mock("@/lib/csv-export", () => ({
  builtScheduleToCsv: () => "",
  downloadCsv: downloadCsvMock,
}));

const exportBuiltScheduleToPdfMock = vi.fn();
const getPdfFilenameMock = vi.fn();
getPdfFilenameMock.mockReturnValue("clinic.pdf");
vi.mock("@/lib/pdf-export", () => ({
  exportBuiltScheduleToPdf: (...a: unknown[]) => exportBuiltScheduleToPdfMock(...a),
  getPdfFilename: (...a: unknown[]) => getPdfFilenameMock(...a),
}));

// Seat-band hosted-checkout orchestrator. Mocked so the wiring test can assert
// the paywall's Continue actually starts checkout (it used to be a dead no-op).
const startSeatBandCheckoutMock = vi.fn();
vi.mock("@/lib/billing/purchase", () => ({
  startSeatBandCheckout: (...args: unknown[]) =>
    startSeatBandCheckoutMock(...args),
}));

const ScheduleDetailClient = (await import("./schedule-detail-client")).default;

const UNLIMITED_BILLING = {
  tier: "pro" as const,
  limits: {
    maxStations: 5,
    maxUsers: 50,
    maxBuildsPerMonth: Number.POSITIVE_INFINITY,
  },
  loading: false,
  refresh: vi.fn(),
};

const FREE_BILLING = {
  tier: "free" as const,
  limits: { maxStations: 1, maxUsers: 3, maxBuildsPerMonth: 5 },
  loading: false,
  refresh: vi.fn(),
};

function baseSchedule(overrides: Record<string, unknown> = {}) {
  return {
    id: "sid1",
    schedule_name: "Clinic",
    employees: [
      {
        employee_name: "Ada",
        employee_email: "ada@x",
        employee_phone: "555",
        role: { is_worker: true, is_creator: true, is_admin: true },
        user_ref: { id: "u1", path: "users/u1" },
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
    ...overrides,
  };
}

beforeEach(() => {
  replaceMock.mockReset();
  pushMock.mockReset();
  getSchedule.mockReset();
  getLatestBuiltSchedule.mockReset();
  getAllPrioritySubmissions.mockReset();
  getMonthlyBuildCount.mockReset();
  updateScheduleName.mockReset();
  addEmployee.mockReset();
  removeEmployee.mockReset();
  publishBuiltSchedule.mockReset();
  deleteSchedule.mockReset();
  incrementMonthlyBuildCount.mockReset();
  downloadCsvMock.mockReset();
  exportBuiltScheduleToPdfMock.mockReset();
  getPdfFilenameMock.mockReset();
  getPdfFilenameMock.mockReturnValue("clinic.pdf");
  startSeatBandCheckoutMock.mockReset();
  useAuthMock.mockReturnValue({
    user: { uid: "u1", email: "ada@x", displayName: "Ada" },
  });
  // Default to unlimited/pro so the pre-P1-4 flows don't hit gates.
  useBillingMock.mockReturnValue(UNLIMITED_BILLING);
  getMonthlyBuildCount.mockResolvedValue(0);
  getAllPrioritySubmissions.mockResolvedValue([]);
  incrementMonthlyBuildCount.mockResolvedValue(undefined);
  mockShifts = ["morning", "night"];
  mockBuildResult = { rows: [], firstWeekday: "2026-05-03", lastWeekday: "2026-05-09", conflicts: [] };
});

describe("ScheduleDetailClient", () => {

  it("renders schedule name heading and employees list", async () => {
    getSchedule.mockResolvedValueOnce(baseSchedule());
    render(<ScheduleDetailClient />);
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: /Clinic/ }))
        .toBeInTheDocument(),
    );
    expect(screen.getByText("Ada")).toBeInTheDocument();
    // Accessible link to Settings
    expect(screen.getByRole("link", { name: /Settings/i }))
      .toBeInTheDocument();
  });

  it("renders error when the schedule is missing", async () => {
    getSchedule.mockResolvedValueOnce(null);
    render(<ScheduleDetailClient />);
    await waitFor(() =>
      expect(screen.getByText(/Schedule not found/i)).toBeInTheDocument(),
    );
  });

  it("adds an employee via the form and calls addEmployee with the right payload", async () => {
    getSchedule
      .mockResolvedValueOnce(baseSchedule())
      .mockResolvedValueOnce(baseSchedule());
    addEmployee.mockResolvedValueOnce(undefined);
    const user = userEvent.setup();
    render(<ScheduleDetailClient />);
    await waitFor(() => expect(screen.getByText("Ada")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: /Add employee/i }));
    await user.type(
      screen.getByPlaceholderText(/Full name/i),
      "Bob",
    );
    await user.click(
      screen.getByRole("button", { name: /^Add employee$/i }),
    );
    await waitFor(() =>
      expect(addEmployee).toHaveBeenCalledWith(
        "sid1",
        expect.objectContaining({
          employee_name: "Bob",
          role: expect.objectContaining({ is_worker: true }),
        }),
      ),
    );
  });

  it("shows an error when addEmployee rejects", async () => {
    getSchedule.mockResolvedValue(baseSchedule());
    addEmployee.mockRejectedValueOnce(new Error("boom"));
    const user = userEvent.setup();
    render(<ScheduleDetailClient />);
    await waitFor(() => expect(screen.getByText("Ada")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: /Add employee/i }));
    await user.type(
      screen.getByPlaceholderText(/Full name/i),
      "Bob",
    );
    await user.click(
      screen.getByRole("button", { name: /^Add employee$/i }),
    );
    await waitFor(() =>
      expect(screen.getByText(/Failed to add employee/i))
        .toBeInTheDocument(),
    );
  });

  it("deletes the schedule and routes away when confirmed", async () => {
    getSchedule.mockResolvedValueOnce(baseSchedule());
    deleteSchedule.mockResolvedValueOnce(undefined);
    const user = userEvent.setup();
    render(<ScheduleDetailClient />);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Delete schedule/i }))
        .toBeInTheDocument(),
    );
    await user.click(
      screen.getByRole("button", { name: /Delete schedule/i }),
    );
    await user.click(
      screen.getByRole("button", { name: /Yes, delete/i }),
    );
    await waitFor(() =>
      expect(deleteSchedule).toHaveBeenCalledWith("sid1", ["u1"]),
    );
    await waitFor(() =>
      expect(replaceMock).toHaveBeenCalledWith("/schedules"),
    );
  });

  it("hides the danger zone when the current user is not a creator", async () => {
    getSchedule.mockResolvedValueOnce({
      ...baseSchedule(),
      employees: [
        {
          employee_name: "Ada",
          employee_email: "ada@x",
          role: { is_worker: true, is_admin: false, is_creator: false },
        },
      ],
    });
    render(<ScheduleDetailClient />);
    await waitFor(() =>
      expect(screen.getByText("Ada")).toBeInTheDocument(),
    );
    expect(
      screen.queryByRole("button", { name: /Delete schedule/i }),
    ).toBeNull();
  });

  it("keeps editing open when saving the name fails", async () => {
    getSchedule.mockResolvedValueOnce(baseSchedule());
    updateScheduleName.mockRejectedValueOnce(new Error("save failed"));
    const user = userEvent.setup();
    render(<ScheduleDetailClient />);
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: /Clinic/ }))
        .toBeInTheDocument(),
    );
    await user.click(screen.getByTitle(/Edit name/i));
    const nameInput = await screen.findByDisplayValue("Clinic");
    await user.clear(nameInput);
    await user.type(nameInput, "New Name");
    await user.click(screen.getByRole("button", { name: /^Save$/i }));
    // Input should still be visible — catch keeps editing open
    await waitFor(() =>
      expect(screen.getByDisplayValue("New Name")).toBeInTheDocument(),
    );
  });

  it("enters and saves the name edit flow", async () => {
    getSchedule.mockResolvedValueOnce(baseSchedule());
    updateScheduleName.mockResolvedValueOnce(undefined);
    const user = userEvent.setup();
    render(<ScheduleDetailClient />);
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: /Clinic/ }))
        .toBeInTheDocument(),
    );
    await user.click(screen.getByTitle(/Edit name/i));
    const nameInput = await screen.findByDisplayValue("Clinic");
    await user.clear(nameInput);
    await user.type(nameInput, "New Name");
    await user.click(screen.getByRole("button", { name: /^Save$/i }));
    await waitFor(() =>
      expect(updateScheduleName).toHaveBeenCalledWith(
        "sid1",
        "New Name",
        ["u1"],
      ),
    );
  });

  it("downloads a PDF when the Download PDF button is clicked", async () => {
    getSchedule.mockResolvedValueOnce(baseSchedule());
    getLatestBuiltSchedule.mockResolvedValueOnce({
      scheduled_shifts: [],
      schedule_name: "Clinic",
    });
    const fakeBlob = new Blob(["pdf"], { type: "application/pdf" });
    exportBuiltScheduleToPdfMock.mockResolvedValueOnce(fakeBlob);
    const createUrl = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:x");
    const revokeUrl = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    const user = userEvent.setup();
    render(<ScheduleDetailClient />);
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: /Clinic/ })).toBeInTheDocument(),
    );
    await user.click(screen.getByRole("button", { name: /Download PDF/i }));
    await waitFor(() => expect(exportBuiltScheduleToPdfMock).toHaveBeenCalled());
    expect(createUrl).toHaveBeenCalledWith(fakeBlob);
    expect(revokeUrl).toHaveBeenCalled();
    createUrl.mockRestore();
    revokeUrl.mockRestore();
  });

  it("shows role badges for Creator, Admin, and Worker roles", async () => {
    getSchedule.mockResolvedValueOnce(
      baseSchedule({
        employees: [
          {
            employee_name: "Alice",
            employee_email: "alice@x",
            employee_phone: "",
            role: { is_worker: true, is_creator: true, is_admin: true },
            user_ref: { id: "u1", path: "users/u1" },
          },
          {
            employee_name: "Bob",
            employee_email: "bob@x",
            employee_phone: "",
            role: { is_worker: true, is_creator: false, is_admin: true },
            user_ref: null,
          },
          {
            employee_name: "Carol",
            employee_email: "carol@x",
            employee_phone: "",
            role: { is_worker: true, is_creator: false, is_admin: false },
            user_ref: null,
          },
        ],
      }),
    );
    render(<ScheduleDetailClient />);
    await waitFor(() => expect(screen.getByText("Alice")).toBeInTheDocument());
    expect(screen.getByText("Bob")).toBeInTheDocument();
    expect(screen.getByText("Carol")).toBeInTheDocument();
    expect(screen.getByText("Creator")).toBeInTheDocument();
    expect(screen.getByText("Admin")).toBeInTheDocument();
    expect(screen.getByText("Worker")).toBeInTheDocument();
  });

  it("shows validation error when adding an employee with empty name", async () => {
    getSchedule.mockResolvedValueOnce(baseSchedule());
    const user = userEvent.setup();
    render(<ScheduleDetailClient />);
    await waitFor(() => expect(screen.getByText("Ada")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: /\+ Add employee/i }));
    // Submit with empty name field
    await user.click(
      screen.getByRole("button", { name: /^Add employee$/i }),
    );
    expect(screen.getByText(/Employee name is required/i)).toBeInTheDocument();
    expect(addEmployee).not.toHaveBeenCalled();
  });

  it("removes an employee via the remove button", async () => {
    getSchedule
      .mockResolvedValueOnce(baseSchedule())
      .mockResolvedValueOnce(baseSchedule());
    removeEmployee.mockResolvedValueOnce(undefined);
    const user = userEvent.setup();
    render(<ScheduleDetailClient />);
    await waitFor(() => expect(screen.getByText("Ada")).toBeInTheDocument());
    const removeBtn = screen.getByTitle("Remove");
    await user.click(removeBtn);
    await waitFor(() =>
      expect(removeEmployee).toHaveBeenCalledWith(
        "sid1",
        expect.objectContaining({ employee_name: "Ada" }),
      ),
    );
  });

  it("shows error message when deleteSchedule rejects", async () => {
    getSchedule.mockResolvedValueOnce(baseSchedule());
    deleteSchedule.mockRejectedValueOnce(new Error("permission denied"));
    const user = userEvent.setup();
    render(<ScheduleDetailClient />);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /Delete schedule/i }),
      ).toBeInTheDocument(),
    );
    await user.click(
      screen.getByRole("button", { name: /Delete schedule/i }),
    );
    await user.click(
      screen.getByRole("button", { name: /Yes, delete/i }),
    );
    await waitFor(() =>
      expect(screen.getByText(/Failed to delete/i)).toBeInTheDocument(),
    );
    expect(replaceMock).not.toHaveBeenCalled();
  });

  it("reports a build error when no shifts are enabled", async () => {
    getSchedule.mockResolvedValue(baseSchedule());
    mockShifts = []; // triggers the "Enable at least one shift" guard
    const user = userEvent.setup();
    render(<ScheduleDetailClient />);
    await waitFor(() =>
      expect(screen.getByText(/Published Schedule/i)).toBeInTheDocument(),
    );
    await user.click(screen.getByRole("button", { name: /\+ Build schedule/i }));
    await user.click(screen.getByRole("button", { name: /^Publish$/ }));
    await waitFor(() =>
      expect(
        screen.getByText(/Enable at least one shift/i),
      ).toBeInTheDocument(),
    );
    expect(publishBuiltSchedule).not.toHaveBeenCalled();
  });

  it("reports a build error when publishBuiltSchedule rejects", async () => {
    getSchedule.mockResolvedValue(baseSchedule());
    getAllPrioritySubmissions.mockResolvedValue([]);
    publishBuiltSchedule.mockRejectedValueOnce(new Error("publish failed"));
    const user = userEvent.setup();
    render(<ScheduleDetailClient />);
    await waitFor(() =>
      expect(screen.getByText(/Published Schedule/i)).toBeInTheDocument(),
    );
    await user.click(screen.getByRole("button", { name: /\+ Build schedule/i }));
    await user.click(screen.getByRole("button", { name: /^Publish$/ }));
    await waitFor(() =>
      expect(
        screen.getByText(/Failed to build schedule/i),
      ).toBeInTheDocument(),
    );
  });

  it("shows conflict summary when the last build returned conflicts", async () => {
    getSchedule.mockResolvedValue(baseSchedule());
    getAllPrioritySubmissions.mockResolvedValue([]);
    mockBuildResult = {
      rows: [
        { name: "Ada", shifts: ["morning"] },
        { name: "Ada", shifts: ["night"] },
      ],
      firstWeekday: "2026-05-03",
      lastWeekday: "2026-05-09",
      conflicts: [
        { dayIndex: 0, worker: "Ada", shifts: ["morning", "night"] },
      ],
    };
    const user = userEvent.setup();
    render(<ScheduleDetailClient />);
    await waitFor(() =>
      expect(screen.getByText(/Published Schedule/i)).toBeInTheDocument(),
    );
    await user.click(screen.getByRole("button", { name: /\+ Build schedule/i }));
    await user.click(screen.getByRole("button", { name: /^Publish$/ }));
    await waitFor(() =>
      expect(screen.getByText(/1 same-day conflict/i)).toBeInTheDocument(),
    );
    expect(
      screen.getByText(/Day 1: Ada is on morning \+ night/i),
    ).toBeInTheDocument();
  });

  it("exports CSV when the built schedule exists", async () => {
    getSchedule.mockResolvedValueOnce(baseSchedule());
    getLatestBuiltSchedule.mockResolvedValueOnce({
      id: "b1",
      schedule: ["morning_shift", "night_shift"],
      first_weekday_datetime: { toDate: () => new Date("2026-05-03") },
      firstWeekday: "2026-05-03",
    });
    const user = userEvent.setup();
    render(<ScheduleDetailClient />);
    await waitFor(() =>
      expect(screen.getByText(/Published Schedule/i)).toBeInTheDocument(),
    );
    await user.click(screen.getByRole("button", { name: /Export CSV/i }));
    await waitFor(() => {
      expect(downloadCsvMock).toHaveBeenCalled();
    });
  });

  it("exports CSV without first_weekday_datetime, falling back to day labels", async () => {
    getSchedule.mockResolvedValueOnce(baseSchedule());
    getLatestBuiltSchedule.mockResolvedValueOnce({
      id: "b1",
      schedule: ["morning_shift", "night_shift"],
      // No first_weekday_datetime — triggers the else branch with DAY_LABELS
    });
    const user = userEvent.setup();
    render(<ScheduleDetailClient />);
    await waitFor(() =>
      expect(screen.getByText(/Published Schedule/i)).toBeInTheDocument(),
    );
    await user.click(screen.getByRole("button", { name: /Export CSV/i }));
    await waitFor(() => {
      expect(downloadCsvMock).toHaveBeenCalled();
    });
  });

  it("early-returns when Export CSV is clicked but no built schedule exists", async () => {
    getSchedule.mockResolvedValue(baseSchedule());
    getLatestBuiltSchedule.mockImplementation(() => Promise.resolve(null));
    const user = userEvent.setup();
    render(<ScheduleDetailClient />);
    await waitFor(() =>
      expect(screen.getByText(/Published Schedule/i)).toBeInTheDocument(),
    );
    await user.click(screen.getByRole("button", { name: /Export CSV/i }));
    // Wait briefly then verify getLatestBuiltSchedule was called (handler
    // ran) but downloadCsv was not (early return).
    await new Promise((r) => setTimeout(r, 200));
    expect(getLatestBuiltSchedule).toHaveBeenCalledWith("sid1");
    expect(downloadCsvMock).not.toHaveBeenCalled();
  });

  it("early-returns when Download PDF is clicked but no built schedule exists", async () => {
    getSchedule.mockResolvedValue(baseSchedule());
    getLatestBuiltSchedule.mockImplementation(() => Promise.resolve(null));
    const user = userEvent.setup();
    render(<ScheduleDetailClient />);
    await waitFor(() =>
      expect(screen.getByText(/Published Schedule/i)).toBeInTheDocument(),
    );
    await user.click(screen.getByRole("button", { name: /Download PDF/i }));
    await new Promise((r) => setTimeout(r, 200));
    expect(getLatestBuiltSchedule).toHaveBeenCalledWith("sid1");
    expect(exportBuiltScheduleToPdfMock).not.toHaveBeenCalled();
  });

  it("shows the unnamed schedule fallback and empty employee message", async () => {
    getSchedule.mockResolvedValueOnce(
      baseSchedule({ schedule_name: null, employees: null }),
    );
    render(<ScheduleDetailClient />);
    await waitFor(() =>
      expect(screen.getByText(/Unnamed Schedule/i)).toBeInTheDocument(),
    );
    expect(screen.getByText(/No employees yet/i)).toBeInTheDocument();
  });

  it("cancels name editing and restores the original name", async () => {
    getSchedule.mockResolvedValueOnce(baseSchedule());
    const user = userEvent.setup();
    render(<ScheduleDetailClient />);
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: /Clinic/ })).toBeInTheDocument(),
    );
    await user.click(screen.getByTitle(/Edit name/i));
    expect(await screen.findByDisplayValue("Clinic")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^Cancel$/i }));
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: /Clinic/ })).toBeInTheDocument(),
    );
  });

  it("supports Enter to save and Escape to cancel in the name editor", async () => {
    getSchedule.mockResolvedValue(baseSchedule());
    updateScheduleName.mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<ScheduleDetailClient />);
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: /Clinic/ })).toBeInTheDocument(),
    );
    // Enter to save
    await user.click(screen.getByTitle(/Edit name/i));
    const input = await screen.findByDisplayValue("Clinic");
    await user.clear(input);
    await user.type(input, "NewName");
    await user.keyboard("{Enter}");
    await waitFor(() =>
      expect(updateScheduleName).toHaveBeenCalledWith("sid1", "NewName", ["u1"]),
    );
    // Edit again, Escape to cancel
    await user.click(screen.getByTitle(/Edit name/i));
    const input2 = await screen.findByDisplayValue("NewName");
    await user.clear(input2);
    await user.type(input2, "Canceled");
    await user.keyboard("{Escape}");
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: /NewName/ })).toBeInTheDocument(),
    );
  });

  it("builds with an empty buildStart (fallback to today) and no authenticated user", async () => {
    useAuthMock.mockReturnValue({ user: null });
    getSchedule.mockResolvedValue(baseSchedule());
    getAllPrioritySubmissions.mockResolvedValue([]);
    const user = userEvent.setup();
    render(<ScheduleDetailClient />);
    await waitFor(() =>
      expect(screen.getByText(/Published Schedule/i)).toBeInTheDocument(),
    );
    await user.click(screen.getByRole("button", { name: /\+ Build schedule/i }));
    // Clear the date input to trigger the empty-string fallback
    const dateInput = screen.getByDisplayValue(/^\d{4}-\d{2}-\d{2}$/);
    await user.clear(dateInput);
    await user.click(screen.getByRole("button", { name: /^Publish$/ }));
    await waitFor(() =>
      expect(publishBuiltSchedule).toHaveBeenCalledTimes(1),
    );
    // No uid means increment is never called
    expect(incrementMonthlyBuildCount).not.toHaveBeenCalled();
  });

  it("exports CSV with null schedule_name and no toDate on first_weekday_datetime", async () => {
    const scheduleNoName = baseSchedule({ schedule_name: null });
    getSchedule.mockResolvedValueOnce(scheduleNoName);
    getLatestBuiltSchedule.mockResolvedValueOnce({
      id: "b1",
      schedule: ["shift_a"],
      // first_weekday_datetime is truthy but has no toDate method
      first_weekday_datetime: {},
    });
    const user = userEvent.setup();
    render(<ScheduleDetailClient />);
    await waitFor(() =>
      expect(screen.getByText(/Published Schedule/i)).toBeInTheDocument(),
    );
    await user.click(screen.getByRole("button", { name: /Export CSV/i }));
    await waitFor(() => {
      expect(downloadCsvMock).toHaveBeenCalled();
    });
  });

  it("shows overflow ellipsis when more than 10 build conflicts are returned", async () => {
    getSchedule.mockResolvedValue(baseSchedule());
    getAllPrioritySubmissions.mockResolvedValue([]);
    const manyConflicts = Array.from({ length: 15 }, (_, i) => ({
      dayIndex: i,
      worker: "Ada",
      shifts: ["morning", "night"],
    }));
    mockBuildResult = {
      rows: [],
      firstWeekday: "2026-05-03",
      lastWeekday: "2026-05-09",
      conflicts: manyConflicts,
    };
    const user = userEvent.setup();
    render(<ScheduleDetailClient />);
    await waitFor(() =>
      expect(screen.getByText(/Published Schedule/i)).toBeInTheDocument(),
    );
    await user.click(screen.getByRole("button", { name: /\+ Build schedule/i }));
    await user.click(screen.getByRole("button", { name: /^Publish$/ }));
    await waitFor(() =>
      expect(screen.getByText(/15 same-day conflicts/i)).toBeInTheDocument(),
    );
    expect(screen.getByText(/and 5 more/i)).toBeInTheDocument();
  });
});

// ------------------------------------------------------------
// P1-4 enforcement gates — build-count and user-count.
// ------------------------------------------------------------
describe("ScheduleDetailClient P1-4 enforcement gates", () => {
  it("free tier at build-limit opens the paywall (trigger=build) and skips publishBuiltSchedule", async () => {
    useBillingMock.mockReturnValue(FREE_BILLING);
    getSchedule.mockResolvedValue(baseSchedule());
    getMonthlyBuildCount.mockResolvedValue(5); // at free-tier cap

    const user = userEvent.setup();
    render(<ScheduleDetailClient />);
    await waitFor(() =>
      expect(screen.getByText(/Published Schedule/i)).toBeInTheDocument(),
    );
    await user.click(screen.getByRole("button", { name: /\+ Build schedule/i }));
    await user.click(screen.getByRole("button", { name: /^Publish$/ }));

    // Paywall modal from P1-3 exposes these stable testids regardless of copy.
    const backdrop = await screen.findByTestId("paywall-backdrop");
    expect(backdrop).toBeInTheDocument();
    const banner = screen.getByTestId("paywall-trigger-banner");
    expect(banner.textContent).toContain("paywall.triggerBuild");
    expect(publishBuiltSchedule).not.toHaveBeenCalled();
    expect(incrementMonthlyBuildCount).not.toHaveBeenCalled();
  });

  it("wires the paywall's Continue to startSeatBandCheckout (band + Firebase uid)", async () => {
    // Regression: this call site used to render <PaywallModal> with NO
    // onSelectBand, so Continue was a dead no-op and the user could never buy.
    startSeatBandCheckoutMock.mockResolvedValueOnce({ status: "success" });
    useBillingMock.mockReturnValue(FREE_BILLING);
    getSchedule.mockResolvedValue(baseSchedule());
    getMonthlyBuildCount.mockResolvedValue(5); // at free-tier cap -> opens paywall

    const user = userEvent.setup();
    render(<ScheduleDetailClient />);
    await waitFor(() =>
      expect(screen.getByText(/Published Schedule/i)).toBeInTheDocument(),
    );
    await user.click(screen.getByRole("button", { name: /\+ Build schedule/i }));
    await user.click(screen.getByRole("button", { name: /^Publish$/ }));

    // Paywall opens; pick the 30-user band, then Continue.
    await screen.findByTestId("paywall-backdrop");
    await user.click(screen.getByTestId("paywall-band-30"));
    await user.click(screen.getByTestId("paywall-continue"));

    await waitFor(() =>
      expect(startSeatBandCheckoutMock).toHaveBeenCalledWith(
        { seats: 30, webOfferId: "up-to-30-employees", mobileOfferId: "offering-id-30-users" },
        "u1",
      ),
    );
    // On success the modal closes (redirect already issued by the orchestrator).
    await waitFor(() =>
      expect(screen.queryByTestId("paywall-backdrop")).toBeNull(),
    );
  });

  it("paid tier skips the build-count gate and publishes + increments", async () => {
    // useBillingMock already defaults to UNLIMITED_BILLING (pro/infinity).
    getSchedule.mockResolvedValue(baseSchedule());
    getMonthlyBuildCount.mockResolvedValue(9999); // shouldn't matter

    const user = userEvent.setup();
    render(<ScheduleDetailClient />);
    await waitFor(() =>
      expect(screen.getByText(/Published Schedule/i)).toBeInTheDocument(),
    );
    await user.click(screen.getByRole("button", { name: /\+ Build schedule/i }));
    await user.click(screen.getByRole("button", { name: /^Publish$/ }));

    await waitFor(() =>
      expect(publishBuiltSchedule).toHaveBeenCalledTimes(1),
    );
    expect(incrementMonthlyBuildCount).toHaveBeenCalledWith("u1");
    expect(screen.queryByTestId("paywall-backdrop")).toBeNull();
  });

  it("under the free-tier build limit: publishes + increments, no paywall", async () => {
    useBillingMock.mockReturnValue(FREE_BILLING);
    getSchedule.mockResolvedValue(baseSchedule());
    getMonthlyBuildCount.mockResolvedValue(2); // 2 < 5

    const user = userEvent.setup();
    render(<ScheduleDetailClient />);
    await waitFor(() =>
      expect(screen.getByText(/Published Schedule/i)).toBeInTheDocument(),
    );
    await user.click(screen.getByRole("button", { name: /\+ Build schedule/i }));
    await user.click(screen.getByRole("button", { name: /^Publish$/ }));

    await waitFor(() =>
      expect(publishBuiltSchedule).toHaveBeenCalledTimes(1),
    );
    expect(incrementMonthlyBuildCount).toHaveBeenCalledWith("u1");
    expect(screen.queryByTestId("paywall-backdrop")).toBeNull();
  });

  it("free tier build proceeds when getMonthlyBuildCount rejects (billing hiccup)", async () => {
    useBillingMock.mockReturnValue(FREE_BILLING);
    getSchedule.mockResolvedValue(baseSchedule());
    getMonthlyBuildCount.mockRejectedValueOnce(new Error("network"));

    const user = userEvent.setup();
    render(<ScheduleDetailClient />);
    await waitFor(() =>
      expect(screen.getByText(/Published Schedule/i)).toBeInTheDocument(),
    );
    await user.click(screen.getByRole("button", { name: /\+ Build schedule/i }));
    await user.click(screen.getByRole("button", { name: /^Publish$/ }));

    await waitFor(() =>
      expect(publishBuiltSchedule).toHaveBeenCalledTimes(1),
    );
    expect(incrementMonthlyBuildCount).toHaveBeenCalledWith("u1");
    expect(screen.queryByTestId("paywall-backdrop")).toBeNull();
  });

  it("at user-count limit, Add employee opens the paywall (trigger=user) and skips addEmployee", async () => {
    useBillingMock.mockReturnValue(FREE_BILLING);
    // Free cap = 3 users; pre-seed with 3 to hit the cap.
    const full = baseSchedule({
      employees: [
        {
          employee_name: "Ada",
          employee_email: "ada@x",
          employee_phone: "",
          role: { is_creator: true, is_admin: true, is_worker: false },
          user_ref: { id: "u1", path: "users/u1" },
        },
        {
          employee_name: "Bee",
          employee_email: "b@x",
          employee_phone: "",
          role: { is_creator: false, is_admin: false, is_worker: true },
          user_ref: null,
        },
        {
          employee_name: "Cee",
          employee_email: "c@x",
          employee_phone: "",
          role: { is_creator: false, is_admin: false, is_worker: true },
          user_ref: null,
        },
      ],
    });
    getSchedule.mockResolvedValue(full);

    const user = userEvent.setup();
    render(<ScheduleDetailClient />);
    await waitFor(() =>
      expect(screen.getByText(/Employees \(3\)/)).toBeInTheDocument(),
    );
    await user.click(screen.getByRole("button", { name: /\+ Add employee/i }));
    const nameInput = await screen.findByPlaceholderText(/Full name \*/i);
    await user.type(nameInput, "Dee");
    await user.click(screen.getByRole("button", { name: /^Add employee$/i }));

    const banner = await screen.findByTestId("paywall-trigger-banner");
    expect(banner.textContent).toContain("paywall.triggerUser");
    expect(addEmployee).not.toHaveBeenCalled();
  });

  // Schedule-built confetti (Flutter parity) — fires once from the
  // publishBuiltSchedule() success path, never from load/render state.
  describe("schedule-built confetti", () => {
    beforeEach(() => {
      // jsdom has no canvas 2d context; returning null makes the burst effect
      // bail early (the component handles a null ctx) without jsdom noise.
      vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
    });

    async function buildOnce(user: ReturnType<typeof userEvent.setup>) {
      await waitFor(() =>
        expect(screen.getByText(/Published Schedule/i)).toBeInTheDocument(),
      );
      await user.click(
        screen.getByRole("button", { name: /\+ Build schedule/i }),
      );
      await user.click(screen.getByRole("button", { name: /^Publish$/ }));
    }

    it("does not show on plain page load and fires once on a successful build", async () => {
      getSchedule.mockResolvedValue(baseSchedule());
      publishBuiltSchedule.mockResolvedValueOnce(undefined);
      const user = userEvent.setup();
      render(<ScheduleDetailClient />);
      await waitFor(() =>
        expect(screen.getByText(/Published Schedule/i)).toBeInTheDocument(),
      );
      // Mount / sign-in / hard-load: no celebration.
      expect(screen.queryByTestId("schedule-built-celebration")).toBeNull();

      await user.click(
        screen.getByRole("button", { name: /\+ Build schedule/i }),
      );
      await user.click(screen.getByRole("button", { name: /^Publish$/ }));
      await waitFor(() =>
        expect(publishBuiltSchedule).toHaveBeenCalledTimes(1),
      );
      // Exactly one celebration overlay, and it does not block the page.
      const overlays = screen.getAllByTestId("schedule-built-celebration");
      expect(overlays).toHaveLength(1);
      expect(overlays[0]).toHaveClass("pointer-events-none");
    });

    it("does not fire when the build fails", async () => {
      getSchedule.mockResolvedValue(baseSchedule());
      publishBuiltSchedule.mockRejectedValueOnce(new Error("publish failed"));
      const user = userEvent.setup();
      render(<ScheduleDetailClient />);
      await buildOnce(user);
      await waitFor(() =>
        expect(screen.getByText(/Failed to build schedule/i)).toBeInTheDocument(),
      );
      expect(screen.queryByTestId("schedule-built-celebration")).toBeNull();
    });

    // Real timers: RTL's waitFor can't advance vitest fake timers (it only
    // detects jest's), so we let the 2.6s auto-dismiss elapse for real.
    it("auto-dismisses and does not re-fire on re-render", async () => {
      getSchedule.mockResolvedValue(baseSchedule());
      publishBuiltSchedule.mockResolvedValueOnce(undefined);
      const user = userEvent.setup();
      const { rerender } = render(<ScheduleDetailClient />);
      await buildOnce(user);
      await waitFor(() =>
        expect(
          screen.getByTestId("schedule-built-celebration"),
        ).toBeInTheDocument(),
      );
      // Burst plays out (~2.6s) → auto-dismiss.
      await waitFor(
        () =>
          expect(screen.queryByTestId("schedule-built-celebration")).toBeNull(),
        { timeout: 4000 },
      );
      // Re-render after dismissal: the trigger is the build-success event
      // only (state guard), so nothing re-fires.
      rerender(<ScheduleDetailClient />);
      expect(screen.queryByTestId("schedule-built-celebration")).toBeNull();
    }, 10000);
  });
});
