import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

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

const getUserSchedules = vi.fn();
vi.mock("@/lib/firestore", () => ({
  getUserSchedules: (uid: string) => getUserSchedules(uid),
}));

const SchedulesPage = (await import("./page")).default;

describe("SchedulesPage", () => {
  beforeEach(() => {
    getUserSchedules.mockReset();
    useAuthMock.mockReturnValue({ user: { uid: "u1" } });
  });

  it("renders heading and empty state when the user has no schedules", async () => {
    getUserSchedules.mockResolvedValueOnce([]);
    render(<SchedulesPage />);
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: /^Schedules$/i }))
        .toBeInTheDocument(),
    );
    expect(screen.getByText(/No schedules found/i)).toBeInTheDocument();
  });

  it("renders schedule cards with employee counts and shift counts", async () => {
    getUserSchedules.mockResolvedValueOnce([
      {
        id: "s1",
        schedule_name: "Clinic",
        employees: [{ employee_name: "A" }, { employee_name: "B" }],
        schedule_settings: {
          enabled_shifts: ["morning", "night"],
        },
      },
      {
        id: "s2",
        schedule_name: "",
        employees: [{ employee_name: "A" }],
        schedule_settings: { enabled_shifts: [] },
      },
    ]);
    render(<SchedulesPage />);
    await waitFor(() =>
      expect(screen.getByText("Clinic")).toBeInTheDocument(),
    );
    expect(screen.getByText("Unnamed schedule")).toBeInTheDocument();
    expect(screen.getByText(/2 employees/)).toBeInTheDocument();
    expect(screen.getByText(/1 employee$/)).toBeInTheDocument();
    expect(screen.getByText(/2 shifts configured/)).toBeInTheDocument();
  });

  it("shows a friendly error when getUserSchedules rejects", async () => {
    getUserSchedules.mockRejectedValueOnce(new Error("boom"));
    render(<SchedulesPage />);
    await waitFor(() =>
      expect(screen.getByText(/Failed to load schedules/i))
        .toBeInTheDocument(),
    );
  });

  it("exposes a 'New schedule' link with accessible name", async () => {
    getUserSchedules.mockResolvedValueOnce([]);
    render(<SchedulesPage />);
    await waitFor(() =>
      expect(screen.getByRole("link", { name: /New schedule/i }))
        .toBeInTheDocument(),
    );
  });
});
