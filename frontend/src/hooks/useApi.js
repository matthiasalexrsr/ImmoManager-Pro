import { useState, useEffect, useCallback } from 'react';
import { api } from '../api';

export function useList(path, deps = []) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const reload = useCallback(() => {
    setLoading(true);
    api.get(path)
      .then(data => { setItems(data); setError(null); })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, [path, ...deps]);

  useEffect(() => { reload(); }, [reload]);

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
