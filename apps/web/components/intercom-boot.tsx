"use client";

import { useEffect, useRef } from "react";
import { getFunctions, httpsCallable } from "firebase/functions";
import { getApp } from "firebase/app";
import { useAuth } from "@/lib/auth-context";
import { bootIntercom, shutdownIntercom } from "@/lib/intercom";

/**
 * Mounts the Intercom support widget for signed-in users.
 *
 * Rendered inside the `(app)` layout so it only runs after the user
 * auth gate has cleared — unauthenticated visitors to landing / login
 * pages never see the widget.
 *
 * Flow on sign-in:
 *   1. Call the Firebase callable `generateIntercomJWT`
 *   2. Boot the Intercom widget with user_id + user_hash (JWT)
 * Flow on sign-out: call Intercom("shutdown") to clear the session.
 *
 * If the JWT fetch fails (e.g. Cloud Function down, network error), the
 * widget stays dormant — we log to console and never surface an error
 * to the user. Support is a nice-to-have, not a blocking feature.
 */
export function IntercomBoot() {
  const { user } = useAuth();
  // Track the uid we've already booted for so we don't re-call boot on
  // every re-render. Shutdown clears this back to null.
  const bootedForUidRef = useRef<string | null>(null);

  useEffect(() => {
    // Signed out → shut down any active session
    if (!user) {
      if (bootedForUidRef.current !== null) {
        shutdownIntercom();
        bootedForUidRef.current = null;
      }
      return;
    }

    // Already booted for this user → nothing to do
    if (bootedForUidRef.current === user.uid) return;

    let cancelled = false;
    (async () => {
      try {
        const functions = getFunctions(getApp());
        const callable = httpsCallable<
          { platform: string },
          { token: string; expires_in?: number }
        >(functions, "generateIntercomJWT");
        const result = await callable({ platform: "web" });
        const jwt = result.data?.token;
        if (!jwt || cancelled) return;
        bootIntercom(
          {
            user_id: user.uid,
            email: user.email ?? undefined,
            name: user.displayName ?? undefined,
          },
          jwt,
        );
        bootedForUidRef.current = user.uid;
      } catch (err) {
        // Intentionally swallow — dormant widget is better than a visible
        // error. Logged for debugging.
        if (typeof console !== "undefined") {
          console.warn("[intercom] JWT fetch failed, widget disabled", err);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [user]);

  // Widget itself is injected into document.body by the Intercom snippet,
  // so this component renders nothing.
  return null;
}
