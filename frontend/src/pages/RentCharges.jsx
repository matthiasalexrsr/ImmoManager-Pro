import { useState, useEffect } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import { useEntities, useDataStore } from '../contexts/DataStoreContext';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import StatusBadge from '../components/StatusBadge';
import { useConfirm } from '../components/ConfirmDialog';

const money = value => value != null ? `${Number(value).toFixed(2)} EUR` : '-';

export default function RentCharges() {
  const { t } = useTranslation();
  const confirm = useConfirm();
  const store = useDataStore();
  const { items: contracts } = useEntities('contracts', '/contracts');
  const [charges, setCharges] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [modal, setModal] = useState(null);
  const [deleteError, setDeleteError] = useState(null);

  const refreshData = () => {
    setLoading(true);
    api.get('/rent-charges').catch(() => [])
      .then(ch => setCharges(ch || []))
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    let cancelled = false;
    api.get('/rent-charges').catch(err => { console.warn('[RentCharges] charges:', err.message); return []; })
      .then(data => { if (!cancelled) setCharges(data || []); })
      .catch(e => { if (!cancelled) setError(e.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

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
    { key: 'month', label: 'Monat', filterType: 'text' },
    { key: 'cold_rent', label: 'Kaltmiete', type: 'number', align: 'right', render: money },
    { key: 'service_charge', label: 'Betriebskosten', type: 'number', align: 'right', render: money },
    { key: 'heating_charge', label: 'Heizkosten', type: 'number', align: 'right', render: money },
    { key: 'other_charges', label: 'Sonstige', type: 'number', align: 'right', render: money },
    { key: 'total_due', label: 'Soll gesamt', type: 'number', align: 'right', render: v => <strong>{money(v)}</strong> },
    { key: 'amount_paid', label: 'Bezahlt', type: 'number', align: 'right', render: money },
    { key: 'remaining', label: 'Offen', type: 'number', align: 'right', render: money },
    { key: 'status', label: 'Status', type: 'status', filterType: 'select',
      render: v => <StatusBadge status={v} /> },
  ];

  const numberDefaults = { type: 'number', required: true, default: 0 };
  const fields = [
    { key: 'contract_id', label: t('tenantsContracts.contracts.title'), required: true, type: 'select',
      options: contracts.map(c => ({ value: c.id, label: c.contract_number })) },
    { key: 'month', label: 'Monat (YYYY-MM)', required: true, placeholder: '2026-06' },
    { key: 'cold_rent', label: 'Kaltmiete (EUR)', ...numberDefaults },
    { key: 'service_charge', label: 'Betriebskosten (EUR)', ...numberDefaults },
    { key: 'heating_charge', label: 'Heizkosten (EUR)', ...numberDefaults },
    { key: 'other_charges', label: 'Sonstige Kosten (EUR)', ...numberDefaults },
    { key: 'amount_paid', label: 'Bereits bezahlt (EUR)', ...numberDefaults },
    { key: 'status', label: 'Status', type: 'select', default: 'open', options: [
      { value: 'open', label: t('status.payment.open') },
      { value: 'partial', label: t('status.payment.partial') || 'Teilweise bezahlt' },
      { value: 'paid', label: t('status.payment.paid') },
      { value: 'overdue', label: t('status.payment.overdue') },
    ]},
  ];

  const handleSave = async (data) => {
    if (modal === 'create') {
      await api.post('/rent-charges', data);
    } else {
      await api.put(`/rent-charges/${modal.id}`, data);
    }
    refreshData();
    if (store) store.invalidateRelated('rent_charges', 'contracts');
  };

  const handleDelete = async (row) => {
    if (!await confirm(`${t('modals.confirmDelete.body')}`)) return;
    setDeleteError(null);
    try {
      await api.del(`/rent-charges/${row.id}`);
      refreshData();
      if (store) store.invalidateRelated('rent_charges', 'contracts');
    } catch (err) {
      setDeleteError(err.message || t('pages.deleteFailed'));
    }
  };

  if (loading) return <div className="page-loading">{t('ui.table.loading')}</div>;
  if (error) return <div className="page"><div className="alert alert-error">{error}</div></div>;

  return (
    <div className="page">
      {deleteError && (
        <div className="alert alert-error" style={{ marginBottom: '1rem' }}>
          {deleteError}
          <button onClick={() => setDeleteError(null)} style={{ marginLeft: '1rem', cursor: 'pointer' }}>x</button>
        </div>
      )}
      <DataTable
        title="Sollstellung"
        columns={COLUMNS}
        data={enriched}
        onAdd={() => setModal('create')}
        onEdit={row => setModal(row)}
        onDelete={handleDelete}
      />
      {modal && (
        <FormModal
          title={modal === 'create' ? 'Sollstellung erstellen' : 'Sollstellung bearbeiten'}
          fields={fields}
          initial={modal === 'create' ? null : modal}
          onSave={handleSave}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  );
}
