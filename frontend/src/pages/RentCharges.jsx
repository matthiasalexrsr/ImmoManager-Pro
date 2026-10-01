import { revisionOptions, revisionSource } from '../editRevision';
import { useState } from 'react';
import { api } from '../api';
import { useFinanceData } from '../hooks/useFinanceData';
import FinanceLoadState from '../components/FinanceLoadState';
import { useTranslation } from '../i18n';
import { useDataStore } from '../contexts/DataStoreContext';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import RentGenerationModal from '../components/RentGenerationModal';
import { useAuth } from '../contexts/AuthContext';
import StatusBadge from '../components/StatusBadge';
import { useConfirm } from '../components/ConfirmDialog';

const money = value => value != null ? `${Number(value).toFixed(2)} EUR` : '-';

export default function RentCharges() {
  const { t } = useTranslation();
  const confirm = useConfirm();
  const store = useDataStore();
  const auth = useAuth();
  const { data: { charges, contracts }, loading, error, reload: refreshData } = useFinanceData({
    charges: '/rent-charges',
    contracts: '/contracts',
  });
  const [modal, setModal] = useState(null);
  const [deleteError, setDeleteError] = useState(null);
  const [generationOpen, setGenerationOpen] = useState(false);
  const [generationResult, setGenerationResult] = useState(null);


  const contractMap = Object.fromEntries(contracts.map(c => [c.id, c]));

  const enriched = charges.map(c => {
    const totalDue = (
      Number(c.cold_rent || 0) +
      Number(c.service_charge || 0) +
      Number(c.heating_charge || 0) +
      Number(c.other_charges || 0)
    );
    const paid = Number(c.amount_paid || 0);
    return {
      ...c,
      contract_label: contractMap[c.contract_id]?.contract_number || '-',
      total_due: totalDue,
      remaining: Math.max(0, totalDue - paid),
    };
  });

  const COLUMNS = [
    { key: 'contract_label', label: t('tenantsContracts.contracts.title'), filterType: 'text' },
    { key: 'month', label: t('pages.rentCharges.columns.month'), filterType: 'text' },
    { key: 'cold_rent', label: t('pages.rentCharges.columns.coldRent'), type: 'number', align: 'right', render: money },
    { key: 'service_charge', label: t('pages.rentCharges.columns.serviceCharge'), type: 'number', align: 'right', render: money },
    { key: 'heating_charge', label: t('pages.rentCharges.columns.heatingCharge'), type: 'number', align: 'right', render: money },
    { key: 'other_charges', label: t('pages.rentCharges.columns.otherCharges'), type: 'number', align: 'right', render: money },
    { key: 'total_due', label: t('pages.rentCharges.columns.totalDue'), type: 'number', align: 'right', render: v => <strong>{money(v)}</strong> },
    { key: 'amount_paid', label: t('pages.rentCharges.columns.paid'), type: 'number', align: 'right', render: money },
    { key: 'remaining', label: t('pages.rentCharges.columns.remaining'), type: 'number', align: 'right', render: money },
    { key: 'status', label: t('ui.form.status'), type: 'status', filterType: 'select',
      render: v => <StatusBadge status={v} /> },
  ];

  const numberDefaults = { type: 'number', required: true, default: 0 };
  const fields = [
    { key: 'contract_id', label: t('tenantsContracts.contracts.title'), required: true, type: 'select',
      options: contracts.map(c => ({ value: c.id, label: c.contract_number })) },
    { key: 'month', label: t('pages.rentCharges.form.month'), required: true, placeholder: '2026-06' },
    { key: 'cold_rent', label: t('pages.rentCharges.form.coldRent'), ...numberDefaults },
    { key: 'service_charge', label: t('pages.rentCharges.form.serviceCharge'), ...numberDefaults },
    { key: 'heating_charge', label: t('pages.rentCharges.form.heatingCharge'), ...numberDefaults },
    { key: 'other_charges', label: t('pages.rentCharges.form.otherCharges'), ...numberDefaults },
  ];

  const handleSave = async (data) => {
    if (modal === 'create') {
      await api.post('/rent-charges', data);
    } else {
      const source = revisionSource(data, modal);
      await api.put(`/rent-charges/${modal.id}`, { ...data, amount_paid: source.amount_paid, status: source.status });
    }
    setModal(null);
    refreshData();
    if (store) store.invalidateRelated('rent_charges', 'contracts');
  };

  const handleDelete = async (row) => {
    if (!await confirm(`${t('modals.confirmDelete.body')}`)) return;
    setDeleteError(null);
    try {
      await api.del(`/rent-charges/${row.id}`, revisionOptions(row));
      refreshData();
      if (store) store.invalidateRelated('rent_charges', 'contracts');
    } catch (err) {
      setDeleteError(err.message || t('pages.deleteFailed'));
    }
  };

  if (loading || error) return <FinanceLoadState loading={loading} error={error} onRetry={refreshData} />;

  return (
    <div className="page">
      {!auth?.isReadonly && <button className="btn btn-primary" onClick={() => setGenerationOpen(true)}>
        {t('pages.rentGeneration.title')}
      </button>}
      <p>{t('pages.rentGeneration.paymentManaged')}</p>
      {generationResult && <p role="status" className="alert alert-success">
        {t('pages.rentGeneration.created')}: {generationResult.created_count} · {t('pages.rentGeneration.existing')}: {generationResult.skipped_count}
      </p>}
      {deleteError && (
        <div className="alert alert-error" role="alert" style={{ marginBottom: '1rem' }}>
          {deleteError}
          <button onClick={() => setDeleteError(null)} style={{ marginLeft: '1rem', cursor: 'pointer' }}>x</button>
        </div>
      )}
      <DataTable
        title={t('pages.rentCharges.title')}
        columns={COLUMNS}
        data={enriched}
        onAdd={!auth?.isReadonly ? () => setModal('create') : undefined}
        onEdit={!auth?.isReadonly ? row => setModal(row) : undefined}
        onDelete={!auth?.isReadonly ? handleDelete : undefined}
      />
      {generationOpen && <RentGenerationModal contracts={contracts} onClose={() => setGenerationOpen(false)}
        onGenerated={result => {
          setGenerationResult(result);
          setGenerationOpen(false);
          refreshData();
          store?.invalidateRelated('rent_charges', 'contracts');
        }} />}
      {modal && (
        <FormModal
          title={modal === 'create' ? t('pages.rentCharges.create') : t('pages.rentCharges.edit')}
          fields={fields}
          initial={modal === 'create' ? null : modal}
          onSave={handleSave}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  );
}
