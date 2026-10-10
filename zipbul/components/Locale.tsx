'use client';
import {useEffect, useSyncExternalStore} from 'react';
import {DEFAULT_LOCALE, translate, type Locale} from '../lib/locale';
const key = 'zipbul-language';
let current: Locale = DEFAULT_LOCALE;
const listeners = new Set<() => void>();
function subscribe(listener: () => void) { listeners.add(listener); return () => {listeners.delete(listener);}; }
export function setLocale(locale: Locale) {
  current = locale;
  try { localStorage.setItem(key, locale); } catch {}
  document.documentElement.lang = locale;
  document.title = locale === 'en' ? 'Zipbul — Field Explorer' : '짚불 — 현장 탐사';
  listeners.forEach(listener => listener());
}
export function t(text: string | null | undefined, ...args: unknown[]) { return translate(text, current, ...args); }
export function useLocale() {
  const locale = useSyncExternalStore(subscribe, () => current, () => DEFAULT_LOCALE);
  useEffect(() => {
    try { const saved = localStorage.getItem(key); if(saved === 'ko' || saved === 'en') setLocale(saved); } catch {}
    const sync = (event: StorageEvent) => { if(event.key === key) setLocale(event.newValue === 'ko' ? 'ko' : 'en'); };
    window.addEventListener('storage', sync);
    return () => window.removeEventListener('storage', sync);
  }, []);
  return {locale, setLocale, t};
}
export function LanguagePicker() {
  const {locale, setLocale} = useLocale();
  return <select className="language-picker" aria-label="Language / 언어" value={locale} onChange={e => setLocale(e.target.value as Locale)}>
    <option value="en">English</option><option value="ko">한국어</option>
  </select>;
}
