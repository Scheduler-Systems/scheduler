"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { upsertUserProfile } from "@/lib/firestore-write";
import { friendlyAuthError } from "@/lib/auth-validation";
import { useI18n } from "@/lib/i18n-context";

export default function OnboardingPage() {
  const { user, loading } = useAuth();
  const { t } = useI18n();
  const router = useRouter();

  const [name, setName] = useState("");
  const [title, setTitle] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [user, loading, router]);

  useEffect(() => {
    if (user?.displayName && !name) setName(user.displayName);
  }, [user, name]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (!user) return;
    if (!name.trim()) {
      setError(t("onboarding.errorNameRequired"));
      return;
    }
    setSubmitting(true);
    try {
      // Role was set on the Choose-Role screen; this step only captures the
      // name (and optional title) and must not overwrite the role.
      await upsertUserProfile(user.uid, user.email ?? "", {
        display_name: name.trim(),
        title: title.trim(),
      });
      router.replace("/dashboard");
    } catch (err) {
      setError(friendlyAuthError(err));
    } finally {
      setSubmitting(false);
    }
  }

  if (loading || !user) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="w-6 h-6 border-2 border-purple-600 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="auth-card-shell">
      <div className="w-full max-w-md space-y-6">
        <div className="text-center">
          <h1 className="text-2xl font-semibold tracking-tight">
            {t("onboarding.heading")}
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            {t("onboarding.subheading")}
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
              {t("onboarding.displayNameLabel")}
            </label>
            <input
              id="name"
              type="text"
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
            />
          </div>

          <div>
            <label htmlFor="title" className="block text-sm font-medium mb-1">
              {t("onboarding.titleLabel")} <span className="text-gray-400">{t("onboarding.titleOptional")}</span>
            </label>
            <input
              id="title"
              type="text"
              placeholder={t("onboarding.titlePlaceholder")}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
            />
          </div>

          <button
            type="submit"
            disabled={submitting}
            className="w-full rounded-md bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50"
          >
            {submitting ? t("onboarding.submitting") : t("onboarding.submit")}
          </button>
        </form>
      </div>
    </div>
  );
}
