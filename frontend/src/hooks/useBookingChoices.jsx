import { useEffect, useState } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';

const choice = value => value && typeof value.id === 'string' && typeof value.label === 'string';

export default function useBookingChoices(kind, selectedId, label) {
  const { t } = useTranslation();
  const [search, setSearch] = useState('');
  const [history, setHistory] = useState([null]);
  const [index, setIndex] = useState(0);
  const [revision, setRevision] = useState(0);
  const params = new URLSearchParams({ page_size: '25' });
  if (search) params.set('search', search);
  if (selectedId) params.set('selected_id', selectedId);
  if (history[index]) params.set('cursor', history[index]);
  const query = params.toString();
  const sourceKey = `${kind}:${query}:${revision}`;
  const [result, setResult] = useState({ sourceKey: null, items: [], selected: null, loading: true, error: null });
  const state = result.sourceKey === sourceKey ? result : { items: [], selected: null, loading: true, error: null };
  useEffect(() => {
    const controller = new AbortController();
    const timer = setTimeout(() => {
      api.get(`/bookings/lookup/${kind}?${query}`, { signal: controller.signal }).then(value => {
        if (controller.signal.aborted) return;
        if (!Array.isArray(value?.items) || !value.items.every(choice) || typeof value.has_more !== 'boolean'
          || (value.selected !== null && !choice(value.selected))
          || (value.has_more ? typeof value.next_cursor !== 'string' || !value.next_cursor : value.next_cursor !== null)) {
          throw new Error('bookingPages.invalidResult');
        }
        setResult({ ...value, sourceKey, loading: false, error: null });
      }).catch(error => { if (!controller.signal.aborted) setResult({ sourceKey, items: [], selected: null, loading: false, error }); });
    }, 150);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [kind, query, sourceKey]);
  const items = [...(state.selected && !state.items.some(item => item.id === state.selected.id) ? [state.selected] : []), ...state.items];
  const restart = () => { setHistory([null]); setIndex(0); setRevision(value => value + 1); };
  return {
    options: items.map(item => ({ value: item.id, label: item.label })),
    disabled: state.loading || Boolean(state.error),
    hint: <span className="booking-choice-hint">
      <label>{t('bookingPages.findReference', { label })}<input type="search" name={`lookup_${kind}`} maxLength={200}
        value={search} onChange={event => { setSearch(event.target.value); setHistory([null]); setIndex(0); }}
        aria-label={t('bookingPages.findReference', { label })} /></label>
      {state.loading && <span role="status">{t('ui.table.loading')}</span>}
      {state.error && <span role="alert">{state.error.message === 'bookingPages.invalidResult' ? t(state.error.message) : state.error.message}
        <button type="button" onClick={restart}>{t('bookingPages.retry')}</button></span>}
      {(index > 0 || state.has_more) && <span className="booking-choice-paging"><button type="button" disabled={!index || state.loading || Boolean(state.error)} onClick={() => setIndex(value => value - 1)}
        aria-label={t('bookingPages.previousChoices', { label })}>{t('bookingPages.previous')}</button>
        <button type="button" disabled={!state.has_more || state.loading || Boolean(state.error)}
          aria-label={t('bookingPages.nextChoices', { label })} onClick={() => {
            setHistory(previous => [...previous.slice(0, index + 1), state.next_cursor]); setIndex(value => value + 1);
          }}>{t('bookingPages.next')}</button></span>}
    </span>,
  };
}
