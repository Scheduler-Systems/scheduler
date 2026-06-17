import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";

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

// Capture the callback so tests can drive onSnapshot emissions manually.
type ThreadsCb = (threads: unknown[]) => void;
const subscribers: ThreadsCb[] = [];
const unsubscribeSpy = vi.fn();

vi.mock("@/lib/chat", () => ({
  subscribeToChatThreads: (_uid: string, cb: ThreadsCb) => {
    subscribers.push(cb);
    return unsubscribeSpy;
  },
}));

const ChatListPage = (await import("./page")).default;

// Timestamp-mock helper: jsdom doesn't ship firebase.Timestamp; any object
// with `.toDate()` satisfies our `timestampToDate` helper at runtime.
function ts(date: Date) {
  return { toDate: () => date };
}

beforeEach(() => {
  subscribers.length = 0;
  unsubscribeSpy.mockReset();
  useAuthMock.mockReset();
  useAuthMock.mockReturnValue({ user: { uid: "me" } });
});

describe("ChatListPage", () => {
  it("renders the list heading and 'New chat' link", async () => {
    render(<ChatListPage />);
    // Flush the initial subscribe callback (empty)
    await act(async () => {
      subscribers[0]?.([]);
    });
    expect(
      screen.getByRole("heading", { name: /^Chats$/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /New chat/i }),
    ).toBeInTheDocument();
  });

  it("shows the empty state when the subscriber emits an empty list", async () => {
    render(<ChatListPage />);
    await act(async () => {
      subscribers[0]?.([]);
    });
    await waitFor(() =>
      expect(screen.getByText(/No conversations yet/i)).toBeInTheDocument(),
    );
  });

  it("renders a row per thread with display name + preview truncation", async () => {
    render(<ChatListPage />);
    await act(async () => {
      subscribers[0]?.([
        {
          id: "t1",
          name: "Ada",
          users: ["me", "u2"],
          is_group: false,
          last_message: {
            text: "short hello",
            sender: "u2",
            timestamp: ts(new Date(Date.now() - 5 * 60 * 1000)),
          },
          created_at: ts(new Date()),
        },
        {
          id: "t2",
          users: ["me", "u3"],
          is_group: false,
          last_message: {
            text: "a".repeat(120),
            sender: "me",
            timestamp: ts(new Date(Date.now() - 2 * 60 * 60 * 1000)),
          },
          created_at: ts(new Date()),
        },
      ]);
    });
    expect(screen.getByTestId("chat-row-t1")).toBeInTheDocument();
    expect(screen.getByTestId("chat-row-t2")).toBeInTheDocument();
    // Thread with name shows the name
    expect(screen.getByText("Ada")).toBeInTheDocument();
    // Thread without name falls back to the other participant's uid
    expect(screen.getByText("u3")).toBeInTheDocument();
    // 120-char preview is truncated with a trailing ellipsis (60 max)
    const rows = screen.getAllByText(/a{50,}/);
    expect(rows[0].textContent?.length).toBeLessThanOrEqual(60);
  });

  it("exposes thread rows as navigable links to /chat/[id]", async () => {
    render(<ChatListPage />);
    await act(async () => {
      subscribers[0]?.([
        {
          id: "t-target",
          name: "Pair",
          users: ["me", "u2"],
          is_group: false,
          last_message: {
            text: "hi",
            sender: "u2",
            timestamp: ts(new Date()),
          },
          created_at: ts(new Date()),
        },
      ]);
    });
    const row = screen.getByTestId("chat-row-t-target") as HTMLAnchorElement;
    expect(row.getAttribute("href")).toBe("/chat/t-target");
  });

  it("shows an unread badge for threads whose last message isn't from me", async () => {
    render(<ChatListPage />);
    await act(async () => {
      subscribers[0]?.([
        {
          id: "unread",
          name: "Bob",
          users: ["me", "bob"],
          is_group: false,
          last_message: {
            text: "yo",
            sender: "bob", // not me → unread
            timestamp: ts(new Date()),
          },
          created_at: ts(new Date()),
        },
        {
          id: "read",
          name: "Carol",
          users: ["me", "carol"],
          is_group: false,
          last_message: {
            text: "ok",
            sender: "me", // mine → read
            timestamp: ts(new Date()),
          },
          created_at: ts(new Date()),
        },
      ]);
    });
    expect(screen.getByTestId("chat-unread-unread")).toBeInTheDocument();
    expect(screen.queryByTestId("chat-unread-read")).toBeNull();
    // Aggregate badge shows the unread count
    expect(screen.getByTestId("chat-unread-total")).toHaveTextContent("1");
  });

  it("invokes the subscriber's unsubscribe on unmount", async () => {
    const { unmount } = render(<ChatListPage />);
    await act(async () => {
      subscribers[0]?.([]);
    });
    unmount();
    expect(unsubscribeSpy).toHaveBeenCalledTimes(1);
  });

  it("shows no unread indicator when thread lacks last_message", async () => {
    render(<ChatListPage />);
    await act(async () => {
      subscribers[0]?.([
        {
          id: "t-nomsg",
          name: "Silent",
          users: ["me", "u2"],
          is_group: false,
          created_at: ts(new Date()),
        },
      ]);
    });
    expect(screen.queryByTestId("chat-unread-t-nomsg")).toBeNull();
    expect(screen.queryByTestId("chat-unread-total")).toBeNull();
  });

  it("hides the relative timestamp when last_message.timestamp is null", async () => {
    render(<ChatListPage />);
    await act(async () => {
      subscribers[0]?.([
        {
          id: "t-nots",
          name: "NoTs",
          users: ["me", "u2"],
          is_group: false,
          last_message: {
            text: "no timestamp",
            sender: "u2",
            timestamp: null,
          },
          created_at: ts(new Date()),
        },
      ]);
    });
    expect(screen.queryByText("now")).not.toBeInTheDocument();
  });

  it("shows fallback avatar initial for nameless threads with no other participant", async () => {
    render(<ChatListPage />);
    await act(async () => {
      subscribers[0]?.([
        {
          id: "t-fallback",
          users: [],
          is_group: false,
          last_message: {
            text: "orphan",
            sender: "someone",
            timestamp: ts(new Date()),
          },
          created_at: ts(new Date()),
        },
      ]);
    });
    const row = screen.getByTestId("chat-row-t-fallback");
    const avatar = row.querySelector('[class*="rounded-full"]');
    expect(avatar?.textContent).toBe("?");
  });
});
