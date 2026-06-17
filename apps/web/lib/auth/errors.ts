export const AuthErrorMessages: Record<string, string> = {
  "auth/wrong-password": "Incorrect password. Please try again.",
  "auth/invalid-credential": "Invalid credentials. Please check your email and password.",
  "auth/user-not-found": "No account found with this email.",
  "auth/email-already-in-use": "An account with this email already exists.",
  "auth/weak-password": "Password is too weak. Please use a stronger password.",
  "auth/invalid-email": "Please enter a valid email address.",
  "auth/operation-not-allowed": "This sign-in method is not enabled.",
  "auth/user-disabled": "This account has been disabled.",
  "auth/too-many-requests": "Too many attempts. Please try again later.",
  "auth/network-request-failed": "Network error. Please check your connection.",
  "auth/requires-recent-login": "Please log in again to perform this action.",
  "auth/invalid-phone-number": "Please enter a valid phone number.",
  "auth/invalid-verification-code": "Invalid verification code. Please try again.",
  "auth/code-expired": "Verification code expired. Please request a new one.",
};

export function getAuthErrorMessage(code: string): string {
  return AuthErrorMessages[code] ?? "An unexpected error occurred. Please try again.";
}
