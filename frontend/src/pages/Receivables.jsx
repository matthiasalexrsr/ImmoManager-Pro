import { bindEditRevision, revisionOptions, revisionSource, snapshotRevision } from '../editRevision';
import { useState } from 'react';
import useWriteAccess from '../hooks/useWriteAccess';
import { api } from '../api';
import { useFinanceData } from '../hooks/useFinanceData';
import FinanceLoadState from '../components/FinanceLoadState';
import { useTranslation } from '../i18n';
import { useDataStore } from '../contexts/DataStoreContext';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import StatusBadge from '../components/StatusBadge';
import { useConfirm } from '../components/ConfirmDialog';

export default function Receivables() {
  const { t } = useTranslation();
  const confirm = useConfirm();
  const store = useDataStore();
  const { data: { receivables, contracts }, loading, error, reload: refreshData } = useFinanceData({
    receivables: '/receivables',
    contracts: '/contracts',
  });
  const [modal, setModal] = useState(null);
  const { canWrite, isAllowed, requireWrite } = useWriteAccess('/receivables', () => setModal(null));
  const [deleteError, setDeleteError] = useState(null);


  const contractMap = Object.fromEntries(contracts.map(c => [c.id, c]));

  const enriched = receivables.map(r => ({
    ...r,
    contract_label: contractMap[r.contract_id]?.contract_number || '—',
  }));

  const COLUMNS = [
    { key: 'contract_label', label: t('tenantsContracts.contracts.title'), filterType: 'text' },
    { key: 'amount_due', label: t('finance.bookings.amount'), type: 'number', align: 'right',
      render: v => v != null ? `${Number(v).toFixed(2)} €` : '—' },
    { key: 'amount_paid', label: t('pages.rentOverview.paid'), type: 'number', render: v => `${Number(v || 0).toFixed(2)} €` },
    { key: 'due_date', label: t('finance.receivables.dueDate'), type: 'date', filterType: 'dateRange' },
    { key: 'status', label: t('ui.form.status'), type: 'status', filterType: 'select',
      render: v => <StatusBadge status={v} /> },
    { key: 'description', label: t('ui.form.description') },
  ];

  const fields = [
    { key: 'contract_id', label: t('tenantsContracts.contracts.title'), required: true, type: 'select',
      options: contracts.map(c => ({ value: c.id, label: c.contract_number })) },
    { key: 'amount_due', label: t('finance.bookings.amount') + ' (€)', type: 'number', required: true },
    { key: 'due_date', label: t('finance.receivables.dueDate'), type: 'date', required: true },
    { key: 'description', label: t('ui.form.description'), type: 'textarea' },
  ];

  const handleSave = async (data) => {
    requireWrite();
    // Payment state is receipt-managed. Only accept editable business fields.
    const payload = bindEditRevision({ contract_id: data.contract_id, amount_due: data.amount_due,
      due_date: data.due_date, description: data.description }, snapshotRevision(data));
    if (modal === 'create') {
      await api.post('/receivables', { ...payload, status: 'open' });
    } else {
      const source = revisionSource(data, modal);
      await api.put(`/receivables/${modal.id}`, { ...payload, status: source.status,
        statement_id: source.statement_id ?? null });
    }
    setModal(null);
    refreshData();
    if (store) store.invalidateRelated('receivables', 'contracts', 'bookings');
  };

  const handleDelete = async (row) => {
    if (!isAllowed()) return;
    if (!await confirm(`${t('modals.confirmDelete.body')}`) || !isAllowed()) return;
    setDeleteError(null);
    try {
      await api.del(`/receivables/${row.id}`, revisionOptions(row));
      refreshData();
      if (store) store.invalidateRelated('receivables', 'contracts', 'bookings');
    } catch (err) {
      setDeleteError(err.message || t('pages.deleteFailed'));
    }
  };

  if (loading || error) return <FinanceLoadState loading={loading} error={error} onRetry={refreshData} />;

  return (
    <div className="page">
      <p>{t('pages.receivables.paymentManaged')} {' '}
        <a href="/rent-overview">{t('pages.receivables.openRentOverview')}</a>
      </p>
      {deleteError && (
        <div className="alert alert-error" role="alert" style={{ marginBottom: '1rem' }}>
          {deleteError}
          <button onClick={() => setDeleteError(null)} style={{ marginLeft: '1rem', cursor: 'pointer' }}>✕</button>
        </div>
      )}
      <DataTable
        title={t('finance.receivables.openReceivables')}
        columns={COLUMNS}
        data={enriched}
        onAdd={canWrite ? () => setModal('create') : undefined}
        onEdit={canWrite ? row => setModal(row) : undefined}
        onDelete={canWrite ? handleDelete : undefined}
      />
      {modal && canWrite && (
        <FormModal
          title={modal === 'create' ? t('ui.buttons.create') : t('ui.buttons.edit')}
          fields={fields}
          initial={modal === 'create' ? null : modal}
          onSave={handleSave}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  );
}
