import { describe, it, expect } from "vitest";
import { dictionary } from "./i18n-dict";
import { SUPPORTED_LOCALES, type Locale } from "./i18n";

const LOCALES: Locale[] = [...SUPPORTED_LOCALES];

describe("i18n dictionary structural consistency", () => {
  it("exports a dictionary with exactly the expected locales (en, he, es)", () => {
    expect(Object.keys(dictionary).sort()).toEqual([...LOCALES].sort());
  });

  it("each locale has a non-empty record of translations", () => {
    for (const locale of LOCALES) {
      expect(dictionary[locale]).toBeDefined();
      expect(Object.keys(dictionary[locale]).length).toBeGreaterThan(0);
    }
  });

  it("all locales share the same set of translation keys", () => {
    const allKeys = LOCALES.map((l) => Object.keys(dictionary[l]));

    // Reference is the first locale's key set.
    const reference = new Set(allKeys[0]);

    // Check every other locale has exactly the same keys.
    for (let i = 1; i < allKeys.length; i++) {
      const keys = new Set(allKeys[i]);

      // Keys in reference but missing from this locale.
      const missing: string[] = [];
      for (const k of reference) {
        if (!keys.has(k)) missing.push(k);
      }

      // Keys in this locale but not in reference.
      const extra: string[] = [];
      for (const k of keys) {
        if (!reference.has(k)) extra.push(k);
      }

      const localeName = LOCALES[i];
      if (missing.length > 0 || extra.length > 0) {
        const msg: string[] = [];
        if (missing.length > 0)
          msg.push(
            `Missing in "${localeName}": ${missing.join(", ")}`,
          );
        if (extra.length > 0)
          msg.push(
            `Extra in "${localeName}" (not in reference): ${extra.join(", ")}`,
          );
        // Fail with a single, descriptive assertion.
        expect(
          { missing, extra },
          `${localeName}: ${msg.join("; ")}`,
        ).toStrictEqual({ missing: [], extra: [] });
      }
    }
  });

  it("all translation values are non-empty strings", () => {
    for (const locale of LOCALES) {
      const dict = dictionary[locale];
      for (const [key, value] of Object.entries(dict)) {
        expect(
          typeof value,
          `${locale}["${key}"] should be a string, got ${typeof value}`,
        ).toBe("string");
        expect(
          value.length,
          `${locale}["${key}"] should not be empty`,
        ).toBeGreaterThan(0);
      }
    }
  });

  it("interpolation parameters ({name}) are consistent across all locales for each key", () => {
    // Regex match all {paramName} patterns in a string.
    const paramPattern = /\{(\w+)\}/g;

    for (const key of Object.keys(dictionary.en)) {
      const paramSets = new Map<Locale, Set<string>>();

      for (const locale of LOCALES) {
        const value = dictionary[locale]?.[key] ?? "";
        const params = new Set<string>();
        let match: RegExpExecArray | null;
        // Reset regex state before each use.
        paramPattern.lastIndex = 0;
        while ((match = paramPattern.exec(value)) !== null) {
          params.add(match[1]);
        }
        paramSets.set(locale, params);
      }

      // Compare each non-en locale against en as reference.
      const enParams = paramSets.get("en")!;
      for (const locale of LOCALES) {
        if (locale === "en") continue;
        const localeParams = paramSets.get(locale)!;

        const missing: string[] = [];
        const extra: string[] = [];

        for (const p of enParams) {
          if (!localeParams.has(p)) missing.push(p);
        }
        for (const p of localeParams) {
          if (!enParams.has(p)) extra.push(p);
        }

        if (missing.length > 0 || extra.length > 0) {
          const msg: string[] = [];
          if (missing.length > 0)
            msg.push(
              `missing {${missing.join(", ")}}`,
            );
          if (extra.length > 0)
            msg.push(
              `extra {${extra.join(", ")}}`,
            );
          // Fail with descriptive assertion.
          expect(
            { key, locale, enParams: [...enParams], localeParams: [...localeParams] },
            `"${key}" in ${locale}: ${msg.join("; ")}`,
          ).toStrictEqual(
            { key, locale, enParams: [...enParams], localeParams: [...enParams] },
          );
        }
      }
    }
  });

  it("keys follow a consistent namespace:section pattern (dotted notation)", () => {
    const keyPattern = /^[a-zA-Z0-9]+(\.[a-zA-Z0-9]+)+$/;
    for (const key of Object.keys(dictionary.en)) {
      expect(
        key,
        `Key "${key}" does not match namespace:section pattern (e.g. "nav.signIn", "landing.heading")`,
      ).toMatch(keyPattern);
    }
  });
});
