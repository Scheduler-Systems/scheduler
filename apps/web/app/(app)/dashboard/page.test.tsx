import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { I18nProvider } from "@/lib/i18n-context";

// The dashboard renders the shared AppBar, which calls useRouter() from
// next/navigation. Mock it so the component tree mounts without the real
// app-router provider (matches how settings/chat tests mock next/navigation).
vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
    prefetch: vi.fn(),
  }),
  usePathname: () => "/",
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("next/link", () => ({
  default: ({
    children,
    href,
    ...rest
  }: {
    children: React.ReactNode;
    href: string;
  } & React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

const useAuthMock = vi.fn();
vi.mock("@/lib/auth-context", () => ({
  useAuth: () => useAuthMock(),
}));

const getDashboardSummary = vi.fn();
vi.mock("@/lib/firestore", () => ({
  getDashboardSummary: (uid: string) => getDashboardSummary(uid),
}));

const DashboardPage = (await import("./page")).default;

function wrap(ui: React.ReactNode) {
  return <I18nProvider>{ui}</I18nProvider>;
}

describe("DashboardPage", () => {
  beforeEach(() => {
    getDashboardSummary.mockReset();
    useAuthMock.mockReturnValue({ user: { uid: "u1" }, loading: false });
  });

  it("renders the dashboard heading and stat cards", async () => {
    getDashboardSummary.mockResolvedValueOnce({
      scheduleCount: 0,
      employeeCount: 0,
      schedules: [],
    });
    render(wrap(<DashboardPage />));
    expect(
      screen.getByRole("heading", { name: /Dashboard/i }),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByText(/No schedules yet/i)).toBeInTheDocument(),
    );
  });

  it("renders counts and schedules table on happy path", async () => {
    getDashboardSummary.mockResolvedValueOnce({
      scheduleCount: 4,
      employeeCount: 7,
      schedules: [
        { id: "s1", name: "Clinic", employeeCount: 3 },
        { id: "s2", name: "", employeeCount: 2 },
      ],
    });
    render(wrap(<DashboardPage />));
    await waitFor(() =>
      expect(screen.getByText("Clinic")).toBeInTheDocument(),
    );
    // Stat cards use unique counts so queries are unambiguous
    expect(screen.getByText("4")).toBeInTheDocument();
    expect(screen.getByText("7")).toBeInTheDocument();
    expect(screen.getByText(/Unnamed schedule/i)).toBeInTheDocument();
    expect(getDashboardSummary).toHaveBeenCalledWith("u1");
  });

  it("gracefully handles a Firestore rejection by keeping loading off", async () => {
    getDashboardSummary.mockRejectedValueOnce(new Error("boom"));
    render(wrap(<DashboardPage />));
    // heading still visible; stat numbers fall back to em-dash during loading
    expect(
      screen.getByRole("heading", { name: /Dashboard/i }),
    ).toBeInTheDocument();
    // wait for finally to fire so skeleton goes away
    await waitFor(() => {
      // empty state since summary is null
      expect(screen.queryByText(/No schedules yet/i)).toBeNull();
    });
  });

  it("skips the fetch entirely when there is no signed-in user", () => {
    useAuthMock.mockReturnValue({ user: null, loading: false });
    render(wrap(<DashboardPage />));
    expect(getDashboardSummary).not.toHaveBeenCalled();
    expect(
      screen.getByRole("heading", { name: /Dashboard/i }),
    ).toBeInTheDocument();
  });

  it("exposes quick-action links with accessible names", async () => {
    getDashboardSummary.mockResolvedValueOnce({
      scheduleCount: 0,
      employeeCount: 0,
      schedules: [],
    });
    render(wrap(<DashboardPage />));
    await waitFor(() =>
      expect(screen.getByText(/No schedules yet/i)).toBeInTheDocument(),
    );
    const newSched = screen.getAllByRole("link", { name: /New schedule/i });
    expect(newSched.length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: /View all schedules/i }))
      .toBeInTheDocument();
  });
});
