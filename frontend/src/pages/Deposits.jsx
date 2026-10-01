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

export default function Deposits() {
  const { t } = useTranslation();
  const confirm = useConfirm();
  const store = useDataStore();
  const { data: { deposits, contracts }, loading, error, reload: refreshData } = useFinanceData({
    deposits: '/deposits',
    contracts: '/contracts',
  });
  const [modal, setModal] = useState(null);
  const [deleteError, setDeleteError] = useState(null);


  const contractMap = Object.fromEntries(contracts.map(c => [c.id, c]));

  const enriched = deposits.map(d => ({
    ...d,
    contract_label: contractMap[d.contract_id]?.contract_number || '—',
  }));

  const COLUMNS = [
    { key: 'contract_label', label: 'Vertrag', filterType: 'text' },
    { key: 'amount', label: 'Betrag (€)', type: 'number', align: 'right',
      render: v => v != null ? `${Number(v).toFixed(2)} €` : '—' },
    { key: 'status', label: 'Status', type: 'status', filterType: 'select',
      render: v => <StatusBadge status={v} /> },
    { key: 'held_date', label: 'Hinterlegt am', type: 'date' },
    { key: 'return_date', label: 'Rückgabe', type: 'date' },
    { key: 'deductions', label: 'Abzüge (€)', type: 'number', align: 'right',
      render: v => v != null ? `${Number(v).toFixed(2)} €` : '—' },
  ];

  const fields = [
    { key: 'contract_id', label: 'Vertrag', required: true, type: 'select',
      options: contracts.map(c => ({ value: c.id, label: c.contract_number })) },
    { key: 'amount', label: 'Kautionsbetrag (€)', type: 'number', required: true },
    { key: 'status', label: 'Status', type: 'select', default: 'held', options: [
      { value: 'held', label: 'Hinterlegt' },
      { value: 'partially_returned', label: 'Teilweise zurückgegeben' },
      { value: 'returned', label: 'Zurückgegeben' },
    ]},
    { key: 'held_date', label: 'Hinterlegungsdatum', type: 'date' },
    { key: 'return_date', label: 'Rückgabedatum', type: 'date' },
    { key: 'deductions', label: 'Abzüge (€)', type: 'number' },
    { key: 'deduction_reason', label: 'Abzugsgrund', type: 'textarea' },
    { key: 'notes', label: 'Notizen', type: 'textarea' },
  ];

  const handleSave = async (data) => {
    if (modal === 'create') {
      await api.post('/deposits', data);
    } else {
      await api.put(`/deposits/${modal.id}`, data);
    }
    setModal(null);
    refreshData();
    if (store) store.invalidateRelated('deposits', 'contracts');
  };

  const handleDelete = async (row) => {
    const name = row.contract_label || row.id;
    if (!await confirm(`"${name}" ${t('modals.confirmDelete.body')}`)) return;
    setDeleteError(null);
    try {
      await api.del(`/deposits/${row.id}`);
      refreshData();
      if (store) store.invalidateRelated('deposits', 'contracts');
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
        title="Kautionen"
        columns={COLUMNS}
        data={enriched}
        onAdd={() => setModal('create')}
        onEdit={row => setModal(row)}
        onDelete={handleDelete}
      />
      {modal && (
        <FormModal
          title={modal === 'create' ? 'Kaution erstellen' : 'Kaution bearbeiten'}
          fields={fields}
          initial={modal === 'create' ? null : modal}
          onSave={handleSave}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  );
}
