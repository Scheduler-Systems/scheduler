import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const authState: { user: { uid: string } | null } = { user: { uid: "u-1" } };

vi.mock("./auth-context", () => ({
  useAuth: () => ({
    user: authState.user,
    loading: false,
    signInWithEmail: vi.fn(),
    signInWithGoogle: vi.fn(),
    signOut: vi.fn(),
    signUpWithEmail: vi.fn(),
    sendPasswordReset: vi.fn(),
    sendVerificationEmail: vi.fn(),
    reloadUser: vi.fn(),
    startPhoneSignIn: vi.fn(),
  }),
}));

vi.mock("./billing/client", () => ({
  fetchCustomerInfo: vi.fn(async () => {
    throw new Error("tests must pass `fetcher` prop");
  }),
}));

const { BillingProvider, useBilling } = await import("./billing-context");
const { FREE_TIER } = await import("./billing/entitlements");

function Harness() {
  const { entitlements, loading, error, refetch } = useBilling();
  return (
    <div>
      <span data-testid="loading">{loading ? "loading" : "ready"}</span>
      <span data-testid="tier">{entitlements.tier}</span>
      <span data-testid="userLimit">{entitlements.userLimit}</span>
      <span data-testid="error">{error ? error.message : ""}</span>
      <button onClick={() => void refetch()}>refetch</button>
    </div>
  );
}

const PRO_TIER = {
  isActive: true,
  tier: "pro" as const,
  userLimit: 30,
  stationLimit: 5,
  entitlements: ["pro_30"],
  tierDisplayName: "Pro",
};

/**
 * Drain pending microtasks so React state updates flush synchronously.
 * Useful when combining fake timers with deferred-promise fetchers.
 */
async function drainMicrotasks() {
  await act(async () => { await Promise.resolve(); });
}

describe("BillingProvider stale guards", () => {
  beforeEach(() => {
    authState.user = { uid: "u-1" };
    vi.clearAllMocks();
  });

  afterEach(() => {
    // Safety net in case a test fails before its own cleanup runs.
    // Without this, fake timers would leak to the next test.
    vi.useRealTimers();
    Object.defineProperty(document, "visibilityState", {
      value: "visible",
      configurable: true,
    });
  });

  it("stops interval when tab is hidden via visibilitychange", async () => {
    vi.useFakeTimers();
    try {
      const fetcher = vi.fn(async () => PRO_TIER);
      render(
        <BillingProvider fetcher={fetcher} refetchIntervalMs={500}>
          <Harness />
        </BillingProvider>,
      );

      // Drain microtasks so the initial doFetch (from useEffect) completes.
      // With fake timers we CANNOT use waitFor (it uses setTimeout internally).
      await drainMicrotasks();

      // Initial fetch should have completed
      expect(screen.getByTestId("loading").textContent).toBe("ready");

      // Advance 500ms — the interval should fire once
      act(() => { vi.advanceTimersByTime(500); });
      await drainMicrotasks();
      const callsAfterOneInterval = fetcher.mock.calls.length;
      expect(callsAfterOneInterval).toBeGreaterThanOrEqual(2);

      // Hide tab — onVisibility calls stop(), clearing the interval
      act(() => {
        Object.defineProperty(document, "visibilityState", {
          value: "hidden",
          configurable: true,
        });
        document.dispatchEvent(new Event("visibilitychange"));
      });

      // Advance 1000ms — the interval is stopped, so no new fetches
      act(() => { vi.advanceTimersByTime(1000); });
      await drainMicrotasks();
      expect(fetcher.mock.calls.length).toBe(callsAfterOneInterval);

      // Show tab — onVisibility calls start(), restarting the interval
      act(() => {
        Object.defineProperty(document, "visibilityState", {
          value: "visible",
          configurable: true,
        });
        document.dispatchEvent(new Event("visibilitychange"));
      });

      // Advance 500ms — the restarted interval should fire once
      act(() => { vi.advanceTimersByTime(500); });
      await drainMicrotasks();
      expect(fetcher.mock.calls.length).toBe(callsAfterOneInterval + 1);
    } finally {
      vi.useRealTimers();
      Object.defineProperty(document, "visibilityState", {
        value: "visible",
        configurable: true,
      });
    }
  });

  it("ignores stale responses when refetch overlaps with in-flight fetch", async () => {
    const resolvers: Array<(value: unknown) => void> = [];
    const fetcher = vi.fn().mockImplementation(() => {
      return new Promise((resolve) => { resolvers.push(resolve); });
    });

    render(
      <BillingProvider fetcher={fetcher}>
        <Harness />
      </BillingProvider>,
    );

    // Initial fetch starts synchronously; loading becomes true
    expect(screen.getByTestId("loading").textContent).toBe("loading");
    const user = userEvent.setup();
    await user.click(screen.getByText("refetch"));

    // Resolve the FIRST fetch — since a second one was kicked off first,
    // the response is stale and should be ignored
    await act(async () => { resolvers[0](PRO_TIER); });
    expect(screen.getByTestId("loading").textContent).toBe("loading");

    // Resolve the SECOND fetch — this one is current, should apply
    await act(async () => {
      resolvers[1]({ ...PRO_TIER, userLimit: 50, entitlements: ["pro_50"] });
    });
    await waitFor(() =>
      expect(screen.getByTestId("loading").textContent).toBe("ready"),
    );
    expect(screen.getByTestId("userLimit").textContent).toBe("50");
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("ignores stale errors when overlapping fetch rejects first", async () => {
    const resolvers: Array<{
      resolve: (value: unknown) => void;
      reject: (err: Error) => void;
    }> = [];
    const fetcher = vi.fn().mockImplementation(() => {
      return new Promise((resolve, reject) => {
        resolvers.push({ resolve, reject });
      });
    });

    render(
      <BillingProvider fetcher={fetcher}>
        <Harness />
      </BillingProvider>,
    );

    expect(screen.getByTestId("loading").textContent).toBe("loading");
    const user = userEvent.setup();
    await user.click(screen.getByText("refetch"));

    // First fetch resolves successfully but is stale — ignored
    await act(async () => { resolvers[0].resolve(PRO_TIER); });
    expect(screen.getByTestId("loading").textContent).toBe("loading");

    // Second fetch rejects — current, so the error should surface
    await act(async () => { resolvers[1].reject(new Error("billing down")); });
    await waitFor(() =>
      expect(screen.getByTestId("loading").textContent).toBe("ready"),
    );
    expect(screen.getByTestId("tier").textContent).toBe(FREE_TIER.tier);
    expect(screen.getByTestId("error").textContent).toBe("billing down");
  });

  it("ignores stale errors when first fetch rejects, second resolves", async () => {
    const resolvers: Array<{
      resolve: (value: unknown) => void;
      reject: (err: Error) => void;
    }> = [];
    const fetcher = vi.fn().mockImplementation(() => {
      return new Promise((resolve, reject) => {
        resolvers.push({ resolve, reject });
      });
    });

    render(
      <BillingProvider fetcher={fetcher}>
        <Harness />
      </BillingProvider>,
    );

    expect(screen.getByTestId("loading").textContent).toBe("loading");
    const user = userEvent.setup();
    await user.click(screen.getByText("refetch"));

    // First fetch rejects but is stale — ignored
    await act(async () => { resolvers[0].reject(new Error("stale error")); });
    expect(screen.getByTestId("loading").textContent).toBe("loading");

    // Second fetch resolves — current, so the result should apply
    await act(async () => {
      resolvers[1].resolve({ ...PRO_TIER, userLimit: 50, entitlements: ["pro_50"] });
    });
    await waitFor(() =>
      expect(screen.getByTestId("loading").textContent).toBe("ready"),
    );
    expect(screen.getByTestId("userLimit").textContent).toBe("50");
    expect(screen.getByTestId("error").textContent).toBe("");
  });

  it("wraps a non-Error thrown value in an Error", async () => {
    const fetcher = vi.fn(async () => {
      // eslint-disable-next-line no-throw-literal
      throw "just a string";
    });
    render(
      <BillingProvider fetcher={fetcher}>
        <Harness />
      </BillingProvider>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("loading").textContent).toBe("ready"),
    );
    expect(screen.getByTestId("tier").textContent).toBe(FREE_TIER.tier);
    // The non-Error string should be wrapped via new Error(String(err))
    expect(screen.getByTestId("error").textContent).toBe("just a string");
  });

  it("falls back to fetchCustomerInfo when no fetcher prop is provided", async () => {
    // The mock for fetchCustomerInfo throws: "tests must pass `fetcher` prop"
    // so this tests that the default fetcher path fires and falls back
    // to FREE_TIER with the error surfaced.
    render(
      <BillingProvider>
        <Harness />
      </BillingProvider>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("loading").textContent).toBe("ready"),
    );
    expect(screen.getByTestId("tier").textContent).toBe(FREE_TIER.tier);
    expect(screen.getByTestId("error").textContent).toMatch(/must pass/);
  });

  it("start() guard prevents duplicate intervals on redundant visibilityVisible dispatch", async () => {
    vi.useFakeTimers();
    try {
      const fetcher = vi.fn(async () => PRO_TIER);
      render(
        <BillingProvider fetcher={fetcher} refetchIntervalMs={1000}>
          <Harness />
        </BillingProvider>,
      );

      await drainMicrotasks();
      expect(screen.getByTestId("loading").textContent).toBe("ready");
      const callsAfterMount = fetcher.mock.calls.length;
      expect(callsAfterMount).toBeGreaterThanOrEqual(1);

      // Dispatch visibilitychange even though tab is already visible.
      // onVisibility calls start() which hits the `if (interval) return;` guard.
      act(() => {
        document.dispatchEvent(new Event("visibilitychange"));
      });

      // Advance 1000ms — with only ONE active interval, one fetch fires.
      act(() => {
        vi.advanceTimersByTime(1000);
      });
      await drainMicrotasks();
      expect(fetcher.mock.calls.length).toBe(callsAfterMount + 1);

      // Advance another 1000ms — same single interval fires again.
      act(() => {
        vi.advanceTimersByTime(1000);
      });
      await drainMicrotasks();
      expect(fetcher.mock.calls.length).toBe(callsAfterMount + 2);
    } finally {
      vi.useRealTimers();
    }
  });

  it("does not start interval when document is hidden on mount", async () => {
    // Set document hidden BEFORE mount so the initial check at line 114
    // (if (document.visibilityState === "visible") start();) evaluates false.
    Object.defineProperty(document, "visibilityState", {
      value: "hidden",
      configurable: true,
    });

    vi.useFakeTimers();
    try {
      const fetcher = vi.fn(async () => PRO_TIER);
      render(
        <BillingProvider fetcher={fetcher} refetchIntervalMs={500}>
          <Harness />
        </BillingProvider>,
      );
      await drainMicrotasks();
      expect(screen.getByTestId("loading").textContent).toBe("ready");

      // Initial fetch happened (from the auth-effect), but no interval is active
      const callsAfterMount = fetcher.mock.calls.length;
      expect(callsAfterMount).toBeGreaterThanOrEqual(1);

      // Advance 1000ms — no interval should be running, so no new fetches
      act(() => {
        vi.advanceTimersByTime(1000);
      });
      await drainMicrotasks();
      expect(fetcher.mock.calls.length).toBe(callsAfterMount);

      // Show tab — onVisibility calls start() and creates a new interval
      Object.defineProperty(document, "visibilityState", {
        value: "visible",
        configurable: true,
      });
      act(() => {
        document.dispatchEvent(new Event("visibilitychange"));
      });

      act(() => {
        vi.advanceTimersByTime(500);
      });
      await drainMicrotasks();
      expect(fetcher.mock.calls.length).toBe(callsAfterMount + 1);
    } finally {
      vi.useRealTimers();
      Object.defineProperty(document, "visibilityState", {
        value: "visible",
        configurable: true,
      });
    }
  });

  it("stop() guard handles redundant visibilityHidden dispatch when interval is already null", async () => {
    vi.useFakeTimers();
    try {
      const fetcher = vi.fn(async () => PRO_TIER);
      render(
        <BillingProvider fetcher={fetcher} refetchIntervalMs={1000}>
          <Harness />
        </BillingProvider>,
      );

      await drainMicrotasks();

      // First hide: stop() clears the interval and sets interval = null
      act(() => {
        Object.defineProperty(document, "visibilityState", {
          value: "hidden",
          configurable: true,
        });
        document.dispatchEvent(new Event("visibilitychange"));
      });

      // Second hide: stop() guard fires (interval already null).
      // The `if (!interval) return;` early-return is exercised.
      act(() => {
        document.dispatchEvent(new Event("visibilitychange"));
      });

      // No interval running — advancing time should not trigger fetches
      const callsAfterHide = fetcher.mock.calls.length;
      act(() => {
        vi.advanceTimersByTime(2000);
      });
      await drainMicrotasks();
      expect(fetcher.mock.calls.length).toBe(callsAfterHide);

      // Show again: a new interval should start
      act(() => {
        Object.defineProperty(document, "visibilityState", {
          value: "visible",
          configurable: true,
        });
        document.dispatchEvent(new Event("visibilitychange"));
      });

      act(() => {
        vi.advanceTimersByTime(1000);
      });
      await drainMicrotasks();
      expect(fetcher.mock.calls.length).toBe(callsAfterHide + 1);
    } finally {
      vi.useRealTimers();
      Object.defineProperty(document, "visibilityState", {
        value: "visible",
        configurable: true,
      });
    }
  });
});
