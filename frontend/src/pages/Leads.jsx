import { useState, useEffect } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import StatusBadge from '../components/StatusBadge';

const COLUMNS = [
  { key: 'full_name', label: 'Name', filterType: 'text' },
  { key: 'email', label: 'E-Mail', filterType: 'text' },
  { key: 'phone', label: 'Telefon' },
  { key: 'source', label: 'Quelle', filterType: 'select' },
  { key: 'status', label: 'Status', type: 'status', filterType: 'select',
    render: v => <StatusBadge status={v} /> },
  { key: 'unit_label', label: 'Einheit', filterType: 'text' },
];

export default function Leads() {
  const { t } = useTranslation();
  const [leads, setLeads] = useState([]);
  const [units, setUnits] = useState([]);
  const [listings, setListings] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(null);
  const [deleteError, setDeleteError] = useState(null);

  const loadData = () => {
    setLoading(true);
    Promise.all([
      api.get('/leads').catch(err => { console.warn('[Leads]', err.message); return []; }),
      api.get('/units').catch(() => []),
      api.get('/listings').catch(() => []),
    ]).then(([l, u, li]) => {
      setLeads(l || []);
      setUnits(u || []);
      setListings(li || []);
    }).finally(() => setLoading(false));
  };

  useEffect(() => { loadData(); }, []);

  const unitMap = Object.fromEntries(units.map(u => [u.id, u]));
  const enriched = leads.map(l => ({
    ...l,
    unit_label: unitMap[l.unit_id]?.label || '—',
  }));

  const fields = [
    { key: 'full_name', label: 'Name', required: true },
    { key: 'email', label: 'E-Mail' },
    { key: 'phone', label: 'Telefon' },
    { key: 'source', label: 'Quelle', type: 'select', options: [
      { value: 'portal', label: 'Portal' },
      { value: 'website', label: 'Website' },
      { value: 'referral', label: 'Empfehlung' },
      { value: 'direct', label: 'Direkt' },
      { value: 'other', label: 'Sonstiges' },
    ]},
    { key: 'unit_id', label: 'Einheit', type: 'select',
      options: units.map(u => ({ value: u.id, label: u.label })) },
    { key: 'listing_id', label: 'Inserat', type: 'select',
      options: listings.map(l => ({ value: l.id, label: l.title })) },
    { key: 'status', label: 'Status', type: 'select', default: 'new', options: [
      { value: 'new', label: 'Neu' },
      { value: 'contacted', label: 'Kontaktiert' },
      { value: 'viewing_scheduled', label: 'Besichtigung geplant' },
      { value: 'offer_sent', label: 'Angebot gesendet' },
      { value: 'accepted', label: 'Angenommen' },
      { value: 'rejected', label: 'Abgelehnt' },
    ]},
    { key: 'notes', label: 'Notizen', type: 'textarea' },
  ];

  const handleSave = async (data) => {
    if (modal === 'create') {
      await api.post('/leads', data);
    } else {
      await api.put(`/leads/${modal.id}`, data);
    }
    loadData();
  };

  const handleDelete = async (row) => {
    if (!window.confirm(`"${row.full_name}" ${t('modals.confirmDelete.body')}`)) return;
    setDeleteError(null);
    try {
      await api.del(`/leads/${row.id}`);
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
        title="Interessenten"
        columns={COLUMNS}
        data={enriched}
        onAdd={() => setModal('create')}
        onEdit={row => setModal(row)}
        onDelete={handleDelete}
      />
      {modal && (
        <FormModal
          title={modal === 'create' ? 'Interessent erstellen' : 'Interessent bearbeiten'}
          fields={fields}
          initial={modal === 'create' ? null : modal}
          onSave={handleSave}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  );
}
