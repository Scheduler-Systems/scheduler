"use client";

import { useEffect, useState } from "react";

import { useAuth } from "@/lib/auth-context";
import { isInternalEmail, orgIdForEmail } from "./audience-tier";
import { evaluateFlag } from "./pilotlight";

// Flags for behavior INTRODUCED after the Flutter→web migration (no Flutter counterpart). During
// pilot each is gated to the INTERNAL audience tier via Pilotlight: default ON for Scheduler-Systems
// staff, OFF for paying customers — so post-migration additions ship dark to customers.
export const CSV_IMPORT_FLAG = "scheduler.csv-import";
export const LOCALE_SWITCHER_FLAG = "scheduler.locale-switcher";

// Flutter→web PARITY feature modules built in later rounds. Each is registered in Pilotlight's
// config-as-code seed script (scripts/seed-growthbook-flags.sh) as internal-only + default-OFF —
// mirroring scheduler.agent-workforce — so the partially-built module is visible to Scheduler-Systems
// staff for review but ships dark to paying customers until it is faithful and signed off. Wrap the
// new module's entry component in `useFeatureFlag(<FLAG>)` to gate it.
export const WEB_ONBOARDING_CAROUSEL_FLAG = "scheduler.web-onboarding-carousel";
export const WEB_EMPLOYEE_INVITE_FLAG = "scheduler.web-employee-invite";
export const WEB_NOTIFICATIONS_CENTER_FLAG = "scheduler.web-notifications-center";
export const WEB_GEMINI_AI_FLAG = "scheduler.web-gemini-ai";
export const WEB_WALKTHROUGHS_FLAG = "scheduler.web-walkthroughs";
export const WEB_CONFETTI_FLAG = "scheduler.web-confetti";

// Default visibility for INTERNAL users when Pilotlight isn't wired/reachable. Customers are never
// affected by this — the internal-tier check returns false for them regardless.
const DEFAULT_INTERNAL_ON = true;

// useFeatureFlag — self-contained internal-audience gate for any Pilotlight flag (no Provider to
// wire into the layout). Customers (non-internal email) ALWAYS get false, resolved SYNCHRONOUSLY so
// the feature never flashes for them. Internal staff get the Pilotlight value, or DEFAULT_INTERNAL_ON
// when Pilotlight is unconfigured/unreachable. A wrong async answer can only affect INTERNAL
// visibility — it can never leak a feature to a customer.
export function useFeatureFlag(flagKey: string): boolean {
  const { user } = useAuth();
  const email = user?.email ?? null;
  const internal = isInternalEmail(email);

  const [pilotlightFlag, setPilotlightFlag] = useState<boolean | null>(null);

  useEffect(() => {
    if (!internal) return; // customers never trigger a Pilotlight call
    const controller = new AbortController();
    let active = true;
    evaluateFlag(flagKey, orgIdForEmail(email), { signal: controller.signal })
      .then((v) => {
        if (active) setPilotlightFlag(v);
      })
      .catch(() => {
        if (active) setPilotlightFlag(null);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [email, internal, flagKey]);

  return internal ? pilotlightFlag ?? DEFAULT_INTERNAL_ON : false;
}
