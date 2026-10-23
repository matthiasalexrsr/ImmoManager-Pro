import { useEffect, useRef, useState } from 'react';

/** Offset pages retain successful rows on retry and reject replies from an older filter. */
export default function usePagedDunning(load, scope, limit = 50) {
  const [attempt, setAttempt] = useState(0);
  const key = `${scope}/${attempt}`;
  const [state, setState] = useState({ key: null, data: null, loading: true, error: null });
  const loader = useRef(load);
  loader.current = load;
  const request = useRef(null);
  const currentKey = useRef(key);
  currentKey.current = key;
  const view = state.key === key ? state : { data: null, loading: true, error: null };

  useEffect(() => {
    const fetchPage = loader.current;
    const task = { key, controller: new AbortController() };
    request.current = task;
    setState({ key, data: null, loading: true, error: null });
    Promise.resolve().then(() => fetchPage({ offset: 0, limit }, { signal: task.controller.signal }))
      .then(data => {
        if (request.current === task && currentKey.current === key) setState({ key, data, loading: false, error: null });
      }).catch(error => {
        if (request.current === task && currentKey.current === key) setState({ key, data: null, loading: false, error: error.message });
      });
    return () => {
      task.controller.abort();
      if (request.current?.key === key) { request.current.controller.abort(); request.current = null; }
    };
  }, [key, limit]);

  const more = async () => {
    if (view.loading || view.moreLoading || !view.data || view.data.items.length >= view.data.total
        || request.current?.pending) return;
    const task = { key, controller: new AbortController(), pending: true };
    request.current = task;
    setState(previous => ({ ...previous, moreLoading: true, error: null }));
    try {
      const next = await loader.current({ offset: view.data.items.length, limit }, { signal: task.controller.signal });
      if (request.current !== task || currentKey.current !== key) return;
      setState(previous => ({ key, data: { ...next, items: [...new Map(
        [...previous.data.items, ...next.items].map(row => [row.id, row])).values()] }, loading: false, error: null }));
    } catch (error) {
      if (request.current === task && currentKey.current === key) setState(previous => ({ ...previous,
        moreLoading: false, error: error.message, failedMore: true }));
    } finally {
      task.pending = false;
    }
  };
  const reload = () => { request.current?.controller.abort(); currentKey.current = null; setAttempt(value => value + 1); };
  return [{ ...view, more }, reload, view.failedMore ? more : reload];
}
