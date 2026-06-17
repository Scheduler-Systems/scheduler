import { describe, it, expect, vi, beforeEach } from "vitest";
import { NextRequest } from "next/server";

const mockVerifySessionCookie = vi.fn();
const mockHandleCorsPreflight = vi.fn();
const mockCorsErrorResponse = vi.fn();
const mockCheckRateLimit = vi.fn();
const mockGetRateLimitKey = vi.fn();

vi.mock("@/lib/firebase/server", () => ({
  verifySessionCookie: (...args: unknown[]) => mockVerifySessionCookie(...args),
}));

vi.mock("./cors", () => ({
  corsErrorResponse: (...args: unknown[]) => mockCorsErrorResponse(...args),
  handleCorsPreflight: (...args: unknown[]) => mockHandleCorsPreflight(...args),
}));

vi.mock("./rate-limit", () => ({
  checkRateLimit: (...args: unknown[]) => mockCheckRateLimit(...args),
  getRateLimitKey: (...args: unknown[]) => mockGetRateLimitKey(...args),
  rateLimitConfigs: {
    default: { windowMs: 60000, maxRequests: 100 },
    auth: { windowMs: 900000, maxRequests: 10 },
    api: { windowMs: 60000, maxRequests: 60 },
    webhook: { windowMs: 60000, maxRequests: 200 },
  },
}));

const { getAuthContext, getClientIdentifier, withAuth, optionalAuth } = await import("./auth");

function makeNextRequest(overrides: {
  url?: string;
  method?: string;
  headers?: Record<string, string>;
  cookieValue?: string | null;
} = {}): NextRequest {
  const url = overrides.url ?? "http://localhost:3000/api/test";
  const method = overrides.method ?? "GET";
  const headers = new Headers(overrides.headers ?? {});
  if (overrides.cookieValue !== undefined) {
    if (overrides.cookieValue !== null) {
      headers.set("cookie", `session=${overrides.cookieValue}`);
    }
  }
  return new NextRequest(url, { method, headers });
}

describe("getAuthContext", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockVerifySessionCookie.mockResolvedValue({ uid: "u1", email: "u1@test.com", valid: true });
    mockCheckRateLimit.mockReturnValue({ allowed: true, remaining: 59, resetTime: Date.now() + 60000 });
    mockGetRateLimitKey.mockReturnValue("client:route");
    mockCorsErrorResponse.mockReturnValue(new Response(JSON.stringify({ error: "err" }), { status: 429 }));
    mockHandleCorsPreflight.mockReturnValue(new Response(null, { status: 204 }));
  });

  it("returns null when no session cookie is present", async () => {
    const req = makeNextRequest();
    const result = await getAuthContext(req);
    expect(result).toBeNull();
  });

  it("returns null when verifySessionCookie returns invalid", async () => {
    mockVerifySessionCookie.mockResolvedValue({ uid: null, email: null, valid: false });
    const req = makeNextRequest({ cookieValue: "bad-cookie" });
    const result = await getAuthContext(req);
    expect(result).toBeNull();
  });

  it("returns auth context when session is valid", async () => {
    mockVerifySessionCookie.mockResolvedValue({ uid: "u1", email: "u1@test.com", valid: true });
    const req = makeNextRequest({ cookieValue: "valid-cookie" });
    const result = await getAuthContext(req);
    expect(result).toEqual({ uid: "u1", email: "u1@test.com", authenticated: true });
  });

  it("handles null email in auth context", async () => {
    mockVerifySessionCookie.mockResolvedValue({ uid: "u2", email: null, valid: true });
    const req = makeNextRequest({ cookieValue: "valid-cookie" });
    const result = await getAuthContext(req);
    expect(result).toEqual({ uid: "u2", email: null, authenticated: true });
  });
});

describe("getClientIdentifier", () => {
  it("uses x-forwarded-for when present", () => {
    const req = makeNextRequest({
      headers: {
        "x-forwarded-for": "10.0.0.1, 10.0.0.2",
        "user-agent": "test-agent",
      },
    });
    const id = getClientIdentifier(req);
    expect(id).toContain("10.0.0.1");
    expect(id).toContain("test-agent");
  });

  it("falls back to 'unknown' when headers are missing", () => {
    const req = makeNextRequest();
    const id = getClientIdentifier(req);
    expect(id).toBe("unknown:unknown");
  });

  it("truncates user-agent to 50 characters", () => {
    const longUA = "a".repeat(100);
    const req = makeNextRequest({
      headers: {
        "x-forwarded-for": "1.2.3.4",
        "user-agent": longUA,
      },
    });
    const id = getClientIdentifier(req);
    const parts = id.split(":");
    expect(parts[1]).toHaveLength(50);
  });
});

describe("withAuth", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockVerifySessionCookie.mockResolvedValue({ uid: "u1", email: "u1@test.com", valid: true });
    mockCheckRateLimit.mockReturnValue({ allowed: true, remaining: 59, resetTime: Date.now() + 60000 });
    mockGetRateLimitKey.mockReturnValue("client:route");
    mockCorsErrorResponse.mockReturnValue(new Response(JSON.stringify({ error: "err" }), { status: 429 }));
    mockHandleCorsPreflight.mockReturnValue(new Response(null, { status: 204 }));
  });

  it("handles OPTIONS preflight", async () => {
    const handler = vi.fn();
    const wrapped = withAuth(handler);
    const req = makeNextRequest({ method: "OPTIONS" });

    await wrapped(req, { params: Promise.resolve({}) });
    expect(mockHandleCorsPreflight).toHaveBeenCalled();
    expect(handler).not.toHaveBeenCalled();
  });

  it("blocks when rate limit is exceeded", async () => {
    mockCheckRateLimit.mockReturnValue({ allowed: false, remaining: 0, resetTime: Date.now() + 60000 });
    const handler = vi.fn();
    const wrapped = withAuth(handler);

    const req = makeNextRequest({
      headers: {
        "x-forwarded-for": "1.2.3.4",
      },
      cookieValue: "valid-cookie",
    });

    await wrapped(req, { params: Promise.resolve({}) });
    expect(mockCorsErrorResponse).toHaveBeenCalledWith("Rate limit exceeded", 429, expect.anything());
    expect(handler).not.toHaveBeenCalled();
  });

  it("blocks unauthenticated requests when requireAuth is true", async () => {
    mockVerifySessionCookie.mockResolvedValue({ uid: null, email: null, valid: false });
    const handler = vi.fn();
    const wrapped = withAuth(handler);

    const req = makeNextRequest({ cookieValue: "bad-cookie" });

    await wrapped(req, { params: Promise.resolve({}) });
    expect(mockCorsErrorResponse).toHaveBeenCalledWith("Unauthorized", 401, expect.anything());
    expect(handler).not.toHaveBeenCalled();
  });

  it("calls handler when authenticated", async () => {
    mockVerifySessionCookie.mockResolvedValue({ uid: "u1", email: "u1@test.com", valid: true });
    const handler = vi.fn().mockResolvedValue(new Response(JSON.stringify({ success: true })));
    const wrapped = withAuth(handler);

    const req = makeNextRequest({ cookieValue: "valid-cookie" });

    await wrapped(req, { params: Promise.resolve({ id: "123" }) });
    expect(handler).toHaveBeenCalledWith(req, expect.objectContaining({ uid: "u1" }), { id: "123" });
  });

  it("calls handler without auth when requireAuth is false", async () => {
    const handler = vi.fn().mockResolvedValue(new Response(JSON.stringify({ success: true })));
    const wrapped = withAuth(handler, { requireAuth: false, rateLimitConfig: "api" });

    const req = makeNextRequest();

    await wrapped(req, { params: Promise.resolve({}) });
    expect(handler).toHaveBeenCalled();
  });

  it("uses correct rate limit key composed of client id and route", async () => {
    const handler = vi.fn().mockResolvedValue(new Response(JSON.stringify({ success: true })));
    const wrapped = withAuth(handler, { requireAuth: false, rateLimitConfig: "api" });

    const req = makeNextRequest({
      url: "http://localhost:3000/api/schedules/123",
      headers: {
        "x-forwarded-for": "10.0.0.1",
        "user-agent": "test-agent",
      },
    });

    await wrapped(req, { params: Promise.resolve({}) });
    expect(mockGetRateLimitKey).toHaveBeenCalled();
    expect(mockCheckRateLimit).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({ windowMs: 60000, maxRequests: 60 }),
    );
  });
});

describe("optionalAuth", () => {
  it("returns a wrapped handler with requireAuth false", async () => {
    vi.clearAllMocks();
    mockCheckRateLimit.mockReturnValue({ allowed: true, remaining: 59, resetTime: Date.now() + 60000 });
    mockGetRateLimitKey.mockReturnValue("client:route");

    const handler = vi.fn().mockResolvedValue(new Response(JSON.stringify({ success: true })));
    const wrapped = optionalAuth(handler);

    const req = makeNextRequest();
    await wrapped(req, { params: Promise.resolve({}) });
    expect(handler).toHaveBeenCalled();
  });
});
