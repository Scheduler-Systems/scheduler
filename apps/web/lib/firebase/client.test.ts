import { describe, it, expect, vi, beforeEach } from "vitest";

const mockApps: unknown[] = [];
const mockApp = { name: "test-app" };

vi.mock("firebase/app", () => ({
  initializeApp: vi.fn((_config: unknown) => {
    mockApps.push(mockApp);
    return mockApp;
  }),
  getApps: vi.fn(() => mockApps),
  getApp: vi.fn(() => mockApp),
}));

vi.mock("firebase/auth", () => ({
  getAuth: vi.fn((app: unknown) => ({ _app: app })),
}));

vi.mock("firebase/firestore", () => ({
  getFirestore: vi.fn((app: unknown) => ({ _app: app })),
}));

vi.mock("firebase/functions", () => ({
  getFunctions: vi.fn((app: unknown) => ({ _app: app })),
}));

vi.mock("firebase/storage", () => ({
  getStorage: vi.fn((app: unknown) => ({ _app: app })),
}));

vi.mock("firebase/analytics", () => ({
  getAnalytics: vi.fn((app: unknown) => ({ _app: app })),
  isSupported: vi.fn(() => Promise.resolve(true)),
}));

vi.mock("firebase/remote-config", () => ({
  getRemoteConfig: vi.fn((app: unknown) => ({ _app: app })),
}));

describe("firebase client", () => {
  beforeEach(() => {
    mockApps.length = 0;
    vi.clearAllMocks();
    vi.resetModules();
  });

  it("creates a new Firebase app when no apps exist", async () => {
    const { initializeApp } = await import("firebase/app");
    const mod = await import("./client");
    expect(initializeApp).toHaveBeenCalledTimes(1);
    expect(mod.app).toBeDefined();
  });

  it("reuses existing Firebase app when apps exist", async () => {
    mockApps.push(mockApp);
    const { initializeApp } = await import("firebase/app");
    const mod = await import("./client");
    expect(initializeApp).not.toHaveBeenCalled();
    expect(mod.app).toBeDefined();
  });

  it("exports auth from getAuth", async () => {
    const { getAuth } = await import("firebase/auth");
    const mod = await import("./client");
    expect(getAuth).toHaveBeenCalled();
    expect(mod.auth).toBeDefined();
  });

  it("exports db from getFirestore", async () => {
    const { getFirestore } = await import("firebase/firestore");
    const mod = await import("./client");
    expect(getFirestore).toHaveBeenCalled();
    expect(mod.db).toBeDefined();
  });

  it("exports functions from getFunctions", async () => {
    const { getFunctions } = await import("firebase/functions");
    const mod = await import("./client");
    expect(getFunctions).toHaveBeenCalled();
    expect(mod.functions).toBeDefined();
  });

  it("exports storage from getStorage", async () => {
    const { getStorage } = await import("firebase/storage");
    const mod = await import("./client");
    expect(getStorage).toHaveBeenCalled();
    expect(mod.storage).toBeDefined();
  });

  it("exports remoteConfig from getRemoteConfig", async () => {
    const { getRemoteConfig } = await import("firebase/remote-config");
    const mod = await import("./client");
    expect(getRemoteConfig).toHaveBeenCalled();
    expect(mod.remoteConfig).toBeDefined();
  });

  describe("getAnalyticsInstance", () => {
    it("returns analytics instance when supported in browser", async () => {
      const { isSupported, getAnalytics } = await import("firebase/analytics");
      vi.mocked(isSupported).mockResolvedValue(true);

      const mod = await import("./client");
      const instance = await mod.getAnalyticsInstance();

      expect(instance).toBeDefined();
      expect(getAnalytics).toHaveBeenCalled();
    });

    it("returns null when analytics is not supported", async () => {
      const { isSupported } = await import("firebase/analytics");
      vi.mocked(isSupported).mockResolvedValue(false);

      vi.resetModules();
      const mod = await import("./client");
      const instance = await mod.getAnalyticsInstance();

      expect(instance).toBeNull();
    });
  });
});
