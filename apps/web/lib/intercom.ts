/**
 * Intercom integration helpers for the Next.js web app.
 *
 * Handles lazy-loading the official Intercom JS snippet and the small
 * wrapper API our (app)-scoped UI uses (boot / update / shutdown).
 *
 * The Intercom widget is only ever loaded for signed-in users inside the
 * `(app)` layout — never on landing or auth routes. The loader is called
 * from a client component inside an effect, so all `window` access in
 * this module is still guarded with `typeof window !== "undefined"`
 * because the file may be imported during SSR / static export.
 */
export interface IntercomUser {
  user_id: string;
  email?: string;
  name?: string;
}

export type IntercomAttrs = Record<string, unknown>;

/**
 * Minimal shape for the `window.Intercom` global — we rely only on the
 * callable form `Intercom(action, payload)` that the official snippet
 * ships. Using `unknown` for args keeps us decoupled from upstream
 * type drift.
 */
export type IntercomFn = (...args: unknown[]) => void;

declare global {
  interface Window {
    Intercom?: IntercomFn;
    intercomSettings?: Record<string, unknown>;
    attachEvent?: (event: string, handler: () => void) => void;
  }
}

/**
 * Reads the Intercom workspace ID from env. Returns `null` if unset so
 * callers can dev-safely no-op instead of failing the app.
 */
function getAppId(): string | null {
  const id = process.env.NEXT_PUBLIC_INTERCOM_APP_ID;
  return id && id.length > 0 ? id : null;
}

/**
 * Lazily injects the Intercom JS snippet and installs the `window.Intercom`
 * stub. Safe to call multiple times — subsequent calls are no-ops once the
 * snippet is already loaded.
 *
 * Mirrors the official loader, adapted so it's SSR-safe (gated on window).
 */
export function loadIntercomSnippet(appId: string): void {
  if (typeof window === "undefined") return;
  // Already loaded (snippet or real widget) — nothing to do.
  if (typeof window.Intercom === "function") return;

  const w = window;
  const d = document;
  const ic = w.Intercom;
  if (typeof ic === "function") {
    // Some other caller already called loadIntercomSnippet — bail.
    return;
  }

  // Queue calls until the real script loads and replaces the stub.
  const queue: unknown[][] = [];
  const stub: IntercomFn = (...args: unknown[]) => {
    queue.push(args);
  };
  (stub as unknown as { q: unknown[][] }).q = queue;
  (stub as unknown as { c: (args: unknown[]) => void }).c = (args) => {
    queue.push(args);
  };
  w.Intercom = stub;

  const load = () => {
    const s = d.createElement("script");
    s.type = "text/javascript";
    s.async = true;
    s.src = `https://widget.intercom.io/widget/${appId}`;
    const x = d.getElementsByTagName("script")[0];
    x?.parentNode?.insertBefore(s, x);
  };

  if (d.readyState === "complete") {
    load();
  } else if (w.addEventListener) {
    w.addEventListener("load", load, false);
  } else if (typeof w.attachEvent === "function") {
    w.attachEvent("onload", load);
  }
}

function callIntercom(action: string, payload?: unknown): void {
  if (typeof window === "undefined") return;
  const fn = window.Intercom;
  if (typeof fn !== "function") return;
  if (payload === undefined) {
    fn(action);
  } else {
    fn(action, payload);
  }
}

/**
 * Boots the Intercom widget for a signed-in user. The `jwt` is the signed
 * `user_hash` issued by the `generateIntercomJWT` Cloud Function and is
 * required for Intercom Identity Verification.
 *
 * No-ops (with a dev-console warning) when `NEXT_PUBLIC_INTERCOM_APP_ID`
 * is unset — this keeps local development usable without Intercom creds.
 */
export function bootIntercom(user: IntercomUser, jwt: string): void {
  const appId = getAppId();
  if (!appId) {
    if (typeof console !== "undefined") {
      console.warn(
        "[intercom] NEXT_PUBLIC_INTERCOM_APP_ID not set — widget disabled",
      );
    }
    return;
  }
  if (typeof window === "undefined") return;
  loadIntercomSnippet(appId);
  callIntercom("boot", {
    app_id: appId,
    user_id: user.user_id,
    user_hash: jwt,
    name: user.name,
    email: user.email,
  });
}

/**
 * Pushes updated attributes to Intercom. Use this whenever user-facing
 * details change while the widget is booted (e.g. display name, plan).
 */
export function updateIntercom(attrs: IntercomAttrs): void {
  const appId = getAppId();
  if (!appId) return;
  callIntercom("update", attrs);
}

/**
 * Tears the widget down on sign-out. After shutdown a fresh `boot` is
 * required to bring the widget back for the next signed-in user.
 */
export function shutdownIntercom(): void {
  const appId = getAppId();
  if (!appId) return;
  callIntercom("shutdown");
}
