import { describe, it, expect } from "vitest";
import {
  isSupportedLocale,
  isRtlLocale,
  resolveLocale,
  translate,
  SUPPORTED_LOCALES,
  DEFAULT_LOCALE,
  type Locale,
} from "./i18n";

const sampleDict = {
  en: { hello: "Hello", greet: "Welcome, {name}" },
  he: { hello: "שלום", greet: "ברוךהבא, {name}" },
  es: { hello: "Hola", greet: "Bienvenido, {name}" },
} satisfies Record<Locale, Record<string, string>>;

describe("SUPPORTED_LOCALES", () => {
  it("includes en, he, es and starts with en as default", () => {
    expect(SUPPORTED_LOCALES).toContain("en");
    expect(SUPPORTED_LOCALES).toContain("he");
    expect(SUPPORTED_LOCALES).toContain("es");
    expect(DEFAULT_LOCALE).toBe("en");
  });
});

describe("isSupportedLocale", () => {
  it("accepts known locales", () => {
    expect(isSupportedLocale("en")).toBe(true);
    expect(isSupportedLocale("he")).toBe(true);
    expect(isSupportedLocale("es")).toBe(true);
  });

  it("rejects unknown locales", () => {
    expect(isSupportedLocale("fr")).toBe(false);
    expect(isSupportedLocale("")).toBe(false);
    expect(isSupportedLocale("EN")).toBe(false);
  });
});

describe("isRtlLocale", () => {
  it("returns true only for he", () => {
    expect(isRtlLocale("he")).toBe(true);
    expect(isRtlLocale("en")).toBe(false);
    expect(isRtlLocale("es")).toBe(false);
  });
});

describe("resolveLocale", () => {
  it("uses the stored locale when supported", () => {
    expect(resolveLocale("he", "en-US,en;q=0.9")).toBe("he");
  });

  it("falls back to browser Accept-Language when storage is empty", () => {
    expect(resolveLocale(null, "es-MX,es;q=0.9,en;q=0.8")).toBe("es");
  });

  it("falls back to default when neither stored nor browser match", () => {
    expect(resolveLocale(null, "fr-FR,fr;q=0.9")).toBe("en");
  });

  it("ignores invalid stored values", () => {
    expect(resolveLocale("xx", "en")).toBe("en");
  });

  it("matches he when accept-language has Hebrew variants", () => {
    expect(resolveLocale(null, "he-IL,he;q=0.9,en;q=0.5")).toBe("he");
  });
});

describe("translate", () => {
  it("returns the localized string", () => {
    expect(translate(sampleDict, "en", "hello")).toBe("Hello");
    expect(translate(sampleDict, "es", "hello")).toBe("Hola");
  });

  it("interpolates {placeholders} when params are passed", () => {
    expect(translate(sampleDict, "en", "greet", { name: "Alice" })).toBe(
      "Welcome, Alice"
    );
  });

  it("falls back to the default locale when key missing in target", () => {
    const partial = {
      en: { hello: "Hello" },
      he: {},
      es: {},
    } as unknown as typeof sampleDict;
    expect(translate(partial, "he", "hello")).toBe("Hello");
  });

  it("falls back to the key itself if missing everywhere", () => {
    expect(translate(sampleDict, "en", "missing.key")).toBe("missing.key");
  });
});
