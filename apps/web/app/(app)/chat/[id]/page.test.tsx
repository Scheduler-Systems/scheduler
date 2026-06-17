import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

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

const paramsMock = { id: "t1" };
vi.mock("next/navigation", () => ({
  useParams: () => paramsMock,
}));

const useAuthMock = vi.fn();
vi.mock("@/lib/auth-context", () => ({
  useAuth: () => useAuthMock(),
}));

// Firebase module stub so the dynamic-imported storage SDK (uploadChatImage)
// doesn't try to instantiate a real app in jsdom.
vi.mock("@/lib/firebase", () => ({
  getFirebaseApp: () => ({ __mock_app: true }),
}));

// Mock firebase/storage so dynamic import in uploadChatImage resolves in jsdom.
const uploadBytesMock = vi.fn().mockResolvedValue(undefined);
vi.mock("firebase/storage", () => ({
  getStorage: vi.fn(() => ({ __mock_storage: true })),
  ref: vi.fn(() => "mock-ref"),
  uploadBytes: uploadBytesMock,
  getDownloadURL: vi.fn(() => "https://example.com/img.jpg"),
}));

// Capture chat subscribers so tests can drive emissions.
type MessagesCb = (messages: unknown[]) => void;
const messageSubs: MessagesCb[] = [];
const msgUnsubscribeSpy = vi.fn();
const getChatThreadMock = vi.fn();

vi.mock("@/lib/chat", () => ({
  subscribeToChatMessages: (_id: string, cb: MessagesCb) => {
    messageSubs.push(cb);
    return msgUnsubscribeSpy;
  },
  getChatThread: (id: string) => getChatThreadMock(id),
}));

const sendChatMessageMock = vi.fn();
const markMessageSeenMock = vi.fn();
vi.mock("@/lib/firestore-write", () => ({
  sendChatMessage: (...args: unknown[]) => sendChatMessageMock(...args),
  markMessageSeen: (...args: unknown[]) => markMessageSeenMock(...args),
}));

const ChatThreadClient = (
  await import("./chat-thread-client")
).default;

function ts(date: Date) {
  return { toDate: () => date };
}

beforeEach(() => {
  messageSubs.length = 0;
  msgUnsubscribeSpy.mockReset();
  getChatThreadMock.mockReset();
  sendChatMessageMock.mockReset();
  markMessageSeenMock.mockReset();
  useAuthMock.mockReset();
  useAuthMock.mockReturnValue({
    user: { uid: "me", displayName: "Me", email: "me@x" },
  });
  getChatThreadMock.mockResolvedValue({
    id: "t1",
    name: "Project Alpha",
    users: ["me", "u2"],
    is_group: false,
    created_at: ts(new Date()),
  });
  sendChatMessageMock.mockResolvedValue("new-msg-id");
  markMessageSeenMock.mockResolvedValue(undefined);
});

describe("ChatThreadClient", () => {
  it("renders the header with the thread name and a back link", async () => {
    render(<ChatThreadClient />);
    await act(async () => {
      messageSubs[0]?.([]);
    });
    await waitFor(() =>
      expect(screen.getByText("Project Alpha")).toBeInTheDocument(),
    );
    const back = screen.getByRole("link", { name: /Back/i }) as HTMLAnchorElement;
    expect(back.getAttribute("href")).toBe("/chat");
  });

  it("renders messages from the subscription, grouped by sender side", async () => {
    render(<ChatThreadClient />);
    await act(async () => {
      messageSubs[0]?.([
        {
          id: "m1",
          text: "hi",
          sender_uid: "u2",
          timestamp: ts(new Date()),
        },
        {
          id: "m2",
          text: "hello",
          sender_uid: "me",
          timestamp: ts(new Date()),
        },
      ]);
    });
    expect(screen.getByTestId("chat-message-m1")).toBeInTheDocument();
    expect(screen.getByTestId("chat-message-m2")).toBeInTheDocument();
    // Mine vs theirs: each row gets the corresponding justify class
    expect(screen.getByTestId("chat-message-m1").className).toMatch(
      /justify-start/,
    );
    expect(screen.getByTestId("chat-message-m2").className).toMatch(
      /justify-end/,
    );
  });

  it("marks incoming messages from others as seen on render (once each)", async () => {
    render(<ChatThreadClient />);
    await act(async () => {
      messageSubs[0]?.([
        {
          id: "m1",
          text: "hi",
          sender_uid: "u2",
          timestamp: ts(new Date()),
        },
        {
          id: "m2",
          text: "hello",
          sender_uid: "me",
          timestamp: ts(new Date()),
        },
      ]);
    });
    await waitFor(() =>
      expect(markMessageSeenMock).toHaveBeenCalledTimes(1),
    );
    expect(markMessageSeenMock).toHaveBeenCalledWith("t1", "m1", "me");
    // Re-emission of the same message shouldn't re-fire markMessageSeen
    await act(async () => {
      messageSubs[0]?.([
        {
          id: "m1",
          text: "hi",
          sender_uid: "u2",
          timestamp: ts(new Date()),
        },
      ]);
    });
    expect(markMessageSeenMock).toHaveBeenCalledTimes(1);
  });

  it("does NOT mark messages seen if user is already in seen_by", async () => {
    render(<ChatThreadClient />);
    await act(async () => {
      messageSubs[0]?.([
        {
          id: "m1",
          text: "hi",
          sender_uid: "u2",
          seen_by: ["me"],
          timestamp: ts(new Date()),
        },
      ]);
    });
    await waitFor(() =>
      expect(screen.getByTestId("chat-message-m1")).toBeInTheDocument(),
    );
    expect(markMessageSeenMock).not.toHaveBeenCalled();
  });

  it("sends a message via sendChatMessage when the composer is submitted", async () => {
    const user = userEvent.setup();
    render(<ChatThreadClient />);
    await act(async () => {
      messageSubs[0]?.([]);
    });
    const input = screen.getByTestId(
      "chat-composer-input",
    ) as HTMLTextAreaElement;
    await user.type(input, "hello world");
    await user.click(screen.getByRole("button", { name: /Send/i }));
    await waitFor(() =>
      expect(sendChatMessageMock).toHaveBeenCalledTimes(1),
    );
    expect(sendChatMessageMock).toHaveBeenCalledWith("t1", {
      text: "hello world",
      sender_uid: "me",
    });
  });

  it("does not send if the textarea and attachment are both empty", async () => {
    const user = userEvent.setup();
    render(<ChatThreadClient />);
    await act(async () => {
      messageSubs[0]?.([]);
    });
    const button = screen.getByRole("button", { name: /Send/i });
    expect(button).toBeDisabled();
    await user.click(button);
    expect(sendChatMessageMock).not.toHaveBeenCalled();
  });

  it("shows an error when sendChatMessage rejects", async () => {
    sendChatMessageMock.mockRejectedValueOnce(new Error("boom"));
    const user = userEvent.setup();
    render(<ChatThreadClient />);
    await act(async () => {
      messageSubs[0]?.([]);
    });
    await user.type(
      screen.getByTestId("chat-composer-input"),
      "test",
    );
    await user.click(screen.getByRole("button", { name: /Send/i }));
    await waitFor(() =>
      expect(
        screen.getByText(/Couldn't send|couldn['’]t send/i),
      ).toBeInTheDocument(),
    );
  });

  it("shows an upload-failure error when image upload throws", async () => {
    uploadBytesMock.mockRejectedValueOnce(new Error("network timeout"));
    const user = userEvent.setup();
    render(<ChatThreadClient />);
    await act(async () => {
      messageSubs[0]?.([]);
    });
    const fileInput = screen.getByTestId(
      "chat-attach-input",
    ) as HTMLInputElement;
    const file = new File(["dummy"], "photo.png", { type: "image/png" });
    await user.upload(fileInput, file);
    await user.type(
      screen.getByTestId("chat-composer-input"),
      "with image",
    );
    await user.click(screen.getByRole("button", { name: /Send/i }));
    await waitFor(() =>
      expect(
        screen.getByText(/Couldn't upload image|couldn['’]t upload/i),
      ).toBeInTheDocument(),
    );
    expect(sendChatMessageMock).not.toHaveBeenCalled();
  });

  it("falls back to the other uid when thread has no name", async () => {
    getChatThreadMock.mockResolvedValueOnce({
      id: "t1",
      users: ["me", "u2"],
      is_group: false,
      created_at: ts(new Date()),
    });
    render(<ChatThreadClient />);
    await act(async () => {
      messageSubs[0]?.([]);
    });
    await waitFor(() => expect(screen.getByText("u2")).toBeInTheDocument());
  });

  it("unsubscribes from messages on unmount", async () => {
    const { unmount } = render(<ChatThreadClient />);
    await act(async () => {
      messageSubs[0]?.([]);
    });
    unmount();
    expect(msgUnsubscribeSpy).toHaveBeenCalledTimes(1);
  });

  it("handles null timestamp (timestampToDate returns null)", async () => {
    render(<ChatThreadClient />);
    await act(async () => {
      messageSubs[0]?.([
        {
          id: "m1",
          text: "no timestamp",
          sender_uid: "me",
          timestamp: null,
        },
      ]);
    });
    await waitFor(() =>
      expect(screen.getByTestId("chat-message-m1")).toBeInTheDocument(),
    );
    // Text should be visible but no time element rendered
    expect(screen.getByText("no timestamp")).toBeInTheDocument();
  });

  it("renders a raw Date timestamp (not Firestore Timestamp)", async () => {
    render(<ChatThreadClient />);
    const rawDate = new Date("2024-01-15T10:30:00");
    await act(async () => {
      messageSubs[0]?.([
        {
          id: "m1",
          text: "dated",
          sender_uid: "u2",
          timestamp: rawDate,
        },
      ]);
    });
    await waitFor(() =>
      expect(screen.getByTestId("chat-message-m1")).toBeInTheDocument(),
    );
    // The raw Date should render via toLocaleTimeString
    expect(screen.getByText("dated")).toBeInTheDocument();
    // Time text should exist (e.g. "10:30 AM")
    expect(screen.getByText(/10:30|AM|10:30/i)).toBeInTheDocument();
  });

  it("renders timestamp from a seconds-based object", async () => {
    render(<ChatThreadClient />);
    await act(async () => {
      messageSubs[0]?.([
        {
          id: "m1",
          text: "epoch",
          sender_uid: "u2",
          timestamp: { seconds: 1705312200 }, // Jan 15, 2024
        },
      ]);
    });
    await waitFor(() =>
      expect(screen.getByTestId("chat-message-m1")).toBeInTheDocument(),
    );
    expect(screen.getByText("epoch")).toBeInTheDocument();
  });

  it("renders an image inside a message when image_url is set", async () => {
    render(<ChatThreadClient />);
    await act(async () => {
      messageSubs[0]?.([
        {
          id: "m1",
          text: "check this photo",
          sender_uid: "u2",
          image_url: "https://example.com/photo.jpg",
          timestamp: ts(new Date()),
        },
      ]);
    });
    await waitFor(() =>
      expect(screen.getByTestId("chat-message-m1")).toBeInTheDocument(),
    );
    const img = screen.getByTestId("chat-message-m1").querySelector("img");
    expect(img).toBeInTheDocument();
    expect(img).toHaveAttribute("src", "https://example.com/photo.jpg");
    // Text is also present alongside the image
    expect(screen.getByText("check this photo")).toBeInTheDocument();
  });

  it("shows sending disabled state while a message is being sent", async () => {
    // Make sendChatMessage hang so we can observe the sending state
    let resolveSend!: (v: unknown) => void;
    sendChatMessageMock.mockImplementationOnce(
      () => new Promise((r) => { resolveSend = r; }),
    );
    const user = userEvent.setup();
    render(<ChatThreadClient />);
    await act(async () => {
      messageSubs[0]?.([]);
    });
    const input = screen.getByTestId("chat-composer-input");
    await user.type(input, "hello");
    await user.click(screen.getByRole("button", { name: /Send/i }));
    // Button should show "Sending…" and be disabled while in-flight
    expect(screen.getByRole("button", { name: /Sending…/i })).toBeDisabled();
    // Resolve the send so the test doesn't hang
    await act(async () => { resolveSend?.("id"); });
  });

  it("cancels thread load on unmount (cancelled flag)", async () => {
    // Make getChatThread hang
    let resolveThread!: (v: unknown) => void;
    getChatThreadMock.mockImplementationOnce(
      () => new Promise((r) => { resolveThread = r; }),
    );
    const { unmount } = render(<ChatThreadClient />);
    // Before the thread resolves, unmount — cancelled should be true
    unmount();
    // Resolve after unmount; no state update should happen (cancelled=true)
    await act(async () => { resolveThread?.({ id: "t1", name: "Late", users: ["me", "u2"], is_group: false, created_at: ts(new Date()) }); });
    // After unmount + late resolution: no crash, component is gone
  });
});
