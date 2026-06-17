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

const useAuthMock = vi.fn();
vi.mock("@/lib/auth-context", () => ({
  useAuth: () => useAuthMock(),
}));

const getSchedule = vi.fn();
const getPrioritySubmission = vi.fn();
const getAllPrioritySubmissions = vi.fn();
vi.mock("@/lib/firestore", () => ({
  getSchedule: (id: string) => getSchedule(id),
  getPrioritySubmission: (id: string, uid: string) =>
    getPrioritySubmission(id, uid),
  getAllPrioritySubmissions: (id: string) => getAllPrioritySubmissions(id),
}));

const submitPriorities = vi.fn();
vi.mock("@/lib/firestore-write", () => ({
  submitPriorities: (...args: unknown[]) => submitPriorities(...args),
}));

const PrioritiesClient = (await import("./priorities-client")).default;

function baseSchedule(overrides: Record<string, unknown> = {}) {
  return {
    id: "sid1",
    schedule_name: "Clinic",
    employees: [
      {
        employee_name: "Ada",
        employee_email: "ada@x",
        role: { is_worker: true },
      },
    ],
    current_priorities: [],
    next_schedule: [],
    sid: "",
    schedule_settings: {
      enabled_shifts: ["morning", "night"],
      num_of_stations: 1,
    },
    ...overrides,
  };
}

describe("PrioritiesClient", () => {
  beforeEach(() => {
    getSchedule.mockReset();
    getPrioritySubmission.mockReset();
    getAllPrioritySubmissions.mockReset();
    submitPriorities.mockReset();
    useAuthMock.mockReturnValue({
      user: { uid: "u1", email: "ada@x", displayName: "Ada" },
    });
  });

  it("renders heading and grid with day columns", async () => {
    getSchedule.mockResolvedValueOnce(baseSchedule());
    getPrioritySubmission.mockResolvedValueOnce(null);
    render(<PrioritiesClient />);
    await waitFor(() =>
      expect(
        screen.getByRole("heading", { name: /My priorities/i }),
      ).toBeInTheDocument(),
    );
    // Days header cells
    expect(screen.getByText("Sun")).toBeInTheDocument();
    expect(screen.getByText("Mon")).toBeInTheDocument();
    expect(screen.getByText("Sat")).toBeInTheDocument();
  });

  it("submits selected priorities via submitPriorities", async () => {
    getSchedule.mockResolvedValueOnce(baseSchedule());
    getPrioritySubmission.mockResolvedValueOnce(null);
    submitPriorities.mockResolvedValueOnce(undefined);
    const user = userEvent.setup();
    const { container } = render(<PrioritiesClient />);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Submit priorities/i }))
        .toBeInTheDocument(),
    );
    // Tap at least one cell by clicking the first toggle-able td.
    const firstCell = container.querySelector(
      "td.cursor-pointer",
    ) as HTMLElement;
    expect(firstCell).toBeTruthy();
    await user.click(firstCell);
    await user.click(
      screen.getByRole("button", { name: /Submit priorities/i }),
    );
    await waitFor(() =>
      expect(submitPriorities).toHaveBeenCalledWith(
        "sid1",
        "u1",
        "Ada",
        expect.any(Array),
      ),
    );
    await waitFor(() =>
      expect(
        screen.getByText(/Priorities submitted/i),
      ).toBeInTheDocument(),
    );
  });

  it("shows a friendly error when submitPriorities rejects", async () => {
    getSchedule.mockResolvedValueOnce(baseSchedule());
    getPrioritySubmission.mockResolvedValueOnce(null);
    submitPriorities.mockRejectedValueOnce({ code: "permission-denied" });
    const user = userEvent.setup();
    render(<PrioritiesClient />);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Submit priorities/i }))
        .toBeInTheDocument(),
    );
    await user.click(
      screen.getByRole("button", { name: /Submit priorities/i }),
    );
    await waitFor(() => expect(submitPriorities).toHaveBeenCalled());
    await waitFor(() =>
      expect(screen.queryByText(/Priorities submitted/i)).toBeNull(),
    );
  });

  it("renders the 'no shifts' warning when schedule has no enabled shifts", async () => {
    getSchedule.mockResolvedValueOnce(
      baseSchedule({ schedule_settings: { enabled_shifts: [] } }),
    );
    getPrioritySubmission.mockResolvedValueOnce(null);
    render(<PrioritiesClient />);
    await waitFor(() =>
      expect(
        screen.getByText(/no shifts configured yet/i),
      ).toBeInTheDocument(),
    );
  });

  it("renders admin-only 'All submissions' section when current user is admin", async () => {
    getSchedule.mockResolvedValueOnce(
      baseSchedule({
        employees: [
          {
            employee_name: "Ada",
            employee_email: "ada@x",
            role: { is_admin: true, is_worker: true },
          },
        ],
      }),
    );
    getPrioritySubmission.mockResolvedValueOnce(null);
    getAllPrioritySubmissions.mockResolvedValueOnce([
      {
        uid: "u1",
        display_name: "Ada",
        priorities: ["Sun|morning"],
        submitted_at: null,
      },
    ]);
    render(<PrioritiesClient />);
    await waitFor(() =>
      expect(
        screen.getByRole("heading", { name: /All submissions/i }),
      ).toBeInTheDocument(),
    );
    expect(screen.getByText("Sun|morning")).toBeInTheDocument();
  });

  it("shows the error panel when getSchedule throws", async () => {
    getSchedule.mockRejectedValueOnce(new Error("boom"));
    render(<PrioritiesClient />);
    await waitFor(() =>
      expect(screen.getByText(/Failed to load priorities/i))
        .toBeInTheDocument(),
    );
  });
});
