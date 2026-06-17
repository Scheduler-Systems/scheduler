"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { upsertUserRole } from "@/lib/firestore-write";
import { friendlyAuthError } from "@/lib/auth-validation";
import type { RoleStruct } from "@/lib/types";

// Mirrors the Flutter ChooseRoleWidget: a dedicated post-verification screen
// where the user picks Manager or Employee (Flutter's two-role model). Manager
// maps to the employer role struct; Employee to the worker struct.
const MANAGER: RoleStruct = { is_creator: true, is_admin: true, is_worker: false };
const EMPLOYEE: RoleStruct = { is_creator: false, is_admin: false, is_worker: true };

export default function ChooseRolePage() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const [submitting, setSubmitting] = useState<"manager" | "employee" | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [user, loading, router]);

  async function choose(role: RoleStruct, which: "manager" | "employee") {
    if (!user) return;
    setError("");
    setSubmitting(which);
    try {
      await upsertUserRole(user.uid, user.email ?? "", role);
      // Name is collected next (the get-name / onboarding step), matching Flutter.
      router.replace("/onboarding");
    } catch (err) {
      setError(friendlyAuthError(err));
      setSubmitting(null);
    }
  }

  if (loading || !user) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="w-6 h-6 border-2 border-purple-600 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="min-h-screen flex flex-col">
      {/* Curved light-purple header (Flutter #F2E1FF, rounded bottom). */}
      <div
        className="bg-[#F2E1FF] rounded-b-[40px] px-6 pt-16 pb-12 text-center"
        style={{ minHeight: "45vh" }}
      >
        <h1 className="text-2xl font-bold tracking-tight text-gray-900">
          Choose Role
        </h1>
        <p className="mt-3 text-sm text-gray-700 max-w-sm mx-auto tracking-wide">
          Choose your Role, so that we prepare what&apos;s best for you.
        </p>
        <div className="mt-8 flex items-center justify-center">
          <div className="w-40 h-40 rounded-full bg-purple-600/10 flex items-center justify-center">
            <svg viewBox="0 0 24 24" className="w-20 h-20 text-purple-600" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path strokeLinecap="round" strokeLinejoin="round" d="M15 19.128a9.38 9.38 0 0 0 2.625.372 9.337 9.337 0 0 0 4.121-.952 4.125 4.125 0 0 0-7.533-2.493M15 19.128v-.003c0-1.113-.285-2.16-.786-3.07M15 19.128v.106A12.318 12.318 0 0 1 8.624 21c-2.331 0-4.512-.645-6.374-1.766l-.001-.109a6.375 6.375 0 0 1 11.964-3.07M12 6.375a3.375 3.375 0 1 1-6.75 0 3.375 3.375 0 0 1 6.75 0Zm8.25 2.25a2.625 2.625 0 1 1-5.25 0 2.625 2.625 0 0 1 5.25 0Z" />
            </svg>
          </div>
        </div>
      </div>

      <div className="flex-1 px-6 py-8 flex flex-col justify-center gap-4 max-w-md w-full mx-auto">
        {error && (
          <div className="rounded-md bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}
        <button
          type="button"
          disabled={submitting !== null}
          onClick={() => choose(MANAGER, "manager")}
          className="w-full h-[54px] rounded-lg bg-purple-600 text-white font-bold hover:bg-purple-700 disabled:opacity-50 transition"
        >
          {submitting === "manager" ? "…" : "Log In as Manager"}
        </button>
        <button
          type="button"
          disabled={submitting !== null}
          onClick={() => choose(EMPLOYEE, "employee")}
          className="w-full h-[54px] rounded-lg bg-[#F551C9] text-white font-bold hover:brightness-95 disabled:opacity-50 transition"
        >
          {submitting === "employee" ? "…" : "Log In as Employee"}
        </button>
      </div>
    </div>
  );
}
