import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const replaceMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock, push: vi.fn() }),
}));

const useAuthMock = vi.fn();
vi.mock("@/lib/auth-context", () => ({
  useAuth: () => useAuthMock(),
}));

const upsertUserProfile = vi.fn();
vi.mock("@/lib/firestore-write", () => ({
  upsertUserProfile: (...args: unknown[]) => upsertUserProfile(...args),
}));

const OnboardingPage = (await import("./page")).default;

describe("OnboardingPage", () => {
  beforeEach(() => {
    replaceMock.mockReset();
    upsertUserProfile.mockReset();
    useAuthMock.mockReturnValue({
      user: {
        uid: "u1",
        email: "ada@example.com",
        displayName: "Ada Lovelace",
      },
      loading: false,
    });
  });

  it("renders heading + pre-fills name from displayName", async () => {
    render(<OnboardingPage />);
    expect(
      screen.getByRole("heading", { name: /Welcome to Scheduler/i }),
    ).toBeInTheDocument();
    // The name input gets populated via the effect
    await waitFor(() => {
      const input = screen.getByLabelText(/Display name/i) as HTMLInputElement;
      expect(input.value).toBe("Ada Lovelace");
    });
    expect(screen.getByLabelText(/Title/i)).toBeInTheDocument();
  });

  it("saves the name (role was set on Choose-Role) and routes to /dashboard", async () => {
    upsertUserProfile.mockResolvedValueOnce(undefined);
    const user = userEvent.setup();
    render(<OnboardingPage />);
    await waitFor(() => {
      expect(
        (screen.getByLabelText(/Display name/i) as HTMLInputElement).value,
      ).toBe("Ada Lovelace");
    });
    // Role selection now lives on the separate Choose-Role screen, so this
    // step has no radios and must NOT write a role (preserving the prior choice).
    expect(screen.queryAllByRole("radio")).toHaveLength(0);
    await user.click(screen.getByRole("button", { name: /Continue/i }));
    await waitFor(() =>
      expect(upsertUserProfile).toHaveBeenCalledWith(
        "u1",
        "ada@example.com",
        expect.objectContaining({
          display_name: "Ada Lovelace",
          title: "",
        }),
      ),
    );
    // The name/title write must not carry a role field.
    expect(upsertUserProfile.mock.calls[0][2]).not.toHaveProperty("role");
    await waitFor(() =>
      expect(replaceMock).toHaveBeenCalledWith("/dashboard"),
    );
  });

  it("rejects blank name client-side without calling Firestore", async () => {
    useAuthMock.mockReturnValue({
      user: { uid: "u1", email: "ada@x", displayName: "" },
      loading: false,
    });
    render(<OnboardingPage />);
    // Bypass native HTML5 required.
    const form = screen
      .getByRole("button", { name: /Continue/i })
      .closest("form")!;
    fireEvent.submit(form);
    expect(
      await screen.findByText(/Please enter your name/),
    ).toBeInTheDocument();
    expect(upsertUserProfile).not.toHaveBeenCalled();
  });

  it("shows a friendly error when Firestore rejects", async () => {
    upsertUserProfile.mockRejectedValueOnce(new Error("boom"));
    const user = userEvent.setup();
    render(<OnboardingPage />);
    await waitFor(() => {
      expect(
        (screen.getByLabelText(/Display name/i) as HTMLInputElement).value,
      ).toBe("Ada Lovelace");
    });
    await user.click(screen.getByRole("button", { name: /Continue/i }));
    await waitFor(() =>
      expect(screen.getByText(/boom/)).toBeInTheDocument(),
    );
  });

  it("redirects unauthenticated users to /login", async () => {
    useAuthMock.mockReturnValue({ user: null, loading: false });
    render(<OnboardingPage />);
    await waitFor(() => expect(replaceMock).toHaveBeenCalledWith("/login"));
  });
});
