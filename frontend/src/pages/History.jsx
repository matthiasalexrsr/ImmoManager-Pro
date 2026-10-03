import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api';
import { useAuth } from '../contexts/AuthContext';
import { checkedPage, errorMessage, principalKey, queryString, usePrivateRead } from '../features/unitInventory/read';
import '../features/unitInventory/UnitInventory.css';
import './History.css';

const defaults = { search: '', entity_type: '', entity_id: '', field_name: '', changed_by: '', changed_from: '', changed_before: '' };
const requiredFields = ['entity_type', 'entity_id', 'field_name'];
const optionalFields = ['old_value', 'new_value', 'changed_by', 'reason'];
const entityNames = { property: 'Immobilie', unit: 'Einheit', contract: 'Mietvertrag', tenant: 'Mieter',
  contact: 'Kontakt', insurance: 'Versicherung', document: 'Dokument', booking: 'Buchung' };
const zoned = value => /(?:Z|[+-]\d\d:\d\d)$/.test(value) ? value : `${value}Z`;
function validPage(data) {
  return checkedPage(data) && data.items.every(row => requiredFields.every(field => typeof row[field] === 'string')
    && optionalFields.every(field => row[field] === null || typeof row[field] === 'string')
    && (row.changed_at === null || typeof row.changed_at === 'string' && Number.isFinite(Date.parse(zoned(row.changed_at)))));
}
const displayTime = value => value === null ? 'Zeitpunkt nicht erfasst' : new Date(zoned(value)).toLocaleString('de-DE');
const utcInput = value => value ? Number.isFinite(Date.parse(value)) ? new Date(value).toISOString() : value : '';

function HistoryInventory({ principal, updateUser }) {
  const [filters, setFilters] = useState(defaults); const [pages, setPages] = useState({ source: '', trail: [null] });
  const [generation, setGeneration] = useState(0); const [authority, setAuthority] = useState({ checking: true, verified: false, error: null });
  const [exporting, setExporting] = useState(false); const [exportError, setExportError] = useState(null);
  const alive = useRef(true); const authRequest = useRef(null); const exportRequest = useRef(null); const filterEpoch = useRef(0);
  const verify = useCallback(async () => {
    authRequest.current?.abort(); exportRequest.current?.abort(); setExporting(false); setExportError(null);
    const controller = new AbortController(); authRequest.current = controller;
    setAuthority({ checking: true, verified: false, error: null });
    try {
      const user = await api.get('/auth/me', { signal: controller.signal });
      if (!alive.current || controller.signal.aborted) return false;
      if (typeof user?.id !== 'string' || !user.id || typeof user?.role !== 'string' || !user.role) throw new Error('Die Anmeldung konnte nicht geprüft werden.');
      if (principalKey(user) !== principal) {
        setAuthority({ checking: false, verified: false, error: new Error('Die Zugriffsrechte wurden geändert. Bitte die Historie neu öffnen.') });
        updateUser?.(user); return false;
      }
      setGeneration(value => value + 1); setAuthority({ checking: false, verified: true, error: null }); return true;
    } catch (error) {
      if (alive.current && !controller.signal.aborted) setAuthority({ checking: false, verified: false, error }); return false;
    }
  }, [principal, updateUser]);
  useEffect(() => {
    alive.current = true; if (principal) void verify();
    const focus = () => { if (document.visibilityState === 'visible') void verify(); };
    window.addEventListener('focus', focus); document.addEventListener('visibilitychange', focus);
    return () => { alive.current = false; authRequest.current?.abort(); exportRequest.current?.abort();
      window.removeEventListener('focus', focus); document.removeEventListener('visibilitychange', focus); };
  }, [principal, verify]);
  const query = queryString({ ...filters, changed_from: utcInput(filters.changed_from), changed_before: utcInput(filters.changed_before), page_size: 25 });
  const trail = pages.source === query ? pages.trail : [null];
  const available = Boolean(principal) && authority.verified && !authority.checking;
  const state = usePrivateRead(available ? `/history/inventory/page?${query}${trail.at(-1) ? `&cursor=${encodeURIComponent(trail.at(-1))}` : ''}` : null, principal, generation);
  const summary = usePrivateRead(available ? `/history/inventory/summary?${query}` : null, principal, generation);
  const page = available && validPage(state.data) ? state.data : null;
  const failure = available && (state.error || (!state.loading && !page ? new Error('Die Historienantwort konnte nicht geprüft werden.') : null));
  const total = available && Number.isSafeInteger(summary.data?.total) && summary.data.total >= 0 ? summary.data.total : null;
  const denied = failure && [401, 403, 404].includes(failure.statusCode) || summary.error && [401, 403, 404].includes(summary.error.statusCode);
  const change = (key, value) => { filterEpoch.current += 1; exportRequest.current?.abort(); setExporting(false); setExportError(null); setFilters(current => ({ ...current, [key]: value })); };
  const refresh = async () => { if (await verify() && alive.current) setPages({ source: query, trail: [null] }); };
  const navigate = async nextTrail => { if (await verify() && alive.current) setPages({ source: query, trail: nextTrail }); };
  const download = async () => {
    const selectedEpoch = filterEpoch.current;
    if (!await verify() || !alive.current || selectedEpoch !== filterEpoch.current) return;
    const controller = new AbortController(); exportRequest.current = controller; setExporting(true);
    try {
      const blob = await api.getBlob(`/history/inventory/export?${query}`, { signal: controller.signal });
      if (!alive.current || controller.signal.aborted) return;
      if (!(blob instanceof Blob) || !blob.size) throw new Error('Der Export enthält keine prüfbare Datei. Bitte erneut starten.');
      const url = URL.createObjectURL(blob); const anchor = document.createElement('a');
      anchor.href = url; anchor.download = 'aenderungshistorie.csv'; anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) { if (alive.current && !controller.signal.aborted) setExportError(error); }
    finally { if (alive.current && !controller.signal.aborted) setExporting(false); }
  };

  return <div className="page unit-inventory history-inventory">
    <header className="inventory-heading"><div><h1 className="page-title">Änderungshistorie</h1><p className="text-muted">Gespeicherte Feldänderungen suchen und ihre ursprünglichen Werte nachvollziehen.</p></div></header>
    {!principal || authority.error ? <div className="panel inventory-error" role="alert">{!principal ? 'Bitte anmelden, um die Historie zu öffnen.' : errorMessage(authority.error)}
      {principal && <button className="btn btn-secondary" onClick={() => { void verify(); }}>Zugriff erneut prüfen</button>}</div> : authority.checking ? <p role="status">Zugriff wird geprüft …</p> : <>
      <section className="panel inventory-filters" aria-label="Historie filtern">
        <label>Historie durchsuchen<input type="search" value={filters.search} onChange={event => change('search', event.target.value)} placeholder="Kennung, Feld, Wert oder Änderungsgrund" /></label>
        {[['changed_from', 'Geändert ab'], ['changed_before', 'Geändert vor']].map(([key, label]) => <label key={key}>{label}<input type="datetime-local" step="1" value={filters[key]} onChange={event => change(key, event.target.value)} /></label>)}
        <details className="history-advanced"><summary>Weitere Filter</summary><div className="history-extra-filters">
          <label>Bereich<select value={filters.entity_type} onChange={event => change('entity_type', event.target.value)}><option value="">Alle Bereiche</option>{Object.entries(entityNames).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          {[['entity_id', 'Datensatzkennung'], ['field_name', 'Geändertes Feld'], ['changed_by', 'Bearbeiterkennung']].map(([key, label]) => <label key={key}>{label}<input value={filters[key]} onChange={event => change(key, event.target.value)} /></label>)}
        </div></details>
        <button className="btn btn-secondary" onClick={() => { filterEpoch.current += 1; exportRequest.current?.abort(); setExporting(false); setExportError(null); setFilters(defaults); }}>Filter zurücksetzen</button>
      </section>
      <div className="inventory-actions"><button className="btn btn-secondary" onClick={() => { void refresh(); }}>Aktualisieren</button>
        <button className="btn btn-secondary" disabled={exporting || Boolean(denied)} onClick={() => { void download(); }}>{exporting ? 'Export wird erstellt …' : 'Alle gefilterten Änderungen exportieren'}</button></div>
      {exportError && <div className="panel inventory-error" role="alert">{errorMessage(exportError)}</div>}
      {!denied && <section className="panel history-count" aria-label="Treffer im gesamten berechtigten Bestand">{summary.loading ? <span role="status">Treffer werden gezählt …</span> : total !== null ? <><strong>{total.toLocaleString('de-DE')}</strong> gespeicherte Feldänderungen passen zu den Filtern.</> : <span role="alert">Trefferzahl nicht verfügbar. {errorMessage(summary.error)}</span>}</section>}
      {state.loading && <p role="status">Änderungen werden geladen …</p>}
      {(failure || denied) && <div className="panel inventory-error" role="alert">{errorMessage(failure || summary.error)} <button className="btn btn-secondary" onClick={() => { void refresh(); }}>Erneut laden</button></div>}
      {!denied && page && <section className="panel inventory-results" aria-label="Gespeicherte Feldänderungen">
        {!page.items.length ? <p>Keine passenden Änderungen auf dieser Seite.</p> : <div className="inventory-table-scroll" tabIndex={0} role="region" aria-label="Gespeicherte Änderungen"><table role="table">
          <thead role="rowgroup"><tr role="row">{['Zeitpunkt', 'Bereich', 'Feld', 'Bearbeiterkennung', 'Änderung'].map(label => <th role="columnheader" scope="col" key={label}>{label}</th>)}</tr></thead>
          <tbody role="rowgroup">{page.items.map(row => <tr role="row" key={row.id}><td role="cell" data-label="Zeitpunkt">{displayTime(row.changed_at)}</td><td role="cell" data-label="Bereich">{entityNames[row.entity_type] || row.entity_type}<span className="history-identity">{row.entity_id}</span></td>
            <th role="rowheader" scope="row" data-label="Feld">{row.field_name}</th><td role="cell" data-label="Bearbeiterkennung">{row.changed_by ?? 'Nicht erfasst'}</td><td role="cell" className="history-change"><details><summary>Werte und Grund anzeigen</summary><dl className="history-values"><dt>Vorher</dt><dd>{row.old_value ?? 'Nicht erfasst'}</dd><dt>Nachher</dt><dd>{row.new_value ?? 'Nicht erfasst'}</dd><dt>Grund</dt><dd>{row.reason ?? 'Nicht erfasst'}</dd><dt>Änderungskennung</dt><dd>{row.id}</dd></dl></details></td></tr>)}</tbody>
        </table></div>}
        <nav className="inventory-pager" aria-label="Historienseiten"><button className="btn btn-secondary" disabled={trail.length === 1} onClick={() => { void navigate(trail.slice(0, -1)); }}>Vorherige Seite</button>
          <span>Seite {trail.length}</span><button className="btn btn-secondary" disabled={!page.has_more} onClick={() => { void navigate([...trail, page.next_cursor]); }}>Nächste Seite</button></nav>
        <p className="text-muted">Zeitangaben in deiner Ortszeit. Neueste Änderungen zuerst. Neue Einträge erscheinen nach dem Aktualisieren. Trefferzahl und Export umfassen alle passenden berechtigten Einträge; Seiten sind eine laufende Ansicht.</p>
      </section>}
    </>}
  </div>;
}

export default function History() {
  const { user, updateUser } = useAuth() || {}; const principal = principalKey(user);
  return <HistoryInventory key={principal} principal={principal} updateUser={updateUser} />;
}
