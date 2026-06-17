// Public scheduling engine entrypoint (billing-free).
//
// OPEN-CORE NOTE
// --------------
// This is the open-source scheduling engine. It deliberately contains NO
// billing / entitlement / RevenueCat logic. Monetization is a separate,
// pluggable concern:
//
//   - In the open-source build, billing is a no-op stub (./billing-stub.mjs):
//     every caller is treated as the free tier and the engine runs unmetered.
//   - To self-host with real billing, implement the BillingProvider interface
//     (see ./billing-stub.mjs) against your own RevenueCat / Stripe / etc.
//     account and pass it in via `createSchedulerApi({ store, billing })`.
//
// The hosted Scheduler Cloud uses a private BillingProvider implementation
// (RevenueCat seat-band catalog + entitlement sync). It is not part of this
// repository (see the private scheduler-cloud control-plane).

import {
  createSchedulerApi,
  createMemoryStore,
  resolveStore,
  createMemoryRateLimit,
} from "./app.mjs";
import { createNoopBilling } from "./billing-stub.mjs";

const store = createMemoryStore();

// Billing defaults to the no-op stub. Supply your own BillingProvider to
// meter/gate; out of the box the engine is unmetered (free tier for all).
const billing = createNoopBilling();

const api = createSchedulerApi({ store, billing });

export const app = api;
export const functions = {
  schedulerApi: api,
  store,
};

export { createSchedulerApi, createMemoryStore, resolveStore, createMemoryRateLimit };
export default api;
