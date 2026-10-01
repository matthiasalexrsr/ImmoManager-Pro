import { useState } from 'react';
import { api } from '../api';
import { useFinanceData } from '../hooks/useFinanceData';
import FinanceLoadState from '../components/FinanceLoadState';
import { useTranslation } from '../i18n';
import { useDataStore } from '../contexts/DataStoreContext';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import { useConfirm } from '../components/ConfirmDialog';

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
  const confirm = useConfirm();
  const store = useDataStore();
  const { data: { keys, properties }, loading, error, reload: refreshData } = useFinanceData({
    keys: '/billing/allocation-keys',
    properties: '/properties',
  });
  const [modal, setModal] = useState(null);
  const [deleteError, setDeleteError] = useState(null);


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
    setModal(null);
    refreshData();
    if (store) store.invalidateRelated('allocation_keys');
  };

  const handleDelete = async (row) => {
    const name = row.name || row.id;
    if (!await confirm(`"${name}" ${t('modals.confirmDelete.body')}`)) return;
    setDeleteError(null);
    try {
      await api.del(`/billing/allocation-keys/${row.id}`);
      refreshData();
      if (store) store.invalidateRelated('allocation_keys');
    } catch (err) {
      setDeleteError(err.message || 'Löschen fehlgeschlagen');
    }
  };

  if (loading || error) return <FinanceLoadState loading={loading} error={error} onRetry={refreshData} />;

  return (
    <div className="page">
      {deleteError && (
        <div className="alert alert-error" role="alert" style={{ marginBottom: '1rem' }}>
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
