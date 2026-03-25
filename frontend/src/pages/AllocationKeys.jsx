import { useState, useEffect } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import { useEntities, useDataStore } from '../contexts/DataStoreContext';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';

const KEY_TYPE_OPTIONS = [
  { value: 'area_sqm', label: 'Fläche (m²)' },
  { value: 'unit_count', label: 'Anzahl Einheiten' },
  { value: 'person_count', label: 'Personenzahl' },
  { value: 'consumption', label: 'Verbrauch' },
];

const KEY_TYPE_LABELS = Object.fromEntries(KEY_TYPE_OPTIONS.map(o => [o.value, o.label]));

const COLUMNS = [
  { key: 'name', label: 'Bezeichnung', filterType: 'text' },
  { key: 'key_type', label: 'Schlüsseltyp', render: v => KEY_TYPE_LABELS[v] || v },
  { key: 'property_label', label: 'Immobilie' },
  { key: 'description', label: 'Beschreibung' },
];

export default function AllocationKeys() {
  const { t } = useTranslation();
  const store = useDataStore();
  const { items: properties } = useEntities('properties', '/properties');
  const [keys, setKeys] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [modal, setModal] = useState(null);
  const [deleteError, setDeleteError] = useState(null);

  const refreshData = () => {
    api.get('/billing/allocation-keys').catch(err => { console.warn('[AllocationKeys] keys:', err.message); return []; })
      .then(k => setKeys(k || []))
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    let cancelled = false;
    api.get('/billing/allocation-keys').catch(err => { console.warn('[AllocationKeys] keys:', err.message); return []; })
      .then(data => { if (!cancelled) setKeys(data || []); })
      .catch(e => { if (!cancelled) setError(e.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  const propertyMap = Object.fromEntries(properties.map(p => [p.id, p.name]));
  const enriched = keys.map(k => ({ ...k, property_label: propertyMap[k.property_id] || '—' }));

  const fields = [
    { key: 'name', label: 'Bezeichnung', required: true, placeholder: 'z.B. Fläche Heizung' },
    { key: 'property_id', label: 'Immobilie', type: 'select', required: true,
      options: properties.map(p => ({ value: p.id, label: p.name })) },
    { key: 'key_type', label: 'Schlüsseltyp', type: 'select', required: true, options: KEY_TYPE_OPTIONS },
    { key: 'description', label: 'Beschreibung', type: 'textarea' },
  ];

  const handleSave = async (data) => {
    if (modal === 'create') {
      await api.post('/billing/allocation-keys', data);
    } else {
      await api.put(`/billing/allocation-keys/${modal.id}`, data);
    }
    refreshData();
    if (store) store.invalidateRelated('allocation_keys');
  };

  const handleDelete = async (row) => {
    const name = row.name || row.id;
    if (!window.confirm(`"${name}" ${t('modals.confirmDelete.body')}`)) return;
    setDeleteError(null);
    try {
      await api.del(`/billing/allocation-keys/${row.id}`);
      refreshData();
      if (store) store.invalidateRelated('allocation_keys');
    } catch (err) {
      setDeleteError(err.message || 'Löschen fehlgeschlagen');
    }
  };

  if (loading) return <div className="page-loading">{t('ui.table.loading')}</div>;
  if (error) return <div className="page"><div className="alert alert-error">{error}</div></div>;

  return (
    <div className="page">
      {deleteError && (
        <div className="alert alert-error" style={{ marginBottom: '1rem' }}>
          {deleteError}
          <button onClick={() => setDeleteError(null)} style={{ marginLeft: '1rem', cursor: 'pointer' }}>✕</button>
        </div>
      )}
      <DataTable
        title="Verteilerschlüssel"
        columns={COLUMNS}
        data={enriched}
        onAdd={() => setModal('create')}
        onEdit={row => setModal(row)}
        onDelete={handleDelete}
      />
      {modal && (
        <FormModal
          title={modal === 'create' ? 'Verteilerschlüssel erstellen' : 'Verteilerschlüssel bearbeiten'}
          fields={fields}
          initial={modal === 'create' ? null : modal}
          onSave={handleSave}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  );
}
