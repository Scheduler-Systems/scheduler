"use client";

import { useEffect, useState } from "react";

import { useAuth } from "@/lib/auth-context";
import { isInternalEmail, orgIdForEmail } from "./audience-tier";
import { evaluateFlag } from "./pilotlight";

// Flutter→web PARITY feature modules, gated to the INTERNAL audience tier via Pilotlight:
// default ON for Scheduler-Systems staff, OFF for paying customers — they ship dark to
// customers until faithful and signed off. Wrap the entry component in `useFeatureFlag(<FLAG>)`.
// (Only flags actually wired to a feature are kept here — premature/dead flag constants were
// removed; add a new one only when its module is built and gated.)
export const WEB_EMPLOYEE_INVITE_FLAG = "scheduler.web-employee-invite";
export const WEB_NOTIFICATIONS_CENTER_FLAG = "scheduler.web-notifications-center";

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
