import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, waitFor } from "@testing-library/react";
import type React from "react";

/**
 * Test double state — these are mutated across tests via the setter
 * functions below. Hoisting variables into the top scope keeps the
 * vi.mock factory functions referencing them stable across resets.
 */
let currentUser: { uid: string; email?: string; displayName?: string } | null =
  null;
const bootSpy = vi.fn();
const shutdownSpy = vi.fn();
const callableSpy = vi.fn();

// Mock the firebase SDK entry points the component touches. We deliberately
// stub `firebase/app` + `firebase/functions` because the component imports
// them directly and we don't want to boot the real SDK in tests.
vi.mock("firebase/app", () => ({
  getApp: () => ({}),
}));

vi.mock("firebase/functions", () => ({
  getFunctions: () => ({}),
  // `httpsCallable(fns, name)` returns a function; we hand back our spy
  // so individual tests can stub its resolution value.
  httpsCallable: () => (payload: unknown) => callableSpy(payload),
}));

vi.mock("@/lib/auth-context", () => ({
  useAuth: () => ({ user: currentUser }),
}));

vi.mock("@/lib/intercom", () => ({
  bootIntercom: (user: unknown, jwt: string) => bootSpy(user, jwt),
  shutdownIntercom: () => shutdownSpy(),
}));

const { IntercomBoot } = await import("./intercom-boot");

function setUser(u: typeof currentUser) {
  currentUser = u;
}

describe("<IntercomBoot>", () => {
  beforeEach(() => {
    bootSpy.mockReset();
    shutdownSpy.mockReset();
    callableSpy.mockReset();
    setUser(null);
  });

  it("does nothing when user is signed out", async () => {
    setUser(null);
    render(<IntercomBoot />);
    // Let the effect run
    await Promise.resolve();
    expect(bootSpy).not.toHaveBeenCalled();
    expect(shutdownSpy).not.toHaveBeenCalled();
    expect(callableSpy).not.toHaveBeenCalled();
  });

  it("fetches a JWT and boots Intercom when a user is signed in", async () => {
    setUser({ uid: "uid-1", email: "ada@example.com", displayName: "Ada" });
    callableSpy.mockResolvedValueOnce({
      data: { token: "jwt-token-1", expires_in: 3600 },
    });

    render(<IntercomBoot />);

    await waitFor(() => {
      expect(callableSpy).toHaveBeenCalledWith({ platform: "web" });
      expect(bootSpy).toHaveBeenCalledWith(
        {
          user_id: "uid-1",
          email: "ada@example.com",
          name: "Ada",
        },
        "jwt-token-1",
      );
    });
    expect(shutdownSpy).not.toHaveBeenCalled();
  });

  it("stays dormant (no crash, no error UI) when the JWT callable rejects", async () => {
    setUser({ uid: "uid-err", email: "x@y.z" });
    const err = new Error("network");
    callableSpy.mockRejectedValueOnce(err);
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);

    render(<IntercomBoot />);

    await waitFor(() => {
      expect(callableSpy).toHaveBeenCalled();
    });
    expect(bootSpy).not.toHaveBeenCalled();
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });

  it("does not boot when the callable returns no token", async () => {
    setUser({ uid: "uid-notoken" });
    callableSpy.mockResolvedValueOnce({ data: {} });

    render(<IntercomBoot />);

    await waitFor(() => {
      expect(callableSpy).toHaveBeenCalled();
    });
    expect(bootSpy).not.toHaveBeenCalled();
  });

  it("shuts down Intercom when the user signs out after being signed in", async () => {
    // Two-step test: first render with a user (boot), then re-render
    // with null user (shutdown). Same instance — we only change what the
    // mocked useAuth returns and force a re-render so React re-runs the
    // effect with the new value.
    setUser({ uid: "uid-42", email: "a@b.c" });
    callableSpy.mockResolvedValueOnce({ data: { token: "jwt-42" } });

    const { rerender } = render(<IntercomBoot />);
    await waitFor(() => expect(bootSpy).toHaveBeenCalled());

    setUser(null);
    // Re-render the SAME element — the ref persists, useAuth re-evaluates,
    // effect re-runs with `user === null` and shuts the widget down.
    rerender(<IntercomBoot /> as React.ReactElement);
    await waitFor(() => {
      expect(shutdownSpy).toHaveBeenCalledTimes(1);
    });
  });
});
