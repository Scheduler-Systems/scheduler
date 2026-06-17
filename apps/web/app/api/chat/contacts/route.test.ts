import { describe, it, expect, vi, beforeEach } from "vitest";
import { NextRequest } from "next/server";

const mockVerifySessionCookie = vi.fn();
const getChatContactsFor = vi.fn();

vi.mock("@/lib/firebase/server", () => ({
  verifySessionCookie: (...a: unknown[]) => mockVerifySessionCookie(...a),
  getAdminDb: () => ({ __fake: true }),
}));

vi.mock("@/lib/server/schedule-contacts", () => ({
  getChatContactsFor: (...a: unknown[]) => getChatContactsFor(...a),
}));

const { GET } = await import("./route");

function req(): NextRequest {
  return new NextRequest("http://localhost:3000/api/chat/contacts", {
    method: "GET",
    headers: new Headers({ cookie: "session=good" }),
  });
}
const ctx = { params: Promise.resolve({}) } as { params: Promise<Record<string, string>> };

describe("GET /api/chat/contacts — scoped chat directory (#51 item 8)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockVerifySessionCookie.mockResolvedValue({ uid: "alice", email: "a@a.com", valid: true });
  });

  it("scopes contacts by the VERIFIED caller uid (not a client-supplied param)", async () => {
    getChatContactsFor.mockResolvedValue([{ uid: "bob", display_name: "Bob" }]);
    const res = await GET(req(), ctx);
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.items).toEqual([{ uid: "bob", display_name: "Bob" }]);
    expect(getChatContactsFor).toHaveBeenCalledWith(expect.anything(), "alice");
  });

  it("401s an unauthenticated caller (no session) — never exposes contacts", async () => {
    mockVerifySessionCookie.mockResolvedValue({ uid: null, valid: false });
    const unauthed = new NextRequest("http://localhost:3000/api/chat/contacts", {
      method: "GET",
    });
    const res = await GET(unauthed, ctx);
    expect(res.status).toBe(401);
    expect(getChatContactsFor).not.toHaveBeenCalled();
  });

  it("500s without leaking internals if resolution throws", async () => {
    getChatContactsFor.mockRejectedValue(new Error("boom"));
    const res = await GET(req(), ctx);
    expect(res.status).toBe(500);
    const body = await res.json();
    expect(JSON.stringify(body)).not.toContain("boom");
  });
});
