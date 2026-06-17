import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";

/**
 * Intercom integration unit tests.
 *
 * These exercise the public surface of `lib/intercom.ts` against a mocked
 * `window.Intercom` global. The Intercom snippet injection itself is
 * exercised via `loadIntercomSnippet` — we don't load the real widget
 * (that would hit network) but we do assert the snippet shape.
 */

// We reset modules between tests so the module-level env read in
// `getAppId()` always reflects the current test's `process.env`.
async function freshImport() {
  return await import("./intercom");
}

describe("lib/intercom", () => {
  const originalAppId = process.env.NEXT_PUBLIC_INTERCOM_APP_ID;

  beforeEach(() => {
    vi.resetModules();
    // Default: app id is set. Individual tests override as needed.
    process.env.NEXT_PUBLIC_INTERCOM_APP_ID = "test_app_id";
    // Clear any previous mock so each test starts clean.
    delete (window as unknown as { Intercom?: unknown }).Intercom;
    delete (window as unknown as { intercomSettings?: unknown }).intercomSettings;
  });

  afterEach(() => {
    if (originalAppId === undefined) {
      delete process.env.NEXT_PUBLIC_INTERCOM_APP_ID;
    } else {
      process.env.NEXT_PUBLIC_INTERCOM_APP_ID = originalAppId;
    }
    vi.restoreAllMocks();
  });

  describe("bootIntercom", () => {
    it("boots the widget with app_id, user_id, user_hash, name, and email", async () => {
      const { bootIntercom } = await freshImport();
      const intercom = vi.fn();
      (window as unknown as { Intercom: unknown }).Intercom = intercom;

      bootIntercom(
        { user_id: "uid-123", name: "Ada Lovelace", email: "ada@example.com" },
        "signed.jwt.token",
      );

      expect(intercom).toHaveBeenCalledWith("boot", {
        app_id: "test_app_id",
        user_id: "uid-123",
        user_hash: "signed.jwt.token",
        name: "Ada Lovelace",
        email: "ada@example.com",
      });
    });

    it("no-ops with a warning when NEXT_PUBLIC_INTERCOM_APP_ID is unset", async () => {
      delete process.env.NEXT_PUBLIC_INTERCOM_APP_ID;
      const { bootIntercom } = await freshImport();
      const intercom = vi.fn();
      (window as unknown as { Intercom: unknown }).Intercom = intercom;
      const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);

      bootIntercom({ user_id: "uid-123" }, "jwt");

      expect(intercom).not.toHaveBeenCalled();
      expect(warn).toHaveBeenCalledTimes(1);
      expect(warn.mock.calls[0]?.[0]).toMatch(/NEXT_PUBLIC_INTERCOM_APP_ID/);
    });

    it("no-ops silently when NEXT_PUBLIC_INTERCOM_APP_ID is unset and console is not available", async () => {
      delete process.env.NEXT_PUBLIC_INTERCOM_APP_ID;
      const origConsole = globalThis.console;
      // Remove console to simulate a sandboxed environment.
      // @ts-expect-error — intentional removal of console for edge-case test
      delete globalThis.console;
      try {
        const { bootIntercom } = await freshImport();
        // Should not throw even though console is absent — the guard at
        // `if (typeof console !== "undefined")` covers the false branch.
        expect(() => {
          bootIntercom({ user_id: "uid-123" }, "jwt");
        }).not.toThrow();
      } finally {
        globalThis.console = origConsole;
      }
    });

    it("loads the Intercom snippet if window.Intercom is missing", async () => {
      const { bootIntercom } = await freshImport();
      // No Intercom global yet — the module should install a stub and
      // inject the <script> tag before anyone calls `Intercom("boot", ...)`.
      bootIntercom({ user_id: "uid-abc" }, "jwt-abc");

      // Stub installed
      expect(typeof (window as unknown as { Intercom?: unknown }).Intercom).toBe(
        "function",
      );
      // Queue reflects the boot call
      const stub = (window as unknown as {
        Intercom: { q?: unknown[][] };
      }).Intercom;
      expect(stub.q).toBeDefined();
      const bootCall = stub.q?.find(
        (args) => Array.isArray(args) && args[0] === "boot",
      );
      expect(bootCall?.[1]).toMatchObject({
        app_id: "test_app_id",
        user_id: "uid-abc",
        user_hash: "jwt-abc",
      });
    });
  });

  describe("shutdownIntercom", () => {
    it("calls Intercom('shutdown') when app id is set", async () => {
      const { shutdownIntercom } = await freshImport();
      const intercom = vi.fn();
      (window as unknown as { Intercom: unknown }).Intercom = intercom;

      shutdownIntercom();

      expect(intercom).toHaveBeenCalledWith("shutdown");
    });

    it("no-ops when NEXT_PUBLIC_INTERCOM_APP_ID is unset", async () => {
      delete process.env.NEXT_PUBLIC_INTERCOM_APP_ID;
      const { shutdownIntercom } = await freshImport();
      const intercom = vi.fn();
      (window as unknown as { Intercom: unknown }).Intercom = intercom;

      shutdownIntercom();

      expect(intercom).not.toHaveBeenCalled();
    });
  });

  describe("loadIntercomSnippet (stub + ready-state branches)", () => {
    it("exposes a `c()` helper on the stub that forwards to the pending queue", async () => {
      const { loadIntercomSnippet } = await freshImport();
      loadIntercomSnippet("t_app");
      const stub = (window as unknown as {
        Intercom: { c?: (args: unknown[]) => void; q?: unknown[][] };
      }).Intercom;
      expect(typeof stub.c).toBe("function");
      // Invoking `c(args)` should push the tuple into the queue alongside
      // any prior stub() calls — this is the path the real Intercom SDK
      // uses when it takes over the stub and flushes its own backlog.
      stub.c?.(["trackEvent", { name: "login" }]);
      expect(stub.q?.some((a) => Array.isArray(a) && a[0] === "trackEvent"))
        .toBe(true);
    });

    it("injects the widget <script> immediately when document.readyState is 'complete'", async () => {
      const { loadIntercomSnippet } = await freshImport();
      // The loader inserts the Intercom script before an existing <script>
      // — seed one so `getElementsByTagName("script")[0]` resolves.
      const anchor = document.createElement("script");
      anchor.id = "intercom-test-anchor";
      document.head.appendChild(anchor);
      try {
        // jsdom reports readyState='complete' by default — assert the script
        // was injected with the expected src.
        loadIntercomSnippet("t_app");
        const scripts = Array.from(document.getElementsByTagName("script"));
        const injected = scripts.find((s) =>
          (s.src || "").includes("widget.intercom.io/widget/t_app"),
        );
        expect(injected).toBeDefined();
        expect(injected?.async).toBe(true);
      } finally {
        anchor.remove();
      }
    });

    it("defers script injection via addEventListener when document.readyState is not 'complete'", async () => {
      const addEventListenerSpy = vi.spyOn(window, "addEventListener");
      const origReadyState = Object.getOwnPropertyDescriptor(
        document,
        "readyState",
      );
      Object.defineProperty(document, "readyState", {
        value: "loading",
        configurable: true,
        writable: true,
      });
      try {
        const { loadIntercomSnippet } = await freshImport();
        loadIntercomSnippet("t_loading");

        // Should have registered a "load" listener, not injected the script.
        expect(addEventListenerSpy).toHaveBeenCalledWith(
          "load",
          expect.any(Function),
          false,
        );
        const scripts = Array.from(
          document.getElementsByTagName("script"),
        );
        const injected = scripts.find((s) =>
          (s.src || "").includes("widget.intercom.io/widget/t_loading"),
        );
        expect(injected).toBeUndefined();
      } finally {
        if (origReadyState) {
          Object.defineProperty(
            document,
            "readyState",
            origReadyState,
          );
        } else {
          Object.defineProperty(document, "readyState", {
            value: "complete",
            configurable: true,
          });
        }
        addEventListenerSpy.mockRestore();
      }
    });

    it("falls back to attachEvent when addEventListener is not available", async () => {
      const attachEventSpy = vi.fn();
      const origAddEventListener = window.addEventListener;
      const origReadyState = Object.getOwnPropertyDescriptor(
        document,
        "readyState",
      );

      // Remove addEventListener and install attachEvent to simulate IE.
      delete (window as { addEventListener?: unknown }).addEventListener;
      (window as { attachEvent?: unknown }).attachEvent = attachEventSpy;
      Object.defineProperty(document, "readyState", {
        value: "loading",
        configurable: true,
        writable: true,
      });
      try {
        const { loadIntercomSnippet } = await freshImport();
        loadIntercomSnippet("t_ie");

        expect(attachEventSpy).toHaveBeenCalledWith(
          "onload",
          expect.any(Function),
        );
        const scripts = Array.from(
          document.getElementsByTagName("script"),
        );
        const injected = scripts.find((s) =>
          (s.src || "").includes("widget.intercom.io/widget/t_ie"),
        );
        expect(injected).toBeUndefined();
      } finally {
        if (origAddEventListener) {
          window.addEventListener = origAddEventListener;
        }
        if (origReadyState) {
          Object.defineProperty(
            document,
            "readyState",
            origReadyState,
          );
        } else {
          Object.defineProperty(document, "readyState", {
            value: "complete",
            configurable: true,
          });
        }
        delete (window as { attachEvent?: unknown }).attachEvent;
      }
    });

    it("no-ops when both addEventListener and attachEvent are missing", async () => {
      const origAddEventListener = window.addEventListener;
      const origAttachEvent = (window as { attachEvent?: unknown }).attachEvent;
      const origReadyState = Object.getOwnPropertyDescriptor(
        document,
        "readyState",
      );

      // Simulate an ancient JS environment with neither API available.
      delete (window as { addEventListener?: unknown }).addEventListener;
      delete (window as { attachEvent?: unknown }).attachEvent;
      Object.defineProperty(document, "readyState", {
        value: "loading",
        configurable: true,
        writable: true,
      });
      try {
        const { loadIntercomSnippet } = await freshImport();
        loadIntercomSnippet("t_legacy");

        // No load listener registered and no script injected.
        const scripts = Array.from(
          document.getElementsByTagName("script"),
        );
        const injected = scripts.find((s) =>
          (s.src || "").includes("widget.intercom.io/widget/t_legacy"),
        );
        expect(injected).toBeUndefined();
      } finally {
        if (origAddEventListener) {
          window.addEventListener = origAddEventListener;
        }
        if (origReadyState) {
          Object.defineProperty(
            document,
            "readyState",
            origReadyState,
          );
        } else {
          Object.defineProperty(document, "readyState", {
            value: "complete",
            configurable: true,
          });
        }
        if (typeof origAttachEvent === "function") {
          (window as { attachEvent?: unknown }).attachEvent = origAttachEvent;
        } else {
          delete (window as { attachEvent?: unknown }).attachEvent;
        }
      }
    });

    it("bails out when window.Intercom is already a function (snippet already loaded)", async () => {
      const { loadIntercomSnippet } = await freshImport();
      // Pre-install a real-looking Intercom function. The loader should
      // leave it untouched (no stub/queue clobber, no new script tag).
      const existing = vi.fn();
      (existing as unknown as { q?: unknown }).q = "sentinel";
      (window as unknown as { Intercom: unknown }).Intercom = existing;
      const beforeScriptCount = document.getElementsByTagName("script").length;
      loadIntercomSnippet("t_app_2");
      expect((window as unknown as { Intercom: unknown }).Intercom).toBe(
        existing,
      );
      // No new <script> injected for t_app_2.
      const afterScripts = Array.from(document.getElementsByTagName("script"));
      const injectedForT2 = afterScripts.find((s) =>
        (s.src || "").includes("widget.intercom.io/widget/t_app_2"),
      );
      expect(injectedForT2).toBeUndefined();
      expect(afterScripts.length).toBe(beforeScriptCount);
    });
  });

  describe("updateIntercom", () => {
    it("forwards attrs to Intercom('update', attrs)", async () => {
      const { updateIntercom } = await freshImport();
      const intercom = vi.fn();
      (window as unknown as { Intercom: unknown }).Intercom = intercom;

      updateIntercom({ plan: "premium", seats: 10 });

      expect(intercom).toHaveBeenCalledWith("update", {
        plan: "premium",
        seats: 10,
      });
    });

    it("no-ops when NEXT_PUBLIC_INTERCOM_APP_ID is unset", async () => {
      delete process.env.NEXT_PUBLIC_INTERCOM_APP_ID;
      const { updateIntercom } = await freshImport();
      const intercom = vi.fn();
      (window as unknown as { Intercom: unknown }).Intercom = intercom;

      updateIntercom({ plan: "premium" });

      expect(intercom).not.toHaveBeenCalled();
    });

    it("no-ops when window.Intercom is not installed", async () => {
      const { updateIntercom } = await freshImport();
      // window.Intercom was deleted in beforeEach — no global set.
      // callIntercom hits `if (typeof fn !== "function") return;` and no-ops.
      expect(() => updateIntercom({ plan: "premium" })).not.toThrow();
    });
  });

  describe("callIntercom (via shutdownIntercom)", () => {
    it("shutdownIntercom no-ops when window.Intercom is not installed", async () => {
      const { shutdownIntercom } = await freshImport();
      // window.Intercom was deleted in beforeEach — no global set.
      // callIntercom hits `if (typeof fn !== "function") return;` and no-ops.
      expect(() => shutdownIntercom()).not.toThrow();
    });
  });
});
