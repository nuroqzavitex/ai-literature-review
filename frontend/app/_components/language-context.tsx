"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { translations, type Language, type TranslationKey } from "./translations";

const STORAGE_KEY = "litreview_lang";
const DEFAULT_LANGUAGE: Language = "vi";

type TranslationValues = Record<string, string | number>;
type LanguageContextValue = {
  lang: Language;
  setLang: (language: Language) => void;
  t: (key: TranslationKey, fallback?: string, values?: TranslationValues) => string;
};

const LanguageContext = createContext<LanguageContextValue | null>(null);

function lookup(language: Language, key: TranslationKey): string | undefined {
  return key.split(".").reduce<unknown>((value, segment) => {
    if (!value || typeof value !== "object") return undefined;
    return (value as Record<string, unknown>)[segment];
  }, translations[language]) as string | undefined;
}

function interpolate(value: string, values?: TranslationValues) {
  if (!values) return value;
  return value.replace(/\{(\w+)\}/g, (token, name: string) =>
    values[name] === undefined ? token : String(values[name])
  );
}

export function LanguageProvider({ children }: Readonly<{ children: React.ReactNode }>) {
  const [lang, setLanguage] = useState<Language>(DEFAULT_LANGUAGE);

  const setLang = useCallback((language: Language) => {
    setLanguage(language);
    window.localStorage.setItem(STORAGE_KEY, language);
  }, []);

  useEffect(() => {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored === "vi" || stored === "en") setLanguage(stored);
  }, []);

  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);

  useEffect(() => {
    function handleStorage(event: StorageEvent) {
      if (event.key === STORAGE_KEY && (event.newValue === "vi" || event.newValue === "en")) {
        setLanguage(event.newValue);
      }
    }
    window.addEventListener("storage", handleStorage);
    return () => window.removeEventListener("storage", handleStorage);
  }, []);

  const value = useMemo<LanguageContextValue>(() => ({
    lang,
    setLang,
    t: (key, fallback, values) => interpolate(lookup(lang, key) ?? fallback ?? key, values),
  }), [lang, setLang]);

  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>;
}

export function useLanguage() {
  const context = useContext(LanguageContext);
  if (!context) throw new Error("useLanguage must be used inside LanguageProvider.");
  return context;
}
