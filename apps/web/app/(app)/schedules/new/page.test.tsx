import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock, replace: vi.fn() }),
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

// P1-4 billing context — mocked so each test can flip tier/limits. The
// default in beforeEach keeps the pre-P1-4 flows under their cap (high
// station limit); gate-specific tests override with FREE_BILLING.
const useBillingMock = vi.fn();
vi.mock("@/lib/billing/billing-context", () => ({
  useBilling: () => useBillingMock(),
}));

// PaywallModal uses useI18n; stub returns keys verbatim.
vi.mock("@/lib/i18n-context", () => ({
  useI18n: () => ({
    t: (key: string) => key,
    locale: "en",
    setLocale: vi.fn(),
  }),
}));

const getUserSchedules = vi.fn();
vi.mock("@/lib/firestore", () => ({
  getUserSchedules: (...a: unknown[]) => getUserSchedules(...a),
}));

const createSchedule = vi.fn();
const updateScheduleSettings = vi.fn();
class ScheduleNameTakenError extends Error {
  constructor(public readonly scheduleName: string) {
    super(`A schedule named "${scheduleName}" already exists`);
    this.name = "ScheduleNameTakenError";
  }
}
vi.mock("@/lib/firestore-write", () => ({
  createSchedule: (...args: unknown[]) => createSchedule(...args),
  updateScheduleSettings: (...args: unknown[]) => updateScheduleSettings(...args),
  ScheduleNameTakenError,
}));

// Seat-band hosted-checkout orchestrator. Mocked so the wiring test can assert
// the paywall's Continue actually starts checkout (it used to be a dead no-op).
const startSeatBandCheckoutMock = vi.fn();
vi.mock("@/lib/billing/purchase", () => ({
  startSeatBandCheckout: (...args: unknown[]) =>
    startSeatBandCheckoutMock(...args),
}));

const NewSchedulePage = (await import("./page")).default;

const UNLIMITED_BILLING = {
  tier: "pro" as const,
  limits: {
    maxStations: 999,
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

function fakeSchedule(id: string, schedule_name?: string) {
  return {
    id,
    schedule_name: schedule_name ?? `S${id}`,
    employees: [],
    current_priorities: [],
    schedule_settings: null,
    sid: "",
    next_schedule: [],
  };
}

beforeEach(() => {
  pushMock.mockReset();
  createSchedule.mockReset();
  updateScheduleSettings.mockReset();
  getUserSchedules.mockReset();
  startSeatBandCheckoutMock.mockReset();
  useAuthMock.mockReturnValue({
    user: { uid: "u1", email: "u@x", displayName: "Ada" },
  });
  useBillingMock.mockReturnValue(UNLIMITED_BILLING);
  getUserSchedules.mockResolvedValue([]);
});

describe("NewSchedulePage", () => {
  it("renders heading and submit button + shift toggles", () => {
    render(<NewSchedulePage />);
    expect(
      screen.getByRole("heading", { name: /New Schedule/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Create schedule/i }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Morning$/i }))
      .toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Afternoon$/i }))
      .toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Night$/i }))
      .toBeInTheDocument();
  });

  it("creates the schedule and routes to its detail page", async () => {
    createSchedule.mockResolvedValueOnce("sid42");
    const user = userEvent.setup();
    render(<NewSchedulePage />);
    await user.type(
      screen.getByPlaceholderText(/Weekly Clinic Rota/i),
      "My Roster",
    );
    await user.click(screen.getByRole("button", { name: /Create schedule/i }));
    await waitFor(() =>
      expect(createSchedule).toHaveBeenCalledWith(
        expect.objectContaining({
          scheduleName: "My Roster",
          numOfStations: 1,
          enabledShifts: expect.arrayContaining(["morning", "afternoon"]),
          ownerUid: "u1",
          ownerEmail: "u@x",
        }),
      ),
    );
    await waitFor(() =>
      expect(pushMock).toHaveBeenCalledWith("/schedules/sid42"),
    );
    // No hours entered → no settings update call
    expect(updateScheduleSettings).not.toHaveBeenCalled();
  });

  it("calls updateScheduleSettings when hours are filled in", async () => {
    createSchedule.mockResolvedValueOnce("sid77");
    updateScheduleSettings.mockResolvedValueOnce(undefined);
    const user = userEvent.setup();
    render(<NewSchedulePage />);
    await user.type(
      screen.getByPlaceholderText(/Weekly Clinic Rota/i),
      "Roster",
    );
    await user.type(
      screen.getByPlaceholderText("06:00–14:00"),
      "06-14",
    );
    await user.click(screen.getByRole("button", { name: /Create schedule/i }));
    await waitFor(() =>
      expect(updateScheduleSettings).toHaveBeenCalledWith(
        "sid77",
        expect.objectContaining({
          morning_hours: "06-14",
        }),
      ),
    );
  });

  it("shows the required-name error when the form is submitted empty", async () => {
    const user = userEvent.setup();
    render(<NewSchedulePage />);
    await user.click(screen.getByRole("button", { name: /Create schedule/i }));
    await waitFor(() =>
      expect(
        screen.getByText(/Schedule name is required/i),
      ).toBeInTheDocument(),
    );
    expect(createSchedule).not.toHaveBeenCalled();
  });

  it("shows the no-shift error when all shift toggles are off", async () => {
    const user = userEvent.setup();
    render(<NewSchedulePage />);
    await user.type(
      screen.getByPlaceholderText(/Weekly Clinic Rota/i),
      "Roster",
    );
    // default has morning+afternoon enabled — toggle them off
    await user.click(screen.getByRole("button", { name: /^Morning$/i }));
    await user.click(screen.getByRole("button", { name: /^Afternoon$/i }));
    await user.click(screen.getByRole("button", { name: /Create schedule/i }));
    await waitFor(() =>
      expect(
        screen.getByText(/Enable at least one shift/i),
      ).toBeInTheDocument(),
    );
    expect(createSchedule).not.toHaveBeenCalled();
  });

  it("surfaces a generic error when createSchedule rejects", async () => {
    createSchedule.mockRejectedValueOnce(new Error("boom"));
    const user = userEvent.setup();
    render(<NewSchedulePage />);
    await user.type(
      screen.getByPlaceholderText(/Weekly Clinic Rota/i),
      "Roster",
    );
    await user.click(screen.getByRole("button", { name: /Create schedule/i }));
    await waitFor(() =>
      expect(
        screen.getByText(/Failed to create schedule/i),
      ).toBeInTheDocument(),
    );
  });

  it("shows the duplicate-name message when createSchedule throws ScheduleNameTakenError (race lost)", async () => {
    // Pre-check passes (no existing schedules), but the transactional uniqueness
    // guard rejects — e.g. a concurrent create won the race.
    getUserSchedules.mockResolvedValue([]);
    createSchedule.mockRejectedValueOnce(new ScheduleNameTakenError("Roster"));
    const user = userEvent.setup();
    render(<NewSchedulePage />);
    await user.type(
      screen.getByPlaceholderText(/Weekly Clinic Rota/i),
      "Roster",
    );
    await user.click(screen.getByRole("button", { name: /Create schedule/i }));
    await waitFor(() =>
      expect(
        screen.getByText(/A schedule with this name already exists/i),
      ).toBeInTheDocument(),
    );
  });
});

// ------------------------------------------------------------
// P1-4 enforcement — station-count gate.
// ------------------------------------------------------------
describe("NewSchedulePage P1-4 station-count gate", () => {
  it("opens the paywall (trigger=station) at the free-tier cap and skips createSchedule", async () => {
    useBillingMock.mockReturnValue(FREE_BILLING);
    getUserSchedules.mockResolvedValue([fakeSchedule("s1")]); // 1 = free cap

    const user = userEvent.setup();
    render(<NewSchedulePage />);
    await user.type(
      screen.getByPlaceholderText(/Weekly Clinic Rota/i),
      "My Schedule",
    );
    await user.click(screen.getByRole("button", { name: /Create schedule/i }));

    const backdrop = await screen.findByTestId("paywall-backdrop");
    expect(backdrop).toBeInTheDocument();
    const banner = screen.getByTestId("paywall-trigger-banner");
    expect(banner.textContent).toContain("paywall.triggerStation");
    expect(createSchedule).not.toHaveBeenCalled();
    expect(pushMock).not.toHaveBeenCalled();
  });

  it("wires the paywall's Continue to startSeatBandCheckout (band + Firebase uid)", async () => {
    // Regression: this call site used to render <PaywallModal> with NO
    // onSelectBand, so Continue was a dead no-op and the user could never buy.
    startSeatBandCheckoutMock.mockResolvedValueOnce({ status: "success" });
    useBillingMock.mockReturnValue(FREE_BILLING);
    getUserSchedules.mockResolvedValue([fakeSchedule("s1")]); // at free cap

    const user = userEvent.setup();
    render(<NewSchedulePage />);
    await user.type(
      screen.getByPlaceholderText(/Weekly Clinic Rota/i),
      "My Schedule",
    );
    await user.click(screen.getByRole("button", { name: /Create schedule/i }));

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

  it("creates normally when under the free-tier cap (0 existing)", async () => {
    useBillingMock.mockReturnValue(FREE_BILLING);
    getUserSchedules.mockResolvedValue([]); // 0 < 1
    createSchedule.mockResolvedValueOnce("sid-new");

    const user = userEvent.setup();
    render(<NewSchedulePage />);
    await user.type(
      screen.getByPlaceholderText(/Weekly Clinic Rota/i),
      "My Schedule",
    );
    await user.click(screen.getByRole("button", { name: /Create schedule/i }));

    await waitFor(() =>
      expect(createSchedule).toHaveBeenCalledTimes(1),
    );
    expect(pushMock).toHaveBeenCalledWith("/schedules/sid-new");
    expect(screen.queryByTestId("paywall-backdrop")).toBeNull();
  });

  it("pro tier with a higher maxStations allows more schedules", async () => {
    useBillingMock.mockReturnValue({
      ...UNLIMITED_BILLING,
      limits: {
        maxStations: 5,
        maxUsers: 50,
        maxBuildsPerMonth: Number.POSITIVE_INFINITY,
      },
    });
    getUserSchedules.mockResolvedValue([
      fakeSchedule("s1"),
      fakeSchedule("s2"),
    ]); // 2 < 5
    createSchedule.mockResolvedValueOnce("sid3");

    const user = userEvent.setup();
    render(<NewSchedulePage />);
    await user.type(
      screen.getByPlaceholderText(/Weekly Clinic Rota/i),
      "Another",
    );
    await user.click(screen.getByRole("button", { name: /Create schedule/i }));
    await waitFor(() =>
      expect(createSchedule).toHaveBeenCalledTimes(1),
    );
    expect(screen.queryByTestId("paywall-backdrop")).toBeNull();
  });
});

// ------------------------------------------------------------
// Duplicate schedule name prevention.
// ------------------------------------------------------------
describe("NewSchedulePage duplicate name check", () => {
  it("shows duplicate-name error and does NOT call createSchedule when exact name matches an existing schedule", async () => {
    getUserSchedules.mockResolvedValue([
      fakeSchedule("s1", "Weekly Clinic Rota"),
    ]);

    const user = userEvent.setup();
    render(<NewSchedulePage />);
    await user.type(
      screen.getByPlaceholderText(/Weekly Clinic Rota/i),
      "Weekly Clinic Rota",
    );
    await user.click(screen.getByRole("button", { name: /Create schedule/i }));

    await waitFor(() =>
      expect(
        screen.getByText(
          /A schedule with this name already exists\. Please choose a different name\./i,
        ),
      ).toBeInTheDocument(),
    );
    expect(createSchedule).not.toHaveBeenCalled();
    expect(pushMock).not.toHaveBeenCalled();
  });

  it("blocks creation when the name differs only in casing (case-insensitive check)", async () => {
    getUserSchedules.mockResolvedValue([
      fakeSchedule("s1", "weekly clinic rota"),
    ]);

    const user = userEvent.setup();
    render(<NewSchedulePage />);
    // Uppercase version of the existing name
    await user.type(
      screen.getByPlaceholderText(/Weekly Clinic Rota/i),
      "WEEKLY CLINIC ROTA",
    );
    await user.click(screen.getByRole("button", { name: /Create schedule/i }));

    await waitFor(() =>
      expect(
        screen.getByText(
          /A schedule with this name already exists\. Please choose a different name\./i,
        ),
      ).toBeInTheDocument(),
    );
    expect(createSchedule).not.toHaveBeenCalled();
    expect(pushMock).not.toHaveBeenCalled();
  });

  it("creates normally when the name does not match any existing schedule", async () => {
    getUserSchedules.mockResolvedValue([
      fakeSchedule("s1", "Existing Schedule"),
    ]);
    createSchedule.mockResolvedValueOnce("sid-unique");

    const user = userEvent.setup();
    render(<NewSchedulePage />);
    await user.type(
      screen.getByPlaceholderText(/Weekly Clinic Rota/i),
      "Brand New Schedule",
    );
    await user.click(screen.getByRole("button", { name: /Create schedule/i }));

    await waitFor(() =>
      expect(createSchedule).toHaveBeenCalledTimes(1),
    );
    expect(pushMock).toHaveBeenCalledWith("/schedules/sid-unique");
    expect(
      screen.queryByText(/already exists/i),
    ).not.toBeInTheDocument();
  });

  it("proceeds with creation when getUserSchedules throws (non-fatal read failure)", async () => {
    getUserSchedules.mockRejectedValueOnce(new Error("network error"));
    createSchedule.mockResolvedValueOnce("sid-fallback");

    const user = userEvent.setup();
    render(<NewSchedulePage />);
    await user.type(
      screen.getByPlaceholderText(/Weekly Clinic Rota/i),
      "My Schedule",
    );
    await user.click(screen.getByRole("button", { name: /Create schedule/i }));

    await waitFor(() =>
      expect(createSchedule).toHaveBeenCalledTimes(1),
    );
    expect(pushMock).toHaveBeenCalledWith("/schedules/sid-fallback");
  });
});
