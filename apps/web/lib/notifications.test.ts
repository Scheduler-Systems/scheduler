import { describe, it, expect, vi, beforeEach } from "vitest";

// Mock firebase/firestore — capture query shape + snapshot callbacks and record
// updateDoc calls, mirroring lib/chat.test.ts's harness so the two data layers
// are tested the same way.

type Listener = {
  path: string;
  constraints: unknown[];
  onNext: (snap: { docs: MockDoc[] }) => void;
  onError: (err: unknown) => void;
  unsubscribe: () => void;
};

interface MockDoc {
  id: string;
  data: () => unknown;
}

const listeners: Listener[] = [];
const unsubscribeCalls: string[] = [];
const updateCalls: { path: string; data: unknown }[] = [];
// Paths that should reject in updateDoc (to test markAllRead's swallow).
const failingUpdatePaths = new Set<string>();

vi.mock("firebase/firestore", () => ({
  collection: (_parent: unknown, ...segments: string[]) => ({
    type: "collection",
    path: segments.join("/"),
  }),
  doc: (_parent: unknown, ...segments: string[]) => ({
    type: "doc",
    path: segments.join("/"),
    id: segments[segments.length - 1],
  }),
  query: (ref: { path: string }, ...constraints: unknown[]) => ({
    path: ref.path,
    _constraints: constraints,
  }),
  where: (field: string, op: string, value: unknown) => ({
    _type: "where",
    field,
    op,
    value,
  }),
  orderBy: (field: string, dir?: string) => ({
    _type: "orderBy",
    field,
    dir: dir ?? "asc",
  }),
  onSnapshot: (
    q: { path: string; _constraints: unknown[] },
    onNext: (snap: { docs: MockDoc[] }) => void,
    onError: (err: unknown) => void
  ) => {
    const unsub = vi.fn(() => {
      unsubscribeCalls.push(q.path);
    });
    listeners.push({
      path: q.path,
      constraints: q._constraints,
      onNext,
      onError,
      unsubscribe: unsub,
    });
    return unsub;
  },
  updateDoc: async (ref: { path: string }, data: unknown) => {
    if (failingUpdatePaths.has(ref.path)) throw new Error("denied");
    updateCalls.push({ path: ref.path, data });
  },
}));

vi.mock("./firebase", () => ({
  getFirebaseDb: () => ({ __mock_db: true }),
}));

const {
  subscribeToScheduleRequests,
  subscribeToNotifications,
  markScheduleRequestRead,
  markNotificationRead,
  markAllRead,
} = await import("./notifications");

beforeEach(() => {
  listeners.length = 0;
  unsubscribeCalls.length = 0;
  updateCalls.length = 0;
  failingUpdatePaths.clear();
});

function lastListener(): Listener {
  const l = listeners[listeners.length - 1];
  if (!l) throw new Error("no listener registered");
  return l;
}

describe("subscribeToScheduleRequests", () => {
  it("queries schedule_requests by to_user_identification (email) ordered created_time desc", () => {
    const cb = vi.fn();
    subscribeToScheduleRequests("boss@acme.com", cb);
    const l = lastListener();
    expect(l.path).toBe("schedule_requests");
    const where = l.constraints.find(
      (c) => (c as { _type?: string })._type === "where"
    ) as { field: string; op: string; value: unknown };
    expect(where.field).toBe("to_user_identification");
    expect(where.op).toBe("==");
    expect(where.value).toBe("boss@acme.com");
    const order = l.constraints.find(
      (c) => (c as { _type?: string })._type === "orderBy"
    ) as { field: string; dir: string };
    expect(order.field).toBe("created_time");
    expect(order.dir).toBe("desc");
  });

  it("delivers requests with id spread onto each doc", () => {
    const cb = vi.fn();
    subscribeToScheduleRequests("boss@acme.com", cb);
    lastListener().onNext({
      docs: [
        {
          id: "r1",
          data: () => ({ is_add_request: true, is_read: false }),
        },
      ],
    });
    expect(cb).toHaveBeenCalledTimes(1);
    expect(cb.mock.calls[0][0]).toEqual([
      { id: "r1", is_add_request: true, is_read: false },
    ]);
  });

  it("empty email → empty list and a no-op unsubscribe (no listener wired)", () => {
    const cb = vi.fn();
    const unsub = subscribeToScheduleRequests("", cb);
    expect(listeners.length).toBe(0);
    expect(cb).toHaveBeenCalledWith([]);
    expect(() => unsub()).not.toThrow();
  });

  it("fail-safe: onError delivers an empty list (renders empty state)", () => {
    const cb = vi.fn();
    subscribeToScheduleRequests("boss@acme.com", cb);
    lastListener().onError(new Error("permission-denied"));
    expect(cb).toHaveBeenLastCalledWith([]);
  });
});

describe("subscribeToNotifications", () => {
  it("queries notifications by to_user (users/{uid} ref) ordered time_created desc", () => {
    const cb = vi.fn();
    subscribeToNotifications("u9", cb);
    const l = lastListener();
    expect(l.path).toBe("notifications");
    const where = l.constraints.find(
      (c) => (c as { _type?: string })._type === "where"
    ) as { field: string; op: string; value: { path: string } };
    expect(where.field).toBe("to_user");
    expect(where.op).toBe("==");
    // to_user filters on the users/{uid} DocumentReference.
    expect(where.value.path).toBe("users/u9");
    const order = l.constraints.find(
      (c) => (c as { _type?: string })._type === "orderBy"
    ) as { field: string; dir: string };
    expect(order.field).toBe("time_created");
    expect(order.dir).toBe("desc");
  });

  it("empty uid → empty list, no listener", () => {
    const cb = vi.fn();
    subscribeToNotifications(null, cb);
    expect(listeners.length).toBe(0);
    expect(cb).toHaveBeenCalledWith([]);
  });

  it("fail-safe: onError → empty list", () => {
    const cb = vi.fn();
    subscribeToNotifications("u9", cb);
    lastListener().onError(new Error("nope"));
    expect(cb).toHaveBeenLastCalledWith([]);
  });
});

describe("mark-as-read writes", () => {
  it("markScheduleRequestRead flips is_read on the right doc", async () => {
    await markScheduleRequestRead("r1");
    expect(updateCalls).toEqual([
      { path: "schedule_requests/r1", data: { is_read: true } },
    ]);
  });

  it("markNotificationRead flips is_read on the right doc", async () => {
    await markNotificationRead("n1");
    expect(updateCalls).toEqual([
      { path: "notifications/n1", data: { is_read: true } },
    ]);
  });

  it("markAllRead updates every id in the named collection and returns the count", async () => {
    const n = await markAllRead(["a", "b", "c"], "notifications");
    expect(n).toBe(3);
    expect(updateCalls.map((c) => c.path)).toEqual([
      "notifications/a",
      "notifications/b",
      "notifications/c",
    ]);
    expect(updateCalls.every((c) => (c.data as { is_read: boolean }).is_read)).toBe(
      true
    );
  });

  it("markAllRead swallows a per-doc failure and keeps going (Flutter has no guard)", async () => {
    failingUpdatePaths.add("schedule_requests/b");
    const n = await markAllRead(["a", "b", "c"], "schedule_requests");
    expect(n).toBe(2); // a + c succeeded, b swallowed
    expect(updateCalls.map((c) => c.path)).toEqual([
      "schedule_requests/a",
      "schedule_requests/c",
    ]);
  });
});
