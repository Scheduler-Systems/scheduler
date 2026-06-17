import { describe, it, expect, vi, beforeEach } from "vitest";
import { NextRequest } from "next/server";

const mockVerifySessionCookie = vi.fn();
const sharesScheduleWith = vi.fn();

vi.mock("@/lib/firebase/server", () => ({
  verifySessionCookie: (...a: unknown[]) => mockVerifySessionCookie(...a),
  getAdminDb: () => ({
    collection: () => ({
      doc: (id: string) => ({
        async get() {
          return {
            exists: true,
            id,
            data: () => ({ uid: id, display_name: id, role: "worker" }),
          };
        },
        async update() {
          return undefined;
        },
        async delete() {
          return undefined;
        },
      }),
    }),
  }),
}));

vi.mock("@/lib/server/schedule-contacts", () => ({
  sharesScheduleWith: (...a: unknown[]) => sharesScheduleWith(...a),
}));

const { GET, PUT, DELETE } = await import("./route");

function req(method = "GET", body?: unknown): NextRequest {
  return new NextRequest("http://localhost:3000/api/employees/bob", {
    method,
    headers: new Headers({ cookie: "session=good" }),
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
}
const ctx = (id: string) => ({ params: Promise.resolve({ id }) }) as {
  params: Promise<Record<string, string>>;
};

describe("/api/employees/[id] — by-id IDOR hardening (#51 item 8)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockVerifySessionCookie.mockResolvedValue({ uid: "alice", email: "a@a.com", valid: true });
  });

  it("GET 403 when the target is NOT a co-member (was: read any profile by uid)", async () => {
    sharesScheduleWith.mockResolvedValue(false);
    const res = await GET(req(), ctx("dave"));
    expect(res.status).toBe(403);
  });

  it("GET 200 when the target is a co-member or self", async () => {
    sharesScheduleWith.mockResolvedValue(true);
    const res = await GET(req(), ctx("bob"));
    expect(res.status).toBe(200);
    expect(sharesScheduleWith).toHaveBeenCalledWith(expect.anything(), "alice", "bob");
  });

  it("PUT 403 when editing another user's profile (was: rename/re-role anyone)", async () => {
    const res = await PUT(req("PUT", { employeeName: "Hacked" }), ctx("bob"));
    expect(res.status).toBe(403);
  });

  it("PUT 200 only for the caller's own profile (self)", async () => {
    const res = await PUT(req("PUT", { employeeName: "Alice New" }), ctx("alice"));
    expect(res.status).toBe(200);
  });

  it("DELETE is denied outright (mirrors allow delete: if false)", async () => {
    const res = await DELETE(req("DELETE"), ctx("bob"));
    expect(res.status).toBe(403);
  });
});
