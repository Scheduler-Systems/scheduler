import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

// Mock next/navigation.usePathname so we can test active-link styling
const pathnameMock = vi.fn<() => string>(() => "/dashboard");
vi.mock("next/navigation", () => ({
  usePathname: () => pathnameMock(),
}));

// Mock useAuth so the nav has a fake user
vi.mock("@/lib/auth-context", () => ({
  useAuth: () => ({
    user: { displayName: "Ada Lovelace", email: "ada@example.com" },
  }),
}));

// Restore the real i18n-context module (vitest.setup.ts mocks it globally).
vi.mock("@/lib/i18n-context", async () =>
  vi.importActual<typeof import("@/lib/i18n-context")>("@/lib/i18n-context")
);

import { I18nProvider } from "@/lib/i18n-context";
const { Nav } = await import("./nav");

function wrap(ui: React.ReactNode) {
  return <I18nProvider>{ui}</I18nProvider>;
}

describe("<Nav>", () => {
  it("renders brand + three primary nav links + avatar", () => {
    pathnameMock.mockReturnValue("/dashboard");
    render(wrap(<Nav />));
    expect(screen.getByText("Scheduler")).toBeTruthy();
    expect(screen.getByText("Dashboard")).toBeTruthy();
    expect(screen.getByText("Schedules")).toBeTruthy();
    expect(screen.getByText("Employees")).toBeTruthy();
    // Avatar uses the user's display name initial
    expect(screen.getByText("A")).toBeTruthy();
  });

  it("shows the user's email next to the avatar", () => {
    pathnameMock.mockReturnValue("/dashboard");
    render(wrap(<Nav />));
    expect(screen.getByText("ada@example.com")).toBeTruthy();
  });

  it("applies the active style to the link that matches the current pathname", () => {
    pathnameMock.mockReturnValue("/schedules/abc");
    render(wrap(<Nav />));
    const schedulesLink = screen.getByRole("link", { name: "Schedules" });
    // Flutter-purple AppBar: active link is highlighted with a translucent
    // white fill + bold weight on the purple bar.
    expect(schedulesLink.className).toMatch(/bg-white\/15/);
    expect(schedulesLink.className).toMatch(/font-medium/);
  });

  it("avatar link routes to /settings and highlights there", () => {
    pathnameMock.mockReturnValue("/settings");
    render(wrap(<Nav />));
    const settingsLink = screen.getByLabelText("Settings");
    expect(settingsLink.getAttribute("href")).toBe("/settings");
    // On the purple AppBar the active avatar inverts to a white chip with
    // purple text.
    expect(settingsLink.className).toMatch(/bg-white/);
    expect(settingsLink.className).toMatch(/text-purple-700/);
  });
});
