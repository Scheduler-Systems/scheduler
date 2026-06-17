import { describe, it, expect, vi, beforeEach } from "vitest";
import { NextRequest } from "next/server";

// withAuth runs for real; we mock only its dependencies so it yields an authed
// context for `alice`. getAdminDb returns a fake whose getAll resolves member
// docs. The membership helpers are stubbed so we drive the authorization paths.
const mockVerifySessionCookie = vi.fn();
const isCallerMemberOfSchedule = vi.fn();
const getScheduleMemberUids = vi.fn();

vi.mock("@/lib/firebase/server", () => ({
  verifySessionCookie: (...a: unknown[]) => mockVerifySessionCookie(...a),
  getAdminDb: () => ({
    collection: () => ({ doc: (id: string) => ({ path: `users/${id}`, id }) }),
    getAll: async (...refs: Array<{ id: string }>) =>
      refs.map((r) => ({
        exists: true,
        id: r.id,
        data: () => ({ uid: r.id, display_name: r.id, role: "worker" }),
      })),
  }),
}));

vi.mock("@/lib/server/schedule-contacts", () => ({
  isCallerMemberOfSchedule: (...a: unknown[]) => isCallerMemberOfSchedule(...a),
  getScheduleMemberUids: (...a: unknown[]) => getScheduleMemberUids(...a),
}));

const { GET } = await import("./route");

function req(qs = ""): NextRequest {
  return new NextRequest(`http://localhost:3000/api/employees${qs}`, {
    method: "GET",
    headers: new Headers({ cookie: "session=good" }),
  });
}
const ctx = { params: Promise.resolve({}) } as { params: Promise<Record<string, string>> };

describe("GET /api/employees — hardened against directory enumeration (#51 item 8)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockVerifySessionCookie.mockResolvedValue({ uid: "alice", email: "a@a.com", valid: true });
    isCallerMemberOfSchedule.mockResolvedValue(true);
    getScheduleMemberUids.mockResolvedValue(["alice", "bob"]);
  });

  it("400s when no scheduleId is supplied (previously returned the WHOLE users collection)", async () => {
    const res = await GET(req(""), ctx);
    expect(res.status).toBe(400);
    expect(getScheduleMemberUids).not.toHaveBeenCalled();
  });

  it("403s when the caller is not a member of the requested schedule (IDOR closed)", async () => {
    isCallerMemberOfSchedule.mockResolvedValue(false);
    const res = await GET(req("?scheduleId=S9"), ctx);
    expect(res.status).toBe(403);
    // must NOT fetch a roster the caller has no right to.
    expect(getScheduleMemberUids).not.toHaveBeenCalled();
  });

  it("returns only the requested schedule's roster for a verified member", async () => {
    const res = await GET(req("?scheduleId=S1"), ctx);
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.items.map((u: { uid: string }) => u.uid).sort()).toEqual(["alice", "bob"]);
    // membership is checked against the VERIFIED uid, not a client-supplied one.
    expect(isCallerMemberOfSchedule).toHaveBeenCalledWith(expect.anything(), "alice", "S1");
  });
});
