import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// -----------------------------------------------------------------------------
// Mocks — register before importing fcm.ts
// -----------------------------------------------------------------------------

const messagingCalls = {
  getMessaging: vi.fn(),
  getToken: vi.fn(),
  onMessage: vi.fn(),
};

// Default behavior — each test can override via `messagingCalls.*.mockImplementation`
messagingCalls.getMessaging.mockReturnValue({ __mock_messaging: true });
messagingCalls.getToken.mockResolvedValue("mock-fcm-token");
messagingCalls.onMessage.mockImplementation(() => () => undefined);

vi.mock("firebase/messaging", () => ({
  getMessaging: (...args: unknown[]) => messagingCalls.getMessaging(...args),
  getToken: (...args: unknown[]) => messagingCalls.getToken(...args),
  onMessage: (...args: unknown[]) => messagingCalls.onMessage(...args),
}));

vi.mock("./firebase", () => ({
  getFirebaseApp: () => ({ __mock_app: true }),
  getFirebaseDb: () => ({ __mock_db: true }),
  getFirebaseAuth: () => ({ __mock_auth: true }),
}));

// firestore-write is consumed via registerFcmToken — mock updateDoc/arrayUnion
// at the firebase/firestore layer so we can assert the exact Firestore write.
const firestoreCalls = {
  updateDoc: vi.fn(),
  arrayUnion: vi.fn(),
};

vi.mock("firebase/firestore", () => ({
  doc: (_db: unknown, ...segments: string[]) => ({
    type: "doc",
    path: segments.join("/"),
  }),
  updateDoc: (ref: { path: string }, data: Record<string, unknown>) => {
    firestoreCalls.updateDoc(ref, data);
    return Promise.resolve();
  },
  arrayUnion: (...values: unknown[]) => {
    firestoreCalls.arrayUnion(...values);
    return { __arrayUnion: values };
  },
  // The following are referenced by firestore-write.ts at import time — stub.
  collection: () => ({}),
  addDoc: () => Promise.resolve({ id: "new" }),
  setDoc: () => Promise.resolve(),
  arrayRemove: () => ({}),
  serverTimestamp: () => ({ __serverTimestamp: true }),
  deleteDoc: () => Promise.resolve(),
  getDocs: () => Promise.resolve({ docs: [] }),
  writeBatch: () => ({
    set: () => undefined,
    delete: () => undefined,
    commit: () => Promise.resolve(),
  }),
  Timestamp: { fromDate: (d: Date) => ({ __timestamp: d.toISOString() }) },
}));

// -----------------------------------------------------------------------------
// Import AFTER mocks
// -----------------------------------------------------------------------------

const {
  requestFcmPermissionAndToken,
  registerFcmToken,
  subscribeToForegroundMessages,
} = await import("./fcm");

// -----------------------------------------------------------------------------
// Helpers
// -----------------------------------------------------------------------------

const mockAuth = {
  currentUser: { uid: "u-1" },
} as unknown as Parameters<typeof requestFcmPermissionAndToken>[0];

function setNotificationPermission(result: NotificationPermission) {
  // jsdom ships Notification but requestPermission varies — stub on globalThis.
  (globalThis as unknown as { Notification: unknown }).Notification = {
    requestPermission: vi.fn().mockResolvedValue(result),
    permission: result,
  };
}

beforeEach(() => {
  messagingCalls.getMessaging.mockReset();
  messagingCalls.getMessaging.mockReturnValue({ __mock_messaging: true });
  messagingCalls.getToken.mockReset();
  messagingCalls.getToken.mockResolvedValue("mock-fcm-token");
  messagingCalls.onMessage.mockReset();
  messagingCalls.onMessage.mockImplementation(() => () => undefined);
  firestoreCalls.updateDoc.mockReset();
  firestoreCalls.arrayUnion.mockReset();
  setNotificationPermission("granted");
});

afterEach(() => {
  delete (globalThis as unknown as { Notification?: unknown }).Notification;
});

// -----------------------------------------------------------------------------
// Tests
// -----------------------------------------------------------------------------

describe("requestFcmPermissionAndToken", () => {
  it("returns the FCM token when permission is granted", async () => {
    setNotificationPermission("granted");
    messagingCalls.getToken.mockResolvedValueOnce("abc123");
    const token = await requestFcmPermissionAndToken(mockAuth);
    expect(token).toBe("abc123");
    expect(messagingCalls.getToken).toHaveBeenCalledTimes(1);
    const [messaging, opts] = messagingCalls.getToken.mock.calls[0];
    expect(messaging).toEqual({ __mock_messaging: true });
    // vapidKey pulled from env (undefined in tests, but passed through)
    expect(opts).toHaveProperty("vapidKey");
  });

  it("returns null when the user denies notification permission", async () => {
    setNotificationPermission("denied");
    const token = await requestFcmPermissionAndToken(mockAuth);
    expect(token).toBeNull();
    // Must NOT call getToken after a permission denial
    expect(messagingCalls.getToken).not.toHaveBeenCalled();
  });

  it("returns null on unsupported browsers (getMessaging throws)", async () => {
    setNotificationPermission("granted");
    messagingCalls.getMessaging.mockImplementationOnce(() => {
      throw new Error("Messaging is not supported in this browser");
    });
    const token = await requestFcmPermissionAndToken(mockAuth);
    expect(token).toBeNull();
  });

  it("returns null when Notification API is unavailable", async () => {
    delete (globalThis as unknown as { Notification?: unknown }).Notification;
    const token = await requestFcmPermissionAndToken(mockAuth);
    expect(token).toBeNull();
  });

  it("returns null when the user is not signed in (no currentUser)", async () => {
    setNotificationPermission("granted");
    const unauthed = {
      currentUser: null,
    } as unknown as Parameters<typeof requestFcmPermissionAndToken>[0];
    const token = await requestFcmPermissionAndToken(unauthed);
    expect(token).toBeNull();
    expect(messagingCalls.getToken).not.toHaveBeenCalled();
  });

  it("returns null when getToken resolves empty string", async () => {
    setNotificationPermission("granted");
    messagingCalls.getToken.mockResolvedValueOnce("");
    const token = await requestFcmPermissionAndToken(mockAuth);
    expect(token).toBeNull();
  });

  it("never throws — a getToken rejection resolves to null", async () => {
    setNotificationPermission("granted");
    messagingCalls.getToken.mockRejectedValueOnce(new Error("transient"));
    await expect(requestFcmPermissionAndToken(mockAuth)).resolves.toBeNull();
  });
});

describe("registerFcmToken", () => {
  it("writes the token to users/{uid}.fcm_tokens via arrayUnion", async () => {
    await registerFcmToken("u-1", "tok-xyz");
    expect(firestoreCalls.updateDoc).toHaveBeenCalledTimes(1);
    const [ref, data] = firestoreCalls.updateDoc.mock.calls[0];
    expect(ref.path).toBe("users/u-1");
    const payload = data as Record<string, unknown>;
    expect(payload.fcm_tokens).toEqual({ __arrayUnion: ["tok-xyz"] });
    expect(firestoreCalls.arrayUnion).toHaveBeenCalledWith("tok-xyz");
  });
});

describe("subscribeToForegroundMessages", () => {
  it("calls onMessage and invokes the callback with normalized payload", async () => {
    let capturedHandler:
      | ((payload: unknown) => void)
      | null = null;
    messagingCalls.onMessage.mockImplementationOnce(
      (_m: unknown, handler: (payload: unknown) => void) => {
        capturedHandler = handler;
        return () => undefined;
      },
    );

    const cb = vi.fn();
    const unsub = await subscribeToForegroundMessages(cb);
    expect(messagingCalls.onMessage).toHaveBeenCalledTimes(1);
    expect(typeof unsub).toBe("function");

    // Simulate an incoming push
    capturedHandler!({
      notification: { title: "Hello", body: "World" },
      data: { url: "/dashboard" },
    });
    expect(cb).toHaveBeenCalledTimes(1);
    const arg = cb.mock.calls[0][0];
    expect(arg.title).toBe("Hello");
    expect(arg.body).toBe("World");
    expect(arg.data.url).toBe("/dashboard");
  });

  it("falls back to data.title/body when notification is absent", async () => {
    let capturedHandler:
      | ((payload: unknown) => void)
      | null = null;
    messagingCalls.onMessage.mockImplementationOnce(
      (_m: unknown, handler: (payload: unknown) => void) => {
        capturedHandler = handler;
        return () => undefined;
      },
    );

    const cb = vi.fn();
    await subscribeToForegroundMessages(cb);
    capturedHandler!({ data: { title: "D-title", body: "D-body" } });
    expect(cb).toHaveBeenCalledWith({
      title: "D-title",
      body: "D-body",
      data: { title: "D-title", body: "D-body" },
    });
  });

  it("returns a no-op unsubscribe when subscription fails", async () => {
    messagingCalls.getMessaging.mockImplementationOnce(() => {
      throw new Error("not supported");
    });
    const unsub = await subscribeToForegroundMessages(vi.fn());
    expect(typeof unsub).toBe("function");
    // Calling the no-op must not throw
    expect(() => unsub()).not.toThrow();
  });
});
