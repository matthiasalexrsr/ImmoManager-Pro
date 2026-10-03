import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../../api';
import { revisionOptions } from '../../editRevision';
import { useAuth } from '../../contexts/AuthContext';
import { useDataStore } from '../../contexts/DataStoreContext';
import { useTranslation } from '../../i18n';
import { useConfirm } from '../../components/ConfirmDialog';
import FormModal from '../../components/FormModal';
import useWriteAccess from '../../hooks/useWriteAccess';
import ReferenceChoice from './ReferenceChoice';
import { checkedPage, errorMessage, principalKey, queryString, usePrivateRead } from './read';
import './UnitInventory.css';

const defaults = { search: '', status: '', unit_type: '', property_id: '', view: 'all', area_min: '', area_max: '', rent_min: '', rent_max: '', sort_by: 'label', sort_order: 'asc' };
const types = { apartment: 'Wohnung', commercial: 'Gewerbe', parking: 'Stellplatz', basement: 'Keller', other: 'Sonstiges' };
const statuses = { vacant: 'Leer', occupied: 'Vermietet', rented: 'Vermietet (Altbestand)', reserved: 'Reserviert' };
const named = (labels, value) => Object.hasOwn(labels, value) ? labels[value] : value;

function Inventory({ principal }) {
  const { locale = 'de-DE' } = useTranslation();
  const confirm = useConfirm();
  const store = useDataStore();
  const [filters, setFilters] = useState(defaults);
  const [pages, setPages] = useState({ source: '', trail: [null] });
  const [generation, setGeneration] = useState(0);
  const [modal, setModal] = useState(null);
  const [property, setProperty] = useState('');
  const [actionError, setActionError] = useState(null);
  const [exporting, setExporting] = useState(false);
  const exportRequest = useRef(null);
  const alive = useRef(true);
  const { canWrite, isAllowed, requireWrite } = useWriteAccess('/units', () => setModal(null));
  useEffect(() => { alive.current = true; return () => { alive.current = false; exportRequest.current?.abort(); }; }, []);
  const query = queryString({ ...filters, page_size: 25 });
  const trail = pages.source === query ? pages.trail : [null];
  const state = usePrivateRead(`/units/inventory/page?${query}${trail.at(-1) ? `&cursor=${encodeURIComponent(trail.at(-1))}` : ''}`, principal, generation);
  const summary = usePrivateRead(`/units/inventory/summary?${query}`, principal, generation);
  const page = checkedPage(state.data) ? state.data : null;
  const failure = state.error || (!state.loading && !page ? new Error('Die Listenantwort ist ungültig.') : null);
  const stats = summary.data && ['total', 'rent_count', 'occupied', 'vacant', 'reserved', 'multiple_active'].every(key => Number.isInteger(summary.data[key]) && summary.data[key] >= 0) ? summary.data : null;
  const money = value => value == null ? '—' : new Intl.NumberFormat(locale, { style: 'currency', currency: 'EUR' }).format(Number(value));
  const number = value => value == null ? '—' : new Intl.NumberFormat(locale).format(value);
  const change = (key, value) => { exportRequest.current?.abort(); setExporting(false); setActionError(null); setFilters(current => ({ ...current, [key]: value })); };
  const refresh = () => { setPages({ source: query, trail: [null] }); setGeneration(value => value + 1); };
  const open = row => { setProperty(row?.property_id || ''); setModal(row || 'create'); };
  const updated = () => { refresh(); store?.invalidateRelated('units', 'properties', 'contracts'); };
  const save = async payload => {
    requireWrite();
    if (!property) throw new Error('Bitte eine Immobilie auswählen.');
    const data = { ...payload, property_id: property };
    if (modal === 'create') await api.post('/units', data);
    else await api.put(`/units/${encodeURIComponent(modal.id)}`, data, revisionOptions(modal));
  };
  const remove = async row => {
    if (!isAllowed() || !await confirm(`„${row.label}“ wirklich löschen?`) || !isAllowed()) return;
    try { await api.del(`/units/${encodeURIComponent(row.id)}`, revisionOptions(row)); if (alive.current) updated(); }
    catch (error) { if (alive.current) setActionError(error); }
  };
  const download = async () => {
    exportRequest.current?.abort();
    const controller = new AbortController(); exportRequest.current = controller;
    setExporting(true); setActionError(null);
    try {
      const blob = await api.getBlob(`/units/inventory/export?${query}`, { signal: controller.signal });
      if (controller.signal.aborted || !alive.current) return;
      const url = URL.createObjectURL(blob); const link = document.createElement('a');
      link.href = url; link.download = 'einheiten.csv'; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) { if (!controller.signal.aborted && alive.current) setActionError(error); }
    finally { if (!controller.signal.aborted && alive.current) setExporting(false); }
  };
  const fields = [
    { key: 'label', label: 'Bezeichnung', required: true },
    { key: 'unit_type', label: 'Art', required: true, type: 'select', options: [...Object.entries(types), ...(modal?.unit_type && !Object.hasOwn(types, modal.unit_type) ? [[modal.unit_type, modal.unit_type]] : [])].map(([value, label]) => ({ value, label })) },
    { key: 'status', label: 'Gespeicherter Status', type: 'select', default: 'vacant', options: [...Object.entries(statuses), ...(modal?.status && !Object.hasOwn(statuses, modal.status) ? [[modal.status, modal.status]] : [])].map(([value, label]) => ({ value, label })) },
    { key: 'floor', label: 'Etage' }, { key: 'area_sqm', label: 'Fläche (m²)', type: 'number' },
    { key: 'rooms', label: 'Zimmer', type: 'number' }, { key: 'person_count', label: 'Personenzahl', type: 'number', step: 1 },
    { key: 'cold_rent', label: 'Kaltmiete (€)', type: 'number' }, { key: 'service_charge_advance', label: 'Nebenkostenvorauszahlung (€)', type: 'number' },
    { key: 'heating_advance', label: 'Heizkostenvorauszahlung (€)', type: 'number' }, { key: 'features', label: 'Ausstattung', type: 'textarea' },
  ];
  return <div className="page unit-inventory">
    <header className="inventory-heading"><div><h1 className="page-title">Einheiten</h1><p className="text-muted">Bestand durchsuchen, Angaben prüfen und Einheiten verwalten.</p></div>
      <div className="inventory-actions"><button className="btn btn-secondary" onClick={refresh}>Aktualisieren</button>{canWrite && <button className="btn btn-primary" onClick={() => open(null)}>Einheit anlegen</button>}</div></header>
    <section aria-label="Kennzahlen der gefilterten Einheiten" className="inventory-summary">
      {summary.loading ? <p role="status">Kennzahlen werden berechnet …</p> : stats ? <>
        {[[stats.total, 'Einheiten'], [stats.occupied, 'Status vermietet'], [stats.vacant, 'Status leer'], [money(stats.average_cold_rent), `Ø Kaltmiete · ${stats.rent_count} Angaben`], [stats.multiple_active, 'Mehrere aktive Verträge']].map(([value, label]) => <div className="panel" key={label}><strong>{value}</strong><span>{label}</span></div>)}
      </> : <div role="alert">Kennzahlen nicht verfügbar. {errorMessage(summary.error)} <button className="btn btn-secondary" onClick={refresh}>Erneut laden</button></div>}
    </section>
    <section className="panel inventory-filters" aria-label="Einheiten filtern">
      <label>Einheiten durchsuchen<input type="search" value={filters.search} onChange={event => change('search', event.target.value)} placeholder="Bezeichnung, Immobilie oder aktive Mietpartei" /></label>
      <label>Status<select value={filters.status} onChange={event => change('status', event.target.value)}><option value="">Alle Status</option>{Object.entries(statuses).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <label>Prüfansicht<select value={filters.view} onChange={event => change('view', event.target.value)}>{[['all', 'Alle Einheiten'], ['no_contract', 'Ohne Vertrag'], ['no_area', 'Ohne Fläche'], ['no_person_count', 'Ohne Personenzahl'], ['multiple_active', 'Mehrere aktive Verträge']].map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <label>Art<select value={filters.unit_type} onChange={event => change('unit_type', event.target.value)}><option value="">Alle Arten</option>{Object.entries(types).map(([value, label]) => <option key={value} value={value}>{label}</option>)}{['Wohnung', 'Gewerbe', 'Stellplatz', 'Keller', 'Sonstiges'].map(value => <option key={value} value={value}>{value} (Altbestand)</option>)}</select></label>
      <label>Sortierung<select value={filters.sort_by} onChange={event => change('sort_by', event.target.value)}>{[['label', 'Bezeichnung'], ['property_name', 'Immobilie'], ['tenant_name', 'Mietpartei'], ['cold_rent', 'Kaltmiete'], ['area_sqm', 'Fläche'], ['rooms', 'Zimmer'], ['status', 'Status']].map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <label>Reihenfolge<select value={filters.sort_order} onChange={event => change('sort_order', event.target.value)}><option value="asc">Aufsteigend</option><option value="desc">Absteigend</option></select></label>
      <label>Fläche ab (m²)<input type="number" value={filters.area_min} onChange={event => change('area_min', event.target.value)} /></label>
      <label>Fläche bis (m²)<input type="number" value={filters.area_max} onChange={event => change('area_max', event.target.value)} /></label>
      <label>Kaltmiete ab (€)<input type="number" value={filters.rent_min} onChange={event => change('rent_min', event.target.value)} /></label>
      <label>Kaltmiete bis (€)<input type="number" value={filters.rent_max} onChange={event => change('rent_max', event.target.value)} /></label>
      <details className="inventory-property-filter"><summary>Immobilie auswählen{filters.property_id ? ' · Filter aktiv' : ''}</summary><ReferenceChoice key={principal} kind="properties" label="Immobilie" principal={principal} value={filters.property_id} onChange={value => change('property_id', value)} /></details>
      <button className="btn btn-secondary" onClick={() => { exportRequest.current?.abort(); setExporting(false); setFilters(defaults); }}>Filter zurücksetzen</button>
    </section>
    <div className="inventory-actions"><button className="btn btn-secondary" onClick={download} disabled={exporting}>{exporting ? 'Export wird erstellt …' : 'Alle gefilterten Einheiten exportieren'}</button></div>
    {actionError && <div className="panel inventory-error" role="alert">{errorMessage(actionError)}</div>}
    {state.loading && <p role="status">Einheiten werden geladen …</p>}
    {failure && <div className="panel inventory-error" role="alert">{errorMessage(failure)} <button className="btn btn-secondary" onClick={refresh}>Erneut laden</button></div>}
    {page && <section aria-label="Gefilterte Einheiten" className="panel inventory-results">
      {!page.items.length ? <p>Keine passenden Einheiten auf dieser Seite.</p> : <div className="inventory-table-scroll" tabIndex={0} role="region" aria-label="Einheitentabelle horizontal scrollen"><table>
        <thead><tr>{['Einheit', 'Immobilie', 'Art', 'Fläche / Zimmer', 'Kaltmiete', 'Warmmiete', 'Aktive Mietpartei', 'Status', 'Aktionen'].map(label => <th scope="col" key={label}>{label}</th>)}</tr></thead>
        <tbody>{page.items.map(row => <tr key={row.id}>
          <th scope="row"><Link to={`/units/${encodeURIComponent(row.id)}`}>{row.label}</Link></th><td>{row.property_name || '—'}</td><td>{named(types, row.unit_type)}</td>
          <td>{number(row.area_sqm)} m² / {number(row.rooms)}</td><td>{money(row.cold_rent)}</td><td>{[row.cold_rent, row.service_charge_advance, row.heating_advance].every(value => value != null) ? money(row.cold_rent + row.service_charge_advance + row.heating_advance) : 'Angaben unvollständig'}</td>
          <td>{row.active_contract_count > 1 ? `${row.active_contract_count} aktive Verträge · Akte prüfen` : row.tenant_name || '—'}</td><td>{named(statuses, row.status)}</td>
          <td>{canWrite && <div className="inventory-actions"><button className="btn btn-secondary btn-sm" onClick={() => open(row)} aria-label={`${row.label} bearbeiten`}>Bearbeiten</button><button className="btn btn-secondary btn-sm" onClick={() => remove(row)} aria-label={`${row.label} löschen`}>Löschen</button></div>}</td>
        </tr>)}</tbody></table></div>}
      <nav aria-label="Einheitenseiten" className="inventory-pager"><button className="btn btn-secondary" disabled={trail.length === 1} onClick={() => setPages({ source: query, trail: trail.slice(0, -1) })}>Vorherige Seite</button><span>Seite {trail.length}</span><button className="btn btn-secondary" disabled={!page.has_more} onClick={() => setPages({ source: query, trail: [...trail, page.next_cursor] })}>Nächste Seite</button></nav>
      <p className="text-muted">Kennzahlen und Export umfassen alle passenden Einheiten. Die Liste zeigt jeweils eine Seite. Warmmiete erfordert alle drei Monatsbeträge.</p>
    </section>}
    {modal && canWrite && <FormModal key={modal.id || 'create'} title={modal === 'create' ? 'Einheit anlegen' : 'Einheit bearbeiten'} fields={fields} initial={modal === 'create' ? null : modal}
      onSave={save} onSaved={updated} onClose={() => setModal(null)}><ReferenceChoice kind="properties" label="Immobilie" value={property} onChange={value => setProperty(value)} principal={principal} required /></FormModal>}
  </div>;
}

export default function UnitInventory() {
  const principal = principalKey(useAuth()?.user);
  return <Inventory key={principal} principal={principal} />;
}
