import { useEffect, useState } from 'react';
import { privateStorageKey } from './workspaceIdentity';

// Per-viewer table conveniences (sorting, rows per page, hidden columns) kept in this browser.
// Storage may be unavailable (private window, blocked site data); the table then works as before.
const PREFIX = 'table_settings:';

function read(key) {
  if (!key) return null;
  try {
    const value = JSON.parse(window.localStorage.getItem(privateStorageKey(PREFIX + key)) || 'null');
    return value && typeof value === 'object' && !Array.isArray(value) ? value : null;
  } catch {
    return null;
  }
}

export function useStoredTableSettings(key, defaults) {
  const [settings, setSettings] = useState(() => ({ ...defaults, ...(read(key) || {}) }));
  useEffect(() => {
    if (!key) return;
    try { window.localStorage.setItem(privateStorageKey(PREFIX + key), JSON.stringify(settings)); } catch { /* not kept */ }
  }, [key, settings]);
  return [settings, setSettings];
}

// What a list shows right now (search, column filters, page), kept for this browser tab only:
// opening a record and coming back finds the list as it was left. A new tab starts fresh.
const VIEW_PREFIX = 'table_view:';

export function readTableView(key) {
  if (!key) return null;
  try {
    const value = JSON.parse(window.sessionStorage.getItem(privateStorageKey(VIEW_PREFIX + key)) || 'null');
    return value && typeof value === 'object' && !Array.isArray(value) ? value : null;
  } catch {
    return null;
  }
}

export function writeTableView(key, view) {
  if (!key) return;
  try { window.sessionStorage.setItem(privateStorageKey(VIEW_PREFIX + key), JSON.stringify(view)); } catch { /* not kept */ }
}

// A saved column setting is the person's choice only where it differed from the column's default of its time
// (savedDefaults: the columns hidden by default then); elsewhere the column takes today's default, so an update
// that hides a secondary column (to keep a list on screen) reaches lists saved before it. Settings saved before
// defaults were recorded count as made when every column was shown: a column hidden in them stays hidden.
export function columnHidden(col, savedHidden, savedDefaults) {
  const hiddenThen = Array.isArray(savedDefaults) && savedDefaults.includes(col.key);
  return savedHidden !== hiddenThen ? savedHidden : Boolean(col.hidden);
}
