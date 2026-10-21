import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../../api';

// Business feeds keep their last successful page on a failed retry. A query change
// owns a new session: late pages must never be appended to another entity/filter.
export default function useCursorFeed(path, enabled = true, loadPage = api.get) {
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState({ path: null, items: [], loading: false, error: null, next_cursor: null });
  const session = useRef(null);
  const more = useRef(null);
  useEffect(() => {
    if (!enabled) return undefined;
    const request = new AbortController();
    session.current = request;
    more.current = null;
    setState(previous => ({ path, items: previous.path === path ? previous.items : [], loading: true, loadingMore: false, error: null, next_cursor: null }));
    loadPage(path, { signal: request.signal }).then(page => {
      if (!Array.isArray(page?.items)) throw new Error('Die Liste konnte nicht gelesen werden.');
      if (!request.signal.aborted) setState({ ...page, path, loading: false, loadingMore: false, error: null });
    }).catch(error => {
      if (!request.signal.aborted) setState(previous => ({ ...previous, loading: false, error: error.message }));
    });
    return () => { request.abort(); if (session.current === request) session.current = null; more.current?.abort(); };
  }, [path, enabled, attempt, loadPage]);
  const retry = useCallback(updateItem => {
    // A successful command may supply its authoritative row immediately. Stop
    // older reads synchronously so they cannot undo that row before the effect
    // for the fresh request starts. Ordinary retry clicks pass no transformer.
    session.current?.abort(); more.current?.abort(); more.current = null;
    setState(previous => ({ ...previous, loading: true, loadingMore: false,
      items: typeof updateItem === 'function' ? previous.items.map(updateItem) : previous.items }));
    setAttempt(value => value + 1);
  }, []);
  const loadMore = useCallback(() => {
    if (!enabled || !state.next_cursor || state.loading || more.current || state.path !== path) return;
    const owner = session.current;
    const request = new AbortController();
    more.current = request;
    setState(previous => ({ ...previous, loadingMore: true, error: null }));
    return loadPage(`${path}${path.includes('?') ? '&' : '?'}cursor=${encodeURIComponent(state.next_cursor)}`, { signal: request.signal }).then(page => {
      if (!Array.isArray(page?.items)) throw new Error('Die nächste Seite konnte nicht gelesen werden.');
      if (request.signal.aborted || session.current !== owner) return;
      setState(previous => {
        const identity = item => item.work_item_key ?? item.document_id ?? item.id;
        const seen = new Set(previous.items.map(identity));
        return { ...previous, ...page, items: [...previous.items, ...page.items.filter(item => !seen.has(identity(item)))], error: null };
      });
      return page;
    }).catch(error => {
      if (!request.signal.aborted && session.current === owner) setState(previous => ({ ...previous, error: error.message }));
    }).finally(() => {
      if (more.current === request) { more.current = null; setState(previous => ({ ...previous, loadingMore: false })); }
    });
  }, [enabled, state, path, loadPage]);
  return { ...(state.path === path && enabled ? state : { items: [], loading: enabled, error: null }), retry, loadMore };
}
