// BillingProvider — the open-core seam between the scheduling engine and any
// monetization backend.
//
// The OPEN-SOURCE build ships ONLY this no-op stub: every actor is the free
// tier, nothing is metered, no external billing API is contacted. The engine
// is fully functional unmetered.
//
// To self-host with real billing, implement this interface against your own
// provider (RevenueCat, Stripe, etc.) and pass it to
// `createSchedulerApi({ store, billing })`. The hosted Scheduler Cloud's
// implementation (RevenueCat seat-band catalog + entitlement sync + webhook)
// lives in a private repository and is NOT included here.
//
// Interface (BillingProvider):
//   getEntitlements(actor)  -> Promise<Entitlements>   // tier + active flags
//   getSeatLimit(actor)     -> Promise<number>         // max seats; Infinity = unlimited
//   isFeatureEnabled(actor, feature) -> Promise<boolean>
//   syncFromProvider(actor) -> Promise<void>           // optional: pull latest from billing backend
//
// Entitlements shape:
//   { tier: "free"|"<custom>", active: string[], seatLimit: number }

export const FREE_ENTITLEMENTS = Object.freeze({
  tier: "free",
  active: [],
  seatLimit: Infinity, // open-source build is unmetered
});

export function createNoopBilling() {
  return {
    async getEntitlements() {
      return { ...FREE_ENTITLEMENTS };
    },
    async getSeatLimit() {
      return Infinity;
    },
    async isFeatureEnabled() {
      // Open-source build: all features available, unmetered.
      return true;
    },
    async syncFromProvider() {
      // No external billing backend in the open-source build.
      return;
    },
  };
}

export default createNoopBilling;
