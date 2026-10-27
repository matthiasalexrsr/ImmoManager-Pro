import { useCallback, useEffect, useState } from 'react';

// The sidebar groups a person keeps open, per signed-in user in this browser only: after a reload
// or the next sign-in the menu looks as it was left (the group of the current page opens anyway).
const keyFor = userId => (userId ? `nav_groups_open:${userId}` : null);

function read(key, known) {
  if (!key) return {};
  try {
    const list = JSON.parse(window.localStorage.getItem(key) || '[]');
    return Array.isArray(list) ? Object.fromEntries(list.filter(group => known.includes(group)).map(group => [group, true])) : {};
  } catch {
    return {};
  }
}

export function useNavGroups(userId, known) {
  const key = keyFor(userId);
  const [open, setOpen] = useState(() => read(key, known));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { setOpen(read(key, known)); }, [key]);
  const update = useCallback(change => {
    setOpen(current => {
      const next = typeof change === 'function' ? change(current) : change;
      if (key) {
        try { window.localStorage.setItem(key, JSON.stringify(Object.keys(next).filter(group => next[group]))); }
        catch { /* not kept */ }
      }
      return next;
    });
  }, [key]);
  return [open, update];
}
