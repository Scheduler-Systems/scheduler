import { describe, it, expect } from "vitest";
import { AuthErrorMessages, getAuthErrorMessage } from "./errors";

describe("AuthErrorMessages", () => {
  it("contains all expected Firebase auth error codes", () => {
    const keys = Object.keys(AuthErrorMessages);
    expect(keys).toContain("auth/wrong-password");
    expect(keys).toContain("auth/invalid-credential");
    expect(keys).toContain("auth/user-not-found");
    expect(keys).toContain("auth/email-already-in-use");
    expect(keys).toContain("auth/weak-password");
    expect(keys).toContain("auth/invalid-email");
    expect(keys).toContain("auth/operation-not-allowed");
    expect(keys).toContain("auth/user-disabled");
    expect(keys).toContain("auth/too-many-requests");
    expect(keys).toContain("auth/network-request-failed");
    expect(keys).toContain("auth/requires-recent-login");
    expect(keys).toContain("auth/invalid-phone-number");
    expect(keys).toContain("auth/invalid-verification-code");
    expect(keys).toContain("auth/code-expired");
  });

  it("has human-readable messages for every code", () => {
    for (const [code, message] of Object.entries(AuthErrorMessages)) {
      expect(message).toBeTruthy();
      expect(typeof message).toBe("string");
      expect(message.length).toBeGreaterThan(5);
    }
  });
});

describe("getAuthErrorMessage", () => {
  it("returns the mapped message for known codes", () => {
    expect(getAuthErrorMessage("auth/wrong-password")).toBe(
      "Incorrect password. Please try again.",
    );
    expect(getAuthErrorMessage("auth/email-already-in-use")).toBe(
      "An account with this email already exists.",
    );
    expect(getAuthErrorMessage("auth/user-not-found")).toBe(
      "No account found with this email.",
    );
    expect(getAuthErrorMessage("auth/invalid-credential")).toBe(
      "Invalid credentials. Please check your email and password.",
    );
    expect(getAuthErrorMessage("auth/weak-password")).toBe(
      "Password is too weak. Please use a stronger password.",
    );
    expect(getAuthErrorMessage("auth/user-disabled")).toBe(
      "This account has been disabled.",
    );
    expect(getAuthErrorMessage("auth/too-many-requests")).toBe(
      "Too many attempts. Please try again later.",
    );
    expect(getAuthErrorMessage("auth/network-request-failed")).toBe(
      "Network error. Please check your connection.",
    );
    expect(getAuthErrorMessage("auth/invalid-phone-number")).toBe(
      "Please enter a valid phone number.",
    );
    expect(getAuthErrorMessage("auth/invalid-verification-code")).toBe(
      "Invalid verification code. Please try again.",
    );
    expect(getAuthErrorMessage("auth/code-expired")).toBe(
      "Verification code expired. Please request a new one.",
    );
  });

  it("returns the fallback message for unknown codes", () => {
    expect(getAuthErrorMessage("auth/unknown-error")).toBe(
      "An unexpected error occurred. Please try again.",
    );
    expect(getAuthErrorMessage("random/thing")).toBe(
      "An unexpected error occurred. Please try again.",
    );
    expect(getAuthErrorMessage("")).toBe(
      "An unexpected error occurred. Please try again.",
    );
  });
});
