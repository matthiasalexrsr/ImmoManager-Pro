import { useState, useEffect, useCallback } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api } from '../api';
import { useDataStore, useEntities } from '../contexts/DataStoreContext';
import { useTranslation } from '../i18n';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import StatusBadge from '../components/StatusBadge';
import { useConfirm } from '../components/ConfirmDialog';
import { bulkDelete } from '../utils/bulkActions';
import { Copy as CopyIcon } from 'lucide-react';
import { duplicateOf } from '../utils/duplicate';
import ObjectScope from '../components/ObjectScope';
import { scopeDefaults } from '../utils/objectScope';
import RelatedPageLinks from '../components/RelatedPageLinks';
import { formatDate } from '../utils/format';

const dayString = value => `${String(value.getFullYear()).padStart(4, '0')}-${String(value.getMonth() + 1).padStart(2, '0')}-${String(value.getDate()).padStart(2, '0')}`;

const EVENT_TYPES = [
  { value: 'viewing', label: 'Besichtigung' },
  { value: 'handover', label: 'Übergabe' },
  { value: 'maintenance', label: 'Wartung' },
  { value: 'meeting', label: 'Besprechung' },
  { value: 'deadline', label: 'Frist' },
  { value: 'other', label: 'Sonstiges' },
];

const COLUMNS = [
  { key: 'title', label: 'Titel', filterType: 'text' },
  { key: 'event_type', label: 'Typ', filterType: 'select',
    render: v => <StatusBadge status={v} /> },
  { key: 'event_date', label: 'Datum', type: 'date', filterType: 'dateRange' },
  { key: 'event_time', label: 'Uhrzeit' },
  { key: 'property_name', subKey: 'unit_label', label: 'Immobilie', filterType: 'text', link: 'property', subLink: 'unit' },
  { key: 'unit_label', hidden: true, label: 'Einheit', filterType: 'text', link: 'unit' },
  { key: 'location', label: 'Ort', filterType: 'text' },
  { key: 'participants', hidden: true, label: 'Teilnehmer' },
];

export default function Calendar() {
  const [params, setParams] = useSearchParams();
  const store = useDataStore();
  const { t } = useTranslation();
  const confirm = useConfirm();
  const [events, setEvents] = useState([]);
  const [properties, setProperties] = useState([]);
  const unitSource = useEntities('units', '/units');
  const units = unitSource.items;
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(null);
  // values of a duplicated appointment for the New form (null: an empty form)
  const [prefill, setPrefill] = useState(null);
  const [deleteError, setDeleteError] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [propertyError, setPropertyError] = useState(null);
  const [loaded, setLoaded] = useState(false);
  const [revision, setRevision] = useState(0);
  const projectId = params.get('maintenance_case_id');
  const filters = new URLSearchParams();
  ['property_id', 'unit_id', 'maintenance_case_id', 'date_from', 'date_to'].forEach(key => {
    if (params.get(key)) filters.set(key, params.get(key));
  });
  const calendarPath = `/calendar${filters.size ? `?${filters}` : ''}`;

  const refreshData = useCallback(() => setRevision(value => value + 1), []);
  useEffect(() => {
    const request = new AbortController();
    setLoading(true);
    Promise.allSettled([
      api.list(calendarPath, { signal: request.signal }),
      api.list('/properties', { signal: request.signal }),
    ]).then(([calendar, properties]) => {
      if (request.signal.aborted) return;
      if (calendar.status === 'fulfilled' && Array.isArray(calendar.value)) {
        setEvents(calendar.value); setLoaded(true); setLoadError(null);
      } else setLoadError(calendar.reason?.message || 'Termine konnten nicht vollständig gelesen werden.');
      if (properties.status === 'fulfilled' && Array.isArray(properties.value)) {
        setProperties(properties.value); setPropertyError(null);
      } else setPropertyError(properties.reason?.message || 'Immobilien konnten nicht gelesen werden.');
      setLoading(false);
    });
    return () => request.abort();
  }, [revision, calendarPath]);
  const choicesReady = !loading && !propertyError && !unitSource.loading && !unitSource.error;
  const propertyNames = new Map(properties.map(property => [property.id, property.name]));
  const unitNames = new Map(units.map(unit => [unit.id, unit.label]));
  const visibleEvents = events.filter(event => (!params.get('property_id') || event.property_id === params.get('property_id'))
    && (!params.get('unit_id') || event.unit_id === params.get('unit_id'))
    && (!projectId || event.maintenance_case_id === projectId)
    && (!params.get('date_from') || event.event_date >= params.get('date_from'))
    && (!params.get('date_to') || event.event_date <= params.get('date_to')));
  const selected = visibleEvents.find(event => event.id === params.get('focus_id'));
  const changeFilter = (key, value) => setParams(current => {
    const next = new URLSearchParams(current); next.delete('focus_id');
    if (value) next.set(key, value); else next.delete(key);
    return next;
  });
  const setPeriod = days => setParams(current => {
    const next = new URLSearchParams(current); ['date_from', 'date_to', 'focus_id'].forEach(key => next.delete(key));
    if (days != null) { const end = new Date(); end.setDate(end.getDate() + days); next.set('date_from', dayString(new Date())); next.set('date_to', dayString(end)); }
    return next;
  });
  const invalidate = () => store?.invalidateRelated('calendar', 'maintenance', 'properties', 'units');

  const fields = [
    { key: 'title', label: 'Titel', required: true },
    { key: 'event_type', label: 'Typ', type: 'select', required: true, options: EVENT_TYPES },
    { key: 'event_date', label: 'Datum', type: 'date', required: true },
    { key: 'event_time', label: 'Uhrzeit', type: modal?.event_time && !/^\d{2}:\d{2}(:\d{2})?$/.test(modal.event_time) ? 'text' : 'time' },
    { key: 'location', label: 'Ort' },
    { key: 'participants', label: 'Teilnehmer' },
    { key: 'property_id', label: 'Immobilie', type: 'select', clearOnChange: ['unit_id'],
      options: properties.map(p => ({ value: p.id, label: p.name })) },
    { key: 'unit_id', label: 'Einheit (optional)', type: 'select',
      options: values => units.filter(unit => !values.property_id || unit.property_id === values.property_id)
        .map(unit => ({ value: unit.id, label: values.property_id ? unit.label : `${propertyNames.get(unit.property_id) || 'Immobilie'} · ${unit.label}` })),
      validate: (value, values) => value && values.property_id && units.find(unit => unit.id === value)?.property_id !== values.property_id
        ? 'Bitte eine Einheit der ausgewählten Immobilie wählen.' : null },
    { key: 'description', label: 'Beschreibung', type: 'textarea' },
  ];

  const handleSave = async (data) => {
    if (!choicesReady) throw new Error('Bitte zuerst die Immobilienauswahl erneut laden.');
    if (modal === 'create') {
      await api.post('/calendar', data);
    } else {
      await api.put(`/calendar/${modal.id}`, data);
    }
    refreshData();
    invalidate();
  };

  const handleDelete = async (row) => {
    if (!await confirm(`"${row.title}" ${t('modals.confirmDelete.body')}`, { action: 'delete' })) return;
    setDeleteError(null);
    try {
      await api.del(`/calendar/${row.id}`);
      refreshData();
      invalidate();
    } catch (err) {
      setDeleteError(err.message || 'Löschen fehlgeschlagen');
    }
  };

  if (loading && !loaded && !modal) return <div className="page-loading">{t('ui.table.loading')}</div>;
  if (loadError && !loaded && !modal) return <div className="page"><p className="alert-error" role="alert">{loadError}{' '}
    <button type="button" className="btn btn-secondary btn-sm" onClick={refreshData}>Erneut laden</button></p></div>;

  return (
    <div className="page">
      <h1 className="page-title">Kalender</h1>
      <ObjectScope params={params} setParams={setParams} properties={properties} units={units} />
      {projectId && <p className="filter-chips">Termine einer Projektakte{' '}
        <Link to={`/maintenance/${encodeURIComponent(projectId)}?tab=appointments`}>Projektakte öffnen</Link>{' '}
        <button type="button" className="btn btn-secondary btn-sm" onClick={() => changeFilter('maintenance_case_id', '')}>Projektfilter aufheben</button></p>}
      <div className="filter-chips" aria-label="Terminzeitraum">
        <label>Von <input type="date" value={params.get('date_from') || ''} onChange={event => changeFilter('date_from', event.target.value)} /></label>
        <label>Bis <input type="date" value={params.get('date_to') || ''} onChange={event => changeFilter('date_to', event.target.value)} /></label>
        <button type="button" className="btn btn-secondary btn-sm" onClick={() => setPeriod(0)}>Heute</button>
        <button type="button" className="btn btn-secondary btn-sm" onClick={() => setPeriod(29)}>Nächste 30 Tage</button>
        <button type="button" className="btn btn-secondary btn-sm" onClick={() => setPeriod(null)}>Alle Termine</button>
      </div>
      {selected && <section className="card" aria-label="Termindetails" style={{ padding: '1rem', marginBottom: '1rem' }}>
        <h2>{selected.title}</h2><p>{formatDate(selected.event_date)}{selected.event_time ? ` · ${selected.event_time}` : ''}</p>
        {selected.location && <p>Ort: {selected.location}</p>}{selected.participants && <p>Teilnehmer: {selected.participants}</p>}
        {selected.description && <p style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{selected.description}</p>}
        <RelatedPageLinks items={[
          ...(selected.maintenance_case_id ? [{ to: `/maintenance/${encodeURIComponent(selected.maintenance_case_id)}?tab=appointments`, label: 'Projektakte und Termin bearbeiten' }] : []),
          ...(selected.property_id ? [{ to: `/properties/${encodeURIComponent(selected.property_id)}`, label: propertyNames.get(selected.property_id) || 'Immobilie öffnen' }] : []),
          ...(selected.unit_id ? [{ to: `/units/${encodeURIComponent(selected.unit_id)}`, label: unitNames.get(selected.unit_id) || 'Einheit öffnen' }] : []),
        ]} />
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => changeFilter('focus_id', '')}>Detailansicht schließen</button>
      </section>}
      {loadError && <p className="alert-error" role="alert">Termine konnten nicht aktualisiert werden. {loadError} Angezeigt wird der zuletzt geladene Stand.{' '}
        <button type="button" className="btn btn-secondary btn-sm" onClick={refreshData}>Erneut laden</button></p>}
      {propertyError && <p className="alert-error" role="alert">Die Immobilienauswahl ist nicht verfügbar. {propertyError}{' '}
        <button type="button" className="btn btn-secondary btn-sm" onClick={refreshData}>Auswahl erneut laden</button></p>}
      {unitSource.error && <p className="alert-error" role="alert">Die Einheitenauswahl ist nicht verfügbar. {unitSource.error}{' '}
        <button type="button" className="btn btn-secondary btn-sm" onClick={unitSource.reload}>Einheiten erneut laden</button></p>}
      {deleteError && (
        <div className="alert alert-error" style={{ marginBottom: '1rem' }}>
          {deleteError}
          <button onClick={() => setDeleteError(null)} style={{ marginLeft: '1rem', cursor: 'pointer' }}>✕</button>
        </div>
      )}
      <DataTable
        title={t('navigation.main.calendar') || 'Kalender'}
        columns={COLUMNS.map(column => column.key === 'title' ? { ...column, render: (value, row) =>
          <Link to={row.maintenance_case_id ? `/maintenance/${encodeURIComponent(row.maintenance_case_id)}?tab=appointments`
            : { search: (() => { const next = new URLSearchParams(params); next.set('focus_id', row.id); return `?${next}`; })() }}>{value}</Link> } : column)}
        data={visibleEvents.map(event => ({ ...event, property_name: propertyNames.get(event.property_id) || '—', unit_label: unitNames.get(event.unit_id) || '—' }))}
        rowName={row => row.title || row.id}
        clearFocusedRow={() => changeFilter('focus_id', '')}
        bulkActions={[bulkDelete({ one: 'Termin', many: 'Termine', remove: row => api.del(`/calendar/${row.id}`),
          finished: () => { refreshData(); invalidate(); } })]}
        onAdd={choicesReady && !projectId ? () => { setPrefill({ ...scopeDefaults(params, units), event_date: params.get('date_from') || dayString(new Date()) }); setModal('create'); } : undefined}
        onEdit={choicesReady ? row => setModal(row) : undefined}
        onDelete={handleDelete}
        rowActions={row => choicesReady ? [{ label: 'Duplizieren', write: true, icon: <CopyIcon size={15} />,
          onClick: () => { setPrefill(duplicateOf(row)); setModal('create'); } }] : []}
      />
      {modal && (
        <FormModal
          title={modal === 'create' ? 'Termin erstellen' : 'Termin bearbeiten'}
          repeatKeep={['event_type', 'event_date', 'property_id']}
          fields={fields}
          initial={modal === 'create' ? prefill : modal}
          onSave={handleSave}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  );
}
