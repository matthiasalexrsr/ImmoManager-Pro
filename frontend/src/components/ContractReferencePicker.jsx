import { useEffect, useId, useState } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';

/** Bounded, source-bound choices; hydrate only the explicitly selected ID. */
export default function ContractReferencePicker({ kind, label, value = '', propertyId, disabled, required, onChange, onSelected }) {
  const { t } = useTranslation();
  const text = key => t(`contractWizard.workflow.${key}`);
  const id = useId();
  const [search, setSearch] = useState('');
  const [offset, setOffset] = useState(0);
  const [result, setResult] = useState({ items: [], selected: null, has_more: false });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    const timer = setTimeout(() => {
      setLoading(true); setError('');
      const query = new URLSearchParams({ search, offset: String(offset), limit: '25' });
      if (propertyId) query.set('property_id', propertyId);
      if (value) query.set('selected_id', value);
      api.get(`/contract-wizard/choices/${kind}?${query}`, { signal: controller.signal })
        .then(data => {
          if (!Array.isArray(data?.items) || typeof data.has_more !== 'boolean') throw new Error(text('malformed'));
          if (!controller.signal.aborted) setResult(data);
        }).catch(err => { if (!controller.signal.aborted) setError(err.message); })
        .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    }, 150);
    return () => { clearTimeout(timer); controller.abort(); };
    // Labels do not change reference identity or reset typed search.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind, propertyId, value, search, offset]);
  useEffect(() => { if (result.selected?.id === value) onSelected?.(result.selected); }, [result.selected, value, onSelected]);
  const choices = result.selected && !result.items.some(item => item.id === result.selected.id)
    ? [result.selected, ...result.items] : result.items;
  return <div className="contract-reference" aria-busy={loading}>
    <label htmlFor={id}>{label}{required && ' *'}</label>
    <div className="contract-reference-search"><input aria-label={`${label}: ${text('search')}`} value={search}
      placeholder={text('search')} disabled={disabled} onChange={event => { setSearch(event.target.value); setOffset(0); }}
      onKeyDown={event => { if (event.key === 'Enter') event.preventDefault(); }} />
      <span aria-live="polite">{loading ? text('loading') : result.items.length ? `${offset + 1}–${offset + result.items.length}` : '0'}</span></div>
    <select id={id} value={value} required={required} disabled={disabled || loading || (['units', 'documents'].includes(kind) && !propertyId)}
      onChange={event => onChange(event.target.value, choices.find(item => item.id === event.target.value))}>
      <option value="">{text('choose')}</option>
      {value && !choices.some(item => item.id === value) && <option value={value}>{text('unavailable')} · {value}</option>}
      {choices.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
    </select>
    <div className="contract-reference-pages"><button type="button" disabled={disabled || loading || offset === 0}
      onClick={() => setOffset(Math.max(0, offset - 25))}>{text('previous')}</button>
      <button type="button" disabled={disabled || loading || !result.has_more} onClick={() => setOffset(offset + 25)}>{text('next')}</button></div>
    {error && <p role="alert">{error}</p>}
  </div>;
}
