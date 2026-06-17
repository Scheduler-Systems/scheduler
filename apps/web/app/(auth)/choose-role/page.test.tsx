import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const replaceMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock, push: vi.fn() }),
}));

const useAuthMock = vi.fn();
vi.mock("@/lib/auth-context", () => ({
  useAuth: () => useAuthMock(),
}));

const upsertUserRole = vi.fn();
vi.mock("@/lib/firestore-write", () => ({
  upsertUserRole: (...args: unknown[]) => upsertUserRole(...args),
}));

const ChooseRolePage = (await import("./page")).default;

describe("ChooseRolePage", () => {
  beforeEach(() => {
    replaceMock.mockReset();
    upsertUserRole.mockReset();
    upsertUserRole.mockResolvedValue(undefined);
    useAuthMock.mockReturnValue({
      user: { uid: "u1", email: "ada@example.com", displayName: "Ada" },
      loading: false,
    });
  });

  it("renders the two Flutter roles (Manager / Employee)", () => {
    render(<ChooseRolePage />);
    expect(screen.getByRole("heading", { name: /choose role/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /log in as manager/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /log in as employee/i })).toBeInTheDocument();
    // No third role — matches Flutter's two-role model.
    expect(screen.queryByRole("button", { name: /worker|admin|creator/i })).toBeNull();
  });

  it("Manager → writes the employer role struct and routes to /onboarding", async () => {
    const user = userEvent.setup();
    render(<ChooseRolePage />);
    await user.click(screen.getByRole("button", { name: /log in as manager/i }));
    await waitFor(() =>
      expect(upsertUserRole).toHaveBeenCalledWith("u1", "ada@example.com", {
        is_creator: true,
        is_admin: true,
        is_worker: false,
      }),
    );
    await waitFor(() => expect(replaceMock).toHaveBeenCalledWith("/onboarding"));
  });

  it("Employee → writes the worker role struct and routes to /onboarding", async () => {
    const user = userEvent.setup();
    render(<ChooseRolePage />);
    await user.click(screen.getByRole("button", { name: /log in as employee/i }));
    await waitFor(() =>
      expect(upsertUserRole).toHaveBeenCalledWith("u1", "ada@example.com", {
        is_creator: false,
        is_admin: false,
        is_worker: true,
      }),
    );
    await waitFor(() => expect(replaceMock).toHaveBeenCalledWith("/onboarding"));
  });
});
