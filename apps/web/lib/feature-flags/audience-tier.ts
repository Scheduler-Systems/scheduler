// Audience-tier gating — the Scheduler mirror of gal-run's hierarchical
// audience model (see gal-shared core/audience-tier). Higher tiers inherit
// lower-tier access: internal > partners > public.
//
// The Scheduler app has no organization concept, so a user's tier is derived
// from their email: Scheduler-Systems staff map to the internal `orgId`
// "scheduler-systems" (which is a member of the Pilotlight `internal-orgs`
// saved group), everyone else is public. This is the source of truth for
// "are WE internal?" and gates the agent-workforce org view to internal staff
// only — paying customers never see it.

export type AudienceTier = "public" | "partners" | "internal";

// Higher rank = more privileged.
export const TIER_RANK: Record<AudienceTier, number> = {
  public: 0,
  partners: 1,
  internal: 2,
};

// meetsAudience returns true when userTier's rank >= the required tier's rank.
export function meetsAudience(
  userTier: AudienceTier,
  required: AudienceTier = "public",
): boolean {
  return TIER_RANK[userTier] >= TIER_RANK[required];
}

// The internal org slugs (lower-cased) that map to the internal audience tier.
// Mirrors the Pilotlight `internal-orgs` saved group; override at build time
// with NEXT_PUBLIC_INTERNAL_ORG_SLUGS (comma-separated).
const DEFAULT_INTERNAL_ORG_SLUGS = [
  "scheduler-systems",
  "gal-run",
  "stratuscloudlabs",
  "projectmasterlabs",
];

export function internalOrgSlugs(): Set<string> {
  const raw = process.env.NEXT_PUBLIC_INTERNAL_ORG_SLUGS;
  const list = raw
    ? raw.split(",").map((s) => s.trim().toLowerCase()).filter(Boolean)
    : DEFAULT_INTERNAL_ORG_SLUGS;
  return new Set(list);
}

// Email domains (lower-cased) that map to the internal `scheduler-systems` org.
// Mirrors the scheduler-api SCHEDULER_INTERNAL_EMAIL_DOMAINS default.
const INTERNAL_EMAIL_DOMAIN = "scheduler-systems.com";

// orgIdForEmail maps a signed-in user to a Pilotlight `orgId` attribute.
// Scheduler-Systems staff → "scheduler-systems" (internal); any other domain →
// that domain verbatim (a non-internal org id). Returns "public" when there is
// no usable email. The value is lower-cased to match the case-sensitive
// Pilotlight saved-group entry "scheduler-systems".
export function orgIdForEmail(email?: string | null): string {
  const e = (email ?? "").trim().toLowerCase();
  const at = e.lastIndexOf("@");
  if (at < 0 || at === e.length - 1) return "public";
  const domain = e.slice(at + 1);
  if (domain === INTERNAL_EMAIL_DOMAIN) return "scheduler-systems";
  return domain;
}

// resolveTierForEmail computes the audience tier for a signed-in user.
export function resolveTierForEmail(email?: string | null): AudienceTier {
  return internalOrgSlugs().has(orgIdForEmail(email)) ? "internal" : "public";
}

// isInternalEmail is a convenience predicate: does this user meet the internal tier?
export function isInternalEmail(email?: string | null): boolean {
  return meetsAudience(resolveTierForEmail(email), "internal");
}
