// Pilotlight (self-hosted GrowthBook) feature-flag reader for the browser.
//
// The agent-workforce org view is gated behind the Pilotlight feature flag
// `scheduler.agent-workforce` (product: scheduler, audience: internal, default
// OFF). Pilotlight is the MANAGED master switch — toggling/targeting happens in
// Pilotlight, not in code.
//
// This reader is deliberately dependency-free and FAIL-SAFE: it fetches the
// GrowthBook SDK feature payload over plain `fetch` and evaluates the single
// `scheduler.agent-workforce` flag for a given `orgId`. It returns:
//   - boolean — the flag's evaluated on/off for this orgId, when Pilotlight is
//     configured and reachable;
//   - null    — when Pilotlight is not configured or unreachable, so the caller
//     can apply its own default (the org view defaults ON for internal staff
//     and OFF for everyone else).
//
// It never throws. Because the caller already blocks non-internal users before
// calling this, a wrong answer here can only affect INTERNAL visibility (never
// leak the feature to customers).

export const AGENT_WORKFORCE_FLAG = "scheduler.agent-workforce";

// The COMPLETE GrowthBook features URL (e.g.
// https://pilotlight.scheduler-systems.com/api/api/features/<sdk-client-key>).
// Supplying the full URL avoids host/base-path ambiguity between environments.
function featuresUrl(): string | null {
  return process.env.NEXT_PUBLIC_PILOTLIGHT_FEATURES_URL?.trim() || null;
}

// Minimal GrowthBook payload shapes (only what we read).
interface GBRule {
  condition?: Record<string, unknown>;
  force?: unknown;
}
interface GBFeature {
  defaultValue?: unknown;
  rules?: GBRule[];
}
interface GBPayload {
  features?: Record<string, GBFeature>;
  savedGroups?: Record<string, unknown[]>;
}

function truthy(v: unknown): boolean {
  return v === true || v === 1 || v === "true" || v === "1";
}

// matchesOrg evaluates a GrowthBook rule condition against a single attribute,
// supporting the operators an internal-audience flag uses: a bare value, $eq,
// $in (inline list), and $inGroup / $in via a savedGroups id.
function matchesOrg(
  condition: Record<string, unknown> | undefined,
  orgId: string,
  savedGroups: Record<string, unknown[]>,
): boolean {
  if (!condition) return true; // no condition → rule applies to everyone
  const c = condition["orgId"];
  if (c === undefined) return false; // a condition on some other attribute → treat as no-match
  if (typeof c === "string") return c === orgId;
  if (c && typeof c === "object") {
    const op = c as Record<string, unknown>;
    if (typeof op["$eq"] === "string") return op["$eq"] === orgId;
    if (Array.isArray(op["$in"])) return (op["$in"] as unknown[]).includes(orgId);
    for (const key of ["$inGroup", "$in"] as const) {
      const ref = op[key];
      if (typeof ref === "string" && Array.isArray(savedGroups[ref])) {
        return savedGroups[ref].includes(orgId);
      }
    }
  }
  return false;
}

// evaluateFlag returns ANY Pilotlight flag's on/off for `orgId`, or null when
// Pilotlight is not configured / unreachable / malformed. Never throws.
// (Generalized from the agent-workforce-only reader so the same fail-safe logic
// gates every internal-audience feature flag.)
export async function evaluateFlag(
  flagKey: string,
  orgId: string,
  init?: { signal?: AbortSignal; fetchImpl?: typeof fetch },
): Promise<boolean | null> {
  const url = featuresUrl();
  if (!url) return null;
  const doFetch = init?.fetchImpl ?? (typeof fetch !== "undefined" ? fetch : null);
  if (!doFetch) return null;
  try {
    const res = await doFetch(url, { signal: init?.signal });
    if (!res.ok) return null;
    const payload = (await res.json()) as GBPayload;
    const feature = payload.features?.[flagKey];
    if (!feature) return null;
    const savedGroups = payload.savedGroups ?? {};
    let value = truthy(feature.defaultValue);
    for (const rule of feature.rules ?? []) {
      if (rule.force === undefined) continue;
      if (matchesOrg(rule.condition, orgId, savedGroups)) {
        value = truthy(rule.force);
      }
    }
    return value;
  } catch {
    return null; // fail-safe — caller applies its default
  }
}

// Back-compat wrapper for the org-view gate.
export function evaluateAgentWorkforceFlag(
  orgId: string,
  init?: { signal?: AbortSignal; fetchImpl?: typeof fetch },
): Promise<boolean | null> {
  return evaluateFlag(AGENT_WORKFORCE_FLAG, orgId, init);
}
