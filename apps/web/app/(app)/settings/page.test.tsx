import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const replaceMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock, push: vi.fn() }),
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
const signOutMock = vi.fn();
vi.mock("@/lib/auth-context", () => ({
  useAuth: () => useAuthMock(),
}));

const SettingsPage = (await import("./page")).default;

describe("SettingsPage", () => {
  beforeEach(() => {
    replaceMock.mockReset();
    signOutMock.mockReset();
    useAuthMock.mockReturnValue({
      user: {
        uid: "u1",
        email: "ada@example.com",
        displayName: "Ada",
        emailVerified: true,
      },
      signOut: signOutMock,
    });
  });

  it("renders the Settings heading + profile card", () => {
    render(<SettingsPage />);
    expect(
      screen.getByRole("heading", { name: /^Settings$/i }),
    ).toBeInTheDocument();
    expect(screen.getByText("Ada")).toBeInTheDocument();
    expect(screen.getByText("ada@example.com")).toBeInTheDocument();
  });

  it("signs out and routes to /login when the Sign out row is clicked", async () => {
    signOutMock.mockResolvedValueOnce(undefined);
    const user = userEvent.setup();
    render(<SettingsPage />);
    await user.click(screen.getByRole("button", { name: /Sign out/i }));
    await waitFor(() => expect(signOutMock).toHaveBeenCalled());
    await waitFor(() =>
      expect(replaceMock).toHaveBeenCalledWith("/login"),
    );
  });

  it("keeps signingOut lifecycle even when signOut rejects", async () => {
    signOutMock.mockRejectedValueOnce(new Error("boom"));
    const user = userEvent.setup();
    render(<SettingsPage />);
    // error is swallowed via finally; we don't want an uncaught throw
    await user.click(screen.getByRole("button", { name: /Sign out/i })).catch(() => undefined);
    await waitFor(() => expect(signOutMock).toHaveBeenCalled());
  });

  it("shows a verify-now CTA when the current user is not verified", () => {
    useAuthMock.mockReturnValue({
      user: {
        uid: "u1",
        email: "ada@example.com",
        displayName: "Ada",
        emailVerified: false,
      },
      signOut: signOutMock,
    });
    render(<SettingsPage />);
    expect(
      screen.getByText(/Email not verified — verify now/i),
    ).toBeInTheDocument();
  });

  it("renders account section links with accessible names", () => {
    render(<SettingsPage />);
    expect(
      screen.getByRole("link", { name: /Employees/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /Schedules/i }),
    ).toBeInTheDocument();
    // There are multiple "Profile" links (card Edit link + menu row)
    expect(screen.getAllByRole("link", { name: /Profile/i }).length)
      .toBeGreaterThan(0);
  });
});
