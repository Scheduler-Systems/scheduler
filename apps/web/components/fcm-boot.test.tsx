import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// -----------------------------------------------------------------------------
// Mocks — register before importing FcmBoot
// -----------------------------------------------------------------------------

const authState: { user: { uid: string } | null } = { user: { uid: "u-1" } };

vi.mock("@/lib/auth-context", () => ({
  useAuth: () => authState,
}));

vi.mock("@/lib/firebase", () => ({
  getFirebaseAuth: () => ({ __mock_auth: true }),
}));

const fcmCalls = {
  requestFcmPermissionAndToken: vi.fn(),
  registerFcmToken: vi.fn(),
  subscribeToForegroundMessages: vi.fn(),
};

vi.mock("@/lib/fcm", () => ({
  requestFcmPermissionAndToken: (...args: unknown[]) =>
    fcmCalls.requestFcmPermissionAndToken(...args),
  registerFcmToken: (...args: unknown[]) =>
    fcmCalls.registerFcmToken(...args),
  subscribeToForegroundMessages: (...args: unknown[]) =>
    fcmCalls.subscribeToForegroundMessages(...args),
}));

const { FcmBoot } = await import("./fcm-boot");

// -----------------------------------------------------------------------------
// Helpers
// -----------------------------------------------------------------------------

let foregroundCallback: ((m: unknown) => void) | null = null;

beforeEach(() => {
  localStorage.clear();
  authState.user = { uid: "u-1" };
  foregroundCallback = null;

  fcmCalls.requestFcmPermissionAndToken.mockReset();
  fcmCalls.requestFcmPermissionAndToken.mockResolvedValue("tok-1");
  fcmCalls.registerFcmToken.mockReset();
  fcmCalls.registerFcmToken.mockResolvedValue(undefined);
  fcmCalls.subscribeToForegroundMessages.mockReset();
  fcmCalls.subscribeToForegroundMessages.mockImplementation(
    (cb: (m: unknown) => void) => {
      foregroundCallback = cb;
      return Promise.resolve(() => undefined);
    },
  );
});

// -----------------------------------------------------------------------------
// Tests
// -----------------------------------------------------------------------------

describe("<FcmBoot>", () => {
  it("renders the 'Enable notifications' prompt when signed in and unanswered", async () => {
    render(<FcmBoot />);
    expect(
      await screen.findByRole("button", { name: /Enable notifications/i }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Skip/i })).toBeInTheDocument();
  });

  it("hides the prompt when localStorage says answered", async () => {
    localStorage.setItem("fcm_prompt_answered", "true");
    render(<FcmBoot />);
    // Give effects a tick
    await waitFor(() => {
      expect(
        screen.queryByRole("button", { name: /Enable notifications/i }),
      ).not.toBeInTheDocument();
    });
  });

  it("hides the prompt when no user is signed in", async () => {
    authState.user = null;
    render(<FcmBoot />);
    await waitFor(() => {
      expect(
        screen.queryByRole("button", { name: /Enable notifications/i }),
      ).not.toBeInTheDocument();
    });
  });

  it("clicking Enable requests a token and registers it, then hides the prompt", async () => {
    const user = userEvent.setup();
    render(<FcmBoot />);
    const enable = await screen.findByRole("button", {
      name: /Enable notifications/i,
    });
    await user.click(enable);
    await waitFor(() => {
      expect(fcmCalls.requestFcmPermissionAndToken).toHaveBeenCalledTimes(1);
    });
    expect(fcmCalls.registerFcmToken).toHaveBeenCalledWith("u-1", "tok-1");
    expect(localStorage.getItem("fcm_prompt_answered")).toBe("true");
    await waitFor(() => {
      expect(
        screen.queryByRole("button", { name: /Enable notifications/i }),
      ).not.toBeInTheDocument();
    });
  });

  it("clicking Enable with no token returned skips registerFcmToken", async () => {
    fcmCalls.requestFcmPermissionAndToken.mockResolvedValueOnce(null);
    const user = userEvent.setup();
    render(<FcmBoot />);
    const enable = await screen.findByRole("button", {
      name: /Enable notifications/i,
    });
    await user.click(enable);
    await waitFor(() => {
      expect(fcmCalls.requestFcmPermissionAndToken).toHaveBeenCalled();
    });
    expect(fcmCalls.registerFcmToken).not.toHaveBeenCalled();
    expect(localStorage.getItem("fcm_prompt_answered")).toBe("true");
  });

  it("clicking Skip sets the localStorage flag and hides the prompt", async () => {
    const user = userEvent.setup();
    render(<FcmBoot />);
    const skip = await screen.findByRole("button", { name: /Skip/i });
    await user.click(skip);
    expect(localStorage.getItem("fcm_prompt_answered")).toBe("true");
    await waitFor(() => {
      expect(
        screen.queryByRole("button", { name: /Enable notifications/i }),
      ).not.toBeInTheDocument();
    });
    // No token request when Skip is chosen
    expect(fcmCalls.requestFcmPermissionAndToken).not.toHaveBeenCalled();
  });

  it("subscribes to foreground messages when signed in", async () => {
    render(<FcmBoot />);
    await waitFor(() => {
      expect(fcmCalls.subscribeToForegroundMessages).toHaveBeenCalledTimes(1);
    });
  });

  it("renders a toast when a foreground push arrives", async () => {
    render(<FcmBoot />);
    await waitFor(() => {
      expect(fcmCalls.subscribeToForegroundMessages).toHaveBeenCalled();
    });
    // subscribeToForegroundMessages returned a Promise — wait a tick for then()
    await waitFor(() => {
      expect(foregroundCallback).not.toBeNull();
    });

    await act(async () => {
      foregroundCallback!({
        title: "New schedule",
        body: "Week of May 3",
        data: { url: "/schedules/abc" },
      });
    });

    expect(await screen.findByText("New schedule")).toBeInTheDocument();
    expect(screen.getByText("Week of May 3")).toBeInTheDocument();
  });

  it("toast can be dismissed by clicking the close button", async () => {
    const user = userEvent.setup();
    render(<FcmBoot />);
    await waitFor(() => {
      expect(foregroundCallback).not.toBeNull();
    });
    await act(async () => {
      foregroundCallback!({
        title: "Ping",
        body: "body",
        data: {},
      });
    });
    const dismiss = await screen.findByRole("button", {
      name: /Dismiss notification/i,
    });
    await user.click(dismiss);
    await waitFor(() => {
      expect(screen.queryByText("Ping")).not.toBeInTheDocument();
    });
  });
});
