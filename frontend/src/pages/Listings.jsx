import { useState, useEffect } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import StatusBadge from '../components/StatusBadge';

const COLUMNS = [
  { key: 'title', label: 'Titel', filterType: 'text' },
  { key: 'unit_label', label: 'Einheit', filterType: 'text' },
  { key: 'portal', label: 'Portal', filterType: 'select' },
  { key: 'target_rent', label: 'Zielmiete (€)', type: 'number', align: 'right',
    render: v => v != null ? `${Number(v).toFixed(2)} €` : '—' },
  { key: 'available_from', label: 'Verfügbar ab', type: 'date' },
  { key: 'status', label: 'Status', type: 'status', filterType: 'select',
    render: v => <StatusBadge status={v} /> },
];

export default function Listings() {
  const { t } = useTranslation();
  const [listings, setListings] = useState([]);
  const [units, setUnits] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(null);
  const [deleteError, setDeleteError] = useState(null);

  const loadData = () => {
    setLoading(true);
    Promise.all([
      api.get('/listings').catch(err => { console.warn('[Listings]', err.message); return []; }),
      api.get('/units').catch(() => []),
    ]).then(([l, u]) => {
      setListings(l || []);
      setUnits(u || []);
    }).finally(() => setLoading(false));
  };

  useEffect(() => { loadData(); }, []);

  const unitMap = Object.fromEntries(units.map(u => [u.id, u]));
  const enriched = listings.map(l => ({
    ...l,
    unit_label: unitMap[l.unit_id]?.label || '—',
  }));

  const fields = [
    { key: 'title', label: 'Titel', required: true },
    { key: 'unit_id', label: 'Einheit', required: true, type: 'select',
      options: units.map(u => ({ value: u.id, label: u.label })) },
    { key: 'portal', label: 'Portal', type: 'select', options: [
      { value: 'immoscout24', label: 'ImmoScout24' },
      { value: 'immowelt', label: 'Immowelt' },
      { value: 'ebay', label: 'eBay Kleinanzeigen' },
      { value: 'website', label: 'Eigene Website' },
      { value: 'other', label: 'Sonstiges' },
    ]},
    { key: 'target_rent', label: 'Zielmiete (€)', type: 'number' },
    { key: 'service_charge', label: 'Nebenkosten (€)', type: 'number' },
    { key: 'available_from', label: 'Verfügbar ab', type: 'date' },
    { key: 'contact_name', label: 'Ansprechpartner' },
    { key: 'contact_email', label: 'Kontakt-E-Mail' },
    { key: 'listing_url', label: 'Link zum Inserat' },
    { key: 'status', label: 'Status', type: 'select', default: 'draft', options: [
      { value: 'draft', label: 'Entwurf' },
      { value: 'active', label: 'Aktiv' },
      { value: 'paused', label: 'Pausiert' },
      { value: 'closed', label: 'Geschlossen' },
    ]},
    { key: 'description', label: 'Beschreibung', type: 'textarea' },
  ];

  const handleSave = async (data) => {
    if (modal === 'create') {
      await api.post('/listings', data);
    } else {
      await api.put(`/listings/${modal.id}`, data);
    }
    loadData();
  };

  const handleDelete = async (row) => {
    if (!window.confirm(`"${row.title}" ${t('modals.confirmDelete.body')}`)) return;
    setDeleteError(null);
    try {
      await api.del(`/listings/${row.id}`);
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
        title="Inserate"
        columns={COLUMNS}
        data={enriched}
        onAdd={() => setModal('create')}
        onEdit={row => setModal(row)}
        onDelete={handleDelete}
      />
      {modal && (
        <FormModal
          title={modal === 'create' ? 'Inserat erstellen' : 'Inserat bearbeiten'}
          fields={fields}
          initial={modal === 'create' ? null : modal}
          onSave={handleSave}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  );
}
