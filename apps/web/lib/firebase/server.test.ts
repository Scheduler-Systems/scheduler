import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

let mockApps: unknown[] = [];
const mockAdminApp = { name: "admin-app" };
let mockVerifySessionCookie = vi.fn().mockResolvedValue({ uid: "u1", email: "a@b.com" });
let mockCreateSessionCookie = vi.fn().mockResolvedValue("session-cookie-value");
let mockRevokeRefreshTokens = vi.fn().mockResolvedValue(undefined);

vi.mock("firebase-admin/app", () => ({
  initializeApp: vi.fn(() => {
    mockApps.push(mockAdminApp);
    return mockAdminApp;
  }),
  getApps: vi.fn(() => mockApps),
  getApp: vi.fn(() => mockAdminApp),
  cert: vi.fn((cred: unknown) => cred),
}));

vi.mock("firebase-admin/auth", () => ({
  getAuth: vi.fn(() => ({
    verifySessionCookie: mockVerifySessionCookie,
    createSessionCookie: mockCreateSessionCookie,
    revokeRefreshTokens: mockRevokeRefreshTokens,
  })),
}));

vi.mock("firebase-admin/firestore", () => ({
  getFirestore: vi.fn((app: unknown) => ({ _app: app })),
}));

describe("firebase server", () => {
  beforeEach(() => {
    mockApps = [];
    mockVerifySessionCookie = vi.fn().mockResolvedValue({ uid: "u1", email: "a@b.com" });
    mockCreateSessionCookie = vi.fn().mockResolvedValue("session-cookie-value");
    mockRevokeRefreshTokens = vi.fn().mockResolvedValue(undefined);
    vi.clearAllMocks();
    vi.resetModules();
    vi.unstubAllEnvs();
    vi.stubEnv("NEXT_PUBLIC_FIREBASE_PROJECT_ID", "test-project");
    vi.stubEnv("FIREBASE_CLIENT_EMAIL", "test@test.com");
    vi.stubEnv("FIREBASE_PRIVATE_KEY", "key-content");
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("initializes getAdminAuth and getAdminDb without throwing", async () => {
    const { getAdminAuth, getAdminDb } = await import("./server");
    const { initializeApp } = await import("firebase-admin/app");

    const auth = getAdminAuth();
    expect(auth).toBeDefined();

    const db = getAdminDb();
    expect(db).toBeDefined();
  });

  it("getAdminAuth returns auth instance", async () => {
    const { getAdminAuth } = await import("./server");
    const adminAuth = getAdminAuth();
    expect(adminAuth).toBeDefined();
    expect(adminAuth).toHaveProperty("verifySessionCookie");
  });

  it("getAdminDb returns firestore instance", async () => {
    const { getAdminDb } = await import("./server");
    const adminDb = getAdminDb();
    expect(adminDb).toBeDefined();
    expect(adminDb).toHaveProperty("_app");
  });

  describe("verifySessionCookie", () => {
    it("returns decoded token on success", async () => {
      mockVerifySessionCookie.mockResolvedValue({ uid: "u99", email: "u99@test.com" });
      const { verifySessionCookie } = await import("./server");

      const result = await verifySessionCookie("valid-cookie");
      expect(result).toEqual({ uid: "u99", email: "u99@test.com", valid: true });
    });

    it("returns invalid on error", async () => {
      mockVerifySessionCookie.mockRejectedValue(new Error("invalid"));
      const { verifySessionCookie } = await import("./server");

      const result = await verifySessionCookie("bad-cookie");
      expect(result).toEqual({ uid: null, email: null, valid: false });
    });
  });

  describe("createSessionCookie", () => {
    it("creates a session cookie with default expiry", async () => {
      const { createSessionCookie } = await import("./server");
      const cookie = await createSessionCookie("id-token");
      expect(cookie).toBe("session-cookie-value");
      expect(mockCreateSessionCookie).toHaveBeenCalledWith("id-token", {
        expiresIn: 604800000,
      });
    });

    it("creates a session cookie with custom expiry", async () => {
      const { createSessionCookie } = await import("./server");
      const cookie = await createSessionCookie("id-token", 3600000);
      expect(cookie).toBe("session-cookie-value");
      expect(mockCreateSessionCookie).toHaveBeenCalledWith("id-token", {
        expiresIn: 3600000,
      });
    });
  });

  describe("revokeSession", () => {
    it("calls revokeRefreshTokens", async () => {
      const { revokeSession } = await import("./server");
      await revokeSession("user-123");
      expect(mockRevokeRefreshTokens).toHaveBeenCalledWith("user-123");
    });
  });
});
