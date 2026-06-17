// Pure helpers for the email-verification waiting screen.
// Firebase-free so they're unit-testable.

export const RESEND_COOLDOWN_MS = 60_000; // 60 seconds

export function isEmailVerified(user: { emailVerified: boolean } | null): boolean {
  return user?.emailVerified === true;
}

export function emailVerificationRateLimitKey(email: string): string {
  return `verify_email_sent_at::${email}`;
}

export function canResendVerification(lastSentMs: number | null): boolean {
  if (lastSentMs === null) return true;
  return Date.now() - lastSentMs >= RESEND_COOLDOWN_MS;
}
