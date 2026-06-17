import { describe, it, expect } from "vitest";
import {
  isValidEmail,
  validatePassword,
  friendlyAuthError,
} from "./auth-validation";

describe("isValidEmail", () => {
  it("accepts ordinary well-formed addresses", () => {
    expect(isValidEmail("user@example.com")).toBe(true);
    expect(isValidEmail("name.tag+label@sub.domain.co")).toBe(true);
  });

  it("rejects addresses with no @ or no domain", () => {
    expect(isValidEmail("not-an-email")).toBe(false);
    expect(isValidEmail("user@")).toBe(false);
    expect(isValidEmail("@example.com")).toBe(false);
  });

  it("rejects whitespace-only or empty input", () => {
    expect(isValidEmail("")).toBe(false);
    expect(isValidEmail("   ")).toBe(false);
  });

  it("trims surrounding whitespace", () => {
    expect(isValidEmail("  user@example.com  ")).toBe(true);
  });
});

describe("validatePassword", () => {
  it("rejects empty or sub-6 passwords to match Firebase Auth defaults", () => {
    expect(validatePassword("").ok).toBe(false);
    expect(validatePassword("abc").ok).toBe(false);
    expect(validatePassword("12345").ok).toBe(false);
  });

  it("accepts any 6+ char password (matches Firebase minimum)", () => {
    expect(validatePassword("abcdef").ok).toBe(true);
    expect(validatePassword("hunter22").ok).toBe(true);
  });

  it("returns a human-readable reason on failure", () => {
    const r = validatePassword("x");
    expect(r.ok).toBe(false);
    expect(r.reason).toMatch(/6/);
  });
});

describe("friendlyAuthError", () => {
  it("maps common Firebase codes to human copy", () => {
    expect(friendlyAuthError({ code: "auth/email-already-in-use" })).toMatch(
      /already/i,
    );
    expect(friendlyAuthError({ code: "auth/weak-password" })).toMatch(/weak/i);
    expect(friendlyAuthError({ code: "auth/invalid-email" })).toMatch(
      /invalid/i,
    );
    expect(friendlyAuthError({ code: "auth/user-not-found" })).toMatch(
      /no account/i,
    );
    expect(friendlyAuthError({ code: "auth/wrong-password" })).toMatch(
      /incorrect/i,
    );
  });

  it("falls back to the error's message when code is unknown", () => {
    expect(
      friendlyAuthError({ code: "auth/some-thing", message: "boom" }),
    ).toBe("boom");
  });

  it("returns a safe default for non-Error input", () => {
    expect(friendlyAuthError(null)).toMatch(/something went wrong/i);
    expect(friendlyAuthError("string")).toMatch(/something went wrong/i);
  });
});
