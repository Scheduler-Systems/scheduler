import { describe, it, expect, beforeEach, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";

describe("usePremiumStore", () => {
  beforeEach(() => {
    vi.resetModules();
  });

  it("has correct default state", async () => {
    const { usePremiumStore } = await import("./premium-store");
    const { result } = renderHook(() => usePremiumStore());

    expect(result.current.isPremium).toBe(false);
    expect(result.current.subscriptionTier).toBeNull();
    expect(result.current.subscriptionExpiry).toBeNull();
  });

  it("setPremium updates isPremium", async () => {
    const { usePremiumStore } = await import("./premium-store");
    const { result } = renderHook(() => usePremiumStore());

    act(() => {
      result.current.setPremium(true);
    });

    expect(result.current.isPremium).toBe(true);
  });

  it("setPremium can set back to false", async () => {
    const { usePremiumStore } = await import("./premium-store");
    const { result } = renderHook(() => usePremiumStore());

    act(() => {
      result.current.setPremium(true);
    });
    expect(result.current.isPremium).toBe(true);

    act(() => {
      result.current.setPremium(false);
    });
    expect(result.current.isPremium).toBe(false);
  });

  it("setSubscriptionTier updates the tier", async () => {
    const { usePremiumStore } = await import("./premium-store");
    const { result } = renderHook(() => usePremiumStore());

    act(() => {
      result.current.setSubscriptionTier("pro");
    });
    expect(result.current.subscriptionTier).toBe("pro");

    act(() => {
      result.current.setSubscriptionTier("enterprise");
    });
    expect(result.current.subscriptionTier).toBe("enterprise");

    act(() => {
      result.current.setSubscriptionTier("free");
    });
    expect(result.current.subscriptionTier).toBe("free");

    act(() => {
      result.current.setSubscriptionTier(null);
    });
    expect(result.current.subscriptionTier).toBeNull();
  });

  it("setSubscriptionExpiry updates the expiry date", async () => {
    const { usePremiumStore } = await import("./premium-store");
    const { result } = renderHook(() => usePremiumStore());

    const expiry = new Date("2026-12-31");
    act(() => {
      result.current.setSubscriptionExpiry(expiry);
    });
    expect(result.current.subscriptionExpiry).toEqual(expiry);
  });

  it("setSubscriptionExpiry can clear to null", async () => {
    const { usePremiumStore } = await import("./premium-store");
    const { result } = renderHook(() => usePremiumStore());

    act(() => {
      result.current.setSubscriptionExpiry(new Date());
    });
    expect(result.current.subscriptionExpiry).not.toBeNull();

    act(() => {
      result.current.setSubscriptionExpiry(null);
    });
    expect(result.current.subscriptionExpiry).toBeNull();
  });
});
