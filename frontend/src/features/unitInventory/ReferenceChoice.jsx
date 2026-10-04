import { useId, useState } from 'react';
import { checkedPage, errorMessage, queryString, usePrivateRead } from './read';

// A page plus one selected record; repeated navigation never grows a stock cache.
export default function ReferenceChoice({ kind, label, value = '', onChange, principal, filters = {}, required = false, disabled = false }) {
  const id = useId();
  const [search, setSearch] = useState('');
  const [pages, setPages] = useState({ source: '', trail: [null] });
  const [generation, setGeneration] = useState(0);
  const source = queryString({ ...filters, search, selected_id: value, page_size: 25 });
  const trail = pages.source === source ? pages.trail : [null];
  const result = usePrivateRead(`/workflow-references/${kind}?${source}${trail.at(-1) ? `&cursor=${encodeURIComponent(trail.at(-1))}` : ''}`, principal, generation);
  const valid = checkedPage(result.data);
  const page = valid ? result.data : null;
  const failure = result.error || (!result.loading && !valid ? new Error('Ungültige Auswahlseite.') : null);
  const name = row => row.name || row.label || row.contract_number || row.title || 'Ohne Bezeichnung';
  return <fieldset className="inventory-reference" disabled={disabled}>
    <legend>{label}{required ? ' *' : ''}</legend>
    <label htmlFor={id}>{label} suchen</label>
    <input id={id} type="search" value={search} onChange={event => setSearch(event.target.value)} autoComplete="off" />
    {value && <p>{result.loading ? 'Auswahl wird geprüft …' : page?.selected ? `Ausgewählt: ${name(page.selected)}` : 'Die bisherige Auswahl ist nicht verfügbar. Bitte erneut auswählen.'}
      <button className="btn btn-secondary btn-sm" type="button" onClick={() => onChange('', null)}>Auswahl entfernen</button></p>}
    {result.loading && <p role="status">Auswahl wird geladen …</p>}
    {failure && <div role="alert">{errorMessage(failure)} <button type="button" className="btn btn-secondary" onClick={() => { setPages({ source, trail: [null] }); setGeneration(g => g + 1); }}>Erneut laden</button></div>}
    {page && <><ul>{page.items.map(row => <li key={row.id}><button type="button" className="btn btn-secondary"
      aria-pressed={row.id === value} onClick={() => onChange(row.id, row)}>{name(row)}{row.tenant_name ? ` · ${row.tenant_name}` : ''}</button></li>)}</ul>
      {!page.items.length && <p>Keine passenden Einträge auf dieser Seite.</p>}
      <nav aria-label={`${label} Auswahlseiten`} className="inventory-pager">
        <button className="btn btn-secondary btn-sm" type="button" disabled={trail.length === 1} onClick={() => setPages({ source, trail: trail.slice(0, -1) })}>Vorherige Auswahlseite</button>
        <span>Seite {trail.length}</span>
        <button className="btn btn-secondary btn-sm" type="button" disabled={!page.has_more} onClick={() => setPages({ source, trail: [...trail, page.next_cursor] })}>Nächste Auswahlseite</button>
      </nav></>}
  </fieldset>;
}
