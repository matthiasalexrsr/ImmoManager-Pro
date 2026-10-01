/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';
import { api } from '../api';
import { useAuth } from './AuthContext';
import { useTranslation } from '../i18n';

const PreferencesContext = createContext(null);
const PATH = '/auth/users/me/preferences';
const DEFAULT_PREFS = {
  theme: 'light', locale: 'de-DE', sidebar_collapsed: false, items_per_page: 25,
  date_format: 'DD.MM.YYYY', currency: 'EUR', default_due_day: 1,
  email_notifications: 'important', reminder_days: '7',
};
function readCache(userId) {
  try {
    const saved = JSON.parse(localStorage.getItem(`user_preferences:${userId}`));
    return saved && typeof saved === 'object' && !Array.isArray(saved)
      ? { ...DEFAULT_PREFS, ...saved } : { ...DEFAULT_PREFS };
  } catch { return { ...DEFAULT_PREFS }; }
}
function cache(userId, value) {
  if (!userId) return;
  try { localStorage.setItem(`user_preferences:${userId}`, JSON.stringify(value)); }
  catch { /* Server persistence remains available when local storage is full. */ }
}
export function usePreferences() { return useContext(PreferencesContext); }

export function PreferencesProvider({ children }) {
  const userId = useAuth()?.user?.id ?? null;
  const { setLocale } = useTranslation();
  const [prefs, setPrefs] = useState({ ...DEFAULT_PREFS });
  const [saveError, setSaveError] = useState(null);
  const current = useRef({ userId: null, value: { ...DEFAULT_PREFS }, epoch: 0, edits: 0 });
  const writes = useRef(Promise.resolve());

  useEffect(() => {
    const media = window.matchMedia('(prefers-color-scheme: dark)');
    const apply = () => document.documentElement.setAttribute('data-theme',
      prefs.theme === 'system' ? (media.matches ? 'dark' : 'light') : prefs.theme);
    apply();
    if (prefs.theme !== 'system') return;
    media.addEventListener?.('change', apply);
    return () => media.removeEventListener?.('change', apply);
  }, [prefs.theme]);

  useEffect(() => {
    const epoch = current.current.epoch + 1;
    const value = userId ? readCache(userId) : { ...DEFAULT_PREFS };
    current.current = { userId, value, epoch, edits: 0 };
    setPrefs(value);
    setSaveError(null);
    // No protected request on the anonymous login page: its 401 would reload it.
    if (!userId) return;
    setLocale(value.locale);
    const controller = new AbortController();
    api.get(PATH, { signal: controller.signal }).then(data => {
      const state = current.current;
      if (controller.signal.aborted || state.epoch !== epoch || state.edits || !data) return;
      const merged = { ...DEFAULT_PREFS, ...data };
      state.value = merged;
      setPrefs(merged);
      setLocale(merged.locale);
      cache(userId, merged);
    }).catch(error => {
      if (!controller.signal.aborted && current.current.epoch === epoch) setSaveError(error.message);
    });
    return () => controller.abort();
  }, [userId, setLocale]);

  const persist = useCallback((value, state) => {
    // Ordered writes prevent a slow previous toggle from overwriting the choice.
    const operation = writes.current.catch(() => {}).then(async () => {
      if (!state.userId || current.current.epoch !== state.epoch) return;
      try {
        await api.put(PATH, value);
        if (current.current.epoch === state.epoch && current.current.edits === state.edits) setSaveError(null);
      } catch (error) {
        if (current.current.epoch === state.epoch) setSaveError(error.message);
      }
    });
    writes.current = operation;
    return operation;
  }, []);
  const updatePrefs = useCallback(updates => {
    const state = current.current;
    const changes = typeof updates === 'function' ? updates(state.value) : updates;
    const value = { ...state.value, ...changes };
    state.value = value;
    state.edits += 1;
    setPrefs(value);
    if (Object.hasOwn(changes, 'locale')) setLocale(value.locale);
    cache(state.userId, value);
    return persist(value, { ...state });
  }, [persist, setLocale]);
  const toggleTheme = useCallback(() => updatePrefs(prev => ({ theme: prev.theme === 'light' ? 'dark' : 'light' })), [updatePrefs]);
  const toggleSidebar = useCallback(() => updatePrefs(prev => ({ sidebar_collapsed: !prev.sidebar_collapsed })), [updatePrefs]);
  const retrySave = useCallback(() => persist(current.current.value, { ...current.current }), [persist]);
  return <PreferencesContext.Provider value={{ prefs, updatePrefs, toggleTheme, toggleSidebar, saveError, retrySave }}>
    {children}
  </PreferencesContext.Provider>;
}
