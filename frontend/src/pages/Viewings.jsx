import { useState, useEffect } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import StatusBadge from '../components/StatusBadge';

const COLUMNS = [
  { key: 'lead_name', label: 'Interessent', filterType: 'text' },
  { key: 'unit_label', label: 'Einheit', filterType: 'text' },
  { key: 'scheduled_at', label: 'Termin', type: 'date', filterType: 'dateRange' },
  { key: 'agent', label: 'Betreuer', filterType: 'text' },
  { key: 'status', label: 'Status', type: 'status', filterType: 'select',
    render: v => <StatusBadge status={v} /> },
];

export default function Viewings() {
  const { t } = useTranslation();
  const [viewings, setViewings] = useState([]);
  const [leads, setLeads] = useState([]);
  const [units, setUnits] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(null);
  const [deleteError, setDeleteError] = useState(null);

  const loadData = () => {
    setLoading(true);
    Promise.all([
      api.get('/viewings').catch(err => { console.warn('[Viewings]', err.message); return []; }),
      api.get('/leads').catch(() => []),
      api.get('/units').catch(() => []),
    ]).then(([v, l, u]) => {
      setViewings(v || []);
      setLeads(l || []);
      setUnits(u || []);
    }).finally(() => setLoading(false));
  };

  useEffect(() => { loadData(); }, []);

  const leadMap = Object.fromEntries(leads.map(l => [l.id, l]));
  const unitMap = Object.fromEntries(units.map(u => [u.id, u]));
  const enriched = viewings.map(v => ({
    ...v,
    lead_name: leadMap[v.lead_id]?.full_name || '—',
    unit_label: unitMap[v.unit_id]?.label || '—',
    scheduled_at: v.scheduled_at?.slice(0, 16)?.replace('T', ' ') || '—',
  }));

  const fields = [
    { key: 'lead_id', label: 'Interessent', required: true, type: 'select',
      options: leads.map(l => ({ value: l.id, label: l.full_name })) },
    { key: 'unit_id', label: 'Einheit', required: true, type: 'select',
      options: units.map(u => ({ value: u.id, label: u.label })) },
    { key: 'scheduled_at', label: 'Termin', type: 'datetime-local', required: true },
    { key: 'agent', label: 'Betreuer' },
    { key: 'status', label: 'Status', type: 'select', default: 'scheduled', options: [
      { value: 'scheduled', label: 'Geplant' },
      { value: 'completed', label: 'Durchgeführt' },
      { value: 'cancelled', label: 'Abgesagt' },
      { value: 'no_show', label: 'Nicht erschienen' },
    ]},
    { key: 'notes', label: 'Notizen', type: 'textarea' },
  ];

  const handleSave = async (data) => {
    if (modal === 'create') {
      await api.post('/viewings', data);
    } else {
      await api.put(`/viewings/${modal.id}`, data);
    }
    loadData();
  };

  const handleDelete = async (row) => {
    if (!window.confirm(`"${row.lead_name}" ${t('modals.confirmDelete.body')}`)) return;
    setDeleteError(null);
    try {
      await api.del(`/viewings/${row.id}`);
      loadData();
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
        title="Besichtigungen"
        columns={COLUMNS}
        data={enriched}
        onAdd={() => setModal('create')}
        onEdit={row => setModal(row)}
        onDelete={handleDelete}
      />
      {modal && (
        <FormModal
          title={modal === 'create' ? 'Besichtigung erstellen' : 'Besichtigung bearbeiten'}
          fields={fields}
          initial={modal === 'create' ? null : modal}
          onSave={handleSave}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  );
}
