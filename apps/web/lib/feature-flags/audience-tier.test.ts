import { describe, it, expect, afterEach } from "vitest";

import {
  TIER_RANK,
  meetsAudience,
  orgIdForEmail,
  resolveTierForEmail,
  isInternalEmail,
  internalOrgSlugs,
} from "./audience-tier";

// -----------------------------------------------------------------------------
// meetsAudience — rank logic. internal > partners > public; higher rank
// inherits lower-tier access. `required` defaults to "public".
// -----------------------------------------------------------------------------

describe("meetsAudience", () => {
  it("ranks internal > partners > public", () => {
    expect(TIER_RANK.internal).toBeGreaterThan(TIER_RANK.partners);
    expect(TIER_RANK.partners).toBeGreaterThan(TIER_RANK.public);
  });

  it("internal meets public, partners, and internal", () => {
    expect(meetsAudience("internal", "public")).toBe(true);
    expect(meetsAudience("internal", "partners")).toBe(true);
    expect(meetsAudience("internal", "internal")).toBe(true);
  });

  it("partners meets public and partners but NOT internal", () => {
    expect(meetsAudience("partners", "public")).toBe(true);
    expect(meetsAudience("partners", "partners")).toBe(true);
    expect(meetsAudience("partners", "internal")).toBe(false);
  });

  it("public meets ONLY public", () => {
    expect(meetsAudience("public", "public")).toBe(true);
    expect(meetsAudience("public", "partners")).toBe(false);
    expect(meetsAudience("public", "internal")).toBe(false);
  });

  it("defaults required to 'public'", () => {
    expect(meetsAudience("public")).toBe(true);
    expect(meetsAudience("partners")).toBe(true);
    expect(meetsAudience("internal")).toBe(true);
  });
});

// -----------------------------------------------------------------------------
// orgIdForEmail — staff domain maps to the internal slug; every other domain
// maps verbatim; no usable email maps to "public". Case-insensitive.
// -----------------------------------------------------------------------------

describe("orgIdForEmail", () => {
  it("maps the staff domain to the internal 'scheduler-systems' slug", () => {
    expect(orgIdForEmail("x@scheduler-systems.com")).toBe("scheduler-systems");
  });

  it("maps any other domain verbatim (NOT to an internal slug)", () => {
    expect(orgIdForEmail("x@acme.com")).toBe("acme.com");
  });

  it("is case-insensitive (lower-cases the result)", () => {
    expect(orgIdForEmail("X@Scheduler-Systems.COM")).toBe("scheduler-systems");
    expect(orgIdForEmail("X@ACME.COM")).toBe("acme.com");
  });

  it("returns 'public' when there is no '@'", () => {
    expect(orgIdForEmail("noatsign")).toBe("public");
  });

  it("returns 'public' for a trailing '@' (empty domain)", () => {
    expect(orgIdForEmail("x@")).toBe("public");
  });

  it("returns 'public' for empty / null / undefined", () => {
    expect(orgIdForEmail("")).toBe("public");
    expect(orgIdForEmail(null)).toBe("public");
    expect(orgIdForEmail(undefined)).toBe("public");
  });
});

// -----------------------------------------------------------------------------
// resolveTierForEmail / isInternalEmail — staff resolve to internal,
// customers resolve to public.
// -----------------------------------------------------------------------------

describe("resolveTierForEmail", () => {
  it("resolves staff (@scheduler-systems.com) to 'internal'", () => {
    expect(resolveTierForEmail("dev@scheduler-systems.com")).toBe("internal");
  });

  it("resolves a customer (@acme.com) to 'public'", () => {
    expect(resolveTierForEmail("user@acme.com")).toBe("public");
  });

  it("resolves null / empty to 'public'", () => {
    expect(resolveTierForEmail(null)).toBe("public");
    expect(resolveTierForEmail("")).toBe("public");
    expect(resolveTierForEmail(undefined)).toBe("public");
  });
});

describe("isInternalEmail", () => {
  it("is true for staff", () => {
    expect(isInternalEmail("dev@scheduler-systems.com")).toBe(true);
  });

  it("is false for a customer", () => {
    expect(isInternalEmail("user@acme.com")).toBe(false);
  });

  it("is false for null", () => {
    expect(isInternalEmail(null)).toBe(false);
  });
});

// -----------------------------------------------------------------------------
// THE HEADLINE INVARIANT — default-deny customer-safety.
//
// A non-staff identity must NEVER reach the internal tier. This is the
// regression guard for "paying customers never accidentally see internal /
// non-working features." If a future refactor makes any non-staff identity
// resolve to "internal", these assertions fail.
//
// Note: `b@gal-run.com` → domain "gal-run.com", which is NOT the internal
// slug "gal-run" (orgIdForEmail only maps the scheduler-systems.com domain to
// a slug; every other domain is returned verbatim). So it is correctly
// non-internal via the email path — asserted explicitly below.
// -----------------------------------------------------------------------------

describe("default-deny customer-safety invariant", () => {
  const NON_STAFF_IDENTITIES: Array<string | null | undefined> = [
    "user@acme.com",
    "a@gmail.com",
    "b@gal-run.com",
    "",
    null,
    undefined,
    "noatsign",
    "trailing@",
  ];

  it.each(NON_STAFF_IDENTITIES)(
    "non-staff identity %j never reaches the internal tier",
    (identity) => {
      expect(resolveTierForEmail(identity)).toBe("public");
      expect(isInternalEmail(identity)).toBe(false);
      expect(meetsAudience(resolveTierForEmail(identity), "internal")).toBe(
        false,
      );
    },
  );

  it("b@gal-run.com resolves via the domain (not the 'gal-run' slug) → public", () => {
    // Documents the real behavior: the email-path org id is the full domain,
    // which is not in the internal-slug set, so this is public — NOT internal.
    expect(orgIdForEmail("b@gal-run.com")).toBe("gal-run.com");
    expect(resolveTierForEmail("b@gal-run.com")).toBe("public");
  });
});

// -----------------------------------------------------------------------------
// internalOrgSlugs — env override is honored.
// -----------------------------------------------------------------------------

describe("internalOrgSlugs", () => {
  const ENV_KEY = "NEXT_PUBLIC_INTERNAL_ORG_SLUGS";
  const original = process.env[ENV_KEY];

  afterEach(() => {
    if (original === undefined) delete process.env[ENV_KEY];
    else process.env[ENV_KEY] = original;
  });

  it("honors the NEXT_PUBLIC_INTERNAL_ORG_SLUGS override", () => {
    process.env[ENV_KEY] = "acme-corp, Widgets-Inc ";
    const slugs = internalOrgSlugs();
    // Trimmed + lower-cased, and the defaults are replaced (not merged).
    expect(slugs.has("acme-corp")).toBe(true);
    expect(slugs.has("widgets-inc")).toBe(true);
    expect(slugs.has("scheduler-systems")).toBe(false);
  });
});
