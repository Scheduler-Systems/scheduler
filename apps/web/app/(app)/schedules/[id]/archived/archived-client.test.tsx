import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

const paramsMock = { id: "sid1" };
vi.mock("next/navigation", () => ({
  useParams: () => paramsMock,
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

const getSchedule = vi.fn();
const getBuiltSchedules = vi.fn();
vi.mock("@/lib/firestore", () => ({
  getSchedule: (id: string) => getSchedule(id),
  getBuiltSchedules: (id: string) => getBuiltSchedules(id),
}));

const ArchivedClient = (await import("./archived-client")).default;

describe("ArchivedClient", () => {
  beforeEach(() => {
    getSchedule.mockReset();
    getBuiltSchedules.mockReset();
  });

  it("renders the heading and empty-state message", async () => {
    getSchedule.mockResolvedValueOnce({
      id: "sid1",
      schedule_name: "Clinic",
      employees: [],
      schedule_settings: {},
      sid: "",
      next_schedule: [],
      current_priorities: [],
    });
    getBuiltSchedules.mockResolvedValueOnce([]);
    render(<ArchivedClient />);
    await waitFor(() =>
      expect(
        screen.getByRole("heading", { name: /Archived schedules/i }),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getByText(/No schedules have been built yet/i),
    ).toBeInTheDocument();
  });

  it("renders a row per built schedule with ranges and row counts", async () => {
    getSchedule.mockResolvedValueOnce({
      id: "sid1",
      schedule_name: "Clinic",
      employees: [],
      schedule_settings: {},
      sid: "",
      next_schedule: [],
      current_priorities: [],
    });
    getBuiltSchedules.mockResolvedValueOnce([
      {
        id: "b1",
        schedule: [{ stringList: ["Ada"] }, { stringList: ["Bob"] }],
        first_weekday: "2026-04-26",
        last_weekday: "2026-05-02",
        time_created: { toDate: () => new Date("2026-04-27T12:00:00Z") },
        current_priorities: ["Sun|morning"],
      },
    ]);
    render(<ArchivedClient />);
    await waitFor(() =>
      expect(screen.getByText(/2026-04-26/)).toBeInTheDocument(),
    );
    expect(screen.getByText(/2 rows/)).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();
  });

  it("renders an error banner when schedule is missing", async () => {
    getSchedule.mockResolvedValueOnce(null);
    getBuiltSchedules.mockResolvedValueOnce([]);
    render(<ArchivedClient />);
    await waitFor(() =>
      expect(screen.getByText(/Schedule not found/i))
        .toBeInTheDocument(),
    );
  });

  it("renders the failure state when getSchedule throws", async () => {
    getSchedule.mockRejectedValueOnce(new Error("boom"));
    getBuiltSchedules.mockResolvedValueOnce([]);
    render(<ArchivedClient />);
    await waitFor(() =>
      expect(screen.getByText(/Failed to load archived schedules/i))
        .toBeInTheDocument(),
    );
  });
});
