"use client";

/**
 * P1-4 BillingProvider — lean tier/limits view the enforcement gates consume.
 *
 * This lives next to `entitlements.ts` (the parser) and `client.ts` (the
 * Firebase callable). The existing richer `lib/billing-context.tsx` exposes
 * the raw `Entitlements` object; this one projects down to the fields the UI
 * gates actually need:
 *
 *   { tier, limits: { maxStations, maxUsers, maxBuildsPerMonth }, loading, refresh }
 *
 * SSR-safe: never imports Firebase at module scope; the fetcher defaults to
 * the existing `fetchCustomerInfo()` which itself lazy-imports firebase/*.
 *
 * Error handling: any thrown fetch error collapses to `tier: "free"` (the
 * strictest gate) — we never leave the UI in an unknown state, and we never
 * re-throw, so gates can always call `useBilling()` without a try/catch.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useAuth } from "../auth-context";
import { fetchCustomerInfo } from "./client";
import { FREE_TIER, type Entitlements, type Tier } from "./entitlements";

/**
 * Per-tier product limits used by the enforcement gates. Sourced from the
 * Flutter app's tier tables (SMR-1720 billing PRD) and `entitlements.ts`
 * for stations. `maxUsers` / `maxBuildsPerMonth` aren't encoded in
 * `entitlements.ts` because that module is a pure RevenueCat parser — these
 * live here as product rules.
 */
export interface BillingLimits {
  maxStations: number;
  maxUsers: number;
  maxBuildsPerMonth: number;
}

const LIMITS_BY_TIER: Record<Tier, BillingLimits> = {
  free: { maxStations: 1, maxUsers: 3, maxBuildsPerMonth: 5 },
  essentials: {
    maxStations: 3,
    maxUsers: 20,
    maxBuildsPerMonth: Number.POSITIVE_INFINITY,
  },
  pro: {
    maxStations: 5,
    maxUsers: 50,
    maxBuildsPerMonth: Number.POSITIVE_INFINITY,
  },
  enterprise: {
    maxStations: Number.POSITIVE_INFINITY,
    maxUsers: Number.POSITIVE_INFINITY,
    maxBuildsPerMonth: Number.POSITIVE_INFINITY,
  },
};

export function limitsForTier(tier: Tier): BillingLimits {
  return LIMITS_BY_TIER[tier] ?? LIMITS_BY_TIER.free;
}

export interface BillingContextValue {
  tier: Tier;
  limits: BillingLimits;
  loading: boolean;
  refresh: () => Promise<void>;
}

const BillingContext = createContext<BillingContextValue | null>(null);

export interface BillingProviderProps {
  children: React.ReactNode;
  /** Swap the fetcher for tests. Defaults to the Firebase callable. */
  fetcher?: () => Promise<Entitlements>;
}

export function BillingProvider({ children, fetcher }: BillingProviderProps) {
  const { user } = useAuth();
  const [tier, setTier] = useState<Tier>("free");
  const [loading, setLoading] = useState(false);

  // Stale-result guard: only the most recent fetch wins. This matters when
  // auth flips between users or `refresh()` races with the sign-in effect.
  const tokenRef = useRef(0);
  const userIdRef = useRef<string | null>(null);
  userIdRef.current = user?.uid ?? null;
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const refresh = useCallback(async (): Promise<void> => {
    const uid = userIdRef.current;
    if (!uid) {
      setTier("free");
      setLoading(false);
      return;
    }
    const myToken = ++tokenRef.current;
    setLoading(true);
    try {
      const result = fetcherRef.current
        ? await fetcherRef.current()
        : await fetchCustomerInfo();
      if (tokenRef.current !== myToken) return;
      setTier(result.tier);
    } catch {
      // Strictest fallback: free tier when billing is unreachable. Tests and
      // production both rely on this — gates stay closed if we can't verify.
      if (tokenRef.current !== myToken) return;
      setTier(FREE_TIER.tier);
    } finally {
      if (tokenRef.current === myToken) setLoading(false);
    }
  }, []);

  // Fire on sign-in / sign-out.
  useEffect(() => {
    void refresh();
  }, [user?.uid, refresh]);

  const value = useMemo<BillingContextValue>(
    () => ({
      tier,
      limits: limitsForTier(tier),
      loading,
      refresh,
    }),
    [tier, loading, refresh],
  );

  return (
    <BillingContext.Provider value={value}>{children}</BillingContext.Provider>
  );
}

export function useBilling(): BillingContextValue {
  const ctx = useContext(BillingContext);
  if (!ctx) throw new Error("useBilling must be used within BillingProvider");
  return ctx;
}
