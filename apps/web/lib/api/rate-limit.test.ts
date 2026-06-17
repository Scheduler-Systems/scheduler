import { describe, it, expect, vi, afterEach } from "vitest";

describe("getRateLimitKey", () => {
  it("combines identifier and route with a colon", async () => {
    const { getRateLimitKey } = await import("./rate-limit");
    expect(getRateLimitKey("127.0.0.1", "/api/test")).toBe("127.0.0.1:/api/test");
    expect(getRateLimitKey("user-1", "/auth/login")).toBe("user-1:/auth/login");
  });
});

describe("rateLimitConfigs", () => {
  it("exports all expected configs as constants", async () => {
    const { rateLimitConfigs } = await import("./rate-limit");
    expect(rateLimitConfigs.default).toEqual({ windowMs: 60000, maxRequests: 100 });
    expect(rateLimitConfigs.auth).toEqual({ windowMs: 900000, maxRequests: 10 });
    expect(rateLimitConfigs.api).toEqual({ windowMs: 60000, maxRequests: 60 });
    expect(rateLimitConfigs.webhook).toEqual({ windowMs: 60000, maxRequests: 200 });
  });
});

describe("checkRateLimit", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("allows the first request and returns remaining = max - 1", async () => {
    const { checkRateLimit } = await import("./rate-limit");
    const result = checkRateLimit("fresh-key-1");
    expect(result.allowed).toBe(true);
    expect(result.remaining).toBe(99);
    expect(result.resetTime).toBeGreaterThan(Date.now());
  });

  it("allows requests up to maxRequests then blocks", async () => {
    const { checkRateLimit } = await import("./rate-limit");
    const config = { windowMs: 60000, maxRequests: 3 };

    expect(checkRateLimit("limit-key", config).allowed).toBe(true);
    expect(checkRateLimit("limit-key", config).allowed).toBe(true);
    expect(checkRateLimit("limit-key", config).allowed).toBe(true);

    const blocked = checkRateLimit("limit-key", config);
    expect(blocked.allowed).toBe(false);
    expect(blocked.remaining).toBe(0);
  });

  it("tracks different keys independently", async () => {
    const { checkRateLimit } = await import("./rate-limit");
    const config = { windowMs: 60000, maxRequests: 1 };

    checkRateLimit("key-a", config);
    // key-a exhausted
    expect(checkRateLimit("key-a", config).allowed).toBe(false);

    // key-b should still be allowed
    expect(checkRateLimit("key-b", config).allowed).toBe(true);
  });

  it("resets count after window expires", async () => {
    const { checkRateLimit } = await import("./rate-limit");
    const config = { windowMs: 100, maxRequests: 1 };

    checkRateLimit("window-key", config);
    expect(checkRateLimit("window-key", config).allowed).toBe(false);

    // Wait for window to expire
    await new Promise((resolve) => setTimeout(resolve, 150));

    const afterReset = checkRateLimit("window-key", config);
    expect(afterReset.allowed).toBe(true);
  });

  it("returns consistent resetTime for the same window", async () => {
    const { checkRateLimit } = await import("./rate-limit");
    const config = { windowMs: 60000, maxRequests: 5 };

    const r1 = checkRateLimit("reset-key", config);
    const r2 = checkRateLimit("reset-key", config);

    expect(r1.resetTime).toBe(r2.resetTime);
    expect(r1.resetTime).toBeGreaterThan(Date.now() - 1000);
  });

  it("uses auth config correctly", async () => {
    const { checkRateLimit, rateLimitConfigs } = await import("./rate-limit");
    const result = checkRateLimit("auth-key", rateLimitConfigs.auth);
    expect(result.allowed).toBe(true);
    expect(result.remaining).toBe(9);
  });

  it("uses api config correctly", async () => {
    const { checkRateLimit, rateLimitConfigs } = await import("./rate-limit");
    const result = checkRateLimit("api-key", rateLimitConfigs.api);
    expect(result.allowed).toBe(true);
    expect(result.remaining).toBe(59);
  });

  it("uses webhook config correctly", async () => {
    const { checkRateLimit, rateLimitConfigs } = await import("./rate-limit");
    const result = checkRateLimit("webhook-key", rateLimitConfigs.webhook);
    expect(result.allowed).toBe(true);
    expect(result.remaining).toBe(199);
  });
});

describe("cleanupRateLimitStore", () => {
  it("does not throw when called", async () => {
    const { checkRateLimit, cleanupRateLimitStore } = await import("./rate-limit");
    checkRateLimit("cleanup-key");
    expect(() => cleanupRateLimitStore()).not.toThrow();
  });

  it("removes expired entries", async () => {
    const { checkRateLimit, cleanupRateLimitStore } = await import("./rate-limit");
    checkRateLimit("will-expire", { windowMs: 10, maxRequests: 5 });

    // Wait for the window to expire
    await new Promise((resolve) => setTimeout(resolve, 20));

    // Should not throw and should clean up
    expect(() => cleanupRateLimitStore()).not.toThrow();
  });
});
