/* eslint-disable react-refresh/only-export-components */
/**
 * DataStoreContext — global reactive data cache for cross-page persistence.
 *
 * Ensures DB items remain consistent across different pages:
 *  - Shared entity cache (properties, units, tenants, etc.)
 *  - Automatic cache invalidation on mutations
 *  - Event-based refresh so all mounted components update together
 *  - Configurable TTL to avoid stale data
 */
import { createContext, useContext, useState, useCallback, useRef, useEffect } from 'react';
import { api } from '../api';

const DataStoreContext = createContext(null);

// Cache TTL in ms — data older than this is considered stale
const CACHE_TTL = 30_000; // 30 seconds

export function useDataStore() {
  return useContext(DataStoreContext);
}

/**
 * Hook to consume a specific entity list from the global store.
 * Automatically fetches on mount if not cached, and re-renders on invalidation.
 */
export function useEntities(entityKey, endpoint) {
  const store = useDataStore();
  const [, setTick] = useState(0);

  // Subscribe to invalidation events for this entity
  useEffect(() => {
    if (!store) return;
    const unsub = store.subscribe(entityKey, () => setTick(t => t + 1));
    // Trigger initial fetch if not cached
    store.ensureLoaded(entityKey, endpoint);
    return unsub;
  }, [store, entityKey, endpoint]);

  if (!store) return { items: [], loading: false, error: null, reload: () => {} };

  const entry = store.getCache(entityKey);
  return {
    items: entry?.data || [],
    loading: entry?.loading || false,
    error: entry?.error || null,
    reload: () => store.invalidate(entityKey, endpoint),
  };
}

export function DataStoreProvider({ children }) {
  // Cache: { [entityKey]: { data, loading, error, fetchedAt, endpoint } }
  const cacheRef = useRef({});
  // Subscribers: { [entityKey]: Set<callback> }
  const subsRef = useRef({});
  // Pending fetches to avoid duplicate requests
  const pendingRef = useRef({});
  // Force re-render trigger
  const [, setVersion] = useState(0);

  const notify = useCallback((entityKey) => {
    const subs = subsRef.current[entityKey];
    if (subs) subs.forEach(cb => cb());
    setVersion(v => v + 1);
  }, []);

  const subscribe = useCallback((entityKey, callback) => {
    if (!subsRef.current[entityKey]) subsRef.current[entityKey] = new Set();
    subsRef.current[entityKey].add(callback);
    return () => subsRef.current[entityKey]?.delete(callback);
  }, []);

  const getCache = useCallback((entityKey) => {
    return cacheRef.current[entityKey] || null;
  }, []);

  const fetchEntity = useCallback(async (entityKey, endpoint) => {
    // Skip if already fetching
    if (pendingRef.current[entityKey]) return;
    pendingRef.current[entityKey] = true;

    cacheRef.current[entityKey] = {
      ...cacheRef.current[entityKey],
      loading: true, error: null, endpoint,
    };
    notify(entityKey);

    try {
      const data = await api.get(endpoint);
      cacheRef.current[entityKey] = {
        data: Array.isArray(data) ? data : [],
        loading: false,
        error: null,
        fetchedAt: Date.now(),
        endpoint,
      };
    } catch (err) {
      cacheRef.current[entityKey] = {
        ...cacheRef.current[entityKey],
        loading: false,
        error: err.message,
        fetchedAt: Date.now(),
        endpoint,
      };
    } finally {
      delete pendingRef.current[entityKey];
      notify(entityKey);
    }
  }, [notify]);

  const ensureLoaded = useCallback((entityKey, endpoint) => {
    const entry = cacheRef.current[entityKey];
    if (!entry || !entry.fetchedAt || (Date.now() - entry.fetchedAt > CACHE_TTL)) {
      fetchEntity(entityKey, endpoint);
    }
  }, [fetchEntity]);

  const invalidate = useCallback((entityKey, endpoint) => {
    const entry = cacheRef.current[entityKey];
    const ep = endpoint || entry?.endpoint;
    if (ep) {
      fetchEntity(entityKey, ep);
    }
  }, [fetchEntity]);

  /**
   * Invalidate caches that have active subscribers (mounted components).
   * This avoids refetching every cached entity after every mutation —
   * only entities that are currently displayed get refreshed immediately.
   * Remaining stale caches will be refreshed via TTL on next access.
   */
  const invalidateAll = useCallback(() => {
    const entries = cacheRef.current;
    const subs = subsRef.current;
    for (const key of Object.keys(entries)) {
      const entry = entries[key];
      if (entry?.endpoint && subs[key]?.size > 0) {
        fetchEntity(key, entry.endpoint);
      } else if (entry) {
        // Mark as stale so ensureLoaded refetches on next mount
        entry.fetchedAt = 0;
      }
    }
  }, [fetchEntity]);

  /**
   * Invalidate related entities after a mutation.
   * E.g., after creating a unit, invalidate both 'units' and 'properties'.
   */
  const invalidateRelated = useCallback((primaryKey, ...relatedKeys) => {
    const entry = cacheRef.current[primaryKey];
    if (entry?.endpoint) fetchEntity(primaryKey, entry.endpoint);
    for (const key of relatedKeys) {
      const rel = cacheRef.current[key];
      if (rel?.endpoint) fetchEntity(key, rel.endpoint);
    }
  }, [fetchEntity]);

  /**
   * Perform a mutation (POST/PUT/PATCH/DELETE) and automatically
   * invalidate relevant caches.
   */
  const mutate = useCallback(async (method, path, data, invalidateKeys = []) => {
    let result;
    if (method === 'POST') result = await api.post(path, data);
    else if (method === 'PUT') result = await api.put(path, data);
    else if (method === 'PATCH') result = await api.patch(path, data);
    else if (method === 'DELETE') result = await api.del(path);
    else throw new Error(`Unknown method: ${method}`);

    // Invalidate specified caches
    for (const key of invalidateKeys) {
      invalidate(key);
    }
    return result;
  }, [invalidate]);

  return (
    <DataStoreContext.Provider value={{
      subscribe, getCache, ensureLoaded, invalidate,
      invalidateAll, invalidateRelated, mutate, fetchEntity,
    }}>
      {children}
    </DataStoreContext.Provider>
  );
}
