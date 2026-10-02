import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api } from '../api';

/** Complete page-local lists, including reference data. Never publish a partial load.
 * Does not change the shared cache or other pages' request semantics.
 * reload resolves false on a read failure: a successful write must not be retried.
 */
export function useFinanceData(sources) {
  const sourceKey = JSON.stringify(sources);
  const endpoints = useMemo(() => JSON.parse(sourceKey), [sourceKey]);
  const empty = useMemo(() => Object.fromEntries(Object.keys(endpoints).map(key => [key, []])), [endpoints]);
  const [state, setState] = useState({ data: empty, loading: true, error: null, sourceKey });
  const requestRef = useRef(null);
  const mountedRef = useRef(false);

  const reload = useCallback(async () => {
    if (!mountedRef.current) return false;
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    const { signal } = controller;
    setState({ data: empty, loading: true, error: null, sourceKey });
    try {
      const entries = await Promise.all(Object.entries(endpoints).map(async ([key, path]) => {
        try {
          const rows = await api.getAll(path, { signal });
          if (!Array.isArray(rows)) throw new Error('Ungültige Listenantwort des Servers.');
          return [key, rows];
        } catch (cause) {
          throw Object.assign(new Error(cause?.message || 'Daten konnten nicht geladen werden.'), {
            cause, endpoint: path, code: cause?.code, requestId: cause?.requestId,
          });
        }
      }));
      if (signal.aborted) return false;
      setState({ data: Object.fromEntries(entries), loading: false, error: null, sourceKey });
      return true;
    } catch (error) {
      if (!signal.aborted) {
        // Stop sibling pagination too; do not display a misleading subset of totals.
        controller.abort();
        setState({ data: empty, loading: false, error, sourceKey });
      }
      return false;
    }
  }, [empty, endpoints, sourceKey]);

  useEffect(() => {
    mountedRef.current = true;
    reload();
    return () => { mountedRef.current = false; requestRef.current?.abort(); };
  }, [reload]);

  const current = state.sourceKey === sourceKey ? state : { data: empty, loading: true, error: null };
  return { ...current, reload };
}
