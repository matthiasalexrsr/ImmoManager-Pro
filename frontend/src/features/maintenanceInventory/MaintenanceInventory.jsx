import { useEffect, useRef, useState } from 'react';
import { api } from '../../api';
import { revisionOptions } from '../../editRevision';
import { useAuth } from '../../contexts/AuthContext';
import { useDataStore } from '../../contexts/DataStoreContext';
import { useConfirm } from '../../components/ConfirmDialog';
import useWriteAccess from '../../hooks/useWriteAccess';
import FormModal from '../../components/FormModal';
import ReferenceChoice from '../unitInventory/ReferenceChoice';
import { principalKey, errorMessage } from '../unitInventory/read';
import { useInventory } from '../inventory/useInventory';
import '../unitInventory/UnitInventory.css';

const statuses = { open: 'Offen', in_progress: 'In Bearbeitung', completed: 'Erledigt', cancelled: 'Abgebrochen' };
const priorities = { low: 'Niedrig', medium: 'Mittel', high: 'Hoch', urgent: 'Dringend' };
const options = labels => Object.entries(labels).map(([value, label]) => ({ value, label }));
const named = (labels, value) => Object.hasOwn(labels, value) ? labels[value] : value;
const today = () => { const now = new Date(); return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`; };
const dateLabel = value => value ? new Intl.DateTimeFormat('de-DE').format(new Date(`${value}T12:00:00`)) : '—';
const costLabel = value => value == null ? '—' : new Intl.NumberFormat('de-DE', { style: 'currency', currency: 'EUR' }).format(value);
const appointmentValue = value => value?.slice(0, 19) || '';

function CaseForm({ initial, principal, onSave, onSaved, onClose }) {
  const [refs, setRefs] = useState({ property_id: initial?.property_id || '', unit_id: initial?.unit_id || '' });
  const fields = [
    { key: 'title', label: 'Titel', required: true }, { key: 'description', label: 'Beschreibung', type: 'textarea' },
    { key: 'category', label: 'Kategorie', hint: 'Zum Beispiel Sanitär, Elektrik, Heizung oder Dach.' },
    { key: 'priority', label: 'Priorität', type: 'select', default: 'medium', options: options({ ...priorities, ...(initial?.priority && !Object.hasOwn(priorities, initial.priority) ? { [initial.priority]: initial.priority } : {}) }) },
    { key: 'status', label: 'Status', type: 'select', default: 'open', options: options({ ...statuses, ...(initial?.status && !Object.hasOwn(statuses, initial.status) ? { [initial.status]: initial.status } : {}) }) },
    { key: 'assignee', label: 'Zuständig' }, { key: 'contractor', label: 'Handwerker' }, { key: 'reported_by', label: 'Gemeldet von' },
    { key: 'due_date', label: 'Fällig am', type: 'date' }, { key: 'appointment_at', label: 'Termin mit Uhrzeit', type: 'datetime-local', step: 1 },
    { key: 'estimated_cost', label: 'Geschätzte Kosten (€)', type: 'number' },
  ];
  const original = initial ? { ...initial, appointment_at: appointmentValue(initial.appointment_at) } : null;
  return <FormModal title={initial ? 'Wartungsfall bearbeiten' : 'Wartungsfall anlegen'} fields={fields} initial={original} onClose={onClose} onSaved={onSaved}
    onSave={payload => {
      if (!refs.property_id) throw new Error('Bitte eine Immobilie auswählen.');
      const appointment = payload.appointment_at === appointmentValue(initial?.appointment_at) ? initial?.appointment_at : payload.appointment_at;
      return onSave({ ...payload, ...refs, unit_id: refs.unit_id || null, appointment_at: appointment || null });
    }}>
    <ReferenceChoice kind="properties" label="Immobilie" value={refs.property_id} principal={principal} required
      onChange={value => setRefs({ property_id: value, unit_id: '' })} />
    <ReferenceChoice key={refs.property_id} kind="units" label="Einheit" value={refs.unit_id} principal={principal} filters={{ property_id: refs.property_id }}
      onChange={(value, row) => setRefs(current => ({ property_id: row?.property_id || current.property_id, unit_id: value }))} />
  </FormModal>;
}

function Inventory({ principal }) {
  const [configuration] = useState(() => ({
    resource: 'maintenance', filename: 'wartung.csv', countFields: ['total', 'open', 'in_progress', 'overdue', 'no_appointment', 'no_assignee'],
    invalidMessage: 'Die Wartungsliste konnte nicht geprüft werden.',
    defaults: { search: '', status: '', priority: '', category: '', property_id: '', view: 'all', as_of: today(), date_from: '', date_to: '', appointment_from: '', appointment_to: '', sort_by: 'due_date', sort_order: 'asc' },
  }));
  const listing = useInventory(principal, configuration);
  const { filters, change, state, page, failure, stats, summary } = listing;
  const store = useDataStore(); const confirm = useConfirm();
  const [modal, setModal] = useState(null); const [actionError, setActionError] = useState(null); const [opening, setOpening] = useState(false);
  const alive = useRef(true); const request = useRef(null);
  const { canWrite, isAllowed, requireWrite } = useWriteAccess('/maintenance', () => setModal(null));
  useEffect(() => { alive.current = true; return () => { alive.current = false; request.current?.abort(); }; }, []);
  const updated = () => { if (alive.current) { listing.refresh(); store?.invalidateRelated('maintenance', 'properties', 'units'); } };
  const open = async row => {
    if (!isAllowed()) return;
    request.current?.abort(); setActionError(null);
    if (!row) { setOpening(false); setModal('create'); return; }
    const controller = new AbortController(); request.current = controller; setOpening(true);
    try {
      const full = await api.get(`/maintenance/${encodeURIComponent(row.id)}`, { signal: controller.signal });
      if (full?.id !== row.id) throw new Error('Der Wartungsfall konnte nicht geprüft werden.');
      if (!controller.signal.aborted && alive.current && isAllowed()) setModal(full);
    } catch (error) { if (!controller.signal.aborted && alive.current) setActionError(error); }
    finally { if (!controller.signal.aborted && alive.current) setOpening(false); }
  };
  const save = async data => {
    requireWrite(); if (!alive.current) throw new Error('Die Anmeldung wurde geändert.');
    if (modal === 'create') await api.post('/maintenance', data);
    else await api.put(`/maintenance/${encodeURIComponent(modal.id)}`, data, revisionOptions(modal));
  };
  const remove = async row => {
    if (!isAllowed() || !await confirm(`„${row.title}“ wirklich löschen?`) || !alive.current || !isAllowed()) return;
    try { await api.del(`/maintenance/${encodeURIComponent(row.id)}`, revisionOptions(row)); updated(); }
    catch (error) { if (alive.current) setActionError(error); }
  };
  const changeFilter = (key, value) => { request.current?.abort(); setOpening(false); change(key, key === 'as_of' ? value || today() : value); };
  return <div className="page unit-inventory">
    <header className="inventory-heading"><div><h1 className="page-title">Wartung & Schäden</h1><p className="text-muted">Fälligkeiten, Termine und Zuständigkeiten über den gesamten Bestand prüfen.</p></div>
      {canWrite && <button className="btn btn-primary" onClick={() => open(null)}>Wartungsfall anlegen</button>}</header>
    <section className="inventory-summary" aria-label="Kennzahlen der gefilterten Wartungsfälle">
      {summary.loading ? <p role="status">Kennzahlen werden berechnet …</p> : stats ? [[stats.total, 'Fälle'], [stats.open, 'Offen'], [stats.in_progress, 'In Bearbeitung'], [stats.overdue, 'Überfällig'], [stats.no_appointment, 'Ohne Termin'], [stats.no_assignee, 'Ohne Zuständigen']].map(([value, label]) => <div className="panel" key={label}><strong>{value}</strong><span>{label}</span></div>)
        : <div role="alert">Kennzahlen nicht verfügbar. {errorMessage(summary.error)} <button className="btn btn-secondary" onClick={listing.refresh}>Erneut laden</button></div>}
    </section>
    <section className="panel inventory-filters" aria-label="Wartungsfälle filtern">
      <label>Wartungsfälle durchsuchen<input type="search" value={filters.search} onChange={event => changeFilter('search', event.target.value)} placeholder="Titel, Zuordnung oder Zuständiger" /></label>
      {[['status', 'Status', [['', 'Alle Status'], ...Object.entries(statuses)]], ['priority', 'Priorität', [['', 'Alle Prioritäten'], ...Object.entries(priorities)]],
        ['view', 'Prüfansicht', [['all', 'Alle Fälle'], ['overdue', 'Überfällig'], ['urgent', 'Hohe Priorität'], ['no_appointment', 'Ohne Termin'], ['no_assignee', 'Ohne Zuständigen']]],
        ['sort_by', 'Sortierung', [['due_date', 'Fälligkeit'], ['appointment_at', 'Termin'], ['title', 'Titel'], ['property_name', 'Immobilie'], ['unit_label', 'Einheit'], ['status', 'Status'], ['priority', 'Priorität'], ['assignee', 'Zuständig'], ['contractor', 'Handwerker'], ['estimated_cost', 'Kostenschätzung'], ['created_at', 'Erstellt am']]],
        ['sort_order', 'Reihenfolge', [['asc', 'Aufsteigend'], ['desc', 'Absteigend']]]].map(([key, label, values]) => <label key={key}>{label}<select aria-label={label} value={filters[key]} onChange={event => changeFilter(key, event.target.value)}>{values.map(([value, text]) => <option key={value} value={value}>{text}</option>)}</select></label>)}
      <label>Kategorie<input value={filters.category} onChange={event => changeFilter('category', event.target.value)} placeholder="Genaue Kategorie" /></label>
      {[['as_of', 'Stichtag für Überfälligkeit'], ['date_from', 'Fällig ab'], ['date_to', 'Fällig bis'], ['appointment_from', 'Termin ab'], ['appointment_to', 'Termin bis']].map(([key, label]) => <label key={key}>{label}<input type="date" value={filters[key]} onChange={event => changeFilter(key, event.target.value)} /></label>)}
      <details className="inventory-property-filter"><summary>Immobilie auswählen{filters.property_id ? ' · Filter aktiv' : ''}</summary><ReferenceChoice kind="properties" label="Immobilie" value={filters.property_id} principal={principal} onChange={value => changeFilter('property_id', value)} /></details>
      <button className="btn btn-secondary" onClick={listing.reset}>Filter zurücksetzen</button>
    </section>
    <div className="inventory-actions"><button className="btn btn-secondary" onClick={listing.refresh}>Aktualisieren</button><button className="btn btn-secondary" disabled={listing.exporting} onClick={listing.download}>{listing.exporting ? 'Export wird erstellt …' : 'Alle gefilterten Wartungsfälle exportieren'}</button></div>
    {(actionError || listing.exportError) && <div role="alert" className="panel inventory-error">{errorMessage(actionError || listing.exportError)}</div>}
    {opening && <p role="status">Wartungsfall wird geöffnet …</p>}{state.loading && <p role="status">Wartungsfälle werden geladen …</p>}
    {failure && <div role="alert" className="panel inventory-error">{errorMessage(failure)} <button className="btn btn-secondary" onClick={listing.refresh}>Erneut laden</button></div>}
    {page && <section className="panel inventory-results" aria-label="Gefilterte Wartungsfälle">
      {!page.items.length ? <p>Keine passenden Wartungsfälle auf dieser Seite.</p> : <div className="inventory-table-scroll" tabIndex={0} role="region" aria-label="Wartungstabelle horizontal scrollen"><table>
        <thead><tr>{['Fall / Kategorie', 'Zuordnung', 'Status / Priorität', 'Zuständigkeit', 'Fälligkeit / Termin', 'Geschätzte Kosten', 'Aktionen'].map(label => <th scope="col" key={label}>{label}</th>)}</tr></thead>
        <tbody>{page.items.map(row => <tr key={row.id}><th scope="row">{row.title}{row.category && <p>{row.category}</p>}</th><td>{[row.property_name, row.unit_label].filter(Boolean).join(' · ') || 'Zuordnung nicht verfügbar'}</td>
          <td>{named(statuses, row.status)}<p>{named(priorities, row.priority)}</p></td><td>{row.assignee || 'Nicht zugewiesen'}{row.contractor && <p>Handwerker: {row.contractor}</p>}{row.reported_by && <p>Gemeldet: {row.reported_by}</p>}</td>
          <td><span>{dateLabel(row.due_date)}</span>{row.due_date && row.due_date < filters.as_of && ['open', 'in_progress'].includes(row.status) && <strong> · Überfällig</strong>}<p>{row.appointment_at ? new Intl.DateTimeFormat('de-DE', { dateStyle: 'short', timeStyle: 'short' }).format(new Date(row.appointment_at)) : 'Ohne Termin'}</p></td>
          <td>{costLabel(row.estimated_cost)}</td><td>{canWrite && <div className="inventory-actions"><button className="btn btn-secondary btn-sm" onClick={() => open(row)} aria-label={`${row.title} bearbeiten`}>Bearbeiten</button><button className="btn btn-secondary btn-sm" onClick={() => remove(row)} aria-label={`${row.title} löschen`}>Löschen</button></div>}</td></tr>)}</tbody>
      </table></div>}
      <nav className="inventory-pager" aria-label="Wartungsseiten"><button className="btn btn-secondary" disabled={listing.pageNumber === 1} onClick={listing.previous}>Vorherige Seite</button><span>Seite {listing.pageNumber}</span><button className="btn btn-secondary" disabled={!page.has_more} onClick={listing.next}>Nächste Seite</button></nav>
      <p className="text-muted">Kennzahlen und Export umfassen alle passenden Fälle. Überfälligkeit gilt zum gewählten Stichtag. Kostenschätzungen sind gespeicherte Planwerte.</p>
    </section>}
    {modal && canWrite && <CaseForm key={modal.id || 'create'} initial={modal === 'create' ? null : modal} principal={principal} onSave={save} onSaved={updated} onClose={() => setModal(null)} />}
  </div>;
}

export default function MaintenanceInventory() {
  const principal = principalKey(useAuth()?.user);
  return <Inventory key={principal} principal={principal} />;
}
