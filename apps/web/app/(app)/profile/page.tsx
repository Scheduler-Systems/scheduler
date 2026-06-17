"use client";

import { useState, useEffect, useCallback } from "react";
import { useAuth } from "@/lib/auth-context";
import { getUserProfile, type UserProfile } from "@/lib/firestore";
import { upsertUserProfile } from "@/lib/firestore-write";
import { friendlyAuthError } from "@/lib/auth-validation";
import { useI18n } from "@/lib/i18n-context";
import type { RoleStruct } from "@/lib/types";

type RoleKey = "worker" | "admin" | "creator";

// Accepts both the Flutter canonical string ("employer" | "employee") and
// the legacy Next.js RoleStruct object written before PR #1748.
function roleKey(role: UserProfile["role"] | undefined | null): RoleKey {
  if (!role) return "worker";
  if (typeof role === "string") {
    return role === "employer" ? "admin" : "worker";
  }
  if (role.is_creator) return "creator";
  if (role.is_admin) return "admin";
  return "worker";
}

function toRoleStruct(role: RoleKey): RoleStruct {
  return {
    is_creator: role === "creator",
    is_admin: role === "admin" || role === "creator",
    is_worker: true,
  };
}

export default function ProfilePage() {
  const { user } = useAuth();
  const { t } = useI18n();
  const [loading, setLoading] = useState(true);
  const [name, setName] = useState("");
  const [title, setTitle] = useState("");
  const [role, setRole] = useState<RoleKey>("worker");
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!user) return;
    try {
      const p = await getUserProfile(user.uid);
      setName(p?.display_name ?? user.displayName ?? "");
      setTitle(p?.title ?? "");
      setRole(roleKey(p?.role));
    } finally {
      setLoading(false);
    }
  }, [user]);

  useEffect(() => {
    load();
  }, [load]);

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    if (!user) return;
    setSaving(true);
    setSaveMsg(null);
    try {
      await upsertUserProfile(user.uid, user.email ?? "", {
        display_name: name.trim(),
        title: title.trim(),
        role: toRoleStruct(role),
      });
      setSaveMsg(t("profile.savedMessage"));
    } catch (err) {
      setSaveMsg(friendlyAuthError(err));
    } finally {
      setSaving(false);
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
    <div className="space-y-6 max-w-md">
      <header>
        <h1 className="text-2xl font-semibold text-gray-900">{t("profile.heading")}</h1>
        <p className="text-sm text-gray-500">
          {t("profile.subheading", { email: user?.email ?? "" })}
        </p>
      </header>

      <form onSubmit={handleSave} className="space-y-4">
        <div>
          <label htmlFor="name" className="block text-sm font-medium mb-1">
            {t("profile.displayNameLabel")}
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
            {t("profile.titleLabel")} <span className="text-gray-400">{t("profile.titleOptional")}</span>
          </label>
          <input
            id="title"
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
          />
        </div>
        <div>
          <label htmlFor="role" className="block text-sm font-medium mb-1">
            {t("profile.roleLabel")}
          </label>
          <select
            id="role"
            value={role}
            onChange={(e) => setRole(e.target.value as RoleKey)}
            className="w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
          >
            <option value="worker">{t("profile.roleWorker")}</option>
            <option value="admin">{t("profile.roleAdmin")}</option>
            <option value="creator">{t("profile.roleCreator")}</option>
          </select>
        </div>
        <div className="flex items-center gap-3">
          <button
            type="submit"
            disabled={saving}
            className="rounded-md bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50"
          >
            {saving ? t("profile.saving") : t("profile.save")}
          </button>
          {saveMsg && <span className="text-sm text-gray-600">{saveMsg}</span>}
        </div>
      </form>
    </div>
  );
}
