import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// Restore the real i18n-context module (vitest.setup.ts mocks it globally).
// `vi.mock` is hoisted and must be at module scope — `vi.unmock` at runtime
// cannot override an already-hoisted global mock.
vi.mock("@/lib/i18n-context", async () =>
  vi.importActual<typeof import("./i18n-context")>("./i18n-context")
);

import { I18nProvider, useI18n } from "./i18n-context";

// Small harness that exposes every hook value as DOM text + exposes setLocale
// as a button so user-event can exercise it.
function Harness() {
  const { locale, setLocale, t } = useI18n();
  return (
    <div>
      <span data-testid="locale">{locale}</span>
      <span data-testid="greet">{t("landing.ctaSecondary")}</span>
      <button onClick={() => setLocale("he")}>switch-he</button>
      <button onClick={() => setLocale("es")}>switch-es</button>
      {/* @ts-expect-error — exercising the guard that rejects bogus locales */}
      <button onClick={() => setLocale("xx")}>switch-xx</button>
    </div>
  );
}

describe("I18nProvider", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.removeAttribute("dir");
    document.documentElement.removeAttribute("lang");
  });

  it("starts in English when no stored locale and no browser preference", () => {
    render(
      <I18nProvider>
        <Harness />
      </I18nProvider>
    );
    expect(screen.getByTestId("locale").textContent).toBe("en");
    expect(screen.getByTestId("greet").textContent).toBe("Sign in");
  });

  it("switchs to Hebrew, flips <html dir/lang>, and persists to localStorage", async () => {
    const user = userEvent.setup();
    render(
      <I18nProvider>
        <Harness />
      </I18nProvider>
    );
    await user.click(screen.getByText("switch-he"));
    expect(screen.getByTestId("locale").textContent).toBe("he");
    expect(screen.getByTestId("greet").textContent).toBe("התחברות");
    expect(document.documentElement.dir).toBe("rtl");
    expect(document.documentElement.lang).toBe("he");
    expect(localStorage.getItem("scheduler.locale")).toBe("he");
  });

  it("switching to Spanish sets dir=ltr", async () => {
    const user = userEvent.setup();
    render(
      <I18nProvider>
        <Harness />
      </I18nProvider>
    );
    await user.click(screen.getByText("switch-es"));
    expect(screen.getByTestId("locale").textContent).toBe("es");
    expect(document.documentElement.dir).toBe("ltr");
  });

  it("ignores unknown locales via setLocale", async () => {
    const user = userEvent.setup();
    render(
      <I18nProvider>
        <Harness />
      </I18nProvider>
    );
    await user.click(screen.getByText("switch-xx"));
    expect(screen.getByTestId("locale").textContent).toBe("en"); // unchanged
  });

  it("hydrates from localStorage on mount", async () => {
    localStorage.setItem("scheduler.locale", "es");
    await act(async () => {
      render(
        <I18nProvider>
          <Harness />
        </I18nProvider>
      );
    });
    expect(screen.getByTestId("locale").textContent).toBe("es");
  });

  it("useI18n throws helpful error outside a provider", () => {
    // Suppress React error boundary noise
    const spy = vi.spyOn(console, "error").mockImplementation(() => undefined);
    expect(() => render(<Harness />)).toThrow(/I18nProvider/);
    spy.mockRestore();
  });
});
