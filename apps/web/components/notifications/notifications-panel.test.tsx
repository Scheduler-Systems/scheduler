import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, act, fireEvent, waitFor } from "@testing-library/react";

// ----- feature flag: drive the gate per-test -----
const flagMock = vi.fn();
vi.mock("@/lib/feature-flags/use-feature-flag", () => ({
  useFeatureFlag: () => flagMock(),
  WEB_NOTIFICATIONS_CENTER_FLAG: "scheduler.web-notifications-center",
}));

// ----- auth -----
const useAuthMock = vi.fn();
vi.mock("@/lib/auth-context", () => ({ useAuth: () => useAuthMock() }));

// ----- router -----
const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock, replace: vi.fn() }),
}));

// ----- data layer: capture subscriber callbacks so tests can emit snapshots -----
type ReqCb = (rs: unknown[]) => void;
type OtherCb = (ns: unknown[]) => void;
const reqSubs: ReqCb[] = [];
const otherSubs: OtherCb[] = [];
const markScheduleRequestRead = vi.fn(async () => {});
const markNotificationRead = vi.fn(async () => {});
const markAllRead = vi.fn(async () => 0);

vi.mock("@/lib/notifications", () => ({
  subscribeToScheduleRequests: (_email: string | null, cb: ReqCb) => {
    reqSubs.push(cb);
    return vi.fn();
  },
  subscribeToNotifications: (_uid: string | null, cb: OtherCb) => {
    otherSubs.push(cb);
    return vi.fn();
  },
  markScheduleRequestRead,
  markNotificationRead,
  markAllRead,
}));

// ----- user-name resolver -----
vi.mock("@/lib/firestore", () => ({
  getUserProfile: vi.fn(async (uid: string) => ({
    uid,
    email: `${uid}@x.com`,
    display_name: uid === "boss" ? "Boss Lady" : "",
  })),
}));

const NotificationsPanel = (await import("./notifications-panel")).default;

function ts(date: Date) {
  return { toDate: () => date };
}

beforeEach(() => {
  reqSubs.length = 0;
  otherSubs.length = 0;
  flagMock.mockReset();
  useAuthMock.mockReset();
  pushMock.mockReset();
  markScheduleRequestRead.mockClear();
  markNotificationRead.mockClear();
  markAllRead.mockClear();
  useAuthMock.mockReturnValue({ user: { uid: "me", email: "me@acme.com" } });
});

describe("NotificationsPanel flag gating (customer-dark)", () => {
  it("renders nothing when the flag is OFF (paying customer)", () => {
    flagMock.mockReturnValue(false);
    const { container } = render(<NotificationsPanel />);
    expect(container.firstChild).toBeNull();
    // No subscription is started for a gated-off user.
    expect(reqSubs.length).toBe(0);
    expect(otherSubs.length).toBe(0);
  });

  it("renders the panel when the flag is ON (internal staff)", async () => {
    flagMock.mockReturnValue(true);
    render(<NotificationsPanel />);
    await act(async () => {
      reqSubs[0]?.([]);
      otherSubs[0]?.([]);
    });
    expect(
      screen.getByRole("heading", { name: /^Notifications$/ })
    ).toBeInTheDocument();
    expect(screen.getByTestId("notifications-tab-requests")).toBeInTheDocument();
    expect(screen.getByTestId("notifications-tab-other")).toBeInTheDocument();
  });
});

describe("NotificationsPanel — schedule requests tab", () => {
  beforeEach(() => flagMock.mockReturnValue(true));

  it("shows an unread add-request row with the actor name and unread styling", async () => {
    render(<NotificationsPanel />);
    await act(async () => {
      reqSubs[0]?.([
        {
          id: "r1",
          is_add_request: true,
          is_join_request: false,
          is_read: false,
          from_user: { id: "boss" },
          schedule_ref: { id: "s1" },
          request_status: "ADD_RQUEST_PENDING",
          created_time: ts(new Date(Date.now() - 60_000)),
        },
      ]);
      otherSubs[0]?.([]);
    });
    expect(screen.getByText("Schedule Add Request")).toBeInTheDocument();
    await waitFor(() =>
      expect(
        screen.getByText(/Boss Lady requests you to join their schedule/)
      ).toBeInTheDocument()
    );
    const tile = screen.getByTestId("notification-request-r1");
    expect(tile).toHaveAttribute("data-read", "false");
  });

  it("tapping a pending request marks it read and navigates to the schedule requests", async () => {
    render(<NotificationsPanel onClose={vi.fn()} />);
    await act(async () => {
      reqSubs[0]?.([
        {
          id: "r1",
          is_add_request: true,
          is_join_request: false,
          is_read: false,
          from_user: { id: "boss" },
          schedule_ref: { id: "s1" },
          request_status: "ADD_RQUEST_PENDING",
          created_time: ts(new Date()),
        },
      ]);
      otherSubs[0]?.([]);
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("notification-request-r1"));
    });
    expect(markScheduleRequestRead).toHaveBeenCalledWith("r1");
    expect(pushMock).toHaveBeenCalledWith("/schedules/s1/requests");
  });

  it("'Mark All as Read' calls markAllRead with the unread ids for the active tab", async () => {
    render(<NotificationsPanel />);
    await act(async () => {
      reqSubs[0]?.([
        { id: "r1", is_add_request: true, is_read: false, from_user: { id: "boss" }, created_time: ts(new Date()) },
        { id: "r2", is_add_request: true, is_read: true, from_user: { id: "boss" }, created_time: ts(new Date()) },
      ]);
      otherSubs[0]?.([]);
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("notifications-mark-all"));
    });
    expect(markAllRead).toHaveBeenCalledWith(["r1"], "schedule_requests");
  });

  it("renders the empty state when there are no requests", async () => {
    render(<NotificationsPanel />);
    await act(async () => {
      reqSubs[0]?.([]);
      otherSubs[0]?.([]);
    });
    expect(
      screen.getByText(/No notifications at this time/)
    ).toBeInTheDocument();
  });
});

describe("NotificationsPanel — other (chat) tab", () => {
  beforeEach(() => flagMock.mockReturnValue(true));

  it("switching to Other shows message notifications and tap navigates to the chat", async () => {
    render(<NotificationsPanel onClose={vi.fn()} />);
    await act(async () => {
      reqSubs[0]?.([]);
      otherSubs[0]?.([
        {
          id: "n1",
          is_read: false,
          from_user: { id: "boss" },
          content: "are you free Tuesday?",
          chat_ref_id: { id: "c9" },
          time_created: ts(new Date()),
          type: "chat",
        },
      ]);
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("notifications-tab-other"));
    });
    await waitFor(() =>
      expect(screen.getByText("are you free Tuesday?")).toBeInTheDocument()
    );
    expect(screen.getByText(/sent you a message/)).toBeInTheDocument();
    await act(async () => {
      fireEvent.click(screen.getByTestId("notification-other-n1"));
    });
    expect(markNotificationRead).toHaveBeenCalledWith("n1");
    expect(pushMock).toHaveBeenCalledWith("/chat/c9");
  });
});
