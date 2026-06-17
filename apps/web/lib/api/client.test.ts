import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// ---- Mutable auth state (controlled per test) ----

const TEST_CORRELATION_ID = "550e8400-e29b-41d4-a716-446655440000";
const TEST_ID_TOKEN = "test-firebase-id-token";
const TEST_UID = "test-user-uid-123";
const TEST_TENANT = "test-tenant-id";
const TEST_BASE_URL = "https://api.scheduler.test";

// These must be set before module imports evaluate the module-level constants.
process.env.NEXT_PUBLIC_SCHEDULER_API_URL = TEST_BASE_URL;
process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID = TEST_TENANT;

// ---- Mocks ----

let mockCurrentUser: { uid: string; getIdToken: () => Promise<string> } | null = {
  uid: TEST_UID,
  getIdToken: vi.fn().mockResolvedValue(TEST_ID_TOKEN),
};

vi.mock("@/lib/firebase", () => ({
  getFirebaseAuth: vi.fn(() => ({
    get currentUser() {
      return mockCurrentUser;
    },
  })),
}));

// ---- Import the module under test AFTER mocks are registered ----
const client = await import("./client");

// ---- Helpers ----

function mockFetchResponse(
  body: unknown,
  status = 200,
  statusText = "OK",
): void {
  globalThis.fetch = vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    statusText,
    json: () => Promise.resolve(body),
  });
}

function mockFetchNetworkError(): void {
  globalThis.fetch = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
}

beforeEach(() => {
  vi.clearAllMocks();
  // Restore authenticated user as default
  mockCurrentUser = {
    uid: TEST_UID,
    getIdToken: vi.fn().mockResolvedValue(TEST_ID_TOKEN),
  };
  // Stub crypto.randomUUID for deterministic correlation IDs
  vi.stubGlobal("crypto", {
    randomUUID: () => TEST_CORRELATION_ID,
  });
  // Default: successful fetch
  mockFetchResponse({});
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

// =========================================================================
// Header / Auth tests
// =========================================================================

describe("request headers", () => {
  it("sends Authorization header with Bearer token", async () => {
    mockFetchResponse({ items: [] });
    await client.listSchedules();
    const callHeaders = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0][1].headers;
    expect(callHeaders.Authorization).toBe(`Bearer ${TEST_ID_TOKEN}`);
  });

  it("sends x-tenant-id header", async () => {
    mockFetchResponse({ items: [] });
    await client.listSchedules();
    const callHeaders = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0][1].headers;
    expect(callHeaders["x-tenant-id"]).toBe(TEST_TENANT);
  });

  it("sends x-user-id header with the current user's uid", async () => {
    mockFetchResponse({ items: [] });
    await client.listSchedules();
    const callHeaders = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0][1].headers;
    expect(callHeaders["x-user-id"]).toBe(TEST_UID);
  });

  it("sends x-correlation-id header", async () => {
    mockFetchResponse({ items: [] });
    await client.listSchedules();
    const callHeaders = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0][1].headers;
    expect(callHeaders["x-correlation-id"]).toBe(TEST_CORRELATION_ID);
  });

  it("sends Content-Type: application/json", async () => {
    mockFetchResponse({ items: [] });
    await client.listSchedules();
    const callHeaders = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0][1].headers;
    expect(callHeaders["Content-Type"]).toBe("application/json");
  });

  it("sends x-user-role: manager", async () => {
    mockFetchResponse({ items: [] });
    await client.listSchedules();
    const callHeaders = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0][1].headers;
    expect(callHeaders["x-user-role"]).toBe("manager");
  });
});

describe("unauthenticated user", () => {
  it("sends empty Authorization and x-user-id when no user is logged in", async () => {
    mockCurrentUser = null;
    mockFetchResponse({ items: [] });
    await client.listSchedules();
    const callHeaders = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0][1].headers;
    expect(callHeaders.Authorization).toBe("Bearer ");
    expect(callHeaders["x-user-id"]).toBe("");
  });
});

// =========================================================================
// Error handling
// =========================================================================

describe("error handling", () => {
  it("throws on network failure", async () => {
    mockFetchNetworkError();
    await expect(client.listSchedules()).rejects.toThrow(TypeError);
  });

  it("throws on 400 Bad Request", async () => {
    mockFetchResponse({ message: "Invalid input" }, 400, "Bad Request");
    await expect(client.listSchedules()).rejects.toThrow(/Invalid input/);
  });

  it("throws on 401 Unauthorized", async () => {
    mockFetchResponse({}, 401, "Unauthorized");
    await expect(client.listSchedules()).rejects.toThrow(/API 401: Unauthorized/);
  });

  it("throws on 500 Internal Server Error", async () => {
    mockFetchResponse({}, 500, "Internal Server Error");
    await expect(client.listSchedules()).rejects.toThrow(/API 500: Internal Server Error/);
  });

  it("falls back to status text when response body has no message", async () => {
    mockFetchResponse({ notMessage: "ignored" }, 403, "Forbidden");
    await expect(client.listSchedules()).rejects.toThrow(/API 403: Forbidden/);
  });

  it("prefers the message from the response body over status text", async () => {
    mockFetchResponse({ message: "Custom error" }, 422, "Unprocessable");
    await expect(client.listSchedules()).rejects.toThrow(/Custom error/);
  });
});

// =========================================================================
// Successful response parsing
// =========================================================================

describe("response parsing", () => {
  it("returns parsed JSON from a successful response", async () => {
    mockFetchResponse({ items: [{ id: "s1", name: "Test Schedule" }] });
    const result = await client.listSchedules();
    expect(result).toEqual({ items: [{ id: "s1", name: "Test Schedule" }] });
  });

  it("handles empty response body gracefully", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.reject(new SyntaxError("Unexpected end of JSON input")),
    });
    const result = await client.listSchedules();
    expect(result).toEqual({});
  });
});

// =========================================================================
// Per-function HTTP method, URL, and body checks
// =========================================================================

describe("listSchedules", () => {
  it("calls GET /v1/tenants/{tenantId}/schedules", async () => {
    mockFetchResponse({ items: [] });
    await client.listSchedules();
    const call = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(call[0]).toBe(`${TEST_BASE_URL}/v1/tenants/${TEST_TENANT}/schedules`);
    // No method means GET by default (fetch default)
    expect(call[1].method ?? "GET").toBe("GET");
    expect(call[1].body).toBeUndefined();
  });
});

describe("getSchedule", () => {
  it("calls GET /v1/tenants/{tenantId}/schedules/{scheduleId}", async () => {
    mockFetchResponse({ id: "s1", name: "My Schedule" });
    await client.getSchedule("s1");
    const call = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(call[0]).toBe(`${TEST_BASE_URL}/v1/tenants/${TEST_TENANT}/schedules/s1`);
    expect(call[1].method ?? "GET").toBe("GET");
    expect(call[1].body).toBeUndefined();
  });
});

describe("createSchedule", () => {
  it("calls POST /v1/tenants/{tenantId}/schedules with JSON body", async () => {
    mockFetchResponse({ id: "s1", name: "New Schedule" });
    const input = { name: "New Schedule", settings: { timezone: "UTC" } };
    await client.createSchedule(input);
    const call = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(call[0]).toBe(`${TEST_BASE_URL}/v1/tenants/${TEST_TENANT}/schedules`);
    expect(call[1].method).toBe("POST");
    expect(JSON.parse(call[1].body)).toEqual(input);
  });

  it("works with only name (minimal input)", async () => {
    mockFetchResponse({ id: "s2", name: "Minimal" });
    await client.createSchedule({ name: "Minimal" });
    const call = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(JSON.parse(call[1].body)).toEqual({ name: "Minimal" });
  });
});

describe("updateSchedule", () => {
  it("calls PATCH /v1/tenants/{tenantId}/schedules/{scheduleId} with updates", async () => {
    mockFetchResponse({ id: "s1", name: "Updated" });
    await client.updateSchedule("s1", { name: "Updated" });
    const call = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(call[0]).toBe(`${TEST_BASE_URL}/v1/tenants/${TEST_TENANT}/schedules/s1`);
    expect(call[1].method).toBe("PATCH");
    expect(JSON.parse(call[1].body)).toEqual({ updates: { name: "Updated" } });
  });
});

describe("deleteSchedule", () => {
  it("calls DELETE /v1/tenants/{tenantId}/schedules/{scheduleId}", async () => {
    mockFetchResponse({ success: true, id: "s1" });
    await client.deleteSchedule("s1");
    const call = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(call[0]).toBe(`${TEST_BASE_URL}/v1/tenants/${TEST_TENANT}/schedules/s1`);
    expect(call[1].method).toBe("DELETE");
    expect(call[1].body).toBeUndefined();
  });
});

describe("createDraft", () => {
  it("calls POST /v1/tenants/{tenantId}/schedules/{scheduleId}/drafts with shifts", async () => {
    mockFetchResponse({ id: "d1", shifts: [] });
    const shifts = [{ employeeId: "e1", start: "09:00" }];
    await client.createDraft("s1", shifts);
    const call = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(call[0]).toBe(`${TEST_BASE_URL}/v1/tenants/${TEST_TENANT}/schedules/s1/drafts`);
    expect(call[1].method).toBe("POST");
    expect(JSON.parse(call[1].body)).toEqual({ shifts });
  });
});

describe("publishDraft", () => {
  it("calls POST /v1/tenants/{tenantId}/schedules/{scheduleId}/publish with draftId", async () => {
    mockFetchResponse({ id: "pub1", publishedAt: "2026-01-01T00:00:00Z" });
    await client.publishDraft("s1", "d1");
    const call = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(call[0]).toBe(`${TEST_BASE_URL}/v1/tenants/${TEST_TENANT}/schedules/s1/publish`);
    expect(call[1].method).toBe("POST");
    expect(JSON.parse(call[1].body)).toEqual({ draftId: "d1" });
  });
});

describe("submitAvailability", () => {
  it("calls POST /v1/tenants/{tenantId}/schedules/{scheduleId}/availability", async () => {
    mockFetchResponse({ id: "a1", state: "submitted" });
    const availability = { mon: ["09:00-17:00"] };
    await client.submitAvailability("s1", availability);
    const call = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(call[0]).toBe(`${TEST_BASE_URL}/v1/tenants/${TEST_TENANT}/schedules/s1/availability`);
    expect(call[1].method).toBe("POST");
    expect(JSON.parse(call[1].body)).toEqual({ availability });
  });
});

describe("createRequest", () => {
  it("calls POST /v1/tenants/{tenantId}/schedules/{scheduleId}/requests", async () => {
    mockFetchResponse({ id: "r1", type: "time-off", state: "pending" });
    await client.createRequest("s1", "time-off", { reason: "vacation" });
    const call = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(call[0]).toBe(`${TEST_BASE_URL}/v1/tenants/${TEST_TENANT}/schedules/s1/requests`);
    expect(call[1].method).toBe("POST");
    expect(JSON.parse(call[1].body)).toEqual({ type: "time-off", details: { reason: "vacation" } });
  });
});

// =========================================================================
// Env var fallback coverage (the two uncovered ?? branches)
// =========================================================================

describe("env var fallbacks", () => {
  it("uses the placeholder tenant ID when NEXT_PUBLIC_FIREBASE_PROJECT_ID is unset", async () => {
    const oldId = process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID;
    delete process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID;
    mockFetchResponse({ items: [] });
    await client.listSchedules();
    const [, opts] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(opts.headers["x-tenant-id"]).toBe("your-firebase-project-id");
    process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID = oldId;
  });

  it("uses empty BASE_URL when NEXT_PUBLIC_SCHEDULER_API_URL is unset", async () => {
    const oldUrl = process.env.NEXT_PUBLIC_SCHEDULER_API_URL;
    delete process.env.NEXT_PUBLIC_SCHEDULER_API_URL;
    vi.resetModules();
    mockFetchResponse({ items: [] });
    const mod = await import("./client");
    await mod.listSchedules();
    const [url] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    // With no base URL, the request path is used directly (no prefix)
    expect(url).toBe(`/v1/tenants/${TEST_TENANT}/schedules`);
    process.env.NEXT_PUBLIC_SCHEDULER_API_URL = oldUrl;
  });
});
