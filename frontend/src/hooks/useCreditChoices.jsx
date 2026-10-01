import { useEffect, useState } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';

const validChoice = (item, kind) => item && typeof item.id === 'string' && item.kind === kind
  && typeof item.date === 'string' && typeof item.text === 'string'
  && typeof item.available_amount === 'string' && /^\d+\.\d{2}$/.test(item.available_amount);

export default function useCreditChoices(contractId, kind, selectedId, label, enabled, generation) {
  const { t, locale } = useTranslation();
  const [search, setSearch] = useState('');
  const [history, setHistory] = useState([null]);
  const [index, setIndex] = useState(0);
  const [revision, setRevision] = useState(0);
  const params = new URLSearchParams({ page_size: '25' });
  if (search) params.set('search', search);
  if (selectedId) params.set('selected_id', selectedId);
  // A new choice type starts at its first page even if the old type had a cursor.
  const owner = `${contractId}:${kind}`;
  const [historyOwner, setHistoryOwner] = useState(owner);
  if (historyOwner === owner && history[index]) params.set('cursor', history[index]);
  const query = params.toString();
  const sourceKey = `${owner}:${query}:${revision}:${generation}`;
  const [result, setResult] = useState({ sourceKey: null });
  const state = result.sourceKey === sourceKey ? result : { items: [], selected: null, loading: true };
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      api.get(`/billing/contracts/${contractId}/credit-choices/${kind}?${query}`, { signal: controller.signal }).then(value => {
        if (controller.signal.aborted) return;
        if (value?.contract_id !== contractId || !Array.isArray(value.items)
          || !value.items.every(item => validChoice(item, kind)) || typeof value.has_more !== 'boolean'
          || (value.selected !== null && !validChoice(value.selected, kind))
          || (value.has_more ? typeof value.next_cursor !== 'string' || !value.next_cursor : value.next_cursor !== null)) {
          throw new Error('pages.statements.credits.invalidResponse');
        }
        setResult({ ...value, sourceKey, loading: false });
      }).catch(error => {
        if (!controller.signal.aborted) setResult({ sourceKey, items: [], selected: null, loading: false, error });
      });
    }, 150);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [enabled, contractId, kind, query, sourceKey]);
  const items = enabled ? [...(state.selected && !state.items.some(item => item.id === state.selected.id) ? [state.selected] : []), ...(state.items || [])] : [];
  const restart = () => { setHistoryOwner(owner); setHistory([null]); setIndex(0); setRevision(value => value + 1); };
  const currentIndex = historyOwner === owner ? index : 0;
  return {
    items,
    options: items.map(item => ({ value: kind === 'booking' ? item.id : `${kind}:${item.id}`,
      label: `${item.date} · ${new Intl.NumberFormat(locale, { style: 'currency', currency: 'EUR' }).format(item.available_amount)} · ${item.text || item.id}` })),
    disabled: enabled && (state.loading || Boolean(state.error)),
    hint: enabled && <span className="booking-choice-hint">
      <label>{t('bookingPages.findReference', { label })}<input type="search" name={`lookup_credit_${kind}`} maxLength={200}
        value={search} onChange={event => { setSearch(event.target.value); restart(); }}
        aria-label={t('bookingPages.findReference', { label })} /></label>
      {state.loading && <span role="status">{t('ui.table.loading')}</span>}
      {state.error && <span role="alert">{state.error.message === 'pages.statements.credits.invalidResponse' ? t(state.error.message) : state.error.message}
        <button type="button" onClick={restart}>{t('ui.buttons.retry')}</button></span>}
      {(currentIndex > 0 || state.has_more) && <span className="booking-choice-paging">
        <button type="button" disabled={!currentIndex || state.loading || Boolean(state.error)} onClick={() => setIndex(value => value - 1)}
          aria-label={t('bookingPages.previousChoices', { label })}>{t('ui.table.previousPage')}</button>
        <button type="button" disabled={!state.has_more || state.loading || Boolean(state.error)} onClick={() => {
          setHistoryOwner(owner); setHistory(previous => [...(historyOwner === owner ? previous.slice(0, index + 1) : [null]), state.next_cursor]); setIndex(currentIndex + 1);
        }} aria-label={t('bookingPages.nextChoices', { label })}>{t('ui.table.nextPage')}</button>
      </span>}
    </span>,
  };
}
