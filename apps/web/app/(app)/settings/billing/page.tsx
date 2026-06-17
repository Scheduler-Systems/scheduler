"use client";

import { useState } from "react";
import Link from "next/link";
import { useAuth } from "@/lib/auth-context";
import { useBilling } from "@/lib/billing-context";
import { openManagementPortal, startSeatBandCheckout } from "@/lib/billing/purchase";
import { useI18n } from "@/lib/i18n-context";
import { PaywallModal } from "@/components/paywall/paywall-modal";
import type { SeatBand } from "@/lib/billing/seat-bands";
import type { Tier } from "@/lib/billing/entitlements";

/**
 * Billing settings page — wire-through for entitlements + purchase + portal.
 *
 * Reads the current tier from the shared `BillingProvider` (which in turn
 * calls `fetchCustomerInfo` → `parseEntitlements` and exposes an error state
 * when the cloud function is unreachable). Renders:
 *   - Current tier name as the page heading.
 *   - Tier limits card: stations, users, builds/month — shown as capacity
 *     indicators. Since P1-5 does not include a `getMonthlyBuildCount`
 *     utility, we render static limits only.
 *   - "Manage subscription" → `openManagementPortal(uid)` then navigates.
 *   - "Upgrade plan" → opens the PaywallModal.
 *
 * Enforcement gates (P1-4) are intentionally not wired here; this page is
 * purely informational + redirect.
 */

// Product-defined monthly build limit per tier. The free tier is capped at
// 5 builds/month (see `paywall.triggerBuild`); paid tiers are unlimited.
const BUILDS_PER_MONTH: Record<Tier, number | null> = {
  free: 5,
  essentials: null,
  pro: null,
  enterprise: null,
};

// Read-back tier display: the free tier uses the localized "Free" string; paid
// read-back buckets (essentials/pro/enterprise) come from `entitlements.tierDisplayName`
// (set by parseEntitlements). The paywall itself is now seat-band based and no
// longer carries per-tier display keys, so we no longer map every Tier to an
// i18n key here.

interface LimitRowProps {
  label: string;
  limit: number | null;
  unlimitedLabel: string;
}

/**
 * Render a single limit row. With no live usage data available in P1-5 we
 * show the limit as a full-capacity bar — a placeholder that becomes
 * meaningful once usage metrics land (P3/P4 work items).
 */
function LimitRow({ label, limit, unlimitedLabel }: LimitRowProps) {
  const display = limit === null || limit >= 999 ? unlimitedLabel : String(limit);
  return (
    <div>
      <div className="flex items-baseline justify-between text-sm">
        <span className="text-gray-700 font-medium">{label}</span>
        <span className="text-gray-900 font-semibold">{display}</span>
      </div>
      <div className="mt-1 h-1.5 w-full rounded-full bg-gray-100 overflow-hidden">
        <div className="h-full bg-purple-600" style={{ width: "100%" }} />
      </div>
    </div>
  );
}

export default function BillingSettingsPage() {
  const { user } = useAuth();
  const { entitlements, loading, error } = useBilling();
  const { t } = useI18n();

  const [paywallOpen, setPaywallOpen] = useState(false);
  const [managingSubscription, setManagingSubscription] = useState(false);
  const [portalError, setPortalError] = useState<string | null>(null);
  const [purchaseError, setPurchaseError] = useState<string | null>(null);

  // Wire the paywall's seat-band selection to the RevenueCat HOSTED checkout.
  // startSeatBandCheckout never throws — it resolves to success / error and
  // redirects the tab to the band's the hosted-checkout page (the real charge happens
  // there). On a successful redirect issue the browser navigates away; the
  // BillingProvider re-reads entitlements when the user returns.
  async function handleSelectBand(band: SeatBand) {
    if (!user) return;
    setPurchaseError(null);
    // RevenueCat customer is keyed by Firebase uid (matches the Flutter app and
    // the getRevenueCatCustomerInfo read-back) — NOT email.
    const result = await startSeatBandCheckout(band, user.uid);
    if (result.status === "success") {
      setPaywallOpen(false);
      // Redirect already issued by startSeatBandCheckout; nothing more to do.
    } else if (result.status === "error") {
      setPurchaseError(result.message ?? "Purchase could not be completed.");
    }
  }

  // Free tier shows the localized "Free" label; paid read-back buckets use the
  // display name computed by parseEntitlements.
  const tierDisplayName =
    entitlements.tier === "free" ? t("paywall.tierFree") : entitlements.tierDisplayName;
  const buildsLimit = BUILDS_PER_MONTH[entitlements.tier] ?? null;

  async function handleManageSubscription() {
    if (!user?.uid) return;
    setManagingSubscription(true);
    setPortalError(null);
    try {
      const url = await openManagementPortal(user.uid);
      if (typeof window !== "undefined") {
        window.location.assign(url);
      }
    } catch (err) {
      setPortalError(err instanceof Error ? err.message : String(err));
      setManagingSubscription(false);
    }
  }

  if (loading) {
    return (
      <div className="space-y-6 max-w-2xl">
        <div className="flex items-center gap-2">
          <Link
            href="/settings"
            className="text-sm text-purple-600 hover:underline"
          >
            ← {t("settings.heading")}
          </Link>
        </div>
        <div className="flex items-center justify-center py-12" data-testid="billing-loading">
          <div className="w-6 h-6 border-2 border-purple-600 border-t-transparent rounded-full animate-spin" />
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-2xl">
      <div>
        <Link
          href="/settings"
          className="text-sm text-purple-600 hover:underline"
        >
          ← {t("settings.heading")}
        </Link>
        <h1 className="mt-2 text-2xl font-semibold text-gray-900">
          {tierDisplayName}
        </h1>
        <p className="text-sm text-gray-500 mt-1">{t("billing.pageTitle")}</p>
      </div>

      {error && (
        <div
          role="alert"
          className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800"
          data-testid="billing-error-banner"
        >
          {t("billing.errorLoad")}
        </div>
      )}

      {/* Current plan card */}
      <div
        className="rounded-xl border border-gray-200 bg-white p-5"
        data-testid="billing-plan-card"
      >
        <p className="text-xs font-semibold uppercase tracking-wider text-gray-400">
          {t("billing.currentPlan")}
        </p>
        <p className="mt-1 text-lg font-semibold text-gray-900">
          {tierDisplayName}
        </p>
      </div>

      {/* Limits card */}
      <div
        className="rounded-xl border border-gray-200 bg-white p-5 space-y-4"
        data-testid="billing-limits-card"
      >
        <p className="text-xs font-semibold uppercase tracking-wider text-gray-400">
          {t("billing.limits")}
        </p>
        <LimitRow
          label={t("billing.limitStations")}
          limit={entitlements.stationLimit}
          unlimitedLabel={t("paywall.stationsUnlimited")}
        />
        <LimitRow
          label={t("billing.limitUsers")}
          limit={entitlements.userLimit}
          unlimitedLabel={t("paywall.stationsUnlimited")}
        />
        <LimitRow
          label={t("billing.limitBuilds")}
          limit={buildsLimit}
          unlimitedLabel={t("paywall.buildsUnlimited")}
        />
      </div>

      {portalError && (
        <div
          role="alert"
          className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800"
          data-testid="billing-portal-error"
        >
          {portalError}
        </div>
      )}

      {/* Actions */}
      <div className="flex flex-col sm:flex-row gap-3">
        <button
          type="button"
          onClick={handleManageSubscription}
          disabled={managingSubscription || !user?.uid}
          className="flex-1 rounded-md border border-purple-600 bg-white px-4 py-2 text-sm font-medium text-purple-700 hover:bg-purple-50 focus:outline-none focus:ring-2 focus:ring-purple-500 disabled:opacity-60 disabled:cursor-not-allowed"
          data-testid="billing-manage-subscription"
        >
          {t("billing.manageSubscription")}
        </button>
        <button
          type="button"
          onClick={() => setPaywallOpen(true)}
          className="flex-1 rounded-md bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700 focus:outline-none focus:ring-2 focus:ring-purple-500"
          data-testid="billing-upgrade-plan"
        >
          {t("billing.upgradePlan")}
        </button>
      </div>

      {purchaseError && (
        <div
          className="rounded-md bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700"
          data-testid="billing-purchase-error"
        >
          {purchaseError}
        </div>
      )}

      <PaywallModal
        open={paywallOpen}
        onClose={() => setPaywallOpen(false)}
        onSelectBand={handleSelectBand}
        trigger="user"
      />
    </div>
  );
}
