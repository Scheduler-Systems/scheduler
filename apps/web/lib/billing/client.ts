/**
 * Billing client — OPEN-SOURCE STUB (BYO billing).
 *
 * The open-source build does NOT call any billing provider. `fetchCustomerInfo`
 * always resolves to the free tier. Replace this module with your own client
 * (e.g. a RevenueCat callable) to enable real entitlements.
 *
 * The hosted Scheduler Cloud's real client lives in a private repository and is
 * NOT included here.
 */

import { FREE_TIER, type Entitlements } from "./entitlements";

export interface FetchOptions {
  /** Overall timeout per attempt (ms). Kept for signature parity. */
  timeoutMs?: number;
  /** Optional userId override. Kept for signature parity. */
  userId?: string;
  /** Injectable callable — used by tests. Ignored by the OSS stub. */
  callable?: (payload: { userId?: string }) => Promise<{ data: unknown }>;
}

/**
 * STUB: the OSS build has no billing provider, so this always returns the free
 * tier. A real implementation would call your provider and parse entitlements.
 */
export async function fetchCustomerInfo(_opts: FetchOptions = {}): Promise<Entitlements> {
  return { ...FREE_TIER };
}
