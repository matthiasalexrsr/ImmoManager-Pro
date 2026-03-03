import { useState, useEffect, useCallback } from 'react';
import { api } from '../api';

export function useList(path, deps = []) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [reloadCount, setReloadCount] = useState(0);

  const depsKey = JSON.stringify(deps);

  useEffect(() => {
    setLoading(true); // eslint-disable-line react-hooks/set-state-in-effect -- data-fetching effect needs loading state
    api.get(path)
      .then(data => { setItems(data); setError(null); })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, [path, depsKey, reloadCount]);

  const reload = useCallback(() => setReloadCount(c => c + 1), []);

  return { items, loading, error, reload };
}

export function useDetail(path) {
  const [item, setItem] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.get(path)
      .then(data => { setItem(data); setError(null); })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, [path]);

  return { item, loading, error };
}
