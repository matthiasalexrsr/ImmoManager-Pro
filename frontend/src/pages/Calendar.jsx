import { useState, useEffect } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import StatusBadge from '../components/StatusBadge';

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
  const [events, setEvents] = useState([]);
  const [properties, setProperties] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(null);
  const [deleteError, setDeleteError] = useState(null);

  const refreshData = () => {
    Promise.all([
      api.get('/calendar').catch(err => { console.warn('[Calendar]', err.message); return []; }),
      api.get('/properties').catch(() => []),
    ]).then(([ev, props]) => {
      setEvents(ev || []);
      setProperties(props || []);
    }).finally(() => setLoading(false));
  };

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      api.get('/calendar').catch(err => { console.warn('[Calendar]', err.message); return []; }),
      api.get('/properties').catch(err => { console.warn('[Calendar] properties:', err.message); return []; }),
    ]).then(([first, second]) => {
      if (cancelled) return;
      setEvents(first || []);
      setProperties(second || []);
    }).catch(e => {
      if (!cancelled) console.warn('[Calendar] load failed:', e.message);
    }).finally(() => {
      if (!cancelled) setLoading(false);
    });

    return () => {
      cancelled = true;
    };
  }, []);

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
    if (modal === 'create') {
      await api.post('/calendar', data);
    } else {
      await api.put(`/calendar/${modal.id}`, data);
    }
    refreshData();
  };

  const handleDelete = async (row) => {
    if (!window.confirm(`"${row.title}" ${t('modals.confirmDelete.body')}`)) return;
    setDeleteError(null);
    try {
      await api.del(`/calendar/${row.id}`);
      refreshData();
    } catch (err) {
      setDeleteError(err.message || 'Löschen fehlgeschlagen');
    }
  };

  if (loading) return <div className="page-loading">{t('ui.table.loading')}</div>;

  return (
    <div className="page">
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
        onAdd={() => setModal('create')}
        onEdit={row => setModal(row)}
        onDelete={handleDelete}
      />
      {modal && (
        <FormModal
          title={modal === 'create' ? 'Termin erstellen' : 'Termin bearbeiten'}
          fields={fields}
          initial={modal === 'create' ? null : modal}
          onSave={handleSave}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  );
}
