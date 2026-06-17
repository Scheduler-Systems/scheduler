"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import {
  DEFAULT_LOCALE,
  isRtlLocale,
  isSupportedLocale,
  resolveLocale,
  translate,
  SUPPORTED_LOCALES,
  type Dictionary,
  type Locale,
} from "./i18n";
import { dictionary } from "./i18n-dict";

const STORAGE_KEY = "scheduler.locale";

interface I18nContextValue {
  locale: Locale;
  setLocale: (next: Locale) => void;
  t: (key: string, params?: Record<string, string | number>) => string;
}

const I18nContext = createContext<I18nContextValue | null>(null);

export function I18nProvider({
  children,
  dict = dictionary,
}: {
  children: React.ReactNode;
  dict?: Dictionary;
}) {
  // Server-render with the default; useEffect resolves to the user's actual
  // locale once we have access to localStorage + navigator.language.
  const [locale, setLocaleState] = useState<Locale>(DEFAULT_LOCALE);

  useEffect(() => {
    const stored =
      typeof window === "undefined" ? null : localStorage.getItem(STORAGE_KEY);
    const accept =
      typeof navigator === "undefined" ? null : navigator.language;
    const resolved = resolveLocale(stored, accept);
    if (resolved !== locale) setLocaleState(resolved);
    // Sync the html attributes for accessibility + RTL flow.
    if (typeof document !== "undefined") {
      document.documentElement.lang = resolved;
      document.documentElement.dir = isRtlLocale(resolved) ? "rtl" : "ltr";
    }
    // intentionally only on first mount — explicit setLocale handles updates
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const setLocale = useCallback((next: Locale) => {
    if (!isSupportedLocale(next)) return;
    setLocaleState(next);
    if (typeof window !== "undefined") {
      localStorage.setItem(STORAGE_KEY, next);
    }
    if (typeof document !== "undefined") {
      document.documentElement.lang = next;
      document.documentElement.dir = isRtlLocale(next) ? "rtl" : "ltr";
    }
  }, []);

  const t = useCallback(
    (key: string, params?: Record<string, string | number>) =>
      translate(dict, locale, key, params),
    [dict, locale]
  );

  const value = useMemo(
    () => ({ locale, setLocale, t }),
    [locale, setLocale, t]
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nContextValue {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error("useI18n must be used within I18nProvider");
  return ctx;
}

export { SUPPORTED_LOCALES };
export type { Locale };
