import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import { ScheduleBuiltCelebration } from "./schedule-built-celebration";

// jsdom has no real canvas 2d context; stub a no-op so the burst effect runs
// without throwing. We're testing the celebration's lifecycle/markup, not pixels.
beforeEach(() => {
  vi.useFakeTimers();
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(
    {
      setTransform: vi.fn(),
      clearRect: vi.fn(),
      save: vi.fn(),
      restore: vi.fn(),
      translate: vi.fn(),
      rotate: vi.fn(),
      fillRect: vi.fn(),
      globalAlpha: 1,
      fillStyle: "",
    } as unknown as CanvasRenderingContext2D,
  );
  // Run one rAF frame synchronously and never schedule another (the burst
  // loop calls rAF again until its duration elapses; returning a fixed id and
  // not recursing keeps the test deterministic without leaking timers). cancel
  // is a no-op so React's effect cleanup can't mismatch timer families.
  let rafCalls = 0;
  vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback): number => {
    if (rafCalls === 0) {
      rafCalls += 1;
      cb(performance.now());
    }
    return 1;
  });
  vi.stubGlobal("cancelAnimationFrame", (): void => {});
});

afterEach(() => {
  vi.runOnlyPendingTimers();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("ScheduleBuiltCelebration", () => {
  it("renders nothing when show is false", () => {
    render(<ScheduleBuiltCelebration show={false} onDone={() => {}} />);
    expect(screen.queryByTestId("schedule-built-celebration")).toBeNull();
  });

  it("renders the schedule-ready banner when show is true", () => {
    render(<ScheduleBuiltCelebration show onDone={() => {}} />);
    const overlay = screen.getByTestId("schedule-built-celebration");
    expect(overlay).toBeInTheDocument();
    // The Flutter "Congrats! Your new schedule is ready." beat
    // (internationalization.dart "NewScheduleCreated").
    expect(
      screen.getByTestId("schedule-built-celebration-banner"),
    ).toHaveTextContent("schedule is ready");
  });

  it("overlay does not capture pointer events (mirrors Flutter IgnorePointer)", () => {
    render(<ScheduleBuiltCelebration show onDone={() => {}} />);
    expect(screen.getByTestId("schedule-built-celebration")).toHaveClass(
      "pointer-events-none",
    );
  });

  it("auto-dismisses via onDone after the celebration duration", () => {
    const onDone = vi.fn();
    render(<ScheduleBuiltCelebration show onDone={onDone} />);
    expect(onDone).not.toHaveBeenCalled();
    act(() => {
      vi.advanceTimersByTime(2600);
    });
    expect(onDone).toHaveBeenCalledTimes(1);
  });

  it("skips the canvas burst under prefers-reduced-motion but still shows the banner", () => {
    vi.stubGlobal(
      "matchMedia",
      (q: string) =>
        ({
          matches: q.includes("prefers-reduced-motion"),
          media: q,
          addEventListener: vi.fn(),
          removeEventListener: vi.fn(),
        }) as unknown as MediaQueryList,
    );
    const getContextSpy = vi.spyOn(HTMLCanvasElement.prototype, "getContext");
    render(<ScheduleBuiltCelebration show onDone={() => {}} />);
    // Banner still present (the celebratory message survives reduced motion).
    expect(
      screen.getByTestId("schedule-built-celebration-banner"),
    ).toBeInTheDocument();
    // The particle effect early-returns before touching the canvas context.
    expect(getContextSpy).not.toHaveBeenCalled();
  });
});
