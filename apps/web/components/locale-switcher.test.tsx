import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// Restore the real i18n-context module (vitest.setup.ts mocks it globally).
vi.mock("@/lib/i18n-context", async () =>
  vi.importActual<typeof import("@/lib/i18n-context")>("@/lib/i18n-context")
);

import { I18nProvider } from "@/lib/i18n-context";
import { LocaleSwitcher } from "./locale-switcher";

function wrapped(ui: React.ReactNode) {
  return <I18nProvider>{ui}</I18nProvider>;
}

describe("<LocaleSwitcher>", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("shows full locale names by default", () => {
    render(wrapped(<LocaleSwitcher />));
    const select = screen.getByLabelText("Language") as HTMLSelectElement;
    const options = Array.from(select.options).map((o) => o.textContent);
    expect(options).toEqual(["English", "עברית", "Español"]);
  });

  it("shows compact codes when compact=true", () => {
    render(wrapped(<LocaleSwitcher compact />));
    const select = screen.getByLabelText("Language") as HTMLSelectElement;
    const options = Array.from(select.options).map((o) => o.textContent);
    expect(options).toEqual(["EN", "HE", "ES"]);
  });

  it("changes locale + flips <html dir> when a new option is picked", async () => {
    const user = userEvent.setup();
    render(wrapped(<LocaleSwitcher />));
    await user.selectOptions(screen.getByLabelText("Language"), "he");
    expect(document.documentElement.dir).toBe("rtl");
  });
});
