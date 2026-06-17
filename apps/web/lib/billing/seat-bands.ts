/**
 * Seat-band offering catalog — OPEN-SOURCE STUB (BYO billing).
 *
 * The open-source build does NOT ship the live per-seat checkout catalog. The
 * band STRUCTURE and types are preserved so the paywall UI renders, but the
 * hosted-checkout URLs are placeholders read from a BYO env var. Wire your own
 * RevenueCat (or other) hosted-checkout base URLs to enable real purchases.
 *
 * The hosted Scheduler Cloud's real catalog — the verified per-seat
 * RevenueCat hosted-checkout offer ids and URLs — lives in a private
 * repository and is NOT included here.
 *
 * BYO config:
 *   NEXT_PUBLIC_CHECKOUT_BASE_URL  e.g. https://pay.example.com  (optional)
 * Each band's checkout URL is `${base}/${webOfferId}/${firebaseUid}`.
 */

/** The fixed per-user count bands. */
export type SeatBandId = 10 | 20 | 30 | 50 | 100;

/** Web hosted-checkout offer id for each band. */
export type WebOfferId =
  | "up-to-10-employees"
  | "up-to-20-employees"
  | "up-to-30-employees"
  | "up-to-50-employees"
  | "up-to-100-employees"
  | "offering-id-employee";

/** Mobile SDK offering id per band — cross-reference / parity only. */
export type MobileOfferId =
  | "offering-id-10-users"
  | "offering-id-20-users"
  | "offering-id-30-users"
  | "offering-id-50-users"
  | "offering-id-100-users"
  | "offering-id-employee";

export interface SeatBand {
  seats: SeatBandId;
  webOfferId: WebOfferId;
  mobileOfferId: MobileOfferId;
}

/** The ordered band catalog (smallest -> largest). */
export const SEAT_BANDS: readonly SeatBand[] = [
  { seats: 10, webOfferId: "up-to-10-employees", mobileOfferId: "offering-id-10-users" },
  { seats: 20, webOfferId: "up-to-20-employees", mobileOfferId: "offering-id-20-users" },
  { seats: 30, webOfferId: "up-to-30-employees", mobileOfferId: "offering-id-30-users" },
  { seats: 50, webOfferId: "up-to-50-employees", mobileOfferId: "offering-id-50-users" },
  { seats: 100, webOfferId: "up-to-100-employees", mobileOfferId: "offering-id-100-users" },
] as const;

/** The smallest band, used as the paywall's default selection. */
export const DEFAULT_SEAT_BAND: SeatBand = SEAT_BANDS[0];

/**
 * STUB hosted-checkout base URLs. The OSS build has NO real checkout endpoints;
 * supply your own via NEXT_PUBLIC_CHECKOUT_BASE_URL (BYO billing). With no env
 * set, these resolve to a clearly non-functional placeholder so a self-hoster
 * notices billing is unconfigured rather than silently charging nothing.
 */
const CHECKOUT_BASE =
  (typeof process !== "undefined" && process.env.NEXT_PUBLIC_CHECKOUT_BASE_URL) ||
  "https://checkout.invalid/byo-billing-unconfigured";

export const HOSTED_CHECKOUT_BASE_URL: Record<WebOfferId, string> = {
  "up-to-10-employees": `${CHECKOUT_BASE}/up-to-10-employees`,
  "up-to-20-employees": `${CHECKOUT_BASE}/up-to-20-employees`,
  "up-to-30-employees": `${CHECKOUT_BASE}/up-to-30-employees`,
  "up-to-50-employees": `${CHECKOUT_BASE}/up-to-50-employees`,
  "up-to-100-employees": `${CHECKOUT_BASE}/up-to-100-employees`,
  "offering-id-employee": `${CHECKOUT_BASE}/offering-id-employee`,
};

/** Map a desired seat count to the correct band (null => above top band). */
export function bandForSeatCount(seatCount: number): SeatBand | null {
  if (!Number.isFinite(seatCount) || seatCount <= 0) return DEFAULT_SEAT_BAND;
  for (const band of SEAT_BANDS) {
    if (seatCount <= band.seats) return band;
  }
  return null;
}

/** Look up a band by its exact seat cap. */
export function bandBySeats(seats: SeatBandId): SeatBand {
  const found = SEAT_BANDS.find((b) => b.seats === seats);
  return found ?? DEFAULT_SEAT_BAND;
}

/** Build the hosted-checkout URL for a band and auth uid (BYO base URL). */
export function hostedCheckoutUrl(webOfferId: WebOfferId, firebaseUid: string): string {
  if (!firebaseUid || typeof firebaseUid !== "string") {
    throw new Error("hostedCheckoutUrl: firebaseUid is required");
  }
  const base = HOSTED_CHECKOUT_BASE_URL[webOfferId] ?? HOSTED_CHECKOUT_BASE_URL["offering-id-employee"];
  return `${base}/${firebaseUid}`;
}
