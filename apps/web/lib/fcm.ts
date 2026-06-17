"use client";

/**
 * Firebase Cloud Messaging helpers for the Next.js web app.
 *
 * Receive-side only — the Flutter Cloud Function `sendUserPushNotification`
 * owns the send path. This module:
 *   1. Requests browser notification permission + registers an FCM token
 *   2. Writes the token to Firestore (users/{uid}.fcm_tokens) so the Cloud
 *      Function can fan out to every active device
 *   3. Wires foreground `onMessage` so the UI can render in-page toasts
 *      (the service worker only shows OS notifications while backgrounded)
 *
 * All firebase/messaging imports are lazy — the module is SSR-safe and never
 * hits the browser API during Next.js prerender.
 */

import type { Auth } from "firebase/auth";
import { registerFcmToken as writeFcmToken } from "./firestore-write";

// Re-export the write helper so callers can import both from `lib/fcm`.
export const registerFcmToken = writeFcmToken;

export interface FcmMessage {
  title: string;
  body: string;
  data: Record<string, string>;
}

export type FcmMessageCallback = (message: FcmMessage) => void;

function isBrowser(): boolean {
  return typeof window !== "undefined" && typeof navigator !== "undefined";
}

/**
 * Requests notification permission and returns an FCM registration token, or
 * null when permission is denied / the browser doesn't support FCM.
 *
 * NEVER throws — the caller is a UI boot component and a rejected push setup
 * must not break the app shell. Errors are logged and surface as null.
 */
export async function requestFcmPermissionAndToken(
  auth: Auth,
): Promise<string | null> {
  if (!isBrowser()) return null;
  if (typeof Notification === "undefined") return null;
  // Mirror Flutter's authenticatedUserStream.where((u) => u != null) — no
  // token unless the user is actually signed in. FCM tokens are per-user.
  if (!auth.currentUser) return null;

  try {
    const permission = await Notification.requestPermission();
    if (permission !== "granted") return null;

    // Lazy-load firebase/messaging so SSR bundles don't trip on `window`.
    const messagingModule = await import("firebase/messaging");
    const { getFirebaseApp } = await import("./firebase");

    const messaging = messagingModule.getMessaging(getFirebaseApp());
    const vapidKey = process.env.NEXT_PUBLIC_FIREBASE_VAPID_KEY;
    const token = await messagingModule.getToken(messaging, {
      vapidKey,
    });
    return token || null;
  } catch (err) {
    // Unsupported browser, denied permission after grant, or a transient
    // service-worker registration failure. Never throw.
    if (typeof console !== "undefined") {
      console.warn("[fcm] token retrieval failed", err);
    }
    return null;
  }
}

/**
 * Subscribes to foreground push messages.
 *
 * Returns an unsubscribe function. When the tab is focused the service worker
 * does NOT show an OS notification — the SDK hands the payload to `onMessage`
 * and the app renders its own toast.
 */
export async function subscribeToForegroundMessages(
  callback: FcmMessageCallback,
): Promise<() => void> {
  if (!isBrowser()) return () => undefined;

  try {
    const messagingModule = await import("firebase/messaging");
    const { getFirebaseApp } = await import("./firebase");

    const messaging = messagingModule.getMessaging(getFirebaseApp());
    return messagingModule.onMessage(messaging, (payload) => {
      const notification = payload.notification ?? {};
      const data = payload.data ?? {};
      callback({
        title: notification.title ?? data.title ?? "",
        body: notification.body ?? data.body ?? "",
        data: data as Record<string, string>,
      });
    });
  } catch (err) {
    if (typeof console !== "undefined") {
      console.warn("[fcm] onMessage subscribe failed", err);
    }
    return () => undefined;
  }
}
