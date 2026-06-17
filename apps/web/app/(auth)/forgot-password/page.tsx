"use client";

import { useState } from "react";
import Link from "next/link";
import { useAuth } from "@/lib/auth-context";
import { isValidEmail, friendlyAuthError } from "@/lib/auth-validation";
import { useI18n } from "@/lib/i18n-context";

export default function ForgotPasswordPage() {
  const { sendPasswordReset } = useAuth();
  const { t } = useI18n();
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (!isValidEmail(email)) {
      setError(t("forgotPassword.errorEmailInvalid"));
      return;
    }
    setSubmitting(true);
    try {
      await sendPasswordReset(email.trim());
      setSent(true);
    } catch (err) {
      setError(friendlyAuthError(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="auth-card-shell">
      <div className="w-full max-w-sm space-y-6">
        <div className="text-center">
          <h1 className="text-2xl font-semibold tracking-tight">
            {t("forgotPassword.heading")}
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            {t("forgotPassword.subheading")}
          </p>
        </div>

        {sent ? (
          <div className="space-y-4">
            <div className="rounded-md bg-green-50 border border-green-200 px-4 py-3 text-sm text-green-800">
              {t("forgotPassword.sentMessage", { email })}
            </div>
            <Link
              href="/login"
              className="block text-center text-sm text-purple-600 hover:underline"
            >
              {t("forgotPassword.backToSignIn")}
            </Link>
          </div>
        ) : (
          <>
            {error && (
              <div className="rounded-md bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
                {error}
              </div>
            )}
            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label
                  htmlFor="email"
                  className="block text-sm font-medium mb-1"
                >
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
              <button
                type="submit"
                disabled={submitting}
                className="w-full rounded-md bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50"
              >
                {submitting
                  ? t("forgotPassword.submitting")
                  : t("forgotPassword.submit")}
              </button>
            </form>
            <Link
              href="/login"
              className="block text-center text-sm text-purple-600 hover:underline"
            >
              {t("forgotPassword.backToSignIn")}
            </Link>
          </>
        )}
      </div>
    </div>
  );
}
