import { useEffect, useId, useState } from 'react';
import { checkedPage, queryString } from '../unitInventory/read';
import { DisputeFailure } from './DisputeOriginals';
import useDisputeRead from './useDisputeRead';

/** The shared read/parser, with a domain-wide denial fence for journal forms. */
export default function DisputeReferenceChoice({ kind, label, value = '', onChange, onResolved, principal, filters = {}, disabled = false, tr, onDenied }) {
  const id = useId(); const [search, setSearch] = useState(''); const [retry, setRetry] = useState(0);
  const [pages, setPages] = useState({ source: '', trail: [null] });
  const source = queryString({ ...filters, search, selected_id: value, page_size: 25 });
  const trail = pages.source === source ? pages.trail : [null];
  const state = useDisputeRead(`/workflow-references/${kind}?${source}${trail.at(-1) ? `&cursor=${encodeURIComponent(trail.at(-1))}` : ''}`,
    principal, retry, row => {
      if (!checkedPage(row) || value && row.selected !== null && row.selected?.id !== value) throw new Error('invalidDisputeResponse');
      return row;
    }, onDenied);
  useEffect(() => { onResolved?.(state.data?.selected || null); }, [state.data, onResolved]);
  const name = row => row.label || row.title || row.name || label;
  return <fieldset disabled={disabled} className="dispute-reference"><legend>{label}</legend>
    <label htmlFor={id}>{label} · {tr('search')}</label><input id={id} type="search" value={search} onChange={event => setSearch(event.target.value)} />
    {state.loading && <p role="status">{tr('loading')}</p>}{state.error && <DisputeFailure error={state.error} tr={tr} onRetry={() => setRetry(count => count + 1)} />}
    {value && <p>{state.data?.selected ? `${tr('selected')}: ${name(state.data.selected)}` : tr('selectionUnavailable')}
      <button type="button" className="btn btn-secondary" onClick={() => onChange('', null)}>{tr('remove')}</button></p>}
    {state.data && <>{!state.data.items.length ? <p>{tr('noChoices')}</p> : <ul>{state.data.items.map(row => <li key={row.id}><button className="btn btn-secondary" type="button" aria-pressed={row.id === value} onClick={() => onChange(row.id, row)}>{name(row)}</button></li>)}</ul>}
      <nav aria-label={`${label} · ${tr('page')}`} className="dispute-actions"><button className="btn btn-secondary" type="button" disabled={trail.length === 1} onClick={() => setPages({ source, trail: trail.slice(0, -1) })}>{tr('previous')}</button><span>{tr('page')} {trail.length}</span>
        <button className="btn btn-secondary" type="button" disabled={!state.data.has_more} onClick={() => setPages({ source, trail: [...trail, state.data.next_cursor] })}>{tr('next')}</button></nav></>}
  </fieldset>;
}
