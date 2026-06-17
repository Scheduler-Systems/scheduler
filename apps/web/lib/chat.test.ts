import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// Mock firebase/firestore — capture the query shape + snapshot callbacks
// so we can assert on how onSnapshot is wired and drive the subscribe
// callbacks manually.

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
const docFixtures = new Map<string, { exists: boolean; data: unknown }>();

function setDocFixture(path: string, data: unknown) {
  docFixtures.set(path, { exists: true, data });
}
function missingDocFixture(path: string) {
  docFixtures.set(path, { exists: false, data: null });
}

vi.mock("firebase/firestore", () => ({
  collection: (parent: unknown, ...segments: string[]) => {
    if (parent && typeof parent === "object" && "path" in (parent as Record<string, unknown>)) {
      const parentPath = (parent as { path: string }).path;
      return { type: "collection", path: [parentPath, ...segments].join("/") };
    }
    return { type: "collection", path: segments.join("/") };
  },
  doc: (parent: unknown, ...segments: string[]) => {
    if (segments.length === 0 && parent && typeof parent === "object") {
      const cPath = (parent as { path: string }).path;
      return { type: "doc", path: `${cPath}/auto-id`, id: "auto-id" };
    }
    return {
      type: "doc",
      path: segments.join("/"),
      id: segments[segments.length - 1],
    };
  },
  getDoc: async (ref: { path: string; id: string }) => {
    const entry = docFixtures.get(ref.path) ?? { exists: false, data: null };
    return {
      exists: () => entry.exists,
      data: () => entry.data,
      id: ref.id,
    };
  },
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
    onError: (err: unknown) => void,
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
}));

vi.mock("./firebase", () => ({
  getFirebaseDb: () => ({ __mock_db: true }),
}));

const {
  subscribeToChatThreads,
  subscribeToChatMessages,
  getChatThread,
  fetchChatContacts,
  findExistingThread,
} = await import("./chat");

beforeEach(() => {
  listeners.length = 0;
  unsubscribeCalls.length = 0;
  docFixtures.clear();
});

function lastListener(): Listener {
  const l = listeners[listeners.length - 1];
  if (!l) throw new Error("no listener registered");
  return l;
}

describe("subscribeToChatThreads", () => {
  it("wires onSnapshot at the `chats` collection with array-contains + orderBy", () => {
    const cb = vi.fn();
    const unsub = subscribeToChatThreads("u1", cb);
    expect(typeof unsub).toBe("function");
    const l = lastListener();
    expect(l.path).toBe("chats");
    const where = l.constraints.find(
      (c) => (c as { _type?: string })._type === "where",
    ) as { field: string; op: string; value: unknown };
    expect(where.field).toBe("users");
    expect(where.op).toBe("array-contains");
    expect(where.value).toBe("u1");
    const order = l.constraints.find(
      (c) => (c as { _type?: string })._type === "orderBy",
    ) as { field: string; dir: string };
    expect(order.field).toBe("last_message.timestamp");
    expect(order.dir).toBe("desc");
  });

  it("delivers threads with id spread onto each doc", () => {
    const cb = vi.fn();
    subscribeToChatThreads("u1", cb);
    const l = lastListener();
    l.onNext({
      docs: [
        {
          id: "t1",
          data: () => ({
            users: ["u1", "u2"],
            is_group: false,
            created_at: { __ts: "now" },
          }),
        },
        {
          id: "t2",
          data: () => ({
            users: ["u1", "u2", "u3"],
            is_group: true,
            name: "Team",
            created_at: { __ts: "now" },
          }),
        },
      ],
    });
    expect(cb).toHaveBeenCalledTimes(1);
    const threads = cb.mock.calls[0][0];
    expect(threads).toHaveLength(2);
    expect(threads[0].id).toBe("t1");
    expect(threads[0].is_group).toBe(false);
    expect(threads[1].id).toBe("t2");
    expect(threads[1].name).toBe("Team");
  });

  it("delivers an empty list on Firestore error (swallows, doesn't throw)", () => {
    const cb = vi.fn();
    subscribeToChatThreads("u1", cb);
    const l = lastListener();
    l.onError(new Error("permission-denied"));
    expect(cb).toHaveBeenCalledTimes(1);
    expect(cb.mock.calls[0][0]).toEqual([]);
  });

  it("returns an Unsubscribe function that is callable", () => {
    const cb = vi.fn();
    const unsub = subscribeToChatThreads("u1", cb);
    unsub();
    expect(unsubscribeCalls).toEqual(["chats"]);
  });
});

describe("subscribeToChatMessages", () => {
  it("subscribes at chats/{threadId}/messages and orders by timestamp asc", () => {
    const cb = vi.fn();
    subscribeToChatMessages("t1", cb);
    const l = lastListener();
    expect(l.path).toBe("chats/t1/messages");
    const order = l.constraints.find(
      (c) => (c as { _type?: string })._type === "orderBy",
    ) as { field: string; dir: string };
    expect(order.field).toBe("timestamp");
    expect(order.dir).toBe("asc");
  });

  it("delivers messages with id spread", () => {
    const cb = vi.fn();
    subscribeToChatMessages("t1", cb);
    const l = lastListener();
    l.onNext({
      docs: [
        {
          id: "m1",
          data: () => ({
            text: "hi",
            sender_uid: "u1",
            timestamp: { __ts: "1" },
          }),
        },
        {
          id: "m2",
          data: () => ({
            text: "pic",
            sender_uid: "u2",
            timestamp: { __ts: "2" },
            image_url: "https://x/y.png",
            seen_by: ["u1"],
          }),
        },
      ],
    });
    const messages = cb.mock.calls[0][0];
    expect(messages).toHaveLength(2);
    expect(messages[0].id).toBe("m1");
    expect(messages[0].sender_uid).toBe("u1");
    expect(messages[1].image_url).toBe("https://x/y.png");
    expect(messages[1].seen_by).toEqual(["u1"]);
  });

  it("swallows errors by emitting []", () => {
    const cb = vi.fn();
    subscribeToChatMessages("t1", cb);
    const l = lastListener();
    l.onError(new Error("oops"));
    expect(cb.mock.calls[0][0]).toEqual([]);
  });

  it("returned Unsubscribe invokes the SDK's unsubscribe", () => {
    const cb = vi.fn();
    const unsub = subscribeToChatMessages("t1", cb);
    unsub();
    expect(unsubscribeCalls).toEqual(["chats/t1/messages"]);
  });
});

describe("getChatThread", () => {
  it("returns the thread with id when the doc exists", async () => {
    setDocFixture("chats/t1", {
      users: ["u1", "u2"],
      is_group: false,
      created_at: { __ts: "now" },
    });
    const thread = await getChatThread("t1");
    expect(thread?.id).toBe("t1");
    expect(thread?.is_group).toBe(false);
    expect(thread?.users).toEqual(["u1", "u2"]);
  });

  it("returns null when the thread doesn't exist", async () => {
    missingDocFixture("chats/missing");
    const thread = await getChatThread("missing");
    expect(thread).toBeNull();
  });
});

describe("fetchChatContacts", () => {
  // SECURITY (#51 item 8): the picker no longer streams the global `users`
  // collection from the client. It reads the server-scoped contacts endpoint,
  // which returns only the caller's schedule co-members. These tests pin that
  // it calls the scoped endpoint (NOT a `users` collection query) and degrades
  // safely.
  const realFetch = globalThis.fetch;
  afterEach(() => {
    globalThis.fetch = realFetch;
  });

  it("GETs the scoped /api/chat/contacts endpoint with credentials", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ items: [] }),
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    await fetchChatContacts();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/chat/contacts");
    expect((init as RequestInit).credentials).toBe("same-origin");
    // It must NOT touch the global users directory directly.
    expect(String(url)).not.toContain("users");
  });

  it("returns the endpoint's items verbatim on 200", async () => {
    const items = [
      { uid: "ua", display_name: "Alice", email: "a@x.com" },
      { uid: "ub", display_name: "Bob" },
    ];
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ items }),
    }) as unknown as typeof fetch;
    const result = await fetchChatContacts();
    expect(result).toEqual(items);
  });

  it("returns [] on a non-ok response (e.g. 401/500)", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      json: async () => ({}),
    }) as unknown as typeof fetch;
    expect(await fetchChatContacts()).toEqual([]);
  });

  it("returns [] when the network request throws (swallows)", async () => {
    globalThis.fetch = vi
      .fn()
      .mockRejectedValue(new Error("network")) as unknown as typeof fetch;
    expect(await fetchChatContacts()).toEqual([]);
  });

  it("returns [] when the body has no items array", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ unexpected: true }),
    }) as unknown as typeof fetch;
    expect(await fetchChatContacts()).toEqual([]);
  });
});

describe("findExistingThread", () => {
  const mkThread = (id: string, users: string[]) =>
    ({ id, users, is_group: users.length > 2 } as unknown as ChatThreadLike);

  type ChatThreadLike = { id: string; users: string[]; is_group: boolean };

  it("matches a thread with the same participant set regardless of order", () => {
    const threads = [
      mkThread("t1", ["u2", "u1"]),
      mkThread("t2", ["u1", "u3"]),
    ];
    const found = findExistingThread(threads as never, ["u1", "u2"]);
    expect(found?.id).toBe("t1");
  });

  it("matches group threads order-independently", () => {
    const threads = [mkThread("g1", ["u3", "u1", "u2"])];
    const found = findExistingThread(threads as never, ["u1", "u2", "u3"]);
    expect(found?.id).toBe("g1");
  });

  it("treats duplicate uids as a set (no double-thread for the same pair)", () => {
    const threads = [mkThread("t1", ["u1", "u2"])];
    const found = findExistingThread(threads as never, ["u1", "u1", "u2"]);
    expect(found?.id).toBe("t1");
  });

  it("returns null when no thread has the exact participant set", () => {
    const threads = [
      mkThread("t1", ["u1", "u2"]),
      mkThread("t2", ["u1", "u2", "u3"]),
    ];
    // Superset / subset must NOT match.
    expect(findExistingThread(threads as never, ["u1", "u2", "u4"])).toBeNull();
    expect(findExistingThread(threads as never, ["u1"])).toBeNull();
  });

  it("returns null for an empty thread list", () => {
    expect(findExistingThread([], ["u1", "u2"])).toBeNull();
  });
});
