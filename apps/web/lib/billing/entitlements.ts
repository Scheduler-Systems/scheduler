/**
 * Billing entitlements — OPEN-SOURCE STUB (BYO billing).
 *
 * The open-source build ships NO real billing logic. Every signed-in user is
 * treated as the free tier and nothing is metered. The exported types and
 * function signatures are preserved so the rest of the app type-checks and
 * runs unchanged.
 *
 * To self-host with real billing, replace this module with an implementation
 * that maps your provider's entitlement IDs to tiers/limits (RevenueCat,
 * Stripe, etc.). The hosted Scheduler Cloud's real implementation — including
 * the verified RevenueCat product-ID -> tier/seat mapping — lives in a private
 * repository and is NOT included here.
 */

export type Tier = "free" | "essentials" | "pro" | "enterprise";

export interface EntitlementDetail {
  id: string;
  expiresDate: string | null;
  productId: string | null;
  userLimit: number | null;
}

export interface Entitlements {
  isActive: boolean;
  tier: Tier;
  userLimit: number;
  stationLimit: number;
  entitlements: string[];
  tierDisplayName: string;
}

/** Default free-tier entitlements — the only tier the OSS build grants. */
export const FREE_TIER: Entitlements = {
  isActive: false,
  tier: "free",
  userLimit: 3,
  stationLimit: 1,
  entitlements: [],
  tierDisplayName: "Free",
};

const TIER_DISPLAY_NAMES: Record<Tier, string> = {
  free: "Free",
  essentials: "Essentials",
  pro: "Pro",
  enterprise: "Enterprise",
};

/**
 * STUB: the open-source build does not map provider entitlement IDs.
 * Always returns the free-tier user limit. Override in your own billing impl.
 */
export function deriveUserLimit(_entitlementId: string): number {
  return FREE_TIER.userLimit;
}

/**
 * STUB: the open-source build treats everyone as free. Override in your own
 * billing impl to map provider entitlement IDs to tiers.
 */
export function deriveTier(_entitlements: string[]): Tier {
  return "free";
}

/** Station/board limit per tier — product-defined. */
export function stationLimitForTier(tier: Tier): number {
  switch (tier) {
    case "enterprise":
      return 999;
    case "pro":
      return 5;
    case "essentials":
      return 3;
    case "free":
    default:
      return 1;
  }
}

/**
 * STUB parser: the open-source build ignores any provider payload and always
 * resolves to the free tier. Override in your own billing impl. `_now` is kept
 * for signature parity with real implementations that check expiry.
 */
export function parseEntitlements(_response: unknown, _now: Date = new Date()): Entitlements {
  void TIER_DISPLAY_NAMES;
  return { ...FREE_TIER };
}
