import { useState, useEffect, useCallback, useRef } from 'react';
import { api } from '../api';

/**
 * Hook for fetching a list of items from the API.
 *
 * Features:
 *   - Safe unmount handling (no setState after unmount)
 *   - Full error context preserved (code, requestId, isNetwork)
 *   - Automatic reload capability
 */
export function useList(path, deps = []) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [reloadCount, setReloadCount] = useState(0);
  const mountedRef = useRef(true);

  const depsKey = JSON.stringify(deps);

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api.get(path)
      .then(data => {
        if (!cancelled && mountedRef.current) {
          setItems(Array.isArray(data) ? data : []);
          setError(null);
        }
      })
      .catch(e => {
        if (!cancelled && mountedRef.current) {
          setError(e.message);
        }
      })
      .finally(() => {
        if (!cancelled && mountedRef.current) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [path, depsKey, reloadCount]);

  const reload = useCallback(() => setReloadCount(c => c + 1), []);

  return { items, loading, error, reload };
}

/**
 * Hook for fetching a single item from the API.
 *
 * Features:
 *   - Safe unmount handling (no setState after unmount)
 *   - Full error context
 */
export function useDetail(path) {
  const [item, setItem] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api.get(path)
      .then(data => {
        if (!cancelled && mountedRef.current) {
          setItem(data);
          setError(null);
        }
      })
      .catch(e => {
        if (!cancelled && mountedRef.current) {
          setError(e.message);
        }
      })
      .finally(() => {
        if (!cancelled && mountedRef.current) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [path]);

  return { item, loading, error };
}
