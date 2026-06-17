import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// Mock the auth-context so we can control the signed-in user without booting
// Firebase. The billing-context module imports useAuth from "./auth-context".
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

// Also mock the billing/client import so we never accidentally touch
// Firebase — tests drive the context via the `fetcher` prop.
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

describe("BillingProvider", () => {
  beforeEach(() => {
    authState.user = { uid: "u-1" };
    vi.clearAllMocks();
  });

  it("loads → ready and surfaces the fetched entitlements", async () => {
    const fetcher = vi.fn(async () => PRO_TIER);
    render(
      <BillingProvider fetcher={fetcher}>
        <Harness />
      </BillingProvider>,
    );
    // loading flips true → false as the effect runs
    await waitFor(() =>
      expect(screen.getByTestId("loading").textContent).toBe("ready"),
    );
    expect(screen.getByTestId("tier").textContent).toBe("pro");
    expect(screen.getByTestId("userLimit").textContent).toBe("30");
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("falls back to the free tier when the fetcher throws", async () => {
    const boom = new Error("cloud function down");
    const fetcher = vi.fn(async () => {
      throw boom;
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
    expect(screen.getByTestId("userLimit").textContent).toBe(
      String(FREE_TIER.userLimit),
    );
    expect(screen.getByTestId("error").textContent).toBe("cloud function down");
  });

  it("refetch() re-invokes the fetcher", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(PRO_TIER)
      .mockResolvedValueOnce({ ...PRO_TIER, userLimit: 50, entitlements: ["pro_50"] });
    render(
      <BillingProvider fetcher={fetcher}>
        <Harness />
      </BillingProvider>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("userLimit").textContent).toBe("30"),
    );
    const user = userEvent.setup();
    await user.click(screen.getByText("refetch"));
    await waitFor(() =>
      expect(screen.getByTestId("userLimit").textContent).toBe("50"),
    );
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("resets to free tier + skips network when user is signed out", async () => {
    authState.user = null;
    const fetcher = vi.fn(async () => PRO_TIER);
    render(
      <BillingProvider fetcher={fetcher}>
        <Harness />
      </BillingProvider>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("tier").textContent).toBe(FREE_TIER.tier),
    );
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("refires after a refetchIntervalMs while the tab is focused", async () => {
    vi.useFakeTimers();
    try {
      const fetcher = vi.fn(async () => PRO_TIER);
      render(
        <BillingProvider fetcher={fetcher} refetchIntervalMs={1000}>
          <Harness />
        </BillingProvider>,
      );
      // drain the initial microtask-queued fetch
      await vi.runOnlyPendingTimersAsync();
      await act(async () => {
        await Promise.resolve();
      });
      const initialCalls = fetcher.mock.calls.length;
      expect(initialCalls).toBeGreaterThanOrEqual(1);

      // Advance 1s of fake time → at least one additional call from the interval.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1000);
      });
      expect(fetcher.mock.calls.length).toBeGreaterThan(initialCalls);
    } finally {
      vi.useRealTimers();
    }
  });

  it("throws when useBilling is used outside a provider", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => undefined);
    expect(() => render(<Harness />)).toThrow(/BillingProvider/);
    spy.mockRestore();
  });
});
