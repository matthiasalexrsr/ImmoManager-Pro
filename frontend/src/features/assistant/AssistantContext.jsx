import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Search, X, FileCheck2 } from 'lucide-react';
import { api } from '../../api';
import { assistantApi, contextSelection } from './assistantApi';
import { contextHref } from './assistantLinks';
import AssistantReportSelection, { FinancialProof } from './AssistantReportSelection';
import AssistantFindings from './AssistantFindings';

const kinds = { property: 'Immobilie', unit: 'Einheit', tenant: 'Partei', contact: 'Kontakt', document: 'Dokument', contract: 'Mietvertrag', booking: 'Buchung', receivable: 'Forderung', invoice: 'Rechnung', task: 'Aufgabe', maintenance: 'Instandhaltung', meter: 'Zähler', standalone_reading: 'Ablesung', calendar: 'Termin', utility_statement: 'Nebenkostenabrechnung', billing_period: 'Abrechnungszeitraum', service_contract: 'Dienstleistungsvertrag', portfolio: 'Bestand' };
export default function AssistantContext({ cards, onChange, disabled, report, onReportChange }) {
  const [expanded, setExpanded] = useState(false);
  const [kind, setKind] = useState('property');
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [bundle, setBundle] = useState(null);
  const generation = useRef(0), alive = useRef(false), selectionRef = useRef(null);
  selectionRef.current = { selection: contextSelection(cards), report };
  useEffect(() => { alive.current = true; return () => { alive.current = false; generation.current += 1; }; }, []);
  const selectedKey = JSON.stringify({ selection: contextSelection(cards), report });
  useEffect(() => { setBundle(null); }, [selectedKey]);
  const search = async (cursor = null) => {
    const epoch = ++generation.current; const session = api.captureSession(); setBusy(true); setError('');
    try {
      const params = new URLSearchParams({ q: query, type: kind, limit: '20', semantic: 'false' }); if (cursor) params.set('cursor', cursor);
      const response = await api.get(`/search?${params}`); session();
      if (!alive.current || epoch !== generation.current) return;
      if (!Array.isArray(response.results)) throw new Error('Die Aktensuche hat eine unvollständige Antwort geliefert.');
      setPage(previous => ({ ...response, results: cursor ? [...(previous?.results || []), ...response.results] : response.results }));
    } catch (failure) { if (alive.current && epoch === generation.current) setError(failure.message); }
    finally { if (alive.current && epoch === generation.current) setBusy(false); }
  };
  const preview = async () => {
    const epoch = ++generation.current; const session = api.captureSession(); const expected = selectedKey;
    setBusy(true); setError('');
    try {
      const response = await assistantApi.previewContext(contextSelection(cards), report); session();
      if (!alive.current || epoch !== generation.current || JSON.stringify(selectionRef.current) !== expected) return;
      setBundle({ ...(response.context || response), findings: response.findings || [], documents: response.documents || [], finance: response.finance });
    } catch (failure) { if (alive.current && epoch === generation.current) setError(failure.message); }
    finally { if (alive.current && epoch === generation.current) setBusy(false); }
  };
  return <div className="assistant-context-panel">
    <div className="assistant-composer-actions"><h3>Aktenkontext ({cards.length})</h3><button className="btn btn-sm btn-secondary" type="button" disabled={disabled} aria-expanded={expanded} onClick={() => setExpanded(value => !value)}>{expanded ? 'Aktensuche schließen' : 'Akte hinzufügen'}</button></div>
    {cards.length > 0 && <div className="assistant-context-grid">{cards.map(card => <div className="assistant-context-card" key={`${card.kind}:${card.id}`}>
      <FileCheck2 size={17} aria-hidden="true" /><div><strong>{card.title}</strong><small>{kinds[card.kind]}{card.detail ? ` · ${card.detail}` : ''}</small><Link to={contextHref(card)}>Akte öffnen →</Link></div>
      <button type="button" className="assistant-remove" aria-label={`Kontext entfernen: ${card.title}`} disabled={disabled} onClick={() => onChange(cards.filter(item => item.kind !== card.kind || item.id !== card.id))}><X size={15} /></button>
    </div>)}</div>}
    {expanded && <div>
      <div className="assistant-context-search"><select aria-label="Aktenart" value={kind} disabled={busy || disabled} onChange={event => { generation.current += 1; setKind(event.target.value); setPage(null); }}>{Object.entries(kinds).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
        <input aria-label="Akten durchsuchen" placeholder="Name, Anschrift oder Bezeichnung" value={query} onChange={event => { generation.current += 1; setQuery(event.target.value); setBusy(false); setPage(null); }} onKeyDown={event => { if (event.key === 'Enter') { event.preventDefault(); event.stopPropagation(); if (!busy && !disabled && query.trim()) search(); } }} />
        <button className="btn btn-secondary" type="button" disabled={busy || disabled || !query.trim()} aria-label="Akten suchen" onClick={() => search()}><Search size={16} /></button></div>
      {page && <ul className="assistant-context-results">{page.results.filter(item => kinds[item.entity_type]).map(item => <li key={`${item.entity_type}:${item.id}`}><div><strong>{item.display}</strong><small>{item.detail}</small></div><button type="button" className="btn btn-sm btn-secondary" disabled={disabled || cards.some(card => card.kind === item.entity_type && card.id === item.id)} onClick={() => onChange([...cards, { kind: item.entity_type, id: item.id, title: item.display, detail: item.detail || '' }])}>Hinzufügen</button></li>)}</ul>}
      {page?.next_cursor && <button className="btn btn-sm btn-secondary" type="button" disabled={busy || disabled} onClick={() => search(page.next_cursor)}>Weitere Akten laden</button>}
      {page && page.results.length === 0 && <p>Keine passenden berechtigten Akten gefunden.</p>}
    </div>}
    <AssistantReportSelection cards={cards} report={report} onChange={onReportChange} disabled={busy || disabled} />
    {cards.length > 0 && <button className="btn btn-sm btn-secondary" type="button" disabled={busy || disabled || Boolean(report && !report.as_of)} onClick={preview}>Ausgewählte Quellen lokal prüfen</button>}
    {busy && <p role="status">Quellen werden gelesen …</p>}
    {error && <p role="alert">{error}</p>}
    {bundle && <div className="assistant-context-proof"><p>{bundle.sources?.length || 0} Quellen lokal gelesen</p>
      {(bundle.warnings || []).map((warning, index) => <p role="status" key={index}>{typeof warning === 'string' ? warning : warning.message}</p>)}
      <AssistantFindings findings={bundle.findings} />
      <FinancialProof finance={bundle.finance} report={report} />
      <details><summary>Quellstände ansehen</summary><p>Quellenpaket {bundle.sha256}</p>{(bundle.sources || []).map(source => <p key={`${source.kind}:${source.id}`}><strong>{source.title}</strong> · Stand {source.revision}{source.sha256 ? ` · SHA-256 ${source.sha256}` : ''}</p>)}</details>
    </div>}
  </div>;
}
