import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const replaceMock = vi.fn();
const searchGet = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock, push: vi.fn() }),
  useSearchParams: () => ({ get: searchGet }),
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

const sendVerification = vi.fn();
const reloadUser = vi.fn();
const signOut = vi.fn();
const useAuthMock = vi.fn();
vi.mock("@/lib/auth-context", () => ({
  useAuth: () => useAuthMock(),
}));

const VerifyEmailClient = (await import("./verify-email-client")).default;

describe("VerifyEmailClient", () => {
  beforeEach(() => {
    replaceMock.mockReset();
    sendVerification.mockReset();
    reloadUser.mockReset();
    signOut.mockReset();
    searchGet.mockReset();
    searchGet.mockReturnValue("ada@example.com");
    localStorage.clear();
    useAuthMock.mockReturnValue({
      user: { uid: "u1", email: "ada@example.com", emailVerified: false },
      loading: false,
      sendVerificationEmail: sendVerification,
      reloadUser,
      signOut,
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders heading + displays the email pulled from query", () => {
    render(<VerifyEmailClient />);
    expect(
      screen.getByRole("heading", { name: /Check your email/i }),
    ).toBeInTheDocument();
    expect(screen.getByText("ada@example.com")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Resend verification email/i }),
    ).toBeInTheDocument();
  });

  it("sends the verification email and shows the success banner", async () => {
    sendVerification.mockResolvedValueOnce(undefined);
    const user = userEvent.setup();
    render(<VerifyEmailClient />);
    await user.click(
      screen.getByRole("button", { name: /Resend verification email/i }),
    );
    await waitFor(() => expect(sendVerification).toHaveBeenCalled());
    await waitFor(() =>
      expect(
        screen.getByText(/Verification email sent/i),
      ).toBeInTheDocument(),
    );
  });

  it("shows a friendly error when the SDK rejects the resend", async () => {
    sendVerification.mockRejectedValueOnce({
      code: "auth/too-many-requests",
    });
    const user = userEvent.setup();
    render(<VerifyEmailClient />);
    await user.click(
      screen.getByRole("button", { name: /Resend verification email/i }),
    );
    await waitFor(() =>
      expect(screen.getByText(/Too many attempts/i)).toBeInTheDocument(),
    );
  });

  it("Continue-anyway button routes to /choose-role", async () => {
    const user = userEvent.setup();
    render(<VerifyEmailClient />);
    await user.click(screen.getByRole("button", { name: /Continue anyway/i }));
    expect(replaceMock).toHaveBeenCalledWith("/choose-role");
  });

  it("Sign-out button signs the user out and routes to /login", async () => {
    signOut.mockResolvedValueOnce(undefined);
    const user = userEvent.setup();
    render(<VerifyEmailClient />);
    await user.click(screen.getByRole("button", { name: /^Sign out$/i }));
    await waitFor(() => expect(signOut).toHaveBeenCalled());
    await waitFor(() => expect(replaceMock).toHaveBeenCalledWith("/login"));
  });

  it("auto-advances to /choose-role if the current user is already verified", async () => {
    useAuthMock.mockReturnValue({
      user: { uid: "u1", email: "ada@x", emailVerified: true },
      loading: false,
      sendVerificationEmail: sendVerification,
      reloadUser,
      signOut,
    });
    render(<VerifyEmailClient />);
    await waitFor(() =>
      expect(replaceMock).toHaveBeenCalledWith("/choose-role"),
    );
  });
});
