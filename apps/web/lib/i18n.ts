// Client-side i18n primitives for the Next.js static export.
//
// We keep all logic Firebase-free + framework-free here so it's
// trivially unit-testable. The React Provider that consumes these
// lives in i18n-context.tsx.

export const SUPPORTED_LOCALES = ["en", "he", "es"] as const;
export type Locale = (typeof SUPPORTED_LOCALES)[number];
export const DEFAULT_LOCALE: Locale = "en";

const RTL_LOCALES = new Set<Locale>(["he"]);

export function isSupportedLocale(input: string): input is Locale {
  return (SUPPORTED_LOCALES as readonly string[]).includes(input);
}

export function isRtlLocale(locale: Locale): boolean {
  return RTL_LOCALES.has(locale);
}

// Pick a locale based on the stored value (localStorage) and the
// browser's Accept-Language header. Returns DEFAULT_LOCALE if neither
// resolves.
export function resolveLocale(
  stored: string | null,
  acceptLanguage: string | null | undefined
): Locale {
  if (stored && isSupportedLocale(stored)) return stored;
  if (acceptLanguage) {
    const tags = acceptLanguage
      .split(",")
      .map((t) => t.trim().split(";")[0].toLowerCase());
    for (const tag of tags) {
      const primary = tag.split("-")[0];
      if (isSupportedLocale(primary)) return primary;
    }
  }
  return DEFAULT_LOCALE;
}

export type Dictionary = Record<Locale, Record<string, string>>;

// Look up a translation key. Falls back through:
//   1. dict[locale][key]
//   2. dict[DEFAULT_LOCALE][key]
//   3. the key itself
// {placeholders} are replaced from `params` if provided.
export function translate(
  dict: Dictionary,
  locale: Locale,
  key: string,
  params?: Record<string, string | number>
): string {
  const raw = dict[locale]?.[key] ?? dict[DEFAULT_LOCALE]?.[key] ?? key;
  if (!params) return raw;
  return raw.replace(/\{(\w+)\}/g, (_match, name) =>
    params[name] !== undefined ? String(params[name]) : `{${name}}`
  );
}
