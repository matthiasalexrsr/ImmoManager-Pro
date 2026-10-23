import { useCallback, useEffect, useState } from 'react';

// Pages a person pinned to the top of the sidebar, per signed-in user in this browser only.
const LIMIT = 8;
const keyFor = userId => (userId ? `nav_favorites:${userId}` : null);

function read(key, known) {
  if (!key) return [];
  try {
    const list = JSON.parse(window.localStorage.getItem(key) || '[]');
    return Array.isArray(list) ? list.filter(path => known.includes(path)).slice(0, LIMIT) : [];
  } catch {
    return [];
  }
}

export function useNavFavorites(userId, known) {
  const key = keyFor(userId);
  const [favorites, setFavorites] = useState(() => read(key, known));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { setFavorites(read(key, known)); }, [key]);
  const toggle = useCallback(path => {
    setFavorites(current => {
      const next = current.includes(path) ? current.filter(p => p !== path) : [...current, path].slice(-LIMIT);
      if (key) { try { window.localStorage.setItem(key, JSON.stringify(next)); } catch { /* not kept */ } }
      return next;
    });
  }, [key]);
  return [favorites, toggle];
}
