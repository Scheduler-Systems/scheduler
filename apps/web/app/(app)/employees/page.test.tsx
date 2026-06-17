import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

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

const EmployeesPage = (await import("./page")).default;

describe("EmployeesPage", () => {
  beforeEach(() => {
    getUserSchedules.mockReset();
    useAuthMock.mockReturnValue({ user: { uid: "u1" } });
  });

  it("renders heading and empty state when no schedules are present", async () => {
    getUserSchedules.mockResolvedValueOnce([]);
    render(<EmployeesPage />);
    await waitFor(() =>
      expect(
        screen.getByRole("heading", { name: /Employees/i }),
      ).toBeInTheDocument(),
    );
    expect(screen.getByText(/No employees found/i)).toBeInTheDocument();
  });

  it("lists employees and filters them via the search box", async () => {
    getUserSchedules.mockResolvedValueOnce([
      {
        id: "s1",
        schedule_name: "Clinic",
        employees: [
          {
            employee_name: "Ada Lovelace",
            employee_email: "ada@x",
            employee_phone: "555",
            role: { is_worker: true },
          },
          {
            employee_name: "Bob Smith",
            employee_email: "bob@x",
            employee_phone: "",
            role: { is_admin: true, is_worker: true },
          },
        ],
      },
    ]);
    render(<EmployeesPage />);
    await waitFor(() =>
      expect(screen.getByText("Ada Lovelace")).toBeInTheDocument(),
    );
    expect(screen.getByText("Bob Smith")).toBeInTheDocument();
    expect(screen.getByText("Admin")).toBeInTheDocument();
    const user = userEvent.setup();
    await user.type(
      screen.getByPlaceholderText(/Search by name or email/i),
      "Ada",
    );
    await waitFor(() =>
      expect(screen.queryByText("Bob Smith")).toBeNull(),
    );
    expect(screen.getByText("Ada Lovelace")).toBeInTheDocument();
  });

  it("renders the error state when getUserSchedules rejects", async () => {
    getUserSchedules.mockRejectedValueOnce(new Error("boom"));
    render(<EmployeesPage />);
    await waitFor(() =>
      expect(
        screen.getByText(/Failed to load employees/i),
      ).toBeInTheDocument(),
    );
  });

  it("does not call firestore when there is no signed-in user", () => {
    useAuthMock.mockReturnValue({ user: null });
    render(<EmployeesPage />);
    expect(getUserSchedules).not.toHaveBeenCalled();
  });

  it("deduplicates the same employee across a single schedule", async () => {
    getUserSchedules.mockResolvedValueOnce([
      {
        id: "s1",
        schedule_name: "Clinic",
        employees: [
          { employee_name: "Ada", employee_email: "ada@x", role: {} },
          { employee_name: "Ada2", employee_email: "ada@x", role: {} },
        ],
      },
    ]);
    render(<EmployeesPage />);
    await waitFor(() =>
      expect(screen.getByText(/Ada$/)).toBeInTheDocument(),
    );
    // Only the first "ada@x" row survives dedup (Ada — not Ada2)
    expect(screen.queryByText("Ada2")).toBeNull();
  });
});
