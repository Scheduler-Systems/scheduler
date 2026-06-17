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

const startPhoneSignIn = vi.fn();
const useAuthMock = vi.fn();
vi.mock("@/lib/auth-context", () => ({
  useAuth: () => useAuthMock(),
}));

const PhoneSignInPage = (await import("./page")).default;

describe("PhoneSignInPage", () => {
  beforeEach(() => {
    replaceMock.mockReset();
    startPhoneSignIn.mockReset();
    useAuthMock.mockReturnValue({
      user: null,
      loading: false,
      startPhoneSignIn,
    });
  });

  it("renders heading + phone-number field with label", () => {
    render(<PhoneSignInPage />);
    expect(
      screen.getByRole("heading", { name: /Sign in with phone/i }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Phone number")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Send code/i }),
    ).toBeInTheDocument();
  });

  it("rejects malformed phone numbers before calling the SDK", async () => {
    const user = userEvent.setup();
    render(<PhoneSignInPage />);
    await user.type(screen.getByLabelText("Phone number"), "not-a-phone");
    await user.click(screen.getByRole("button", { name: /Send code/i }));
    expect(
      await screen.findByText(/Enter a full phone number with country code/),
    ).toBeInTheDocument();
    expect(startPhoneSignIn).not.toHaveBeenCalled();
  });

  it("advances to the code step on success and verifies the code", async () => {
    const confirm = vi.fn().mockResolvedValue({ user: { uid: "u1" } });
    startPhoneSignIn.mockResolvedValueOnce({ confirm });
    const user = userEvent.setup();
    render(<PhoneSignInPage />);
    await user.type(screen.getByLabelText("Phone number"), "+14155551234");
    await user.click(screen.getByRole("button", { name: /Send code/i }));
    // After advancing, verification-code input appears
    await waitFor(() =>
      expect(screen.getByLabelText("Verification code")).toBeInTheDocument(),
    );
    await user.type(screen.getByLabelText("Verification code"), "123456");
    await user.click(screen.getByRole("button", { name: /^Verify$/ }));
    await waitFor(() => expect(confirm).toHaveBeenCalledWith("123456"));
    await waitFor(() =>
      expect(replaceMock).toHaveBeenCalledWith("/choose-role"),
    );
  });

  it("shows a friendly error when startPhoneSignIn rejects", async () => {
    startPhoneSignIn.mockRejectedValueOnce({ code: "auth/too-many-requests" });
    const user = userEvent.setup();
    render(<PhoneSignInPage />);
    await user.type(screen.getByLabelText("Phone number"), "+14155551234");
    await user.click(screen.getByRole("button", { name: /Send code/i }));
    await waitFor(() =>
      expect(screen.getByText(/Too many attempts/i)).toBeInTheDocument(),
    );
  });

  it("redirects already-signed-in users to /dashboard", async () => {
    useAuthMock.mockReturnValue({
      user: { uid: "u1" },
      loading: false,
      startPhoneSignIn,
    });
    render(<PhoneSignInPage />);
    await waitFor(() =>
      expect(replaceMock).toHaveBeenCalledWith("/dashboard"),
    );
  });
});
