import { useEffect, useState } from 'react';
import { api } from '../api';
import { annotateRevisions } from '../editRevision';

export function bookingFilterParams(filters) {
  return new URLSearchParams(Object.entries(filters).filter(([, value]) => value !== '' && value != null));
}

export default function useBookingPage(filters, cursor, pageSize, revision) {
  const params = bookingFilterParams(filters);
  params.set('page_size', pageSize);
  if (cursor) params.set('cursor', cursor);
  const query = params.toString();
  const sourceKey = `${query}:${revision}`;
  const [state, setState] = useState({ sourceKey: null, items: [], loading: true, error: null, hasMore: false, nextCursor: null });
  useEffect(() => {
    const controller = new AbortController();
    setState({ sourceKey, items: [], loading: true, error: null, hasMore: false, nextCursor: null });
    api.get(`/bookings/page?${query}`, { signal: controller.signal }).then(value => {
      if (controller.signal.aborted) return;
      if (!Array.isArray(value?.items) || typeof value.has_more !== 'boolean'
        || (value.has_more ? typeof value.next_cursor !== 'string' || !value.next_cursor : value.next_cursor !== null)) {
        throw new Error('bookingPages.invalidResult');
      }
      setState({ sourceKey, items: annotateRevisions(value.items, '/bookings'), loading: false, error: null,
        hasMore: value.has_more, nextCursor: value.next_cursor });
    }).catch(error => { if (!controller.signal.aborted) setState({ sourceKey, items: [], loading: false, error, hasMore: false, nextCursor: null }); });
    return () => controller.abort();
  }, [query, sourceKey]);
  return state.sourceKey === sourceKey ? state : { items: [], loading: true, error: null, hasMore: false, nextCursor: null };
}
