import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const paramsMock: { id: string } = { id: "sid1" };
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
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

const getScheduleChangeRequestsForSchedule = vi.fn();
vi.mock("@/lib/requests", () => ({
  getScheduleChangeRequestsForSchedule: (id: string) =>
    getScheduleChangeRequestsForSchedule(id),
}));

const getSchedule = vi.fn();
vi.mock("@/lib/firestore", () => ({
  getSchedule: (id: string) => getSchedule(id),
}));

const useAuthMock = vi.fn();
vi.mock("@/lib/auth-context", () => ({
  useAuth: () => useAuthMock(),
}));

const RequestsInboxPage = (await import("./page")).default;

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
      enabled_shifts: ["morning"],
      num_of_stations: 1,
      submission_deadline: null,
    },
    sid: "",
  };
}

function ts(iso: string) {
  return { toDate: () => new Date(iso) };
}

describe("RequestsInboxPage", () => {
  beforeEach(() => {
    getScheduleChangeRequestsForSchedule.mockReset();
    getSchedule.mockReset();
    useAuthMock.mockReturnValue({
      user: { uid: "viewer", displayName: "Viewer", email: "viewer@x" },
    });
  });

  it("renders the empty state when there are no requests", async () => {
    getSchedule.mockResolvedValueOnce(baseSchedule());
    getScheduleChangeRequestsForSchedule.mockResolvedValueOnce([]);
    render(<RequestsInboxPage />);
    await waitFor(() =>
      expect(screen.getByText(/No requests yet/i)).toBeInTheDocument()
    );
  });

  it("splits pending vs resolved across tabs", async () => {
    getSchedule.mockResolvedValueOnce(baseSchedule());
    getScheduleChangeRequestsForSchedule.mockResolvedValueOnce([
      {
        id: "r1",
        DateTime: ts("2026-05-01T08:00:00Z"),
        Reason: "Swap with Bob: trip",
        userId: "u1",
        status: "sent",
        scheduleId: "sid1",
      },
      {
        id: "r2",
        DateTime: ts("2026-04-30T08:00:00Z"),
        Reason: "Swap with Ada: doctor",
        userId: "u2",
        status: "accepted",
        scheduleId: "sid1",
      },
      {
        id: "r3",
        DateTime: ts("2026-04-29T08:00:00Z"),
        Reason: "family",
        userId: "u2",
        status: "rejected",
        scheduleId: "sid1",
      },
    ]);
    const user = userEvent.setup();
    render(<RequestsInboxPage />);
    await waitFor(() =>
      expect(
        screen.getByRole("heading", { name: /Shift change requests/i })
      ).toBeInTheDocument()
    );
    // Pending tab (default) — only r1
    const list = await screen.findByRole("list");
    expect(within(list).getAllByRole("listitem")).toHaveLength(1);
    expect(within(list).getByText(/Ada/)).toBeInTheDocument();
    // Click Resolved tab — now shows r2 + r3
    await user.click(screen.getByRole("tab", { name: /Resolved/i }));
    const resolvedList = await screen.findByRole("list");
    expect(within(resolvedList).getAllByRole("listitem")).toHaveLength(2);
    // Approved + Rejected labels
    expect(within(resolvedList).getByText(/Approved/i)).toBeInTheDocument();
    expect(within(resolvedList).getByText(/Rejected/i)).toBeInTheDocument();
  });

  it("resolves employee name for the requester", async () => {
    getSchedule.mockResolvedValueOnce(baseSchedule());
    getScheduleChangeRequestsForSchedule.mockResolvedValueOnce([
      {
        id: "r1",
        DateTime: ts("2026-05-01T08:00:00Z"),
        Reason: "Swap with Ada: x",
        userId: "u2",
        status: "sent",
        scheduleId: "sid1",
      },
    ]);
    render(<RequestsInboxPage />);
    await waitFor(() =>
      expect(screen.getByRole("list")).toBeInTheDocument()
    );
    // Requester = Bob (uid u2)
    expect(screen.getByText(/Bob/)).toBeInTheDocument();
    // Target = Ada
    expect(screen.getByText(/Ada/)).toBeInTheDocument();
  });

  // Regression: a requester who is the signed-in viewer but has no linked employee
  // record (e.g. the schedule creator) must show their name, never a raw auth uid.
  it("resolves the signed-in viewer's own name instead of a raw uid", async () => {
    useAuthMock.mockReturnValue({
      user: { uid: "ucreator", displayName: "Demo Creator", email: "demo@x" },
    });
    getSchedule.mockResolvedValueOnce(baseSchedule()); // employees are u1/u2 only
    getScheduleChangeRequestsForSchedule.mockResolvedValueOnce([
      {
        id: "r1",
        DateTime: ts("2026-05-01T08:00:00Z"),
        Reason: "Swap with Ada: x",
        userId: "ucreator",
        status: "sent",
        scheduleId: "sid1",
      },
    ]);
    render(<RequestsInboxPage />);
    await waitFor(() =>
      expect(screen.getByRole("list")).toBeInTheDocument(),
    );
    expect(screen.getByText(/Demo Creator/)).toBeInTheDocument();
    expect(screen.queryByText("ucreator")).toBeNull();
  });

  it("each row is a link to the request detail page", async () => {
    getSchedule.mockResolvedValueOnce(baseSchedule());
    getScheduleChangeRequestsForSchedule.mockResolvedValueOnce([
      {
        id: "r1",
        DateTime: ts("2026-05-01T08:00:00Z"),
        Reason: "x",
        userId: "u1",
        status: "sent",
        scheduleId: "sid1",
      },
    ]);
    render(<RequestsInboxPage />);
    await waitFor(() =>
      expect(screen.getByRole("list")).toBeInTheDocument()
    );
    const rowLink = screen
      .getAllByRole("link")
      .find((a) => a.getAttribute("href") === "/schedules/sid1/requests/r1");
    expect(rowLink).toBeDefined();
  });
});
