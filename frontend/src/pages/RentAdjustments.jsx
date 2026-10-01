import { useState } from 'react';
import { api } from '../api';
import { useFinanceData } from '../hooks/useFinanceData';
import FinanceLoadState from '../components/FinanceLoadState';
import { useTranslation } from '../i18n';
import { useDataStore } from '../contexts/DataStoreContext';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import StatusBadge from '../components/StatusBadge';
import { useConfirm } from '../components/ConfirmDialog';

const COLUMNS = [
  { key: 'contract_number', label: 'Vertrag', filterType: 'text' },
  { key: 'adjustment_type', label: 'Art', filterType: 'select',
    render: v => v === 'index' ? 'Indexmiete' : v === 'stepped' ? 'Staffelmiete' : v || '—' },
  { key: 'effective_date', label: 'Wirksamkeit', type: 'date', filterType: 'dateRange' },
  { key: 'previous_rent', label: 'Bisherige Miete (€)', type: 'number', align: 'right',
    render: v => v != null ? `${Number(v).toFixed(2)} €` : '—' },
  { key: 'new_rent', label: 'Neue Miete (€)', type: 'number', align: 'right',
    render: v => v != null ? `${Number(v).toFixed(2)} €` : '—' },
  { key: 'increase_percent', label: 'Erhöhung (%)', type: 'number', align: 'right',
    render: v => v != null ? `${Number(v).toFixed(1)} %` : '—' },
  { key: 'status', label: 'Status', type: 'status', filterType: 'select',
    render: v => <StatusBadge status={v} /> },
];

export default function RentAdjustments() {
  const { t } = useTranslation();
  const confirm = useConfirm();
  const store = useDataStore();
  const { data: { adjustments, contracts }, loading, error, reload: refreshData } = useFinanceData({
    adjustments: '/rent-adjustments',
    contracts: '/contracts',
  });
  const [modal, setModal] = useState(null);
  const [deleteError, setDeleteError] = useState(null);


  const contractMap = Object.fromEntries(contracts.map(c => [c.id, c]));
  const enriched = adjustments.map(a => ({
    ...a,
    contract_number: contractMap[a.contract_id]?.contract_number || '—',
  }));

  const fields = [
    { key: 'contract_id', label: 'Vertrag', required: true, type: 'select',
      options: contracts.map(c => ({ value: c.id, label: c.contract_number })) },
    { key: 'adjustment_type', label: 'Art', required: true, type: 'select', options: [
      { value: 'index', label: 'Indexmiete' },
      { value: 'stepped', label: 'Staffelmiete' },
    ]},
    { key: 'effective_date', label: 'Wirksamkeitsdatum', type: 'date', required: true },
    { key: 'previous_rent', label: 'Bisherige Miete (€)', type: 'number', required: true },
    { key: 'new_rent', label: 'Neue Miete (€)', type: 'number', required: true },
    { key: 'increase_percent', label: 'Erhöhung (%)', type: 'number' },
    { key: 'index_base_year', label: 'Index-Basisjahr', type: 'number' },
    { key: 'index_value', label: 'Indexwert', type: 'number' },
    { key: 'status', label: 'Status', type: 'select', default: 'pending', options: [
      { value: 'pending', label: 'Ausstehend' },
      { value: 'applied', label: 'Angewendet' },
      { value: 'rejected', label: 'Abgelehnt' },
    ]},
    { key: 'notes', label: 'Notizen', type: 'textarea' },
  ];

  const handleSave = async (data) => {
    if (modal === 'create') {
      await api.post('/rent-adjustments', data);
    } else {
      await api.put(`/rent-adjustments/${modal.id}`, data);
    }
    setModal(null);
    refreshData();
    if (store) store.invalidateRelated('rent_adjustments', 'contracts');
  };

  const handleDelete = async (row) => {
    if (!await confirm(`"${row.contract_number}" ${t('modals.confirmDelete.body')}`)) return;
    setDeleteError(null);
    try {
      await api.del(`/rent-adjustments/${row.id}`);
      refreshData();
      if (store) store.invalidateRelated('rent_adjustments', 'contracts');
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
        title="Mietanpassungen"
        columns={COLUMNS}
        data={enriched}
        onAdd={() => setModal('create')}
        onEdit={row => setModal(row)}
        onDelete={handleDelete}
      />
      {modal && (
        <FormModal
          title={modal === 'create' ? 'Mietanpassung erstellen' : 'Mietanpassung bearbeiten'}
          fields={fields}
          initial={modal === 'create' ? null : modal}
          onSave={handleSave}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  );
}
