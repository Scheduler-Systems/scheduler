import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, waitFor, screen } from "@testing-library/react";

const replaceMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock, push: vi.fn() }),
}));

const useAuthMock = vi.fn();
vi.mock("@/lib/auth-context", () => ({
  useAuth: () => useAuthMock(),
}));

const HomePage = (await import("./home-page")).default;

describe("HomePage", () => {
  beforeEach(() => {
    replaceMock.mockReset();
  });

  it("renders the loading spinner with an accessible aria-label", () => {
    useAuthMock.mockReturnValue({ user: null, loading: true });
    render(<HomePage />);
    expect(screen.getByLabelText("Loading")).toBeInTheDocument();
    expect(replaceMock).not.toHaveBeenCalled();
  });

  it("routes signed-in users to /dashboard once auth resolves", async () => {
    useAuthMock.mockReturnValue({ user: { uid: "u1" }, loading: false });
    render(<HomePage />);
    await waitFor(() =>
      expect(replaceMock).toHaveBeenCalledWith("/dashboard"),
    );
  });

  it("routes anonymous users to /phone-signin once auth resolves", async () => {
    useAuthMock.mockReturnValue({ user: null, loading: false });
    render(<HomePage />);
    await waitFor(() =>
      // Phone-first entry, matching Flutter.
      expect(replaceMock).toHaveBeenCalledWith("/phone-signin"),
    );
  });

  it("does not route while auth is still loading", () => {
    useAuthMock.mockReturnValue({ user: null, loading: true });
    render(<HomePage />);
    expect(replaceMock).not.toHaveBeenCalled();
  });
});
