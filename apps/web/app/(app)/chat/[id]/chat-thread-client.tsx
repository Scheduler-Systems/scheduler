"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
  type FormEvent,
} from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { useI18n } from "@/lib/i18n-context";
import {
  subscribeToChatMessages,
  getChatThread,
} from "@/lib/chat";
import { sendChatMessage, markMessageSeen } from "@/lib/firestore-write";
import type { ChatMessage, ChatThread } from "@/lib/chat-types";
import { getFirebaseApp } from "@/lib/firebase";

/**
 * Upload an image File to Firebase Storage at
 * `chats/{threadId}/images/{messageId}.{ext}` and return the download URL.
 *
 * Dynamically imports `firebase/storage` so the module isn't pulled into the
 * initial route chunk — attachments are a rarely-used code path on the web
 * side and the SDK weighs non-trivially. Matches the lazy-import pattern in
 * `fcm-boot.tsx` / `intercom-boot.tsx`.
 */
async function uploadChatImage(
  threadId: string,
  messageId: string,
  file: File
): Promise<string> {
  const { getStorage, ref, uploadBytes, getDownloadURL } = await import(
    "firebase/storage"
  );
  const storage = getStorage(getFirebaseApp());
  const ext = file.name.includes(".")
    ? file.name.split(".").pop() ?? "bin"
    : "bin";
  const path = `chats/${threadId}/images/${messageId}.${ext}`;
  const storageRef = ref(storage, path);
  await uploadBytes(storageRef, file);
  return getDownloadURL(storageRef);
}

function timestampToDate(ts: unknown): Date | null {
  if (!ts) return null;
  if (ts instanceof Date) return ts;
  if (typeof ts === "object" && ts !== null) {
    const maybe = ts as { toDate?: () => Date; seconds?: number };
    if (typeof maybe.toDate === "function") {
      try {
        return maybe.toDate();
      } catch {
        return null;
      }
    }
    if (typeof maybe.seconds === "number") {
      return new Date(maybe.seconds * 1000);
    }
  }
  return null;
}

function avatarInitial(label: string): string {
  const c = label?.trim?.()?.[0];
  return (c ?? "?").toUpperCase();
}

export default function ChatThreadClient() {
  const { id } = useParams<{ id: string }>();
  const { user } = useAuth();
  const { t } = useI18n();

  const [thread, setThread] = useState<ChatThread | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(true);

  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const [attachment, setAttachment] = useState<File | null>(null);

  const scrollRef = useRef<HTMLDivElement | null>(null);

  // Track message ids we've already marked as seen so we don't re-issue the
  // arrayUnion write on every re-render. A Ref (not state) so the check
  // happens synchronously during render without an effect-thrash.
  const seenIdsRef = useRef<Set<string>>(new Set());

  // Load thread metadata (one-shot; thread rename flows through a separate
  // future phase so we don't need a live subscriber for the header).
  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    getChatThread(id).then((t) => {
      if (!cancelled) setThread(t);
    });
    return () => {
      cancelled = true;
    };
  }, [id]);

  // Subscribe to messages; newest arrives at the bottom (data layer orders asc).
  useEffect(() => {
    if (!id) return;
    const unsubscribe = subscribeToChatMessages(id, (next) => {
      setMessages(next);
      setLoading(false);
    });
    return () => unsubscribe();
  }, [id]);

  // Mark incoming messages as seen — only the ones NOT by me and NOT already
  // in the seen ref. The write is best-effort (markMessageSeen silently
  // swallows permission errors on the server side).
  useEffect(() => {
    if (!id || !user) return;
    for (const m of messages) {
      if (m.sender_uid === user.uid) continue;
      if (seenIdsRef.current.has(m.id)) continue;
      if ((m.seen_by ?? []).includes(user.uid)) {
        seenIdsRef.current.add(m.id);
        continue;
      }
      seenIdsRef.current.add(m.id);
      markMessageSeen(id, m.id, user.uid).catch(() => undefined);
    }
  }, [id, messages, user]);

  // Auto-scroll to bottom whenever new messages arrive.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [messages.length]);

  const onAttach = useCallback((e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0] ?? null;
    setAttachment(file);
  }, []);

  const onSubmit = useCallback(
    async (e: FormEvent<HTMLFormElement>) => {
      e.preventDefault();
      if (!user || !id) return;
      const trimmed = text.trim();
      if (!trimmed && !attachment) return;
      setSending(true);
      setSendError(null);
      try {
        let imageUrl: string | undefined;
        if (attachment) {
          // messageId isn't known before write; use a client-side random id
          // for the storage path so the upload happens in parallel with the
          // Firestore batch. sendChatMessage writes the image_url back on
          // the message doc regardless of storage-path messageId parity.
          const pseudoId = `${Date.now()}-${Math.random()
            .toString(36)
            .slice(2, 8)}`;
          try {
            imageUrl = await uploadChatImage(id, pseudoId, attachment);
          } catch {
            setSendError(t("chat.imageUploadFailed"));
            setSending(false);
            return;
          }
        }
        await sendChatMessage(id, {
          text: trimmed,
          sender_uid: user.uid,
          ...(imageUrl ? { image_url: imageUrl } : {}),
        });
        setText("");
        setAttachment(null);
      } catch {
        setSendError(t("chat.sendFailed"));
      } finally {
        setSending(false);
      }
    },
    [user, id, text, attachment, t]
  );

  if (!user || !id) return null;

  const headerName =
    thread?.name && thread.name.trim().length > 0
      ? thread.name
      : thread?.users?.find((u) => u !== user.uid) ?? t("chat.unknownThread");

  return (
    <div className="flex flex-col h-[calc(100vh-10rem)] min-h-[400px]">
      {/* Top bar */}
      <div className="flex items-center gap-3 border-b border-gray-200 bg-white px-4 py-3">
        <Link
          href="/chat"
          aria-label={t("chat.backToList")}
          className="text-sm text-purple-600 hover:underline font-medium"
        >
          {t("chat.backToList")}
        </Link>
        <div
          aria-hidden="true"
          className="w-8 h-8 rounded-full bg-purple-600 flex items-center justify-center text-white text-sm font-semibold"
        >
          {avatarInitial(headerName)}
        </div>
        <h1 className="text-lg font-semibold truncate">{headerName}</h1>
      </div>

      {/* Messages scroll area */}
      <div
        ref={scrollRef}
        data-testid="chat-messages-scroll"
        className="flex-1 overflow-y-auto bg-gray-50 px-4 py-3 space-y-2"
      >
        {loading ? (
          <div className="flex items-center justify-center py-20">
            <div className="w-6 h-6 border-2 border-purple-600 border-t-transparent rounded-full animate-spin" />
          </div>
        ) : messages.length === 0 ? (
          <div className="text-center text-sm text-gray-400 py-20">
            {t("chat.emptyMessage")}
          </div>
        ) : (
          messages.map((m) => {
            const mine = m.sender_uid === user.uid;
            const when = timestampToDate(m.timestamp);
            return (
              <div
                key={m.id}
                data-testid={`chat-message-${m.id}`}
                className={`flex items-end gap-2 ${
                  mine ? "justify-end" : "justify-start"
                }`}
              >
                {!mine && (
                  <div
                    aria-hidden="true"
                    className="flex-shrink-0 w-7 h-7 rounded-full bg-gray-300 flex items-center justify-center text-white text-xs font-semibold"
                  >
                    {avatarInitial(m.sender_uid)}
                  </div>
                )}
                <div
                  className={`max-w-[75%] rounded-2xl px-3 py-2 text-sm shadow-sm ${
                    mine
                      ? "bg-purple-600 text-white"
                      : "bg-white text-gray-900 border border-gray-200"
                  }`}
                >
                  {m.image_url && (
                    // Intentional: Firebase Storage URLs don't benefit from
                    // next/image's loader here (static export = no image
                    // optimization anyway). Keeping <img> keeps the bundle
                    // + SSR tree clean.
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={m.image_url}
                      alt=""
                      className="rounded mb-1 max-h-60 object-cover"
                    />
                  )}
                  {m.text && (
                    <p className="whitespace-pre-wrap break-words">{m.text}</p>
                  )}
                  {when && (
                    <p
                      className={`mt-1 text-[10px] ${
                        mine ? "text-purple-100" : "text-gray-400"
                      }`}
                    >
                      {when.toLocaleTimeString([], {
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                    </p>
                  )}
                </div>
                {mine && (
                  <div
                    aria-hidden="true"
                    className="flex-shrink-0 w-7 h-7 rounded-full bg-purple-700 flex items-center justify-center text-white text-xs font-semibold"
                  >
                    {avatarInitial(user.displayName ?? user.email ?? "?")}
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>

      {/* Composer */}
      <form
        onSubmit={onSubmit}
        className="border-t border-gray-200 bg-white px-4 py-3 space-y-2"
      >
        {sendError && (
          <p className="text-xs text-red-600" role="alert">
            {sendError}
          </p>
        )}
        {attachment && (
          <p className="text-xs text-gray-500 truncate">
            {attachment.name}
          </p>
        )}
        <div className="flex items-end gap-2">
          <label
            className="flex-shrink-0 inline-flex items-center justify-center w-9 h-9 rounded-full bg-gray-100 text-gray-600 hover:bg-gray-200 cursor-pointer"
            aria-label={t("chat.attachImage")}
            title={t("chat.attachImage")}
          >
            <input
              type="file"
              accept="image/*"
              className="hidden"
              onChange={onAttach}
              data-testid="chat-attach-input"
            />
            <svg
              className="w-5 h-5"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={1.5}
                d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13"
              />
            </svg>
          </label>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={t("chat.composerPlaceholder")}
            rows={1}
            className="flex-1 resize-none rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
            data-testid="chat-composer-input"
          />
          <button
            type="submit"
            disabled={sending || (!text.trim() && !attachment)}
            className="flex-shrink-0 rounded-lg bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {sending ? t("chat.sending") : t("chat.sendButton")}
          </button>
        </div>
      </form>
    </div>
  );
}
