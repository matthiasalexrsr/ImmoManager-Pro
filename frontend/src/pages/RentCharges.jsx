import { useState, useEffect } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import StatusBadge from '../components/StatusBadge';

export default function RentCharges() {
  const { t } = useTranslation();
  const [charges, setCharges] = useState([]);
  const [contracts, setContracts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [modal, setModal] = useState(null);
  const [deleteError, setDeleteError] = useState(null);

  const refreshData = () => {
    setLoading(true);
    Promise.all([
      api.get('/rent-charges').catch(() => []),
      api.get('/contracts').catch(() => []),
    ]).then(([ch, conts]) => {
      setCharges(ch || []);
      setContracts(conts || []);
    }).catch(e => setError(e.message)).finally(() => setLoading(false));
  };

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      api.get('/rent-charges').catch(err => { console.warn('[RentCharges] charges:', err.message); return []; }),
      api.get('/contracts').catch(err => { console.warn('[RentCharges] contracts:', err.message); return []; }),
    ]).then(([r, c]) => {
      if (cancelled) return;
      setCharges(r || []);
      setContracts(c || []);
    }).catch(e => {
      if (!cancelled) setError(e.message);
    }).finally(() => {
      if (!cancelled) setLoading(false);
    });

    return () => {
      cancelled = true;
    };
  }, []);

  const contractMap = Object.fromEntries(contracts.map(c => [c.id, c]));

  const enriched = charges.map(c => ({
    ...c,
    contract_label: contractMap[c.contract_id]?.contract_number || '—',
  }));

  const COLUMNS = [
    { key: 'contract_label', label: t('tenantsContracts.contracts.title'), filterType: 'text' },
    { key: 'month', label: 'Monat', filterType: 'text' },
    { key: 'amount', label: t('finance.bookings.amount'), type: 'number', align: 'right',
      render: v => v != null ? `${Number(v).toFixed(2)} €` : '—' },
    { key: 'status', label: 'Status', type: 'status', filterType: 'select',
      render: v => <StatusBadge status={v} /> },
    { key: 'due_date', label: t('finance.receivables.dueDate'), type: 'date' },
  ];

  const fields = [
    { key: 'contract_id', label: t('tenantsContracts.contracts.title'), required: true, type: 'select',
      options: contracts.map(c => ({ value: c.id, label: c.contract_number })) },
    { key: 'month', label: 'Monat (YYYY-MM)', required: true },
    { key: 'amount', label: t('finance.bookings.amount') + ' (€)', type: 'number', required: true },
    { key: 'status', label: 'Status', type: 'select', default: 'open', options: [
      { value: 'open', label: t('status.payment.open') },
      { value: 'paid', label: t('status.payment.paid') },
      { value: 'overdue', label: t('status.payment.overdue') },
    ]},
    { key: 'due_date', label: t('finance.receivables.dueDate'), type: 'date' },
    { key: 'description', label: t('ui.form.description'), type: 'textarea' },
  ];

  const handleSave = async (data) => {
    if (modal === 'create') {
      await api.post('/rent-charges', data);
    } else {
      await api.put(`/rent-charges/${modal.id}`, data);
    }
    refreshData();
  };

  const handleDelete = async (row) => {
    if (!window.confirm(`${t('modals.confirmDelete.body')}`)) return;
    setDeleteError(null);
    try {
      await api.del(`/rent-charges/${row.id}`);
      refreshData();
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
          <button onClick={() => setDeleteError(null)} style={{ marginLeft: '1rem', cursor: 'pointer' }}>✕</button>
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
