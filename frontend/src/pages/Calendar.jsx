import { revisionOptions } from '../editRevision';
import { useState, useEffect } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import StatusBadge from '../components/StatusBadge';
import { useConfirm } from '../components/ConfirmDialog';
import OperationalTickPanel from '../components/OperationalTickPanel';
import useWriteAccess from '../hooks/useWriteAccess';

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
  const { canWrite, isAllowed, requireWrite } = useWriteAccess('/calendar', () => { setModal(null); setScheduleEditor(null); });
  const confirm = useConfirm();
  const [events, setEvents] = useState([]);
  const [properties, setProperties] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(null);
  const [deleteError, setDeleteError] = useState(null);
  const [error, setError] = useState(null);
  const [revision, setRevision] = useState(0);
  const [scheduleEditor, setScheduleEditor] = useState(null);

  const refreshData = () => setRevision(value => value + 1);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError(null);
    Promise.all([api.getAll('/calendar', { signal: controller.signal }), api.getAll('/properties', { signal: controller.signal }),
      api.get('/calendar/schedules', { signal: controller.signal })]).then(([rows, props, schedules]) => {
      if (controller.signal.aborted) return;
      setEvents(rows.map(row => ({ ...row, schedule: schedules.find(plan => plan.source_id === row.id) })));
      setProperties(props);
    }).catch(err => { if (!controller.signal.aborted) setError(err.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [revision]);
  const columns = [...COLUMNS, { key: 'schedule', label: t('operational.recurrence'), render: (value, row) => <>
    {value?.active ? value.recurrence_rule : '—'} {canWrite && <button type="button" className="btn btn-sm btn-secondary"
      aria-label={`${t('operational.configure')} ${row.title}`} onClick={() => setScheduleEditor(row)}>{t('operational.configure')}</button>}
  </> }];
  const scheduleFields = [
    { key: 'recurrence_rule', label: t('operational.recurrence'), required: true, placeholder: 'FREQ=MONTHLY;COUNT=12', hint: t('operational.calendarRuleHint') },
    { key: 'active', label: t('operational.active'), type: 'select', required: true, options: [{ value: 'true', label: t('operational.yes') }, { value: 'false', label: t('operational.no') }] },
  ];
  const saveSchedule = async values => {
    requireWrite();
    await api.put(`/calendar/${scheduleEditor.id}/schedule`, { ...values, active: values.active === 'true', full_catch_up: true });
    refreshData();
  };

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
    requireWrite();
    if (modal === 'create') {
      await api.post('/calendar', data);
    } else {
      await api.put(`/calendar/${modal.id}`, data);
    }
    refreshData();
  };

  const handleDelete = async (row) => {
    if (!isAllowed()) return;
    if (!await confirm(`"${row.title}" ${t('modals.confirmDelete.body')}`)) return;
    if (!isAllowed()) return;
    setDeleteError(null);
    try {
      await api.del(`/calendar/${row.id}`, revisionOptions(row));
      refreshData();
    } catch (err) {
      setDeleteError(err.message || 'Löschen fehlgeschlagen');
    }
  };

  if (loading) return <div className="page-loading">{t('ui.table.loading')}</div>;

  return (
    <div className="page">
      <OperationalTickPanel onCompleted={refreshData} />
      {error && <div role="alert">{error} <button type="button" className="btn btn-secondary" onClick={refreshData}>{t('operational.retry')}</button></div>}
      {deleteError && (
        <div className="alert alert-error" style={{ marginBottom: '1rem' }}>
          {deleteError}
          <button onClick={() => setDeleteError(null)} style={{ marginLeft: '1rem', cursor: 'pointer' }}>✕</button>
        </div>
      )}
      <DataTable
        title={t('navigation.main.calendar') || 'Kalender'}
        columns={columns}
        data={events}
        onAdd={canWrite ? () => setModal('create') : undefined}
        onEdit={canWrite ? row => setModal(row) : undefined}
        onDelete={canWrite ? handleDelete : undefined}
      />
      {scheduleEditor && <FormModal title={t('operational.configure')} fields={scheduleFields}
        initial={{ recurrence_rule: scheduleEditor.schedule?.recurrence_rule || 'FREQ=MONTHLY', active: scheduleEditor.schedule?.active === false ? 'false' : 'true' }}
        onSave={saveSchedule} onClose={() => setScheduleEditor(null)} />}
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
