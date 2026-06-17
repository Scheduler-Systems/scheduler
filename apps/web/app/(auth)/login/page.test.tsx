import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { I18nProvider } from "@/lib/i18n-context";

// Router mocks
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

// Auth mocks
const signInEmail = vi.fn();
const signInGoogle = vi.fn();
const useAuthMock = vi.fn();
vi.mock("@/lib/auth-context", () => ({
  useAuth: () => useAuthMock(),
}));

// Firebase.getFirebaseAuth() used inside the page to decide verify-routing.
const mockCurrentUser = { emailVerified: true };
vi.mock("@/lib/firebase", () => ({
  getFirebaseAuth: () => ({ currentUser: mockCurrentUser }),
}));

const LoginPage = (await import("./page")).default;

function wrap(ui: React.ReactNode) {
  return <I18nProvider>{ui}</I18nProvider>;
}

describe("LoginPage", () => {
  beforeEach(() => {
    replaceMock.mockReset();
    signInEmail.mockReset();
    signInGoogle.mockReset();
    mockCurrentUser.emailVerified = true;
    useAuthMock.mockReturnValue({
      user: null,
      loading: false,
      signInWithEmail: signInEmail,
      signInWithGoogle: signInGoogle,
    });
  });

  it("renders heading + form controls with accessible labels", () => {
    render(wrap(<LoginPage />));
    expect(
      screen.getByRole("heading", { name: /Scheduler/i }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Email")).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /^Sign in$/i }),
    ).toBeInTheDocument();
  });

  it("submits email sign-in and routes to /dashboard when verified", async () => {
    signInEmail.mockResolvedValueOnce(undefined);
    mockCurrentUser.emailVerified = true;
    const user = userEvent.setup();
    render(wrap(<LoginPage />));
    await user.type(screen.getByLabelText("Email"), "ada@example.com");
    await user.type(screen.getByLabelText("Password"), "hunter2");
    await user.click(screen.getByRole("button", { name: /^Sign in$/i }));
    await waitFor(() =>
      expect(signInEmail).toHaveBeenCalledWith("ada@example.com", "hunter2"),
    );
    await waitFor(() =>
      expect(replaceMock).toHaveBeenCalledWith("/dashboard"),
    );
  });

  it("routes unverified users to /verify-email with the email in the query", async () => {
    signInEmail.mockResolvedValueOnce(undefined);
    mockCurrentUser.emailVerified = false;
    const user = userEvent.setup();
    render(wrap(<LoginPage />));
    await user.type(screen.getByLabelText("Email"), "unverified@example.com");
    await user.type(screen.getByLabelText("Password"), "hunter2");
    await user.click(screen.getByRole("button", { name: /^Sign in$/i }));
    await waitFor(() =>
      expect(replaceMock).toHaveBeenCalledWith(
        expect.stringContaining("/verify-email?email=unverified%40example.com"),
      ),
    );
  });

  it("shows a friendly error message on wrong-password failures", async () => {
    signInEmail.mockRejectedValueOnce({ code: "auth/wrong-password" });
    const user = userEvent.setup();
    render(wrap(<LoginPage />));
    await user.type(screen.getByLabelText("Email"), "ada@example.com");
    await user.type(screen.getByLabelText("Password"), "bad");
    await user.click(screen.getByRole("button", { name: /^Sign in$/i }));
    await waitFor(() =>
      expect(screen.getByText(/Password is incorrect/)).toBeInTheDocument(),
    );
  });

  it("supports Google sign-in and surfaces popup failures", async () => {
    signInGoogle.mockRejectedValueOnce({ code: "auth/network-request-failed" });
    const user = userEvent.setup();
    render(wrap(<LoginPage />));
    await user.click(
      screen.getByRole("button", { name: /Continue with Google/i }),
    );
    await waitFor(() =>
      expect(screen.getByText(/Network error/)).toBeInTheDocument(),
    );
  });

  it("shows a loading spinner and skips the form when loading", () => {
    useAuthMock.mockReturnValue({
      user: null,
      loading: true,
      signInWithEmail: signInEmail,
      signInWithGoogle: signInGoogle,
    });
    render(wrap(<LoginPage />));
    expect(screen.queryByLabelText("Email")).not.toBeInTheDocument();
  });

  it("redirects signed-in users to /dashboard via effect", async () => {
    useAuthMock.mockReturnValue({
      user: { uid: "u1" },
      loading: false,
      signInWithEmail: signInEmail,
      signInWithGoogle: signInGoogle,
    });
    render(wrap(<LoginPage />));
    await waitFor(() =>
      expect(replaceMock).toHaveBeenCalledWith("/dashboard"),
    );
  });
});
