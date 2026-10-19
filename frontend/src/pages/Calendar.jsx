import { useState, useEffect, useCallback } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import StatusBadge from '../components/StatusBadge';
import { useConfirm } from '../components/ConfirmDialog';
import { bulkDelete } from '../utils/bulkActions';
import { Copy as CopyIcon } from 'lucide-react';
import { duplicateOf } from '../utils/duplicate';

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
  { key: 'location', label: 'Ort', filterType: 'text' },
  { key: 'participants', label: 'Teilnehmer' },
];

export default function Calendar() {
  const { t } = useTranslation();
  const confirm = useConfirm();
  const [events, setEvents] = useState([]);
  const [properties, setProperties] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(null);
  // values of a duplicated appointment for the New form (null: an empty form)
  const [prefill, setPrefill] = useState(null);
  const [deleteError, setDeleteError] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [propertyError, setPropertyError] = useState(null);
  const [loaded, setLoaded] = useState(false);
  const [revision, setRevision] = useState(0);

  const refreshData = useCallback(() => setRevision(value => value + 1), []);
  useEffect(() => {
    const request = new AbortController();
    setLoading(true);
    Promise.allSettled([
      api.list('/calendar', { signal: request.signal }),
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
  }, [revision]);
  const choicesReady = !loading && !propertyError;

  const fields = [
    { key: 'title', label: 'Titel', required: true },
    { key: 'event_type', label: 'Typ', type: 'select', required: true, options: EVENT_TYPES },
    { key: 'event_date', label: 'Datum', type: 'date', required: true },
    { key: 'event_time', label: 'Uhrzeit', placeholder: 'z.B. 14:00' },
    { key: 'location', label: 'Ort' },
    { key: 'participants', label: 'Teilnehmer' },
    { key: 'property_id', label: 'Immobilie', type: 'select',
      options: properties.map(p => ({ value: p.id, label: p.name })) },
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
  };

  const handleDelete = async (row) => {
    if (!await confirm(`"${row.title}" ${t('modals.confirmDelete.body')}`)) return;
    setDeleteError(null);
    try {
      await api.del(`/calendar/${row.id}`);
      refreshData();
    } catch (err) {
      setDeleteError(err.message || 'Löschen fehlgeschlagen');
    }
  };

  if (loading && !loaded && !modal) return <div className="page-loading">{t('ui.table.loading')}</div>;
  if (loadError && !loaded && !modal) return <div className="page"><p className="alert-error" role="alert">{loadError}{' '}
    <button type="button" className="btn btn-secondary btn-sm" onClick={refreshData}>Erneut laden</button></p></div>;

  return (
    <div className="page">
      {loadError && <p className="alert-error" role="alert">Termine konnten nicht aktualisiert werden. {loadError} Angezeigt wird der zuletzt geladene Stand.{' '}
        <button type="button" className="btn btn-secondary btn-sm" onClick={refreshData}>Erneut laden</button></p>}
      {propertyError && <p className="alert-error" role="alert">Die Immobilienauswahl ist nicht verfügbar. {propertyError}{' '}
        <button type="button" className="btn btn-secondary btn-sm" onClick={refreshData}>Auswahl erneut laden</button></p>}
      {deleteError && (
        <div className="alert alert-error" style={{ marginBottom: '1rem' }}>
          {deleteError}
          <button onClick={() => setDeleteError(null)} style={{ marginLeft: '1rem', cursor: 'pointer' }}>✕</button>
        </div>
      )}
      <DataTable
        title={t('navigation.main.calendar') || 'Kalender'}
        columns={COLUMNS}
        data={events}
        rowName={row => row.title || row.id}
        bulkActions={[bulkDelete({ one: 'Termin', many: 'Termine', remove: row => api.del(`/calendar/${row.id}`),
          finished: () => refreshData() })]}
        onAdd={choicesReady ? () => { setPrefill(null); setModal('create'); } : undefined}
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
