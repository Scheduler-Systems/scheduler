/* eslint-disable no-undef */
/**
 * Firebase Cloud Messaging service worker.
 *
 * MUST live at /firebase-messaging-sw.js — the Firebase Messaging SDK hard-codes
 * this path when it auto-registers the service worker. If you move it the SDK
 * silently fails to receive background messages.
 *
 * The compat SDK is used here (via importScripts) because service workers can't
 * import the modular ESM build. `messagingSenderId` is baked in — it's safe to
 * expose publicly (Firebase project sender ID is not a secret) and env vars
 * aren't available inside service worker scope anyway.
 *
 * See: https://firebase.google.com/docs/cloud-messaging/js/receive#handle_messages_when_your_web_app_is_in_the_background
 */

importScripts(
  "https://www.gstatic.com/firebasejs/12.12.1/firebase-app-compat.js"
);
importScripts(
  "https://www.gstatic.com/firebasejs/12.12.1/firebase-messaging-compat.js"
);

// Matches apps/web/lib/firebase.ts — keep in sync if the Firebase project changes.
firebase.initializeApp({
  apiKey: "fcm-web-placeholder",
  authDomain: "your-firebase-project-id.firebaseapp.com",
  projectId: "your-firebase-project-id",
  storageBucket: "your-firebase-project-id.firebasestorage.app",
  messagingSenderId: "000000000000",
  appId: "1:000000000000:web:0000000000000000000000",
});

const messaging = firebase.messaging();

// Fires when a push arrives while the tab is backgrounded or closed.
// Foreground messages are routed through onMessage() in apps/web/lib/fcm.ts.
messaging.onBackgroundMessage((payload) => {
  const notification = payload.notification || {};
  const data = payload.data || {};
  const title = notification.title || data.title || "Scheduler";
  const body = notification.body || data.body || "";
  const url = data.url || data.click_action || "/";

  self.registration.showNotification(title, {
    body,
    icon: notification.icon || "/favicon.ico",
    data: { url },
  });
});

// When the user taps the OS notification: focus an existing tab on the target
// URL if one is open, otherwise open a fresh tab.
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const targetUrl = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil(
    self.clients
      .matchAll({ type: "window", includeUncontrolled: true })
      .then((clientsArr) => {
        for (const client of clientsArr) {
          if (client.url.includes(targetUrl) && "focus" in client) {
            return client.focus();
          }
        }
        if (self.clients.openWindow) {
          return self.clients.openWindow(targetUrl);
        }
        return null;
      })
  );
});
