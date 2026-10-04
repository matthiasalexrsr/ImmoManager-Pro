import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../../api';
import { accessDenied, checkedSummary, families, freshTrails, summaryQuery } from './dashboardModel';

const initial = principal => ({ principal, status: 'loading', data: null, error: null, loadedAt: null, version: 0,
  trails: freshTrails(), query: { limit: 5, asOf: null } });

/** One request publishes counts and all three current work pages together. */
export default function useDashboardSummary(principal, onDenied) {
  const [state, setState] = useState(() => initial(principal));
  const current = useRef(state); const request = useRef(null); const attempt = useRef(null); const alive = useRef(false);
  const publish = useCallback(value => { current.current = value; setState(value); }, []);
  const load = useCallback(async (query, trails) => {
    request.current?.abort();
    const controller = new AbortController(); request.current = controller;
    attempt.current = { query, trails };
    const previous = current.current.principal === principal ? current.current : initial(principal);
    publish({ ...previous, status: 'loading', error: null });
    try {
      const data = checkedSummary(await api.get(summaryQuery(query, trails), { signal: controller.signal }), query, trails);
      if (!alive.current || controller.signal.aborted) return;
      publish({ principal, status: 'ready', data, error: null, loadedAt: new Date(), version: previous.version + 1, trails,
        query: { ...query, asOf: data.as_of } });
    } catch (error) {
      if (!alive.current || controller.signal.aborted) return;
      if (accessDenied(error)) {
        publish({ ...initial(principal), status: 'error', error }); onDenied?.(error);
      } else publish({ ...current.current, status: 'error', error });
    }
  }, [principal, onDenied, publish]);
  useEffect(() => {
    alive.current = true;
    if (principal) void load({ limit: 5, asOf: null }, freshTrails());
    return () => { alive.current = false; request.current?.abort(); };
  }, [principal, load]);
  const reset = useCallback((limit = current.current.query.limit) => load({ limit, asOf: null }, freshTrails()), [load]);
  const retry = () => { if (attempt.current) void load(attempt.current.query, attempt.current.trails); };
  const navigate = (family, direction) => {
    const actual = current.current;
    if (!families.includes(family) || actual.status !== 'ready' || !actual.data) return;
    const trail = actual.trails[family]; const page = actual.data.work_hints[family];
    if ((direction === 'next' && !page.has_more) || (direction === 'previous' && trail.length === 1)) return;
    const next = direction === 'next' ? [...trail, page.next_after] : direction === 'previous' ? trail.slice(0, -1) : [null];
    void load(actual.query, { ...actual.trails, [family]: next });
  };
  return { ...(state.principal === principal ? state : initial(principal)), reset, retry, navigate };
}
