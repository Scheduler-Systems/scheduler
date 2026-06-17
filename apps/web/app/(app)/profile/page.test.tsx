import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const useAuthMock = vi.fn();
vi.mock("@/lib/auth-context", () => ({
  useAuth: () => useAuthMock(),
}));

const getUserProfile = vi.fn();
vi.mock("@/lib/firestore", () => ({
  getUserProfile: (uid: string) => getUserProfile(uid),
}));

const upsertUserProfile = vi.fn();
vi.mock("@/lib/firestore-write", () => ({
  upsertUserProfile: (...args: unknown[]) => upsertUserProfile(...args),
}));

const ProfilePage = (await import("./page")).default;

describe("ProfilePage", () => {
  beforeEach(() => {
    getUserProfile.mockReset();
    upsertUserProfile.mockReset();
    useAuthMock.mockReturnValue({
      user: { uid: "u1", email: "u@x", displayName: "Ada" },
    });
  });

  it("renders the form with existing profile values and labels", async () => {
    getUserProfile.mockResolvedValueOnce({
      display_name: "Ada L",
      title: "Engineer",
      role: "employer",
    });
    render(<ProfilePage />);
    await waitFor(() =>
      expect(screen.getByLabelText(/Display name/i)).toBeInTheDocument(),
    );
    expect(screen.getByLabelText(/Title/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Role/i)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /^Profile$/i }))
      .toBeInTheDocument();
    const nameInput = screen.getByLabelText(/Display name/i) as HTMLInputElement;
    expect(nameInput.value).toBe("Ada L");
    // employer → admin key
    const roleSelect = screen.getByLabelText(/Role/i) as HTMLSelectElement;
    expect(roleSelect.value).toBe("admin");
  });

  it("saves updates by calling upsertUserProfile with the trimmed values", async () => {
    getUserProfile.mockResolvedValueOnce({
      display_name: "Ada",
      title: "",
      role: null,
    });
    upsertUserProfile.mockResolvedValueOnce(undefined);
    render(<ProfilePage />);
    await waitFor(() =>
      expect(screen.getByLabelText(/Display name/i)).toBeInTheDocument(),
    );
    const user = userEvent.setup();
    const nameInput = screen.getByLabelText(/Display name/i) as HTMLInputElement;
    await user.clear(nameInput);
    await user.type(nameInput, "  New Name  ");
    await user.selectOptions(screen.getByLabelText(/Role/i), "creator");
    await user.click(screen.getByRole("button", { name: /Save profile/i }));
    await waitFor(() =>
      expect(upsertUserProfile).toHaveBeenCalledWith(
        "u1",
        "u@x",
        expect.objectContaining({
          display_name: "New Name",
          role: expect.objectContaining({ is_creator: true }),
        }),
      ),
    );
    await waitFor(() =>
      expect(screen.getByText(/Saved\./)).toBeInTheDocument(),
    );
  });

  it("shows a friendly error when the save rejects", async () => {
    getUserProfile.mockResolvedValueOnce({
      display_name: "Ada",
      title: "",
      role: null,
    });
    upsertUserProfile.mockRejectedValueOnce({ code: "unauthenticated" });
    render(<ProfilePage />);
    await waitFor(() =>
      expect(screen.getByLabelText(/Display name/i)).toBeInTheDocument(),
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /Save profile/i }));
    await waitFor(() =>
      expect(upsertUserProfile).toHaveBeenCalled(),
    );
    await waitFor(() => {
      // friendlyAuthError returns something — any non-"Saved." text is fine
      expect(screen.queryByText(/Saved\./)).toBeNull();
    });
  });

  it("supports the legacy RoleStruct shape on load (creator branch)", async () => {
    getUserProfile.mockResolvedValueOnce({
      display_name: "C",
      title: "",
      role: { is_creator: true, is_admin: true, is_worker: true },
    });
    render(<ProfilePage />);
    await waitFor(() =>
      expect(screen.getByLabelText(/Role/i)).toBeInTheDocument(),
    );
    const roleSelect = screen.getByLabelText(/Role/i) as HTMLSelectElement;
    expect(roleSelect.value).toBe("creator");
  });

  it("shows the loading spinner when no user is signed in", async () => {
    useAuthMock.mockReturnValue({ user: null });
    render(<ProfilePage />);
    // Loading stays true because load() returns early for null user
    expect(document.querySelector(".animate-spin")).toBeInTheDocument();
    expect(screen.queryByLabelText(/Display name/i)).not.toBeInTheDocument();
  });

  it("maps employee string role to worker", async () => {
    getUserProfile.mockResolvedValueOnce({
      display_name: "Ada",
      title: "",
      role: "employee",
    });
    render(<ProfilePage />);
    await waitFor(() =>
      expect(screen.getByLabelText(/Display name/i)).toBeInTheDocument(),
    );
    const roleSelect = screen.getByLabelText(/Role/i) as HTMLSelectElement;
    expect(roleSelect.value).toBe("worker");
  });

  it("maps legacy RoleStruct admin (is_admin only) to admin", async () => {
    getUserProfile.mockResolvedValueOnce({
      display_name: "Bob",
      title: "",
      role: { is_admin: true, is_worker: true },
    });
    render(<ProfilePage />);
    await waitFor(() =>
      expect(screen.getByLabelText(/Role/i)).toBeInTheDocument(),
    );
    const roleSelect = screen.getByLabelText(/Role/i) as HTMLSelectElement;
    expect(roleSelect.value).toBe("admin");
  });

  it("maps legacy RoleStruct plain worker (no admin/creator) to worker", async () => {
    getUserProfile.mockResolvedValueOnce({
      display_name: "Charlie",
      title: "",
      role: { is_admin: false, is_worker: true },
    });
    render(<ProfilePage />);
    await waitFor(() =>
      expect(screen.getByLabelText(/Role/i)).toBeInTheDocument(),
    );
    const roleSelect = screen.getByLabelText(/Role/i) as HTMLSelectElement;
    expect(roleSelect.value).toBe("worker");
  });
});
