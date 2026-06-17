"use client";

import { useI18n, type Locale } from "@/lib/i18n-context";

const LABELS: Record<Locale, string> = {
  en: "EN",
  he: "HE",
  es: "ES",
};

const FULL_LABELS: Record<Locale, string> = {
  en: "English",
  he: "עברית",
  es: "Español",
};

export function LocaleSwitcher({ compact = false }: { compact?: boolean }) {
  const { locale, setLocale } = useI18n();

  return (
    <label className="inline-flex items-center gap-1 text-xs text-gray-500">
      <span className="sr-only">Language</span>
      <select
        value={locale}
        onChange={(e) => setLocale(e.target.value as Locale)}
        className="rounded border border-gray-200 bg-white px-1.5 py-1 text-xs text-gray-700 focus:outline-none focus:ring-2 focus:ring-purple-500"
        aria-label="Language"
      >
        {(Object.keys(LABELS) as Locale[]).map((l) => (
          <option key={l} value={l}>
            {compact ? LABELS[l] : FULL_LABELS[l]}
          </option>
        ))}
      </select>
    </label>
  );
}
