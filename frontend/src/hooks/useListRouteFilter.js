import { useSearchParams } from 'react-router-dom';

/** Workflow filters travel with links and browser history, including named views. */
export default function useListRouteFilter(allowed, exactKeys = ['focus_id']) {
  const [params, setParams] = useSearchParams();
  const focused = exactKeys.some(key => params.get(key));
  const requested = params.get('status') || params.get('filter') || 'all';
  const filter = !focused && allowed.includes(requested) ? requested : 'all';
  const setFilter = value => setParams(current => {
    const next = new URLSearchParams(current);
    ['filter', 'status', 'suche', ...exactKeys].forEach(key => next.delete(key));
    if (allowed.includes(value) && value !== 'all') next.set('filter', value);
    return next;
  });
  return [filter, setFilter, params];
}
