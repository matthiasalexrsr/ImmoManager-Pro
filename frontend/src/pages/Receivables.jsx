import { useState, useEffect } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import StatusBadge from '../components/StatusBadge';

export default function Receivables() {
  const { t } = useTranslation();
  const [receivables, setReceivables] = useState([]);
  const [contracts, setContracts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [modal, setModal] = useState(null);
  const [deleteError, setDeleteError] = useState(null);

  const refreshData = () => {
    setLoading(true);
    Promise.all([
      api.get('/receivables').catch(() => []),
      api.get('/contracts').catch(() => []),
    ]).then(([recs, conts]) => {
      setReceivables(recs || []);
      setContracts(conts || []);
    }).catch(e => setError(e.message)).finally(() => setLoading(false));
  };

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      api.get('/receivables').catch(err => { console.warn('[Receivables] receivables:', err.message); return []; }),
      api.get('/contracts').catch(err => { console.warn('[Receivables] contracts:', err.message); return []; }),
    ]).then(([r, c]) => {
      if (cancelled) return;
      setReceivables(r || []);
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

  const enriched = receivables.map(r => ({
    ...r,
    contract_label: contractMap[r.contract_id]?.contract_number || '—',
  }));

  const COLUMNS = [
    { key: 'contract_label', label: t('tenantsContracts.contracts.title'), filterType: 'text' },
    { key: 'amount_due', label: t('finance.bookings.amount'), type: 'number', align: 'right',
      render: v => v != null ? `${Number(v).toFixed(2)} €` : '—' },
    { key: 'due_date', label: t('finance.receivables.dueDate'), type: 'date', filterType: 'dateRange' },
    { key: 'status', label: 'Status', type: 'status', filterType: 'select',
      render: v => <StatusBadge status={v} /> },
    { key: 'description', label: t('ui.form.description') },
  ];

  const fields = [
    { key: 'contract_id', label: t('tenantsContracts.contracts.title'), required: true, type: 'select',
      options: contracts.map(c => ({ value: c.id, label: c.contract_number })) },
    { key: 'amount_due', label: t('finance.bookings.amount') + ' (€)', type: 'number', required: true },
    { key: 'due_date', label: t('finance.receivables.dueDate'), type: 'date', required: true },
    { key: 'status', label: 'Status', type: 'select', default: 'open', options: [
      { value: 'open', label: t('status.payment.open') },
      { value: 'paid', label: t('status.payment.paid') },
      { value: 'overdue', label: t('status.payment.overdue') },
      { value: 'cancelled', label: t('status.payment.cancelled') },
    ]},
    { key: 'description', label: t('ui.form.description'), type: 'textarea' },
  ];

  const handleSave = async (data) => {
    if (modal === 'create') {
      await api.post('/receivables', data);
    } else {
      await api.put(`/receivables/${modal.id}`, data);
    }
    refreshData();
  };

  const handleDelete = async (row) => {
    if (!window.confirm(`${t('modals.confirmDelete.body')}`)) return;
    setDeleteError(null);
    try {
      await api.del(`/receivables/${row.id}`);
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
        title={t('finance.receivables.openReceivables')}
        columns={COLUMNS}
        data={enriched}
        onAdd={() => setModal('create')}
        onEdit={row => setModal(row)}
        onDelete={handleDelete}
      />
      {modal && (
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
