"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useAuth } from "./auth-context";
import { fetchCustomerInfo } from "./billing/client";
import { FREE_TIER, type Entitlements } from "./billing/entitlements";

const DEFAULT_REFETCH_INTERVAL_MS = 5 * 60 * 1000; // 5 minutes

interface BillingContextValue {
  entitlements: Entitlements;
  loading: boolean;
  error: Error | null;
  refetch: () => Promise<void>;
}

const BillingContext = createContext<BillingContextValue | null>(null);

export interface BillingProviderProps {
  children: React.ReactNode;
  /**
   * Swap the fetcher for tests. Defaults to the real Firebase callable.
   */
  fetcher?: () => Promise<Entitlements>;
  /** Override refetch cadence. Defaults to 5 min. */
  refetchIntervalMs?: number;
}

export function BillingProvider({
  children,
  fetcher,
  refetchIntervalMs = DEFAULT_REFETCH_INTERVAL_MS,
}: BillingProviderProps) {
  const { user } = useAuth();
  const [entitlements, setEntitlements] = useState<Entitlements>(FREE_TIER);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  // Track in-flight work so we don't thrash state on rapid auth changes or
  // tab-focus events. `activeToken` is the monotonically-increasing request
  // number — we only apply a result if it still matches the latest request.
  const tokenRef = useRef(0);
  const userIdRef = useRef<string | null>(null);
  userIdRef.current = user?.uid ?? null;

  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const doFetch = useCallback(async () => {
    const uid = userIdRef.current;
    if (!uid) {
      // Signed out — reset to free tier synchronously, no network.
      setEntitlements(FREE_TIER);
      setError(null);
      setLoading(false);
      return;
    }
    const myToken = ++tokenRef.current;
    setLoading(true);
    setError(null);
    try {
      const result = fetcherRef.current
        ? await fetcherRef.current()
        : await fetchCustomerInfo();
      if (tokenRef.current !== myToken) return; // stale
      setEntitlements(result);
    } catch (err) {
      if (tokenRef.current !== myToken) return; // stale
      // Graceful fallback: free tier so the UI stays functional when billing is down.
      setEntitlements(FREE_TIER);
      setError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      if (tokenRef.current === myToken) setLoading(false);
    }
  }, []);

  // Trigger on sign-in / sign-out.
  useEffect(() => {
    void doFetch();
  }, [user?.uid, doFetch]);

  // Periodic refetch while the tab is focused AND the user is signed in.
  useEffect(() => {
    if (!user?.uid) return;
    if (typeof window === "undefined") return;

    let interval: ReturnType<typeof setInterval> | null = null;

    const start = () => {
      if (interval) return;
      interval = setInterval(() => {
        void doFetch();
      }, refetchIntervalMs);
    };
    const stop = () => {
      if (!interval) return;
      clearInterval(interval);
      interval = null;
    };

    const onVisibility = () => {
      if (document.visibilityState === "visible") start();
      else stop();
    };

    if (document.visibilityState === "visible") start();
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      stop();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [user?.uid, doFetch, refetchIntervalMs]);

  const value = useMemo<BillingContextValue>(
    () => ({
      entitlements,
      loading,
      error,
      refetch: doFetch,
    }),
    [entitlements, loading, error, doFetch],
  );

  return <BillingContext.Provider value={value}>{children}</BillingContext.Provider>;
}

export function useBilling(): BillingContextValue {
  const ctx = useContext(BillingContext);
  if (!ctx) throw new Error("useBilling must be used within BillingProvider");
  return ctx;
}
