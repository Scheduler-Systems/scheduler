import { describe, it, expect } from "vitest";
import {
  isEmailVerified,
  emailVerificationRateLimitKey,
  canResendVerification,
  RESEND_COOLDOWN_MS,
} from "./verify-email";

describe("isEmailVerified", () => {
  it("returns true when emailVerified is true", () => {
    expect(isEmailVerified({ emailVerified: true } as never)).toBe(true);
  });

  it("returns false when emailVerified is false", () => {
    expect(isEmailVerified({ emailVerified: false } as never)).toBe(false);
  });

  it("returns false for null user", () => {
    expect(isEmailVerified(null)).toBe(false);
  });
});

describe("emailVerificationRateLimitKey", () => {
  it("produces a namespaced key from the email", () => {
    const key = emailVerificationRateLimitKey("user@example.com");
    expect(key).toContain("user@example.com");
    expect(key).toMatch(/verify/i);
  });
});

describe("canResendVerification", () => {
  it("allows send when no previous timestamp is stored", () => {
    expect(canResendVerification(null)).toBe(true);
  });

  it("blocks resend within the cooldown window", () => {
    const recentMs = Date.now() - RESEND_COOLDOWN_MS / 2;
    expect(canResendVerification(recentMs)).toBe(false);
  });

  it("allows resend after the cooldown window has elapsed", () => {
    const oldMs = Date.now() - RESEND_COOLDOWN_MS - 1000;
    expect(canResendVerification(oldMs)).toBe(true);
  });

  it("allows resend at exactly the boundary", () => {
    const boundaryMs = Date.now() - RESEND_COOLDOWN_MS;
    expect(canResendVerification(boundaryMs)).toBe(true);
  });
});
