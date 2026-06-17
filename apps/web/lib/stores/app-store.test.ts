import { describe, it, expect, beforeEach, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";

vi.stubGlobal("localStorage", undefined);

describe("useAppStore", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.unstubAllGlobals();
  });

  it("has correct default state", async () => {
    const { useAppStore } = await import("./app-store");
    const { result } = renderHook(() => useAppStore());

    expect(result.current.currentScheduleId).toBeNull();
    expect(result.current.sidebarOpen).toBe(true);
    expect(result.current.onboardingStep).toBe(0);
    expect(result.current.currentDisplayName).toBe("");
  });

  it("setCurrentSchedule sets currentScheduleId", async () => {
    const { useAppStore } = await import("./app-store");
    const { result } = renderHook(() => useAppStore());

    act(() => {
      result.current.setCurrentSchedule("schedule-1");
    });

    expect(result.current.currentScheduleId).toBe("schedule-1");
  });

  it("setCurrentSchedule can clear with null", async () => {
    const { useAppStore } = await import("./app-store");
    const { result } = renderHook(() => useAppStore());

    act(() => {
      result.current.setCurrentSchedule("schedule-1");
    });
    expect(result.current.currentScheduleId).toBe("schedule-1");

    act(() => {
      result.current.setCurrentSchedule(null);
    });
    expect(result.current.currentScheduleId).toBeNull();
  });

  it("toggleSidebar flips sidebarOpen", async () => {
    const { useAppStore } = await import("./app-store");
    const { result } = renderHook(() => useAppStore());

    expect(result.current.sidebarOpen).toBe(true);

    act(() => {
      result.current.toggleSidebar();
    });
    expect(result.current.sidebarOpen).toBe(false);

    act(() => {
      result.current.toggleSidebar();
    });
    expect(result.current.sidebarOpen).toBe(true);
  });

  it("setOnboardingStep updates the step", async () => {
    const { useAppStore } = await import("./app-store");
    const { result } = renderHook(() => useAppStore());

    act(() => {
      result.current.setOnboardingStep(3);
    });
    expect(result.current.onboardingStep).toBe(3);
  });

  it("setCurrentDisplayName sets the name", async () => {
    const { useAppStore } = await import("./app-store");
    const { result } = renderHook(() => useAppStore());

    act(() => {
      result.current.setCurrentDisplayName("Test User");
    });
    expect(result.current.currentDisplayName).toBe("Test User");
  });

  it("supports multiple stores independently", async () => {
    const { useAppStore } = await import("./app-store");
    const { result: r1 } = renderHook(() => useAppStore());
    const { result: r2 } = renderHook(() => useAppStore());

    act(() => {
      r1.current.setCurrentSchedule("sched-a");
    });

    expect(r2.current.currentScheduleId).toBe("sched-a");
  });
});
