import { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { api } from '../api';

const PreferencesContext = createContext(null);

const DEFAULT_PREFS = {
  theme: 'light',
  locale: 'de-DE',
  sidebar_collapsed: false,
  items_per_page: 25,
  date_format: 'DD.MM.YYYY',
  currency: 'EUR',
};

export function usePreferences() {
  return useContext(PreferencesContext);
}

export function PreferencesProvider({ children }) {
  const [prefs, setPrefs] = useState(() => {
    const saved = localStorage.getItem('user_preferences');
    return saved ? { ...DEFAULT_PREFS, ...JSON.parse(saved) } : DEFAULT_PREFS;
  });

  // Apply theme to document
  useEffect(() => {
    const theme = prefs.theme === 'system'
      ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
      : prefs.theme;
    document.documentElement.setAttribute('data-theme', theme);
  }, [prefs.theme]);

  // Load preferences from server
  useEffect(() => {
    api.get('/users/me/preferences')
      .then(data => {
        if (data) {
          const merged = { ...DEFAULT_PREFS, ...data };
          setPrefs(merged);
          localStorage.setItem('user_preferences', JSON.stringify(merged));
        }
      })
      .catch(() => {}); // Not logged in or no preferences
  }, []);

  const updatePrefs = useCallback((updates) => {
    setPrefs(prev => {
      const next = { ...prev, ...updates };
      localStorage.setItem('user_preferences', JSON.stringify(next));
      // Persist to server (fire and forget)
      api.put('/users/me/preferences', next).catch(() => {});
      return next;
    });
  }, []);

  const toggleTheme = useCallback(() => {
    setPrefs(prev => {
      const nextTheme = prev.theme === 'light' ? 'dark' : 'light';
      const next = { ...prev, theme: nextTheme };
      localStorage.setItem('user_preferences', JSON.stringify(next));
      api.put('/users/me/preferences', next).catch(() => {});
      return next;
    });
  }, []);

  const toggleSidebar = useCallback(() => {
    setPrefs(prev => {
      const next = { ...prev, sidebar_collapsed: !prev.sidebar_collapsed };
      localStorage.setItem('user_preferences', JSON.stringify(next));
      api.put('/users/me/preferences', next).catch(() => {});
      return next;
    });
  }, []);

  return (
    <PreferencesContext.Provider value={{ prefs, updatePrefs, toggleTheme, toggleSidebar }}>
      {children}
    </PreferencesContext.Provider>
  );
}
