"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import type { ConfirmationResult } from "firebase/auth";
import { useAuth } from "@/lib/auth-context";
import { friendlyAuthError } from "@/lib/auth-validation";
import { isEmailVerified } from "@/lib/verify-email";
import { getFirebaseAuth } from "@/lib/firebase";
import { useI18n } from "@/lib/i18n-context";

const RECAPTCHA_CONTAINER_ID = "recaptcha-phone-signin";

export default function PhoneSignInPage() {
  const { user, loading, startPhoneSignIn, signInWithGoogle } = useAuth();
  const { t } = useI18n();
  const router = useRouter();

  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [confirmation, setConfirmation] = useState<ConfirmationResult | null>(
    null,
  );
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!loading && user) router.replace("/dashboard");
  }, [user, loading, router]);

  async function handleGoogleSignIn() {
    setError("");
    setSubmitting(true);
    try {
      await signInWithGoogle();
      const current = getFirebaseAuth().currentUser;
      if (current && !isEmailVerified(current)) router.replace("/verify-email");
      else router.replace("/choose-role");
    } catch (err: unknown) {
      setError(friendlyAuthError(err));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleSendCode(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (!/^\+\d{7,15}$/.test(phone.trim())) {
      setError(t("phoneSignin.invalidPhone"));
      return;
    }
    setSubmitting(true);
    try {
      const result = await startPhoneSignIn(phone.trim(), RECAPTCHA_CONTAINER_ID);
      setConfirmation(result);
    } catch (err) {
      setError(friendlyAuthError(err));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleVerifyCode(e: React.FormEvent) {
    e.preventDefault();
    if (!confirmation) return;
    setError("");
    setSubmitting(true);
    try {
      await confirmation.confirm(code.trim());
      router.replace("/choose-role");
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
            {t("phoneSignin.heading")}
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            {t("phoneSignin.subheading")}
          </p>
        </div>

        {error && (
          <div className="rounded-md bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        {!confirmation ? (
          <form onSubmit={handleSendCode} className="space-y-4">
            <div>
              <label htmlFor="phone" className="block text-sm font-medium mb-1">
                {t("phoneSignin.phoneLabel")}
              </label>
              <input
                id="phone"
                type="tel"
                placeholder="+14155551234"
                required
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
              />
              <p className="mt-1 text-xs text-gray-500">
                {t("phoneSignin.phoneHint")}
              </p>
            </div>
            <button
              type="submit"
              disabled={submitting}
              className="w-full rounded-md bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50"
            >
              {submitting ? t("phoneSignin.sendingCode") : t("phoneSignin.sendCode")}
            </button>
          </form>
        ) : (
          <form onSubmit={handleVerifyCode} className="space-y-4">
            <div>
              <label htmlFor="code" className="block text-sm font-medium mb-1">
                {t("phoneSignin.codeLabel")}
              </label>
              <input
                id="code"
                type="text"
                inputMode="numeric"
                pattern="[0-9]{6}"
                required
                value={code}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
              />
            </div>
            <button
              type="submit"
              disabled={submitting}
              className="w-full rounded-md bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50"
            >
              {submitting ? t("phoneSignin.verifying") : t("phoneSignin.verify")}
            </button>
          </form>
        )}

        <div id={RECAPTCHA_CONTAINER_ID} />

        {/* Alternative sign-in methods — matches Flutter's phone-first entry,
            where phone is primary and Email/Google are offered below. */}
        {!confirmation && (
          <>
            <div className="relative">
              <div className="absolute inset-0 flex items-center">
                <div className="w-full border-t border-gray-200" />
              </div>
              <div className="relative flex justify-center text-xs text-gray-500 uppercase">
                <span className="bg-gray-50 px-2">{t("common.or")}</span>
              </div>
            </div>

            <Link
              href="/login"
              className="w-full flex items-center justify-center gap-2 rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
            >
              Continue with Email
            </Link>

            <button
              onClick={handleGoogleSignIn}
              disabled={submitting}
              className="w-full flex items-center justify-center gap-2 rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
            >
              <svg className="w-4 h-4" viewBox="0 0 24 24">
                <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" />
                <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
                <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" />
                <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" />
              </svg>
              {t("login.continueWithGoogle")}
            </button>

            <p className="text-center text-sm text-gray-500">
              {t("login.noAccount")}{" "}
              <Link href="/signup" className="text-purple-600 hover:underline">
                {t("login.createOne")}
              </Link>
            </p>
          </>
        )}
        <p className="text-center text-xs text-gray-500">
          {t("phoneSignin.recaptchaNote")}
        </p>
      </div>
    </div>
  );
}
