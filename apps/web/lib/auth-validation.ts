// Pure auth-form validation + Firebase error mapping.
// Kept free of Firebase imports so it's trivially unit-testable.

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function isValidEmail(input: string): boolean {
  return EMAIL_RE.test(input.trim());
}

export interface PasswordCheck {
  ok: boolean;
  reason?: string;
}

export function validatePassword(input: string): PasswordCheck {
  if (input.length < 6) {
    return { ok: false, reason: "Password must be at least 6 characters." };
  }
  return { ok: true };
}

const AUTH_ERROR_COPY: Record<string, string> = {
  "auth/email-already-in-use":
    "That email is already in use. Try signing in instead.",
  "auth/weak-password": "That password is too weak. Use at least 6 characters.",
  "auth/invalid-email": "That email address looks invalid.",
  "auth/user-not-found": "No account found for that email.",
  "auth/wrong-password": "Password is incorrect.",
  "auth/invalid-credential": "Email or password is incorrect.",
  "auth/too-many-requests":
    "Too many attempts. Please wait a moment and try again.",
  "auth/network-request-failed":
    "Network error. Check your connection and retry.",
};

export function friendlyAuthError(err: unknown): string {
  if (err && typeof err === "object") {
    const e = err as { code?: unknown; message?: unknown };
    if (typeof e.code === "string" && AUTH_ERROR_COPY[e.code]) {
      return AUTH_ERROR_COPY[e.code];
    }
    if (typeof e.message === "string" && e.message) return e.message;
  }
  return "Something went wrong. Please try again.";
}
