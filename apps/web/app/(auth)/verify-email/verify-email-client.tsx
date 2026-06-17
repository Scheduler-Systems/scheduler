"use client";

import { useState, useEffect, useRef } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/lib/auth-context";
import {
  isEmailVerified,
  emailVerificationRateLimitKey,
  canResendVerification,
  RESEND_COOLDOWN_MS,
} from "@/lib/verify-email";
import { friendlyAuthError } from "@/lib/auth-validation";
import { useI18n } from "@/lib/i18n-context";

export default function VerifyEmailClient() {
  const { user, loading, sendVerificationEmail, reloadUser, signOut } =
    useAuth();
  const { t } = useI18n();
  const router = useRouter();
  const searchParams = useSearchParams();

  const emailFromQuery = searchParams.get("email") ?? "";

  const [resending, setResending] = useState(false);
  const [resendMsg, setResendMsg] = useState<string | null>(null);
  const [resendSuccess, setResendSuccess] = useState(false);
  const [cooldownRemaining, setCooldownRemaining] = useState(0);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Resolve the displayed email: prefer live user, then query param
  const displayEmail = user?.email ?? emailFromQuery;

  // If already verified, go straight to onboarding
  useEffect(() => {
    if (!loading && user && isEmailVerified(user)) {
      router.replace("/choose-role");
    }
  }, [user, loading, router]);

  // Poll Firebase every 5 s to auto-advance once verified
  useEffect(() => {
    if (!user) return;
    pollRef.current = setInterval(async () => {
      await reloadUser();
    }, 5000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [user, reloadUser]);

  // Tick down cooldown counter
  useEffect(() => {
    if (cooldownRemaining <= 0) return;
    const id = setInterval(() => {
      setCooldownRemaining((prev) => Math.max(0, prev - 1));
    }, 1000);
    return () => clearInterval(id);
  }, [cooldownRemaining]);

  async function handleResend() {
    if (!user) return;
    const key = emailVerificationRateLimitKey(user.email ?? "");
    const lastSent = localStorage.getItem(key);
    if (!canResendVerification(lastSent ? Number(lastSent) : null)) {
      const secs = Math.ceil(
        (RESEND_COOLDOWN_MS - (Date.now() - Number(lastSent))) / 1000
      );
      setResendSuccess(false);
      setResendMsg(t("verifyEmail.rateLimitMessage", { seconds: secs }));
      return;
    }

    setResending(true);
    setResendMsg(null);
    setResendSuccess(false);
    try {
      await sendVerificationEmail();
      localStorage.setItem(key, String(Date.now()));
      setCooldownRemaining(Math.ceil(RESEND_COOLDOWN_MS / 1000));
      setResendSuccess(true);
      setResendMsg(t("verifyEmail.sentMessage"));
    } catch (err) {
      setResendSuccess(false);
      setResendMsg(friendlyAuthError(err));
    } finally {
      setResending(false);
    }
  }

  async function handleSkip() {
    router.replace("/choose-role");
  }

  async function handleSignOut() {
    await signOut();
    router.replace("/login");
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
        {/* Icon */}
        <div className="flex justify-center">
          <div className="w-16 h-16 rounded-full bg-purple-50 flex items-center justify-center">
            <svg
              className="w-8 h-8 text-purple-600"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={1.5}
                d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"
              />
            </svg>
          </div>
        </div>

        <div className="text-center space-y-2">
          <h1 className="text-2xl font-semibold tracking-tight">
            {t("verifyEmail.heading")}
          </h1>
          <p className="text-sm text-gray-500">
            {displayEmail
              ? (() => {
                  const msg = t("verifyEmail.subheadingWithEmail", {
                    email: displayEmail,
                  });
                  const [before, after = ""] = msg.split(displayEmail);
                  return (
                    <>
                      {before}
                      <span className="font-medium text-gray-700">
                        {displayEmail}
                      </span>
                      {after}
                    </>
                  );
                })()
              : t("verifyEmail.subheadingNoEmail")}
          </p>
        </div>

        {resendMsg && (
          <div
            className={`rounded-md px-4 py-3 text-sm ${
              resendSuccess
                ? "bg-green-50 border border-green-200 text-green-700"
                : "bg-red-50 border border-red-200 text-red-700"
            }`}
          >
            {resendMsg}
          </div>
        )}

        <div className="space-y-3">
          <button
            type="button"
            onClick={handleResend}
            disabled={resending || cooldownRemaining > 0}
            className="w-full rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
          >
            {resending
              ? t("verifyEmail.resending")
              : cooldownRemaining > 0
                ? t("verifyEmail.resendIn", { seconds: cooldownRemaining })
                : t("verifyEmail.resend")}
          </button>

          <button
            type="button"
            onClick={handleSkip}
            className="w-full rounded-md bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700"
          >
            {t("verifyEmail.continueAnyway")}
          </button>
        </div>

        <div className="text-center space-y-1">
          <p className="text-xs text-gray-500">
            {t("verifyEmail.wrongEmailPrefix")}{" "}
            <button
              type="button"
              onClick={handleSignOut}
              className="text-purple-600 underline hover:no-underline"
            >
              {t("common.signOut")}
            </button>{" "}
            {t("verifyEmail.wrongEmailSuffix")}
          </p>
          <p className="text-xs text-gray-500">
            {t("verifyEmail.alreadyVerifiedPrefix")}{" "}
            <Link
              href="/login"
              className="text-purple-600 underline hover:no-underline"
            >
              {t("verifyEmail.signInLink")}
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
