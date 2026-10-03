import { useEffect, useRef, useState } from 'react';
import { api } from '../../api';
import { revisionOptions } from '../../editRevision';
import { useAuth } from '../../contexts/AuthContext';
import { useDataStore } from '../../contexts/DataStoreContext';
import { useConfirm } from '../../components/ConfirmDialog';
import useWriteAccess from '../../hooks/useWriteAccess';
import FormModal from '../../components/FormModal';
import BillingDimensionValue from '../billingDimensions/BillingDimensionValue';
import { DIMENSION_HINTS, meterPayload } from '../billingDimensions/billingDimensions';
import ReferenceChoice from '../unitInventory/ReferenceChoice';
import { checkedPage, errorMessage, principalKey, queryString, usePrivateRead } from '../unitInventory/read';
import { useInventory } from '../inventory/useInventory';
import '../unitInventory/UnitInventory.css';
import '../billingDimensions/BillingDimensions.css';
import './MeterInventory.css';

const types = { cold_water: 'Kaltwasser', hot_water: 'Warmwasser', heating: 'Heizung', electricity: 'Strom', gas: 'Gas' };
const named = value => types[value] || value;
const today = () => { const now = new Date(); return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`; };
const dateLabel = value => value ? new Intl.DateTimeFormat('de-DE').format(new Date(`${value}T12:00:00`)) : '—';
const number = value => value == null ? '—' : new Intl.NumberFormat('de-DE', { maximumFractionDigits: 20 }).format(value);
const label = row => row.serial_number || row.id;
const validDetail = row => row && typeof row.id === 'string' && typeof row.unit_id === 'string' && row.unit_id
  && typeof row.meter_type === 'string' && typeof row.updated_at === 'string' && typeof row.edit_etag === 'string';

function MeterForm({ initial, principal, onSave, onSaved, onClose }) {
  const fields = [
    { key: 'unit_id', label: 'Einheit', required: true, type: 'select',
      render: ({ value, onChange, inputProps }) => <ReferenceChoice kind="units" label="Einheit" value={value} onChange={onChange} principal={principal} required disabled={inputProps.disabled} /> },
    { key: 'meter_type', label: 'Typ', type: 'select', required: true,
      render: ({ value, onChange, inputProps }) => <><label htmlFor={inputProps.id}>Typ *</label><select {...inputProps} value={value} onChange={event => onChange(event.target.value)}>
        <option value="">Bitte auswählen</option>{Object.entries({ ...types, ...(value && !Object.hasOwn(types, value) ? { [value]: value } : {}) }).map(([key, text]) => <option key={key} value={key}>{text}</option>)}
      </select><label htmlFor={`${inputProps.id}-custom`}>Individueller Zählertyp</label><input id={`${inputProps.id}-custom`} disabled={inputProps.disabled} value={Object.hasOwn(types, value) ? '' : value || ''} onChange={event => onChange(event.target.value)} placeholder="Gespeicherten eigenen Typ verwenden" /></> },
    { key: 'measurement_unit', label: 'Tatsächliche Maßeinheit', placeholder: 'z. B. m³ oder kWh', hint: DIMENSION_HINTS.meterUnit },
    { key: 'serial_number', label: 'Seriennummer' }, { key: 'location', label: 'Standort' },
    { key: 'installation_date', label: 'Einbaudatum', type: 'date' }, { key: 'next_inspection', label: 'Nächste Prüfung', type: 'date' },
    { key: 'supplier', label: 'Versorger' }, { key: 'contract_number', label: 'Vertragsnummer' },
    { key: 'contract_end_date', label: 'Vertragslaufzeit bis', type: 'date' },
    { key: 'is_active', label: 'Status', type: 'select', default: true, options: [{ value: 'true', label: 'Aktiv' }, { value: 'false', label: 'Inaktiv' }] },
  ];
  return <FormModal title={initial ? 'Zähler bearbeiten' : 'Zähler anlegen'} fields={fields} initial={initial} draftConfig={{ collection: 'meters' }} onClose={onClose} onSaved={onSaved}
    onSave={payload => {
      if (!payload.unit_id) throw new Error('Bitte eine Einheit auswählen.');
      return onSave(meterPayload({ ...payload, is_active: payload.is_active === true || payload.is_active === 'true' }));
    }} />;
}

function ReadingForm({ meter, onSave, onSaved, onClose }) {
  const fields = [
    { key: 'meter_id', type: 'hidden', required: true, default: meter.id },
    { key: 'reading_date', label: 'Ablesedatum', type: 'date', required: true, default: today() },
    { key: 'value', label: 'Zählerstand', type: 'number', required: true, step: 'any' },
    { key: 'recorded_by', label: 'Erfasst von' }, { key: 'notes', label: 'Notizen', type: 'textarea' },
  ];
  return <FormModal title={`Ablesung erfassen · ${label(meter)}`} fields={fields}
    draftConfig={{ collection: 'meters/readings', formKey: `meter:${meter.id}` }} onSave={onSave} onSaved={onSaved} onClose={onClose}>
    <p>Aktuelle Stammdateneinheit: <BillingDimensionValue value={meter.measurement_unit} kind="unit" />. Der eingegebene Originalstand wird unverändert gespeichert.</p>
  </FormModal>;
}

function Readings({ meter, principal, generation, canWrite, onAdd, onEdit, onClose }) {
  const [filters, setFilters] = useState({ search: '', date_from: '', date_to: '', sort_order: 'desc' });
  const [pages, setPages] = useState({ source: '', trail: [null] });
  const [refresh, setRefresh] = useState(0);
  const query = queryString({ ...filters, page_size: 25 });
  const source = JSON.stringify([query, generation, refresh]);
  const trail = pages.source === source ? pages.trail : [null];
  const state = usePrivateRead(`/meters/${encodeURIComponent(meter.id)}/readings/page?${query}${trail.at(-1) ? `&cursor=${encodeURIComponent(trail.at(-1))}` : ''}`, principal, `${generation}:${refresh}`);
  const page = checkedPage(state.data) && state.data.items.every(row => row.meter_id === meter.id && typeof row.reading_date === 'string' && typeof row.value === 'number') ? state.data : null;
  const failure = state.error || (!state.loading && !page ? new Error('Die Ableseliste konnte nicht geprüft werden.') : null);
  const reload = () => { setRefresh(value => value + 1); };
  return <section className="panel inventory-results meter-readings" aria-label="Ablesungen des geöffneten Zählers">
    <div className="inventory-heading"><div><h2>Ablesungen · {label(meter)}</h2><p>{meter.property_name} · {meter.unit_label} · {named(meter.meter_type)}</p>
      <p>Aktuelle Stammdateneinheit: <BillingDimensionValue value={meter.measurement_unit} kind="unit" /></p></div>
      <div className="inventory-actions"><button className="btn btn-secondary" onClick={reload}>Ablesungen aktualisieren</button>{canWrite && <><button className="btn btn-primary" onClick={onAdd}>Ablesung erfassen</button><button className="btn btn-secondary" onClick={onEdit}>Zähler bearbeiten</button></>}<button className="btn btn-secondary" onClick={onClose}>Ablesungen schließen</button></div></div>
    <p className="text-muted">Die Liste zeigt gespeicherte Originalstände. Historische Zuordnungen und Verbrauchsgrundlagen werden in der Abrechnungsakte geprüft; die heutige Stammdateneinheit ersetzt sie nicht.</p>
    <div className="inventory-filters"><label>Ablesungen durchsuchen<input type="search" value={filters.search} onChange={event => setFilters(current => ({ ...current, search: event.target.value }))} placeholder="Erfasst von oder Notizen" /></label>
      {[['date_from', 'Ablesedatum von'], ['date_to', 'Ablesedatum bis']].map(([key, text]) => <label key={key}>{text}<input type="date" value={filters[key]} onChange={event => setFilters(current => ({ ...current, [key]: event.target.value }))} /></label>)}
      <label>Ablesereihenfolge<select value={filters.sort_order} onChange={event => setFilters(current => ({ ...current, sort_order: event.target.value }))}><option value="desc">Neueste zuerst</option><option value="asc">Älteste zuerst</option></select></label>
    </div>
    {state.loading && <p role="status">Ablesungen werden geladen …</p>}{failure && <div role="alert">{errorMessage(failure)} <button className="btn btn-secondary" onClick={reload}>Erneut laden</button></div>}
    {page && <>{!page.items.length ? <p>Keine passenden Ablesungen auf dieser Seite.</p> : <div className="inventory-table-scroll" role="region" tabIndex={0} aria-label="Ablesetabelle horizontal scrollen"><table>
      <thead><tr>{['Datum', 'Originalstand', 'Erfasst von', 'Notizen'].map(text => <th key={text} scope="col">{text}</th>)}</tr></thead><tbody>{page.items.map(row => <tr key={row.id}><th scope="row">{dateLabel(row.reading_date)}</th><td>{number(row.value)}</td><td>{row.recorded_by || '—'}</td><td>{row.notes || '—'}</td></tr>)}</tbody>
    </table></div>}<nav className="inventory-pager" aria-label="Ableseseiten"><button className="btn btn-secondary" disabled={trail.length === 1} onClick={() => setPages({ source, trail: trail.slice(0, -1) })}>Vorherige Ableseseite</button><span>Seite {trail.length}</span><button className="btn btn-secondary" disabled={!page.has_more} onClick={() => setPages({ source, trail: [...trail, page.next_cursor] })}>Nächste Ableseseite</button></nav></>}
  </section>;
}

function Inventory({ principal }) {
  const [configuration] = useState(() => ({ resource: 'meters', filename: 'zaehler.csv', countFields: ['total', 'active', 'inactive', 'no_reading', 'unknown_unit', 'overdue', 'due_soon'], invalidMessage: 'Die Zählerliste konnte nicht geprüft werden.',
    defaults: { search: '', property_id: '', unit_id: '', meter_type: '', measurement_unit: '', supplier: '', is_active: '', view: 'all', as_of: today(), inspection_from: '', inspection_to: '', sort_by: 'serial_number', sort_order: 'asc' } }));
  const listing = useInventory(principal, configuration);
  const { filters, state, page, failure, stats, summary } = listing;
  const store = useDataStore(); const confirm = useConfirm();
  const [modal, setModal] = useState(null); const [selected, setSelected] = useState(null);
  const [opening, setOpening] = useState(false); const [actionError, setActionError] = useState(null); const [generation, setGeneration] = useState(0);
  const request = useRef(null); const saveRequest = useRef(null); const alive = useRef(true);
  const { canWrite, isAllowed, requireWrite } = useWriteAccess('/meters', () => { setModal(null); request.current?.abort(); saveRequest.current?.abort(); });
  useEffect(() => { alive.current = true; return () => { alive.current = false; request.current?.abort(); saveRequest.current?.abort(); }; }, []);
  const open = async (row, editing = false) => {
    if (editing && !isAllowed()) return;
    request.current?.abort(); setActionError(null);
    if (!row) { setOpening(false); setModal({ kind: 'meter', initial: null }); return; }
    const controller = new AbortController(); request.current = controller; setOpening(true);
    try {
      const full = await api.get(`/meters/inventory/detail/${encodeURIComponent(row.id)}`, { signal: controller.signal });
      if (!validDetail(full) || full.id !== row.id) throw new Error('Der Zähler konnte nicht geprüft werden.');
      if (!controller.signal.aborted && alive.current) {
        if (editing && isAllowed()) setModal({ kind: 'meter', initial: full });
        else if (!editing) setSelected(full);
      }
    } catch (error) { if (!controller.signal.aborted && alive.current) setActionError(error); }
    finally { if (!controller.signal.aborted && alive.current) setOpening(false); }
  };
  const updated = () => { if (alive.current) { listing.refresh(); setGeneration(value => value + 1); store?.invalidateRelated('meters', 'units'); } };
  const saved = () => { if (alive.current) { if (modal?.kind === 'meter' && selected?.id === modal.initial?.id) setSelected(null); updated(); } };
  const save = async payload => {
    requireWrite(); if (!alive.current) throw new Error('Die Anmeldung wurde geändert.');
    saveRequest.current?.abort(); const controller = new AbortController(); saveRequest.current = controller;
    if (modal.kind === 'reading') {
      if (payload.meter_id !== modal.meter.id) throw new Error('Die Ablesung gehört zu einem anderen Zähler.');
      await api.post(`/meters/${encodeURIComponent(modal.meter.id)}/readings`, payload, { signal: controller.signal });
    } else if (!modal.initial) await api.post('/meters', payload, { signal: controller.signal });
    else await api.put(`/meters/${encodeURIComponent(modal.initial.id)}`, payload, { ...revisionOptions(modal.initial), ...revisionOptions(payload), signal: controller.signal });
  };
  const remove = async row => {
    if (!isAllowed() || !await confirm(`„${label(row)}“ wirklich löschen?`) || !alive.current || !isAllowed()) return;
    try { await api.del(`/meters/${encodeURIComponent(row.id)}`, revisionOptions(row)); if (alive.current) { if (selected?.id === row.id) setSelected(null); updated(); } }
    catch (error) { if (alive.current) setActionError(error); }
  };
  const change = (key, value) => { request.current?.abort(); setOpening(false); listing.change(key, key === 'as_of' ? value || today() : value); };
  return <div className="page unit-inventory meter-inventory">
    <header className="inventory-heading"><div><h1 className="page-title">Zähler</h1><p className="text-muted">Aktuellen Bestand, letzte Originalstände und Prüftermine durchsuchen.</p></div>{canWrite && <button className="btn btn-primary" onClick={() => open(null, true)}>Zähler anlegen</button>}</header>
    <section className="inventory-summary" aria-label="Kennzahlen der gefilterten Zähler">{summary.loading ? <p role="status">Kennzahlen werden berechnet …</p> : stats ? [[stats.total, 'Zähler gesamt'], [stats.active, 'Aktiv'], [stats.inactive, 'Inaktiv'], [stats.no_reading, 'Ohne Ablesung'], [stats.unknown_unit, 'Maßeinheit ungeklärt'], [stats.overdue, 'Prüfung überfällig'], [stats.due_soon, 'Prüfung in 30 Tagen']].map(([value, text]) => <div className="panel" key={text}><strong>{value}</strong><span>{text}</span></div>)
      : <div role="alert">Kennzahlen nicht verfügbar. {errorMessage(summary.error)} <button className="btn btn-secondary" onClick={listing.refresh}>Erneut laden</button></div>}</section>
    <section className="panel inventory-filters" aria-label="Zähler filtern"><label>Zähler durchsuchen<input type="search" value={filters.search} onChange={event => change('search', event.target.value)} placeholder="Seriennummer, Zuordnung oder Versorger" /></label>
      {[['is_active', 'Status', [['', 'Alle Status'], ['true', 'Aktiv'], ['false', 'Inaktiv']]], ['view', 'Prüfansicht', [['all', 'Alle Zähler'], ['no_reading', 'Ohne Ablesung'], ['unknown_unit', 'Maßeinheit ungeklärt'], ['overdue', 'Prüfung überfällig'], ['due_soon', 'Prüfung in 30 Tagen']]],
        ['sort_by', 'Sortierung', [['serial_number', 'Seriennummer'], ['meter_type', 'Typ'], ['measurement_unit', 'Maßeinheit'], ['property_name', 'Immobilie'], ['unit_label', 'Einheit'], ['supplier', 'Versorger'], ['next_inspection', 'Prüftermin'], ['last_reading_date', 'Letztes Ablesedatum'], ['last_reading_value', 'Letzter Originalstand']]], ['sort_order', 'Reihenfolge', [['asc', 'Aufsteigend'], ['desc', 'Absteigend']]]].map(([key, text, values]) => <label key={key}>{text}<select value={filters[key]} onChange={event => change(key, event.target.value)}>{values.map(([value, title]) => <option key={value} value={value}>{title}</option>)}</select></label>)}
      {[['meter_type', 'Genauer Zählertyp'], ['measurement_unit', 'Genaue Maßeinheit'], ['supplier', 'Genauer Versorger']].map(([key, text]) => <label key={key}>{text}<input value={filters[key]} onChange={event => change(key, event.target.value)} placeholder="Auch eigene gespeicherte Werte" /></label>)}
      {[['as_of', 'Stichtag für Prüftermine'], ['inspection_from', 'Prüftermin von'], ['inspection_to', 'Prüftermin bis']].map(([key, text]) => <label key={key}>{text}<input type="date" value={filters[key]} onChange={event => change(key, event.target.value)} /></label>)}
      <details className="inventory-property-filter"><summary>Immobilie oder Einheit auswählen</summary><ReferenceChoice kind="properties" label="Immobilie" principal={principal} value={filters.property_id} onChange={value => { change('property_id', value); change('unit_id', ''); }} /><ReferenceChoice key={filters.property_id} kind="units" label="Einheit" principal={principal} value={filters.unit_id} filters={{ property_id: filters.property_id }} onChange={value => change('unit_id', value)} /></details>
      <button className="btn btn-secondary" onClick={listing.reset}>Filter zurücksetzen</button>
    </section>
    <div className="inventory-actions"><button className="btn btn-secondary" onClick={updated}>Aktualisieren</button><button className="btn btn-secondary" disabled={listing.exporting} onClick={listing.download}>{listing.exporting ? 'Export wird erstellt …' : 'Alle gefilterten Zähler exportieren'}</button></div>
    {(actionError || listing.exportError) && <div className="panel inventory-error" role="alert">{errorMessage(actionError || listing.exportError)}</div>}
    {opening && <p role="status">Zähler wird geöffnet …</p>}{state.loading && <p role="status">Zähler werden geladen …</p>}
    {failure && <div className="panel inventory-error" role="alert">{errorMessage(failure)} <button className="btn btn-secondary" onClick={listing.refresh}>Erneut laden</button></div>}
    {page && <section className="panel inventory-results" aria-label="Gefilterte Zähler">{!page.items.length ? <p>Keine passenden Zähler auf dieser Seite.</p> : <div className="inventory-table-scroll" tabIndex={0} role="region" aria-label="Zählertabelle horizontal scrollen"><table>
      <thead><tr>{['Zähler / Typ', 'Aktuelle Zuordnung', 'Aktuelle Maßeinheit', 'Letzter Originalstand', 'Prüftermin', 'Versorger / Standort', 'Status', 'Aktionen'].map(text => <th scope="col" key={text}>{text}</th>)}</tr></thead>
      <tbody>{page.items.map(row => <tr key={row.id}><th scope="row">{label(row)}<p>{named(row.meter_type)}</p></th><td>{row.property_name}<p>{row.unit_label}</p></td><td><BillingDimensionValue value={row.measurement_unit} kind="unit" /></td><td>{row.last_reading_id ? <>{number(row.last_reading_value)}<p>{dateLabel(row.last_reading_date)}</p></> : 'Keine Ablesung'}</td>
        <td>{dateLabel(row.next_inspection)}{row.next_inspection && row.next_inspection < filters.as_of && <strong> · Überfällig</strong>}</td><td>{row.supplier || '—'}<p>{row.location || '—'}</p></td><td>{row.is_active ? 'Aktiv' : 'Inaktiv'}</td><td><div className="inventory-actions"><button className="btn btn-secondary btn-sm" onClick={() => open(row)} aria-label={`${label(row)} Ablesungen anzeigen`}>Ablesungen</button>{canWrite && <><button className="btn btn-secondary btn-sm" onClick={() => open(row, true)} aria-label={`${label(row)} bearbeiten`}>Bearbeiten</button><button className="btn btn-secondary btn-sm" onClick={() => remove(row)} aria-label={`${label(row)} löschen`}>Löschen</button></>}</div></td></tr>)}</tbody>
    </table></div>}<nav className="inventory-pager" aria-label="Zählerseiten"><button className="btn btn-secondary" disabled={listing.pageNumber === 1} onClick={listing.previous}>Vorherige Seite</button><span>Seite {listing.pageNumber}</span><button className="btn btn-secondary" disabled={!page.has_more} onClick={listing.next}>Nächste Seite</button></nav><p className="text-muted">Kennzahlen und Export umfassen alle gefilterten Zähler. Die Liste zeigt eine Seite; Ablesungen werden erst beim Öffnen geladen.</p></section>}
    {selected && <Readings key={selected.id} meter={selected} principal={principal} generation={generation} canWrite={canWrite} onAdd={() => setModal({ kind: 'reading', meter: selected })} onEdit={() => open(selected, true)} onClose={() => setSelected(null)} />}
    {modal && canWrite && (modal.kind === 'reading' ? <ReadingForm key={`reading:${modal.meter.id}`} meter={modal.meter} onSave={save} onSaved={saved} onClose={() => setModal(null)} />
      : <MeterForm key={modal.initial?.id || 'create'} initial={modal.initial} principal={principal} onSave={save} onSaved={saved} onClose={() => setModal(null)} />)}
  </div>;
}

export default function MeterInventory() {
  const principal = principalKey(useAuth()?.user);
  return <Inventory key={principal} principal={principal} />;
}
