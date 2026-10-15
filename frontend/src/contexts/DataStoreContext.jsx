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
import { createContext, useContext, useState, useCallback, useEffect, useMemo } from 'react';
import { api } from '../api';
import { useAuth } from './AuthContext';

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
export function useEntities(entityKey, endpoint, enabled = true) {
  const store = useDataStore();
  const [, setTick] = useState(0);

  // Subscribe to invalidation events for this entity
  useEffect(() => {
    if (!store || !enabled) return;
    const unsub = store.subscribe(entityKey, () => setTick(t => t + 1));
    // Trigger initial fetch if not cached
    store.ensureLoaded(entityKey, endpoint);
    return unsub;
  }, [store, entityKey, endpoint, enabled]);

  if (!store) return { items: [], loading: false, error: null, reload: () => {} };

  const entry = store.getCache(entityKey);
  return {
    items: entry?.data || [],
    loading: enabled && (!entry || Boolean(entry.loading)),
    error: entry?.error || null,
    reload: () => store.invalidate(entityKey, endpoint),
  };
}

export function DataStoreProvider({ children }) {
  const user = useAuth()?.user;
  const scopeKey = JSON.stringify([user?.id || null, user?.role || null, user?.portfolio_access || null, [...(user?.portfolio_ids || [])].sort()]);
  return <ScopedDataStore scopeKey={scopeKey}>{children}</ScopedDataStore>;
}

function ScopedDataStore({ children, scopeKey }) {
  // Cache: { [entityKey]: { data, loading, error, fetchedAt, endpoint } }
  // Each identity owns a separate cache object. Late reads retain their old
  // object and can never populate the newly authorized viewer’s cache.
  const cacheScope = useMemo(() => ({ cache: {}, subscribers: {}, pending: {} }), [scopeKey]);
  // Force re-render trigger
  const [, setVersion] = useState(0);

  const notify = useCallback((entityKey) => {
    const subs = cacheScope.subscribers[entityKey];
    if (subs) subs.forEach(cb => cb());
    setVersion(v => v + 1);
  }, [cacheScope]);

  const subscribe = useCallback((entityKey, callback) => {
    if (!cacheScope.subscribers[entityKey]) cacheScope.subscribers[entityKey] = new Set();
    cacheScope.subscribers[entityKey].add(callback);
    return () => cacheScope.subscribers[entityKey]?.delete(callback);
  }, [cacheScope]);

  const getCache = useCallback((entityKey) => {
    return cacheScope.cache[entityKey] || null;
  }, [cacheScope]);

  const fetchEntity = useCallback(async (entityKey, endpoint) => {
    // Skip if already fetching
    if (cacheScope.pending[entityKey]) return;
    cacheScope.pending[entityKey] = true;

    cacheScope.cache[entityKey] = {
      ...cacheScope.cache[entityKey],
      loading: true, error: null, endpoint,
    };
    notify(entityKey);

    try {
      const data = await api.list(endpoint);
      cacheScope.cache[entityKey] = {
        data: Array.isArray(data) ? data : [],
        loading: false,
        error: null,
        fetchedAt: Date.now(),
        endpoint,
      };
    } catch (err) {
      cacheScope.cache[entityKey] = {
        ...cacheScope.cache[entityKey],
        loading: false,
        error: err.message,
        fetchedAt: Date.now(),
        endpoint,
      };
    } finally {
      delete cacheScope.pending[entityKey];
      notify(entityKey);
    }
  }, [notify, cacheScope]);

  const ensureLoaded = useCallback((entityKey, endpoint) => {
    const entry = cacheScope.cache[entityKey];
    if (!entry || !entry.fetchedAt || (Date.now() - entry.fetchedAt > CACHE_TTL)) {
      fetchEntity(entityKey, endpoint);
    }
  }, [fetchEntity, cacheScope]);

  const invalidate = useCallback((entityKey, endpoint) => {
    const entry = cacheScope.cache[entityKey];
    const ep = endpoint || entry?.endpoint;
    if (ep) {
      fetchEntity(entityKey, ep);
    }
  }, [fetchEntity, cacheScope]);

  /**
   * Invalidate caches that have active subscribers (mounted components).
   * This avoids refetching every cached entity after every mutation —
   * only entities that are currently displayed get refreshed immediately.
   * Remaining stale caches will be refreshed via TTL on next access.
   */
  const invalidateAll = useCallback(() => {
    const entries = cacheScope.cache;
    const subs = cacheScope.subscribers;
    for (const key of Object.keys(entries)) {
      const entry = entries[key];
      if (entry?.endpoint && subs[key]?.size > 0) {
        fetchEntity(key, entry.endpoint);
      } else if (entry) {
        // Mark as stale so ensureLoaded refetches on next mount
        entry.fetchedAt = 0;
      }
    }
  }, [fetchEntity, cacheScope]);

  /**
   * Invalidate related entities after a mutation.
   * E.g., after creating a unit, invalidate both 'units' and 'properties'.
   */
  const invalidateRelated = useCallback((primaryKey, ...relatedKeys) => {
    const entry = cacheScope.cache[primaryKey];
    if (entry?.endpoint) fetchEntity(primaryKey, entry.endpoint);
    for (const key of relatedKeys) {
      const rel = cacheScope.cache[key];
      if (rel?.endpoint) fetchEntity(key, rel.endpoint);
    }
  }, [fetchEntity, cacheScope]);

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

  // Stable value: useEntities subscribes in an effect that depends on it.
  const value = useMemo(() => ({
    subscribe, getCache, ensureLoaded, invalidate,
    invalidateAll, invalidateRelated, mutate, fetchEntity,
  }), [subscribe, getCache, ensureLoaded, invalidate, invalidateAll, invalidateRelated, mutate, fetchEntity]);

  return (
    <DataStoreContext.Provider value={value}>
      {children}
    </DataStoreContext.Provider>
  );
}
