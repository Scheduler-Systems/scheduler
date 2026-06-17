import assert from "node:assert/strict";
import test from "node:test";

class MockNextRequest {
  constructor(url, init = {}) {
    this.url = url || "https://scheduler.systems/api/test";
    this.method = init.method || "GET";
    this._headers = new Map(Object.entries(init.headers || {}));
    this._cookies = new Map();
    if (init.cookies) {
      for (const [k, v] of Object.entries(init.cookies))
        this._cookies.set(k, v);
    }
    this._body = init.body ?? null;
    this.nextUrl = {
      searchParams: new URL(this.url).searchParams,
      pathname: new URL(this.url).pathname,
    };
  }
  get cookies() {
    return {
      get: (name) => {
        const val = this._cookies.get(name);
        return val ? { value: val } : undefined;
      },
    };
  }
  get headers() {
    return {
      get: (name) => this._headers.get(name) ?? null,
    };
  }
  async json() {
    return this._body;
  }
  async text() {
    return typeof this._body === "string"
      ? this._body
      : JSON.stringify(this._body);
  }
}

function simulateMiddleware(
  wrapped,
  req,
  context = { params: Promise.resolve({}) },
) {
  return wrapped(req, context);
}

async function readBody(res) {
  const text = await res.text();
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

test("withAuth returns 401 for unauthenticated request", async () => {
  const { withAuth } = await import("../lib/api/auth.ts");
  let called = false;
  const handler = withAuth(async () => {
    called = true;
    const { NextResponse } = await import("next/server");
    return NextResponse.json({ ok: true });
  });

  const req = new MockNextRequest("https://scheduler.systems/api/test");
  const result = await simulateMiddleware(handler, req);

  assert.equal(result.status, 401);
  assert.equal(called, false);
  const body = await readBody(result);
  assert.equal(body.error, "Unauthorized");
});

test("withAuth returns 204 for OPTIONS preflight", async () => {
  const { withAuth } = await import("../lib/api/auth.ts");
  const handler = withAuth(async () => {
    const { NextResponse } = await import("next/server");
    return NextResponse.json({});
  });

  const req = new MockNextRequest("https://scheduler.systems/api/test", {
    method: "OPTIONS",
    headers: { origin: "http://localhost:3000" },
  });
  const result = await simulateMiddleware(handler, req);

  assert.equal(result.status, 204);
});

test("optionalAuth lets unauthenticated requests through", async () => {
  const { optionalAuth } = await import("../lib/api/auth.ts");
  const handler = optionalAuth(async (req, auth) => {
    const { NextResponse } = await import("next/server");
    return NextResponse.json({ auth: !!auth });
  });

  const req = new MockNextRequest("https://scheduler.systems/api/test");
  const result = await simulateMiddleware(handler, req);

  assert.equal(result.status, 200);
  const body = await readBody(result);
  assert.equal(body.auth, false);
});

test("withAuth rejects invalid session cookie", async () => {
  const { withAuth } = await import("../lib/api/auth.ts");
  const handler = withAuth(async () => {
    const { NextResponse } = await import("next/server");
    return NextResponse.json({});
  });

  const req = new MockNextRequest("https://scheduler.systems/api/test", {
    cookies: { session: "invalid_token" },
  });
  const result = await simulateMiddleware(handler, req);

  assert.equal(result.status, 401);
});

test("withAuth returns 429 when rate limit exceeded", async () => {
  const { withAuth } = await import("../lib/api/auth.ts");

  const handler = withAuth(
    async () => {
      const { NextResponse } = await import("next/server");
      return NextResponse.json({});
    },
    { requireAuth: false, rateLimitConfig: "auth" },
  );

  // Clear any residual rate limit state by churning through fresh keys
  for (let i = 0; i < 15; i++) {
    const req = new MockNextRequest(
      `https://scheduler.systems/api/test-ll/${i}`,
      { headers: { "x-forwarded-for": "192.168.1.99", "user-agent": "t" } },
    );
    await simulateMiddleware(handler, req);
  }

  // Now use same url to exhaust the 10 limit
  let last;
  for (let i = 0; i < 15; i++) {
    const req = new MockNextRequest("https://scheduler.systems/api/ratelimit", {
      headers: { "x-forwarded-for": "10.0.0.1", "user-agent": "test" },
    });
    last = await simulateMiddleware(handler, req);
  }

  assert.equal(last.status, 429);
  const body = await readBody(last);
  assert.equal(body.error, "Rate limit exceeded");
});

test("getAuthContext returns null without session cookie", async () => {
  const { getAuthContext } = await import("../lib/api/auth.ts");
  const req = new MockNextRequest("https://scheduler.systems/api/test");
  const result = await getAuthContext(req);
  assert.equal(result, null);
});

test("getAuthContext returns null for invalid session", async () => {
  const { getAuthContext } = await import("../lib/api/auth.ts");
  const req = new MockNextRequest("https://scheduler.systems/api/test", {
    cookies: { session: "bad_token" },
  });
  const result = await getAuthContext(req);
  assert.equal(result, null);
});

test("withAuth resolves params from async context", async () => {
  const { withAuth } = await import("../lib/api/auth.ts");
  let capturedParams;

  const handler = withAuth(
    async (req, auth, params) => {
      capturedParams = params;
      const { NextResponse } = await import("next/server");
      return NextResponse.json({});
    },
    { requireAuth: false, rateLimitConfig: "api" },
  );

  const req = new MockNextRequest("https://scheduler.systems/api/test");
  const context = { params: Promise.resolve({ id: "schedule_123" }) };
  await simulateMiddleware(handler, req, context);

  assert.equal(capturedParams.id, "schedule_123");
});

test("verifySessionCookie returns valid=false for invalid token", async () => {
  const { verifySessionCookie } = await import("../lib/firebase/server.ts");
  const result = await verifySessionCookie("bad_token");
  assert.equal(result.valid, false);
  assert.equal(result.uid, null);
});
