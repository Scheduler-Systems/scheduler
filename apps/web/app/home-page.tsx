"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";

// Root page matches the legacy Flutter web behavior: show a brief spinner
// while we wait for Firebase auth to resolve, then route to /dashboard
// (signed in) or /login (anonymous).
export default function HomePage() {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (loading) return;
    router.replace(user ? "/dashboard" : "/phone-signin");
  }, [user, loading, router]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div
        aria-label="Loading"
        className="w-6 h-6 border-2 border-purple-600 border-t-transparent rounded-full animate-spin"
      />
    </div>
  );
}
