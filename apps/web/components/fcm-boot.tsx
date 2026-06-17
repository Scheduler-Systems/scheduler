"use client";

/**
 * FcmBoot — client-only bootstrap for Firebase Cloud Messaging on the web.
 *
 * Responsibilities:
 *   1. When a signed-in user visits an authed page, offer an "Enable
 *      notifications" prompt. Never request permission without a click, per
 *      browser UX guidance and Chrome's auto-deny heuristics.
 *   2. On accept: request permission, pull an FCM token, write it to
 *      users/{uid}.fcm_tokens (arrayUnion, multi-device safe).
 *   3. Subscribe to foreground messages and render them as lightweight toasts
 *      (the service worker only shows OS notifications while backgrounded).
 *   4. Remember the user's answer ("enabled" or "skipped") in localStorage so
 *      we don't nag on every page load.
 *
 * Mounted once, as a sibling of <Nav /> + <main /> in app/(app)/layout.tsx.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useAuth } from "@/lib/auth-context";
import { getFirebaseAuth } from "@/lib/firebase";
import {
  requestFcmPermissionAndToken,
  registerFcmToken,
  subscribeToForegroundMessages,
  type FcmMessage,
} from "@/lib/fcm";

const PROMPT_ANSWERED_KEY = "fcm_prompt_answered";

interface Toast {
  id: number;
  title: string;
  body: string;
}

function readPromptAnswered(): boolean {
  if (typeof window === "undefined") return true; // Don't render during SSR
  try {
    return window.localStorage.getItem(PROMPT_ANSWERED_KEY) === "true";
  } catch {
    return false;
  }
}

function writePromptAnswered(): void {
  try {
    window.localStorage.setItem(PROMPT_ANSWERED_KEY, "true");
  } catch {
    // Private browsing or quota — ignore; worst case we re-prompt later.
  }
}

export function FcmBoot() {
  const { user } = useAuth();
  // Tracks whether the user has actively answered (Skip/Enable) in THIS
  // session. Combined with localStorage + user presence, the memo below
  // computes the visible state without a setState-in-effect pattern.
  const [sessionAnswered, setSessionAnswered] = useState(false);
  const [busy, setBusy] = useState(false);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const toastIdRef = useRef(0);

  const showPrompt = useMemo(() => {
    if (!user) return false;
    if (sessionAnswered) return false;
    if (readPromptAnswered()) return false;
    return true;
  }, [user, sessionAnswered]);

  // Subscribe to foreground messages as soon as the user is signed in. If the
  // user never enabled notifications this is a no-op — getMessaging just
  // creates an instance and onMessage listens.
  useEffect(() => {
    if (!user) return;
    let unsub: (() => void) | null = null;
    let cancelled = false;

    subscribeToForegroundMessages((msg: FcmMessage) => {
      toastIdRef.current += 1;
      const id = toastIdRef.current;
      setToasts((prev) => [
        ...prev,
        { id, title: msg.title, body: msg.body },
      ]);
      // Auto-dismiss after 5s
      setTimeout(() => {
        setToasts((prev) => prev.filter((t) => t.id !== id));
      }, 5000);
    }).then((fn) => {
      if (cancelled) {
        fn();
        return;
      }
      unsub = fn;
    });

    return () => {
      cancelled = true;
      if (unsub) unsub();
    };
  }, [user]);

  const handleEnable = useCallback(async () => {
    if (!user) return;
    setBusy(true);
    try {
      const token = await requestFcmPermissionAndToken(getFirebaseAuth());
      if (token) {
        await registerFcmToken(user.uid, token);
      }
    } finally {
      writePromptAnswered();
      setSessionAnswered(true);
      setBusy(false);
    }
  }, [user]);

  const handleSkip = useCallback(() => {
    writePromptAnswered();
    setSessionAnswered(true);
  }, []);

  const dismissToast = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  return (
    <>
      {showPrompt && (
        <div
          role="dialog"
          aria-label="Enable notifications"
          className="fixed bottom-4 left-4 right-4 sm:left-auto sm:right-4 sm:max-w-sm z-50 bg-white border border-gray-200 rounded-lg shadow-lg p-4"
        >
          <div className="flex items-start gap-3">
            <div className="flex-1">
              <p className="text-sm font-medium text-gray-900">
                Stay on top of schedule changes
              </p>
              <p className="text-xs text-gray-500 mt-0.5">
                Get notified when a schedule is published or when you&apos;re
                asked to submit priorities.
              </p>
            </div>
          </div>
          <div className="flex items-center justify-end gap-2 mt-3">
            <button
              type="button"
              onClick={handleSkip}
              disabled={busy}
              className="text-xs px-3 py-1.5 rounded-md text-gray-500 hover:text-gray-700"
            >
              Skip
            </button>
            <button
              type="button"
              onClick={handleEnable}
              disabled={busy}
              className="text-xs px-3 py-1.5 rounded-md bg-purple-600 text-white font-medium hover:bg-purple-700 disabled:opacity-50"
            >
              {busy ? "Enabling…" : "Enable notifications"}
            </button>
          </div>
        </div>
      )}

      {toasts.length > 0 && (
        <div
          aria-live="polite"
          className="fixed top-4 right-4 z-50 flex flex-col gap-2 max-w-sm"
        >
          {toasts.map((toast) => (
            <div
              key={toast.id}
              role="status"
              className="bg-white border border-gray-200 rounded-lg shadow-lg p-3 flex items-start gap-2"
            >
              <div className="flex-1 min-w-0">
                {toast.title && (
                  <p className="text-sm font-medium text-gray-900 truncate">
                    {toast.title}
                  </p>
                )}
                {toast.body && (
                  <p className="text-xs text-gray-600 mt-0.5 break-words">
                    {toast.body}
                  </p>
                )}
              </div>
              <button
                type="button"
                aria-label="Dismiss notification"
                onClick={() => dismissToast(toast.id)}
                className="text-gray-400 hover:text-gray-600 text-sm leading-none"
              >
                x
              </button>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
