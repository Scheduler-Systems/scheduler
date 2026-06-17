import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { I18nProvider } from "@/lib/i18n-context";

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

const signUp = vi.fn();
const useAuthMock = vi.fn();
vi.mock("@/lib/auth-context", () => ({
  useAuth: () => useAuthMock(),
}));

const mockCurrentUser = { emailVerified: false };
vi.mock("@/lib/firebase", () => ({
  getFirebaseAuth: () => ({ currentUser: mockCurrentUser }),
}));

const SignupPage = (await import("./page")).default;

function wrap(ui: React.ReactNode) {
  return <I18nProvider>{ui}</I18nProvider>;
}

describe("SignupPage", () => {
  beforeEach(() => {
    replaceMock.mockReset();
    signUp.mockReset();
    mockCurrentUser.emailVerified = false;
    useAuthMock.mockReturnValue({
      user: null,
      loading: false,
      signUpWithEmail: signUp,
    });
  });

  it("renders heading + fields with accessible labels", () => {
    render(wrap(<SignupPage />));
    expect(
      screen.getByRole("heading", { name: /Create your account/i }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Your name")).toBeInTheDocument();
    expect(screen.getByLabelText("Email")).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
    expect(screen.getByLabelText("Confirm password")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Create account/i }),
    ).toBeInTheDocument();
  });

  it("creates an account, routes to /verify-email when unverified", async () => {
    signUp.mockResolvedValueOnce(undefined);
    mockCurrentUser.emailVerified = false;
    const user = userEvent.setup();
    render(wrap(<SignupPage />));
    await user.type(screen.getByLabelText("Your name"), "Ada");
    await user.type(screen.getByLabelText("Email"), "ada@example.com");
    await user.type(screen.getByLabelText("Password"), "hunter2");
    await user.type(screen.getByLabelText("Confirm password"), "hunter2");
    await user.click(screen.getByRole("button", { name: /Create account/i }));
    await waitFor(() =>
      expect(signUp).toHaveBeenCalledWith("ada@example.com", "hunter2", "Ada"),
    );
    await waitFor(() =>
      expect(replaceMock).toHaveBeenCalledWith(
        expect.stringContaining("/verify-email?email=ada%40example.com"),
      ),
    );
  });

  it("rejects blank name client-side without calling the SDK", async () => {
    const user = userEvent.setup();
    render(wrap(<SignupPage />));
    await user.type(screen.getByLabelText("Email"), "ada@example.com");
    await user.type(screen.getByLabelText("Password"), "hunter2");
    await user.type(screen.getByLabelText("Confirm password"), "hunter2");
    // Bypass native HTML5 validation (required inputs) — we're testing
    // the component-level validator.
    const form = screen
      .getByRole("button", { name: /Create account/i })
      .closest("form")!;
    fireEvent.submit(form);
    expect(
      await screen.findByText(/Please enter your name/),
    ).toBeInTheDocument();
    expect(signUp).not.toHaveBeenCalled();
  });

  it("rejects mismatched passwords client-side", async () => {
    const user = userEvent.setup();
    render(wrap(<SignupPage />));
    await user.type(screen.getByLabelText("Your name"), "Ada");
    await user.type(screen.getByLabelText("Email"), "ada@example.com");
    await user.type(screen.getByLabelText("Password"), "hunter2");
    await user.type(screen.getByLabelText("Confirm password"), "different");
    await user.click(screen.getByRole("button", { name: /Create account/i }));
    expect(
      await screen.findByText(/Passwords don't match/),
    ).toBeInTheDocument();
    expect(signUp).not.toHaveBeenCalled();
  });

  it("shows a friendly error when the SDK rejects with email-already-in-use", async () => {
    signUp.mockRejectedValueOnce({ code: "auth/email-already-in-use" });
    const user = userEvent.setup();
    render(wrap(<SignupPage />));
    await user.type(screen.getByLabelText("Your name"), "Ada");
    await user.type(screen.getByLabelText("Email"), "ada@example.com");
    await user.type(screen.getByLabelText("Password"), "hunter2");
    await user.type(screen.getByLabelText("Confirm password"), "hunter2");
    await user.click(screen.getByRole("button", { name: /Create account/i }));
    await waitFor(() =>
      expect(
        screen.getByText(/That email is already in use/),
      ).toBeInTheDocument(),
    );
  });

  it("redirects already-signed-in users to /dashboard", async () => {
    useAuthMock.mockReturnValue({
      user: { uid: "u1" },
      loading: false,
      signUpWithEmail: signUp,
    });
    render(wrap(<SignupPage />));
    await waitFor(() =>
      expect(replaceMock).toHaveBeenCalledWith("/dashboard"),
    );
  });
});
