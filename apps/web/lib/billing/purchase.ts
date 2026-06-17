/**
 * Purchase orchestrator — OPEN-SOURCE STUB (BYO billing).
 *
 * The open-source build ships NO real purchase integration. The exported types
 * and function signatures are preserved so the paywall UI compiles and runs.
 *
 *   - `startSeatBandCheckout` redirects to the BYO hosted-checkout URL built by
 *     ./seat-bands (driven by NEXT_PUBLIC_CHECKOUT_BASE_URL). With no env set it
 *     redirects to a clearly non-functional placeholder.
 *   - `startPurchase` (Web SDK path) and `openManagementPortal` are no-ops that
 *     report "billing not configured" — implement against your own provider.
 *
 * The hosted Scheduler Cloud's real purchase flow (RevenueCat Web SDK +
 * management portal callable) lives in a private repository and is NOT here.
 */

import { hostedCheckoutUrl, type SeatBand } from "./seat-bands";

export type PurchaseStatus = "success" | "cancelled" | "error";

export interface PurchaseResult {
  status: PurchaseStatus;
  message?: string;
}

export interface PurchaseDeps {
  /** Injectable SDK loader (tests). Unused by the OSS stub. */
  loadSdk?: () => Promise<unknown>;
  /** Injectable management-URL callable (tests). Unused by the OSS stub. */
  managementUrlCallable?: () => Promise<{ data: unknown }>;
  /** Injectable redirect sink (tests). */
  redirect?: (url: string) => void;
}

function redirectTo(url: string): void {
  if (typeof window !== "undefined") window.location.assign(url);
}

/**
 * STUB: the OSS build has no Web SDK billing integration. Always reports that
 * billing is not configured. Override with your own provider integration.
 */
export async function startPurchase(
  _planId: string,
  _appUserId: string,
  _deps: PurchaseDeps = {},
): Promise<PurchaseResult> {
  return {
    status: "error",
    message: "Billing is not configured in this build (BYO billing).",
  };
}

/**
 * Redirect to the BYO hosted-checkout URL for a seat band. URL base is
 * configured via NEXT_PUBLIC_CHECKOUT_BASE_URL (see ./seat-bands).
 */
export async function startSeatBandCheckout(
  band: SeatBand,
  appUserId: string,
  deps: Pick<PurchaseDeps, "redirect"> = {},
): Promise<PurchaseResult> {
  if (typeof window === "undefined") {
    return { status: "error", message: "Purchases are only available in the browser." };
  }
  if (!band || typeof band.webOfferId !== "string") {
    return { status: "error", message: "Invalid plan selected." };
  }
  if (!appUserId || typeof appUserId !== "string") {
    return { status: "error", message: "You must be signed in to purchase." };
  }
  const redirect = deps.redirect ?? redirectTo;
  try {
    redirect(hostedCheckoutUrl(band.webOfferId, appUserId));
    return { status: "success" };
  } catch {
    return { status: "error", message: "Could not start checkout." };
  }
}

/**
 * STUB: the OSS build has no management portal. Throws so callers surface a
 * clear "not configured" error. Override with your own provider integration.
 */
export async function openManagementPortal(
  uid: string,
  _deps: Pick<PurchaseDeps, "managementUrlCallable"> = {},
): Promise<string> {
  if (!uid || typeof uid !== "string") {
    throw new Error("openManagementPortal: uid is required");
  }
  throw new Error("openManagementPortal: billing is not configured in this build (BYO billing).");
}
