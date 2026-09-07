"use client";

import { useLanguage } from "./language-context";

export default function LanguageToggle() {
  const { lang, setLang } = useLanguage();
  return (
    <div className="language-toggle" aria-label="Language">
      <button type="button" className={lang === "vi" ? "active" : ""} aria-pressed={lang === "vi"} onClick={() => setLang("vi")}>VI</button>
      <button type="button" className={lang === "en" ? "active" : ""} aria-pressed={lang === "en"} onClick={() => setLang("en")}>EN</button>
    </div>
  );
}
