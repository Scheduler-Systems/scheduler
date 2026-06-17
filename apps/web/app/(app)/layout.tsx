"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { BillingProvider } from "@/lib/billing/billing-context";
import { Nav } from "@/components/nav";
import { IntercomBoot } from "@/components/intercom-boot";
import { FcmBoot } from "@/components/fcm-boot";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !user) router.replace("/phone-signin");
  }, [user, loading, router]);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="w-6 h-6 border-2 border-purple-600 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (!user) return null;

  // BillingProvider sits inside the auth gate so the tier resolves against a
  // known-signed-in user — see `lib/billing/billing-context.tsx`. It wraps
  // the authed surface (Nav + page content) and the Intercom/FCM boots so
  // any child can call `useBilling()` to gate behavior.
  return (
    <BillingProvider>
      <div className="min-h-screen flex flex-col">
        <Nav />
        <main className="flex-1 container mx-auto px-4 py-6 max-w-6xl">{children}</main>
        <IntercomBoot />
        <FcmBoot />
      </div>
    </BillingProvider>
  );
}
