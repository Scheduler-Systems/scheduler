import assert from "node:assert/strict";
import test from "node:test";

// --- Auth middleware tests ---

test("getAuthContext returns null without session cookie", async () => {
  const { getAuthContext } = await import("../lib/api/auth.ts");
  const req = { cookies: { get: () => undefined } };
  const result = await getAuthContext(req);
  assert.equal(result, null);
});

test("getAuthContext returns null for invalid session", async () => {
  const { getAuthContext } = await import("../lib/api/auth.ts");

  const req = {
    cookies: {
      get(name) {
        if (name === "session") return { value: "bad_token" };
      },
    },
  };
  const result = await getAuthContext(req);
  assert.equal(result, null);
});

test("getClientIdentifier uses x-forwarded-for and user-agent", async () => {
  const { getClientIdentifier } = await import("../lib/api/auth.ts");
  const req = {
    headers: {
      get(name) {
        if (name === "x-forwarded-for") return "10.0.0.1, 10.0.0.2";
        if (name === "user-agent") return "Mozilla/5.0 test-browser";
      },
    },
  };
  const id = getClientIdentifier(req);
  assert.match(id, /^10\.0\.0\.1:/);
  assert.ok(id.includes("Mozilla"));
});

test("getClientIdentifier returns unknown for missing headers", async () => {
  const { getClientIdentifier } = await import("../lib/api/auth.ts");
  const req = { headers: { get: () => undefined } };
  const id = getClientIdentifier(req);
  assert.equal(id, "unknown:unknown");
});

// --- CORS tests ---

test("corsHeaders returns allowed origins for known origin", async () => {
  const { corsHeaders } = await import("../lib/api/cors.ts");
  const headers = corsHeaders("http://localhost:3000");
  assert.equal(headers["Access-Control-Allow-Origin"], "http://localhost:3000");
  assert.equal(headers["Access-Control-Allow-Credentials"], "true");
});

test("corsHeaders omits allow-origin for unknown origin", async () => {
  const { corsHeaders } = await import("../lib/api/cors.ts");
  const headers = corsHeaders("https://evil.com");
  assert.equal(headers["Access-Control-Allow-Origin"], undefined);
});

test("handleCorsPreflight returns 204", async () => {
  const { handleCorsPreflight } = await import("../lib/api/cors.ts");
  const req = { headers: { get: () => "http://localhost:3000" } };
  const res = handleCorsPreflight(req);
  assert.equal(res.status, 204);
});

// --- Rate limit tests ---

test("checkRateLimit allows requests within window", async () => {
  const { checkRateLimit, getRateLimitKey } =
    await import("../lib/api/rate-limit.ts");
  const key = getRateLimitKey("test:limit", "/api/test");
  const result = checkRateLimit(key, { windowMs: 60000, maxRequests: 5 });
  assert.equal(result.allowed, true);
  assert.equal(result.remaining, 4);
});

test("checkRateLimit blocks after exceeding max", async () => {
  const { checkRateLimit, getRateLimitKey } =
    await import("../lib/api/rate-limit.ts");
  const key = getRateLimitKey("test:block", "/api/block");
  for (let i = 0; i < 3; i++)
    checkRateLimit(key, { windowMs: 60000, maxRequests: 3 });
  const result = checkRateLimit(key, { windowMs: 60000, maxRequests: 3 });
  assert.equal(result.allowed, false);
  assert.equal(result.remaining, 0);
});

test("checkRateLimit resets after window", async () => {
  const { checkRateLimit, getRateLimitKey } =
    await import("../lib/api/rate-limit.ts");
  const key = getRateLimitKey("test:reset", "/api/reset");

  const frozenNow = 1000000;
  const origNow = Date.now;
  Date.now = () => frozenNow;

  checkRateLimit(key, { windowMs: 1000, maxRequests: 1 });
  assert.equal(
    checkRateLimit(key, { windowMs: 1000, maxRequests: 1 }).allowed,
    false,
  );

  Date.now = () => frozenNow + 2000;
  assert.equal(
    checkRateLimit(key, { windowMs: 1000, maxRequests: 1 }).allowed,
    true,
  );

  Date.now = origNow;
});

// --- Validation schemas ---

test("paginationSchema defaults page to 1 and pageSize to 20", async () => {
  const { paginationSchema } = await import("../types/api.ts");
  const result = paginationSchema.parse({});
  assert.equal(result.page, 1);
  assert.equal(result.pageSize, 20);
});

test("scheduleCreateSchema validates valid input", async () => {
  const { scheduleCreateSchema } = await import("../types/api.ts");
  const result = scheduleCreateSchema.parse({
    scheduleName: "Test Schedule",
    employees: [
      {
        employeeName: "Alice",
        employeeId: "alice_1",
        employeeRole: "manager",
        employeePriority: 1,
        employeeAvailability: ["morning", "night"],
      },
    ],
    currentPriorities: ["alice_1"],
    scheduleSettings: {
      shiftHours: {
        morning: "06:00-14:00",
        noon: "14:00-22:00",
        night: "22:00-06:00",
      },
      timezone: "UTC",
    },
  });
  assert.equal(result.scheduleName, "Test Schedule");
  assert.equal(result.employees.length, 1);
});

test("scheduleCreateSchema rejects empty employees", async () => {
  const { scheduleCreateSchema } = await import("../types/api.ts");
  assert.throws(() => {
    scheduleCreateSchema.parse({
      scheduleName: "Test",
      employees: [],
      currentPriorities: [],
      scheduleSettings: {
        shiftHours: { morning: "", noon: "", night: "" },
        timezone: "",
      },
    });
  });
});

test("employeeCreateSchema validates employee role", async () => {
  const { employeeCreateSchema } = await import("../types/api.ts");
  const result = employeeCreateSchema.parse({
    employeeName: "Bob",
    employeeId: "bob_1",
    employeeRole: "worker",
    employeePriority: 0,
    employeeAvailability: [],
  });
  assert.equal(result.employeeRole, "worker");
  assert.throws(() => {
    employeeCreateSchema.parse({
      employeeName: "Bob",
      employeeId: "bob_1",
      employeeRole: "invalid",
      employeePriority: 0,
      employeeAvailability: [],
    });
  });
});

test("webhookEventSchema validates event payload", async () => {
  const { webhookEventSchema } = await import("../types/api.ts");
  const result = webhookEventSchema.parse({
    event: "purchase.initial",
    data: { product_id: "pro_monthly" },
  });
  assert.equal(result.event, "purchase.initial");
});

// --- Type conversion functions ---

test("fromFirestoreSchedule converts snake_case to camelCase", async () => {
  const { fromFirestoreSchedule } = await import("../types/schedule.ts");
  const result = fromFirestoreSchedule("sched_1", {
    schedule_name: "Weekend Roster",
    employees: [
      {
        employee_name: "Alice",
        employee_id: "alice_1",
        employee_role: "manager",
        employee_priority: 1,
        employee_availability: ["morning"],
      },
    ],
    current_priorities: ["alice_1"],
    schedule_settings: {
      shift_hours: { morning: "06:00", noon: "14:00", night: "22:00" },
      timezone: "America/New_York",
    },
    sid: "creator_1",
  });
  assert.equal(result.scheduleName, "Weekend Roster");
  assert.equal(result.employees[0].employeeName, "Alice");
  assert.equal(result.scheduleSettings.shiftHours.morning, "06:00");
  assert.equal(result.scheduleSettings.timezone, "America/New_York");
});

test("fromFirestoreUser converts snake_case to camelCase", async () => {
  const { fromFirestoreUser } = await import("../types/user.ts");
  const result = fromFirestoreUser("user_1", {
    display_name: "John Doe",
    uid: "auth_123",
    role: "manager",
    is_premium: true,
    language: "en",
  });
  assert.equal(result.displayName, "John Doe");
  assert.equal(result.role, "manager");
  assert.equal(result.isPremium, true);
});

// --- Auth errors ---

test("getAuthErrorMessage returns known error message", async () => {
  const { getAuthErrorMessage } = await import("../lib/auth/errors.ts");
  assert.match(
    getAuthErrorMessage("auth/wrong-password"),
    /Incorrect password/,
  );
  assert.match(getAuthErrorMessage("auth/user-not-found"), /No account found/);
});

test("getAuthErrorMessage returns default for unknown code", async () => {
  const { getAuthErrorMessage } = await import("../lib/auth/errors.ts");
  assert.match(getAuthErrorMessage("auth/unknown-error"), /unexpected error/);
});
