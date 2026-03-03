/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, useState, useEffect, useCallback } from 'react';

const I18nContext = createContext(null);

// Cache loaded translations
const translationCache = {};

function getNestedValue(obj, path) {
  return path.split('.').reduce((o, key) => (o && o[key] !== undefined ? o[key] : null), obj);
}

export function useTranslation() {
  const ctx = useContext(I18nContext);
  if (!ctx) return { t: (key) => key, locale: 'de-DE', setLocale: () => {} };
  return ctx;
}

export function I18nProvider({ children }) {
  const [locale, setLocaleState] = useState(() => localStorage.getItem('locale') || 'de-DE');
  const [translations, setTranslations] = useState({});
  const [fallback, setFallback] = useState({});

  // Load a locale's translations
  const loadTranslations = useCallback(async (loc) => {
    if (translationCache[loc]) return translationCache[loc];
    try {
      const res = await fetch(`/i18n/${loc}`);
      if (res.ok) {
        const data = await res.json();
        translationCache[loc] = data;
        return data;
      }
    } catch { /* ignore */ }
    return {};
  }, []);

  useEffect(() => {
    // Load current locale and German fallback
    Promise.all([
      loadTranslations(locale),
      locale !== 'de-DE' ? loadTranslations('de-DE') : Promise.resolve({}),
    ]).then(([current, fb]) => {
      setTranslations(current);
      setFallback(fb);
    });
  }, [locale, loadTranslations]);

  const setLocale = useCallback((loc) => {
    localStorage.setItem('locale', loc);
    setLocaleState(loc);
  }, []);

  const t = useCallback((key, params) => {
    let value = getNestedValue(translations, key)
      || getNestedValue(fallback, key)
      || key;
    if (params && typeof value === 'string') {
      Object.entries(params).forEach(([k, v]) => {
        value = value.replace(`{{${k}}}`, v);
      });
    }
    return value;
  }, [translations, fallback]);

  return (
    <I18nContext.Provider value={{ t, locale, setLocale }}>
      {children}
    </I18nContext.Provider>
  );
}
