/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import { useAuth } from './AuthContext';
import { setDateFormat, setFormatLocale, setCurrencyDisplay } from '../utils/format';

const PreferencesContext = createContext(null);
const DEFAULT_PREFS = { theme: 'light', locale: 'de-DE', sidebar_collapsed: false, items_per_page: 25,
  date_format: 'DD.MM.YYYY', currency: 'EUR', default_due_day: 1, email_notifications: 'important', reminder_days: '7', currency_display: 'symbol', density: 'comfortable', start_page: '/', quiet_start: '', quiet_end: '', _revision: 0 };
export function usePreferences() { return useContext(PreferencesContext); }

export function PreferencesProvider({ children }) {
  const [prefs, setPrefs] = useState(DEFAULT_PREFS);
  const [error, setError] = useState(null);
  const [ready, setReady] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const pending = useRef(null);
  const saving = useRef(false);
  const userId = useAuth()?.user?.id;
  const { setLocale } = useTranslation();
  useEffect(() => {
    let live = true; setPrefs(DEFAULT_PREFS); setReady(false); pending.current = null;
    if (!userId) return;
    const same = api.captureSession();
    api.get('/auth/users/me/preferences').then(data => {
      same(); if (live) { setPrefs({ ...DEFAULT_PREFS, ...data }); setReady(true); setError(null); }
    }).catch(failure => { if (live) setError(failure.message); });
    return () => { live = false; };
  }, [userId, attempt]);
  useEffect(() => {
    const theme = prefs.theme === 'system' ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light') : prefs.theme;
    document.documentElement.setAttribute('data-theme', theme);
    document.documentElement.setAttribute('data-density', prefs.density || 'comfortable');
    setFormatLocale(prefs.locale); setDateFormat(prefs.date_format); setCurrencyDisplay(prefs.currency_display); setLocale(prefs.locale);
  }, [prefs.theme, prefs.locale, prefs.date_format, prefs.density, prefs.currency_display, setLocale]);
  const updatePrefs = useCallback(async updates => {
    if (!ready || saving.current) return;
    saving.current = true;
    const identity = JSON.stringify(updates);
    if (pending.current?.identity !== identity) pending.current = { identity, body: {
      values: updates, base_revision: prefs._revision, idempotency_key: crypto.randomUUID() } };
    const same = api.captureSession();
    try {
      const result = await api.put('/auth/users/me/settings', pending.current.body);
      same(); setPrefs({ ...DEFAULT_PREFS, ...result.response }); pending.current = null; setError(null);
      window.dispatchEvent(new Event('settings-changed'));
    } catch (failure) { if (failure.code === 'SESSION_CHANGED') return; setError(failure.message || 'Einstellung nicht gespeichert. Erneut versuchen.'); }
    finally { saving.current = false; }
  }, [prefs._revision, ready]);
  useEffect(() => {
    const change = event => { if (event.detail !== prefs.locale) updatePrefs({ locale: event.detail }); };
    window.addEventListener('preference-locale', change);
    return () => window.removeEventListener('preference-locale', change);
  }, [prefs.locale, updatePrefs]);
  const toggleTheme = useCallback(() => updatePrefs({ theme: prefs.theme === 'dark' ? 'light' : 'dark' }), [prefs.theme, updatePrefs]);
  const toggleSidebar = useCallback(() => updatePrefs({ sidebar_collapsed: !prefs.sidebar_collapsed }), [prefs.sidebar_collapsed, updatePrefs]);
  return <PreferencesContext.Provider value={{ prefs, ready, error, updatePrefs, toggleTheme, toggleSidebar, reload: () => setAttempt(n => n + 1) }}>{children}</PreferencesContext.Provider>;
}
