import useWriteAccess from '../hooks/useWriteAccess';
import { revisionOptions } from '../editRevision';
import { useState } from 'react';
import { api } from '../api';
import { useFinanceData } from '../hooks/useFinanceData';
import FinanceLoadState from '../components/FinanceLoadState';
import { useTranslation } from '../i18n';
import { useDataStore } from '../contexts/DataStoreContext';
import { useAuth } from '../contexts/AuthContext';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import { useConfirm } from '../components/ConfirmDialog';
import BillingDimensionValue from '../features/billingDimensions/BillingDimensionValue';
import {
  DIMENSION_HINTS,
  allocationKeyPayload,
  billingPrincipalKey,
} from '../features/billingDimensions/billingDimensions';
import '../features/billingDimensions/BillingDimensions.css';

const KEY_TYPE_OPTIONS = [
  { value: 'area_sqm', label: 'Fläche (m²)' },
  { value: 'unit_count', label: 'Anzahl Einheiten' },
  { value: 'person_count', label: 'Personenzahl' },
  { value: 'consumption', label: 'Verbrauch' },
];

const KEY_TYPE_LABELS = Object.fromEntries(KEY_TYPE_OPTIONS.map(o => [o.value, o.label]));

function dimensionCell(value, kind, row) {
  if (row.key_type !== 'consumption' && !value) return '—';
  return <BillingDimensionValue value={value} kind={kind} required={row.key_type === 'consumption'} />;
}

const COLUMNS = [
  { key: 'name', label: 'Bezeichnung', filterType: 'text' },
  { key: 'key_type', label: 'Schlüsseltyp', render: v => KEY_TYPE_LABELS[v] || v },
  { key: 'consumption_medium', label: 'Medium', render: (value, row) => dimensionCell(value, 'medium', row) },
  { key: 'consumption_unit', label: 'Maßeinheit', render: (value, row) => dimensionCell(value, 'unit', row) },
  { key: 'property_label', label: 'Immobilie' },
  { key: 'description', label: 'Beschreibung' },
];

function AllocationKeysView() {
  const { t } = useTranslation();
  const confirm = useConfirm();
  const store = useDataStore();
  const { data: { keys, properties }, loading, error, reload: refreshData } = useFinanceData({
    keys: '/billing/allocation-keys',
    properties: '/properties',
  });
  const [modal, setModal] = useState(null);
  const { canWrite, isAllowed, requireWrite } = useWriteAccess('/billing', () => setModal(null));
  const [deleteError, setDeleteError] = useState(null);

  const propertyMap = Object.fromEntries(properties.map(p => [p.id, p.name]));
  const enriched = keys.map(k => ({ ...k, property_label: propertyMap[k.property_id] || '—' }));

  const fields = [
    { key: 'name', label: 'Bezeichnung', required: true, placeholder: 'z.B. Verbrauch Kaltwasser' },
    { key: 'property_id', label: 'Immobilie', type: 'select', required: true,
      options: properties.map(p => ({ value: p.id, label: p.name })) },
    { key: 'key_type', label: 'Schlüsseltyp', type: 'select', required: true, options: KEY_TYPE_OPTIONS },
    { key: 'consumption_medium', label: 'Verbrauchsmedium',
      placeholder: 'z.B. cold_water', hint: DIMENSION_HINTS.medium },
    { key: 'consumption_unit', label: 'Maßeinheit',
      placeholder: 'z.B. m³ oder kWh', hint: DIMENSION_HINTS.allocationUnit },
    { key: 'description', label: 'Beschreibung', type: 'textarea' },
  ];

  const handleSave = async (data) => {
    requireWrite();
    const payload = allocationKeyPayload(data);
    if (modal === 'create') {
      await api.post('/billing/allocation-keys', payload);
    } else {
      await api.put(`/billing/allocation-keys/${modal.id}`, payload);
    }
  };

  const afterSave = () => {
    refreshData();
    if (store) store.invalidateRelated('allocation_keys');
  };

  const handleDelete = async (row) => {
    if (!isAllowed()) return;
    const name = row.name || row.id;
    if (!await confirm(`"${name}" ${t('modals.confirmDelete.body')}`)) return;
    setDeleteError(null);
    try {
      if (!isAllowed()) return;
      await api.del(`/billing/allocation-keys/${row.id}`, revisionOptions(row));
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
        onAdd={canWrite ? () => setModal('create') : undefined}
        onEdit={canWrite ? row => setModal(row) : undefined}
        onDelete={canWrite ? handleDelete : undefined}
      />
      {modal && canWrite && (
        <FormModal onSaved={afterSave} draftConfig={{ collection: 'billing/allocation-keys' }}
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

export default function AllocationKeys() {
  const auth = useAuth();
  const binding = billingPrincipalKey(auth);
  return <AllocationKeysView key={binding || 'billing-allocation-keys-neutral'} />;
}
