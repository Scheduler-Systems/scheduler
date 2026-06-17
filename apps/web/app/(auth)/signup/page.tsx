"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { isEmailVerified } from "@/lib/verify-email";
import {
  isValidEmail,
  validatePassword,
  friendlyAuthError,
} from "@/lib/auth-validation";
import { useI18n } from "@/lib/i18n-context";

export default function SignupPage() {
  const { user, loading, signUpWithEmail } = useAuth();
  const router = useRouter();
  const { t } = useI18n();

  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [passwordConfirm, setPasswordConfirm] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!loading && user) router.replace("/dashboard");
  }, [user, loading, router]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");

    if (!name.trim()) {
      setError(t("signup.errorNameRequired"));
      return;
    }
    if (!isValidEmail(email)) {
      setError(t("signup.errorEmailInvalid"));
      return;
    }
    const pw = validatePassword(password);
    if (!pw.ok) {
      setError(pw.reason ?? t("signup.errorPasswordInvalid"));
      return;
    }
    if (password !== passwordConfirm) {
      setError(t("signup.errorPasswordsMismatch"));
      return;
    }

    setSubmitting(true);
    try {
      await signUpWithEmail(email.trim(), password, name);
      // Route through email verification; skip if already verified (e.g. social sign-in)
      const auth = (await import("@/lib/firebase")).getFirebaseAuth();
      if (!isEmailVerified(auth.currentUser)) {
        router.replace(
          `/verify-email?email=${encodeURIComponent(email.trim())}`
        );
      } else {
        router.replace("/choose-role");
      }
    } catch (err) {
      setError(friendlyAuthError(err));
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="w-6 h-6 border-2 border-purple-600 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="auth-card-shell">
      <div className="w-full max-w-sm space-y-6">
        <div className="text-center">
          <h1 className="text-2xl font-semibold tracking-tight">
            {t("signup.heading")}
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            {t("signup.subheading")}
          </p>
        </div>

        {error && (
          <div className="rounded-md bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="name" className="block text-sm font-medium mb-1">
              {t("signup.nameLabel")}
            </label>
            <input
              id="name"
              type="text"
              autoComplete="name"
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
            />
          </div>
          <div>
            <label htmlFor="email" className="block text-sm font-medium mb-1">
              {t("common.email")}
            </label>
            <input
              id="email"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
            />
          </div>
          <div>
            <label
              htmlFor="password"
              className="block text-sm font-medium mb-1"
            >
              {t("common.password")}
            </label>
            <input
              id="password"
              type="password"
              autoComplete="new-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
            />
            <p className="mt-1 text-xs text-gray-500">
              {t("signup.passwordHint")}
            </p>
          </div>
          <div>
            <label
              htmlFor="password-confirm"
              className="block text-sm font-medium mb-1"
            >
              {t("signup.passwordConfirmLabel")}
            </label>
            <input
              id="password-confirm"
              type="password"
              autoComplete="new-password"
              required
              value={passwordConfirm}
              onChange={(e) => setPasswordConfirm(e.target.value)}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
            />
          </div>
          <button
            type="submit"
            disabled={submitting}
            className="w-full rounded-md bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50"
          >
            {submitting ? t("signup.submitting") : t("signup.submit")}
          </button>
        </form>

        <p className="text-center text-sm text-gray-500">
          {t("signup.haveAccount")}{" "}
          <Link href="/login" className="text-purple-600 hover:underline">
            {t("signup.signInLink")}
          </Link>
        </p>
      </div>
    </div>
  );
}
