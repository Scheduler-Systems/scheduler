import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const pushMock = vi.fn();
const paramsMock: { id: string; requestId: string } = {
  id: "sid1",
  requestId: "rc1",
};
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

const getScheduleChangeRequest = vi.fn();
const updateScheduleChangeRequestStatus = vi.fn();
vi.mock("@/lib/requests", () => ({
  getScheduleChangeRequest: (id: string) => getScheduleChangeRequest(id),
  updateScheduleChangeRequestStatus: (...args: unknown[]) =>
    updateScheduleChangeRequestStatus(...args),
}));

const getSchedule = vi.fn();
vi.mock("@/lib/firestore", () => ({
  getSchedule: (id: string) => getSchedule(id),
}));

const RequestDetailPage = (await import("./page")).default;

function baseSchedule() {
  return {
    id: "sid1",
    schedule_name: "Clinic",
    employees: [
      {
        employee_name: "Ada",
        employee_email: "ada@x",
        employee_phone: "",
        role: { is_worker: true },
        user_ref: { id: "u1", path: "users/u1" },
      },
      {
        employee_name: "Bob",
        employee_email: "bob@x",
        employee_phone: "",
        role: { is_worker: true },
        user_ref: { id: "u2", path: "users/u2" },
      },
    ],
    current_priorities: [],
    next_schedule: [],
    schedule_settings: null,
    sid: "",
  };
}

function pendingRequest() {
  return {
    id: "rc1",
    DateTime: { toDate: () => new Date("2026-05-01T08:00:00Z") },
    Reason: "Swap with Ada: family trip",
    userId: "u2",
    status: "sent",
    scheduleId: "sid1",
  };
}

describe("RequestDetailPage", () => {
  beforeEach(() => {
    pushMock.mockReset();
    getScheduleChangeRequest.mockReset();
    updateScheduleChangeRequestStatus.mockReset();
    getSchedule.mockReset();
    useAuthMock.mockReturnValue({
      user: { uid: "u1", email: "ada@x", displayName: "Ada" },
    });
  });

  it("renders requester, target, shift and reason", async () => {
    getSchedule.mockResolvedValueOnce(baseSchedule());
    getScheduleChangeRequest.mockResolvedValueOnce(pendingRequest());
    render(<RequestDetailPage />);
    await waitFor(() =>
      expect(
        screen.getByRole("heading", { name: /Request detail/i })
      ).toBeInTheDocument()
    );
    // Requester name resolved from uid u2 -> Bob
    expect(screen.getByText(/Bob/)).toBeInTheDocument();
    // Target name from embedded marker
    expect(screen.getByText(/Ada/)).toBeInTheDocument();
    // Reason body (without the "Swap with X:" prefix)
    expect(screen.getByText(/family trip/)).toBeInTheDocument();
  });

  it("approves by calling updateScheduleChangeRequestStatus('accepted')", async () => {
    getSchedule.mockResolvedValueOnce(baseSchedule());
    getScheduleChangeRequest.mockResolvedValueOnce(pendingRequest());
    updateScheduleChangeRequestStatus.mockResolvedValueOnce(undefined);
    const user = userEvent.setup();
    render(<RequestDetailPage />);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /^Approve$/i })
      ).toBeInTheDocument()
    );
    await user.click(screen.getByRole("button", { name: /^Approve$/i }));
    await waitFor(() =>
      expect(updateScheduleChangeRequestStatus).toHaveBeenCalledWith(
        "rc1",
        "accepted",
        "u1"
      )
    );
    await waitFor(() =>
      expect(pushMock).toHaveBeenCalledWith("/schedules/sid1/requests")
    );
  });

  it("rejects by calling updateScheduleChangeRequestStatus('rejected')", async () => {
    getSchedule.mockResolvedValueOnce(baseSchedule());
    getScheduleChangeRequest.mockResolvedValueOnce(pendingRequest());
    updateScheduleChangeRequestStatus.mockResolvedValueOnce(undefined);
    const user = userEvent.setup();
    render(<RequestDetailPage />);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /^Reject$/i })
      ).toBeInTheDocument()
    );
    await user.click(screen.getByRole("button", { name: /^Reject$/i }));
    await waitFor(() =>
      expect(updateScheduleChangeRequestStatus).toHaveBeenCalledWith(
        "rc1",
        "rejected",
        "u1"
      )
    );
    await waitFor(() =>
      expect(pushMock).toHaveBeenCalledWith("/schedules/sid1/requests")
    );
  });

  it("disables both buttons when the request is already accepted", async () => {
    getSchedule.mockResolvedValueOnce(baseSchedule());
    getScheduleChangeRequest.mockResolvedValueOnce({
      ...pendingRequest(),
      status: "accepted",
    });
    render(<RequestDetailPage />);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /^Approve$/i })
      ).toBeInTheDocument()
    );
    expect(
      screen.getByRole("button", { name: /^Approve$/i })
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: /^Reject$/i })
    ).toBeDisabled();
    // Status badge reads "Approved"
    expect(screen.getByText(/^Approved$/i)).toBeInTheDocument();
  });

  it("disables both buttons when the request is already rejected", async () => {
    getSchedule.mockResolvedValueOnce(baseSchedule());
    getScheduleChangeRequest.mockResolvedValueOnce({
      ...pendingRequest(),
      status: "rejected",
    });
    render(<RequestDetailPage />);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /^Approve$/i })
      ).toBeInTheDocument()
    );
    expect(
      screen.getByRole("button", { name: /^Approve$/i })
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: /^Reject$/i })
    ).toBeDisabled();
    expect(screen.getByText(/^Rejected$/i)).toBeInTheDocument();
  });

  it("shows an error banner when approve rejects", async () => {
    getSchedule.mockResolvedValueOnce(baseSchedule());
    getScheduleChangeRequest.mockResolvedValueOnce(pendingRequest());
    updateScheduleChangeRequestStatus.mockRejectedValueOnce(new Error("boom"));
    const user = userEvent.setup();
    render(<RequestDetailPage />);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /^Approve$/i })
      ).toBeInTheDocument()
    );
    await user.click(screen.getByRole("button", { name: /^Approve$/i }));
    await waitFor(() =>
      expect(screen.getByRole("alert")).toBeInTheDocument()
    );
    expect(pushMock).not.toHaveBeenCalled();
  });

  it("renders not-found state when the request is missing", async () => {
    getSchedule.mockResolvedValueOnce(baseSchedule());
    getScheduleChangeRequest.mockResolvedValueOnce(null);
    render(<RequestDetailPage />);
    await waitFor(() =>
      expect(screen.getByText(/Request not found/i)).toBeInTheDocument()
    );
  });
});
