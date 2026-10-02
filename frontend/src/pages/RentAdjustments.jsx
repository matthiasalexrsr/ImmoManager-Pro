import { revisionOptions } from '../editRevision';
import { useRef, useState } from 'react';
import { api } from '../api';
import { useFinanceData } from '../hooks/useFinanceData';
import FinanceLoadState from '../components/FinanceLoadState';
import { useTranslation } from '../i18n';
import useWriteAccess from '../hooks/useWriteAccess';
import { useDataStore } from '../contexts/DataStoreContext';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import { useConfirm } from '../components/ConfirmDialog';

export default function RentAdjustments() {
  const { t, locale } = useTranslation();
  const confirm = useConfirm();
  const store = useDataStore();
  const { data: { adjustments, contracts }, loading, error, reload: refreshData } = useFinanceData({
    adjustments: '/rent-adjustments', contracts: '/contracts',
  });
  const [modal, setModal] = useState(null);
  const { canWrite, isAllowed, requireWrite } = useWriteAccess('/rent-adjustments', () => setModal(null));
  const [deleteError, setDeleteError] = useState(null);
  const [deleting, setDeleting] = useState(false);
  const deletionPending = useRef(false);
  const writable = canWrite && !deleting;
  const text = key => t(`pages.rentAdjustments.${key}`);
  const money = value => value == null ? '—' : new Intl.NumberFormat(locale || 'de-DE', { style: 'currency', currency: 'EUR' }).format(value);
  const contractMap = Object.fromEntries(contracts.map(contract => [contract.id, contract]));
  const enriched = adjustments.map(adjustment => ({
    ...adjustment, contract_number: contractMap[adjustment.contract_id]?.contract_number || '—',
  }));
  const columns = [
    { key: 'contract_number', label: text('contract'), filterType: 'text' },
    { key: 'adjustment_type', label: text('type'), filterType: 'select',
      render: value => value === 'index' || value === 'stepped' ? text(value) : value || '—' },
    { key: 'effective_date', label: text('effectiveDate'), type: 'date', filterType: 'dateRange' },
    { key: 'previous_rent', label: text('previousRent'), type: 'number', align: 'right', render: money },
    { key: 'new_rent', label: text('newRent'), type: 'number', align: 'right', render: money },
    { key: 'increase_percent', label: text('increasePercent'), type: 'number', align: 'right',
      render: value => value == null ? '—' : `${new Intl.NumberFormat(locale || 'de-DE', { maximumFractionDigits: 2 }).format(value)} %` },
    { key: 'status', label: text('status'), type: 'status', filterType: 'select', render: value =>
      <span className={`badge ${value === 'applied' ? 'badge-green' : value === 'pending' ? 'badge-yellow' : 'badge-gray'}`}>
        {['pending', 'applied', 'rejected'].includes(value) ? text(value) : value || '—'}
      </span> },
  ];
  const rentField = { type: 'number', required: true, min: 0, max: 9999999999.99, step: 0.01 };
  const fields = [
    { key: 'contract_id', label: text('contract'), required: true, type: 'select',
      options: contracts.map(contract => ({ value: contract.id, label: contract.contract_number })) },
    { key: 'adjustment_type', label: text('type'), required: true, type: 'select', options: [
      { value: 'index', label: text('index') }, { value: 'stepped', label: text('stepped') },
    ] },
    { key: 'effective_date', label: text('effectiveDate'), type: 'date', required: true, hint: text('effectiveHint') },
    { key: 'previous_rent', label: text('previousRent'), ...rentField, hint: text('baselineHint') },
    { key: 'new_rent', label: text('newRent'), ...rentField },
    { key: 'increase_percent', label: text('increasePercent'), type: 'number', step: 'any' },
    { key: 'index_base_year', label: text('indexBaseYear'), type: 'number', step: 1 },
    { key: 'index_value', label: text('indexValue'), type: 'number', step: 'any' },
    { key: 'status', label: text('status'), type: 'select', required: true, default: 'pending', hint: text('statusHint'), options: [
      { value: 'pending', label: text('pending') }, { value: 'applied', label: text('applied') },
      { value: 'rejected', label: text('rejected') },
    ] },
    { key: 'notes', label: text('notes'), type: 'textarea' },
  ];
  const refresh = () => {
    refreshData();
    store?.invalidateRelated('rent_adjustments', 'contracts', 'rent_charges');
  };
  const handleSave = async data => {
    requireWrite();
    if (deleting) throw new Error(text('deleting'));
    if (modal === 'create') await api.post('/rent-adjustments', data);
    else await api.put(`/rent-adjustments/${modal.id}`, data);
  };

  const afterSave = () => {
    refresh();
  };
  const handleDelete = async row => {
    if (!isAllowed() || deletionPending.current) return;
    deletionPending.current = true;
    setDeleting(true);
    try {
      if (!await confirm(`"${row.contract_number}" ${t('modals.confirmDelete.body')}`)) return;
      if (!isAllowed()) return;
      setDeleteError(null);
      await api.del(`/rent-adjustments/${row.id}`, revisionOptions(row));
      refresh();
    } catch (err) {
      setDeleteError(err.message || t('pages.deleteFailed'));
    } finally {
      deletionPending.current = false;
      setDeleting(false);
    }
  };
  if (loading || error) return <FinanceLoadState loading={loading} error={error} onRetry={refreshData} />;
  return (
    <div className="page">
      <div className="alert alert-info" role="note" style={{ marginBottom: '1rem' }}>
        <strong>{text('policyTitle')}</strong><p style={{ margin: '0.35rem 0 0' }}>{text('policy')}</p>
      </div>
      {deleteError && <div className="alert alert-error" role="alert" style={{ marginBottom: '1rem' }}>
        {deleteError}<button type="button" aria-label={t('ui.buttons.close')} onClick={() => setDeleteError(null)}>✕</button>
      </div>}
      {deleting && <p role="status">{text('deleting')}</p>}
      <DataTable title={text('title')} columns={columns} data={enriched}
        onAdd={writable ? () => setModal('create') : undefined}
        onEdit={writable ? row => setModal(row) : undefined} onDelete={writable ? handleDelete : undefined} />
      {modal && canWrite && <FormModal onSaved={afterSave} draftConfig={{ collection: 'rent-adjustments' }} title={text(modal === 'create' ? 'create' : 'edit')} fields={fields}
        initial={modal === 'create' ? null : modal} onSave={handleSave} saveDisabled={!writable} onClose={() => setModal(null)} />}
    </div>
  );
}
