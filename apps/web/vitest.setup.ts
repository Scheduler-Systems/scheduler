import "@testing-library/jest-dom/vitest";
import { vi } from "vitest";
import type { ReactNode } from "react";

// Node 25+ intercepts localStorage with a CLI flag, which can break jsdom
// tests. Ensure a real Storage instance is always available.
if (typeof localStorage === "undefined" || typeof localStorage.getItem !== "function") {
  const store = new Map<string, string>();
  const storage = {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => { store.set(key, value); },
    removeItem: (key: string) => { store.delete(key); },
    clear: () => { store.clear(); },
    get length() { return store.size; },
    key: (index: number) => [...store.keys()][index] ?? null,
  };
  Object.defineProperty(globalThis, "localStorage", {
    value: storage,
    writable: true,
  });
}

// Global mock for i18n context — tests shouldn't need to wrap every render
// in an I18nProvider. Pages call `useI18n()` via the real provider in prod,
// but here we stub it so `t(key)` resolves against the real EN dictionary,
// letting existing text-based assertions (`/No schedules yet/i`) keep working.
// Tests that specifically exercise Provider behavior (lib/i18n-context.test.tsx,
// components/locale-switcher.test.tsx, components/nav.test.tsx) opt out via
// `vi.unmock("@/lib/i18n-context")` at the top of those files.
vi.mock("@/lib/i18n-context", async () => {
  const actual = await vi.importActual<
    typeof import("./lib/i18n-context")
  >("@/lib/i18n-context");
  const { dictionary } = await vi.importActual<
    typeof import("./lib/i18n-dict")
  >("./lib/i18n-dict");
  // Stable `t` function — returning a new function per render would
  // invalidate `useEffect([..., t])` dependency lists and trigger re-fetches.
  const t = (key: string, params?: Record<string, string | number>) => {
    const raw = dictionary.en[key] ?? key;
    if (!params) return raw;
    return raw.replace(/\{(\w+)\}/g, (_, k) =>
      params[k] !== undefined ? String(params[k]) : `{${k}}`
    );
  };
  // Stable context value — see comment above.
  const contextValue = {
    locale: "en" as const,
    setLocale: () => undefined,
    t,
  };
  return {
    ...actual,
    useI18n: () => contextValue,
    I18nProvider: ({ children }: { children: ReactNode }) => children,
  };
});
