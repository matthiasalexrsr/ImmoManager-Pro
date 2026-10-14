import { useEffect, useState } from 'react';

// Per-viewer table conveniences (sorting, rows per page, hidden columns) kept in this browser.
// Storage may be unavailable (private window, blocked site data); the table then works as before.
const PREFIX = 'table_settings:';

function read(key) {
  if (!key) return null;
  try {
    const value = JSON.parse(window.localStorage.getItem(PREFIX + key) || 'null');
    return value && typeof value === 'object' ? value : null;
  } catch {
    return null;
  }
}

export function useStoredTableSettings(key, defaults) {
  const [settings, setSettings] = useState(() => ({ ...defaults, ...(read(key) || {}) }));
  useEffect(() => {
    if (!key) return;
    try { window.localStorage.setItem(PREFIX + key, JSON.stringify(settings)); } catch { /* not kept */ }
  }, [key, settings]);
  return [settings, setSettings];
}
