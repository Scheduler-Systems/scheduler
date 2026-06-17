import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { I18nProvider } from "@/lib/i18n-context";

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

const sendReset = vi.fn();
vi.mock("@/lib/auth-context", () => ({
  useAuth: () => ({ sendPasswordReset: sendReset }),
}));

const ForgotPasswordPage = (await import("./page")).default;

function wrap(ui: React.ReactNode) {
  return <I18nProvider>{ui}</I18nProvider>;
}

describe("ForgotPasswordPage", () => {
  beforeEach(() => {
    sendReset.mockReset();
  });

  it("renders heading + email field with label", () => {
    render(wrap(<ForgotPasswordPage />));
    expect(
      screen.getByRole("heading", { name: /Reset your password/i }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Email")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Send reset link/i }),
    ).toBeInTheDocument();
  });

  it("rejects invalid emails client-side without calling the SDK", async () => {
    const user = userEvent.setup();
    render(wrap(<ForgotPasswordPage />));
    const input = screen.getByLabelText("Email") as HTMLInputElement;
    await user.type(input, "not-an-email");
    // Bypass native HTML5 validation (required/type=email) by submitting
    // the form directly — the component-level validator is what we want
    // to exercise.
    const form = input.closest("form")!;
    fireEvent.submit(form);
    expect(
      await screen.findByText(/Enter a valid email/),
    ).toBeInTheDocument();
    expect(sendReset).not.toHaveBeenCalled();
  });

  it("sends the reset email and shows the success banner on success", async () => {
    sendReset.mockResolvedValueOnce(undefined);
    const user = userEvent.setup();
    render(wrap(<ForgotPasswordPage />));
    await user.type(screen.getByLabelText("Email"), "ada@example.com");
    await user.click(screen.getByRole("button", { name: /Send reset link/i }));
    await waitFor(() =>
      expect(sendReset).toHaveBeenCalledWith("ada@example.com"),
    );
    await waitFor(() =>
      expect(
        screen.getByText(/If an account exists for ada@example.com/i),
      ).toBeInTheDocument(),
    );
  });

  it("shows a friendly error when the SDK rejects", async () => {
    sendReset.mockRejectedValueOnce({ code: "auth/too-many-requests" });
    const user = userEvent.setup();
    render(wrap(<ForgotPasswordPage />));
    await user.type(screen.getByLabelText("Email"), "ada@example.com");
    await user.click(screen.getByRole("button", { name: /Send reset link/i }));
    await waitFor(() =>
      expect(screen.getByText(/Too many attempts/i)).toBeInTheDocument(),
    );
  });
});
