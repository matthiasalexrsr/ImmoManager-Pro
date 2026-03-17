import { useState, useEffect } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import { useEntities, useDataStore } from '../contexts/DataStoreContext';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import StatusBadge from '../components/StatusBadge';

export default function Deposits() {
  const { t } = useTranslation();
  const store = useDataStore();
  const { items: contracts } = useEntities('contracts', '/contracts');
  const [deposits, setDeposits] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [modal, setModal] = useState(null);
  const [deleteError, setDeleteError] = useState(null);

  const refreshData = () => {
    api.get('/deposits').catch(err => { console.warn('[Deposits] deposits:', err.message); return []; })
      .then(data => setDeposits(data || []))
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    let cancelled = false;
    api.get('/deposits').catch(err => { console.warn('[Deposits] deposits:', err.message); return []; })
      .then(data => { if (!cancelled) setDeposits(data || []); })
      .catch(e => { if (!cancelled) setError(e.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

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
    refreshData();
    if (store) store.invalidateAll();
  };

  const handleDelete = async (row) => {
    const name = row.contract_label || row.id;
    if (!window.confirm(`"${name}" ${t('modals.confirmDelete.body')}`)) return;
    setDeleteError(null);
    try {
      await api.del(`/deposits/${row.id}`);
      refreshData();
      if (store) store.invalidateAll();
    } catch (err) {
      setDeleteError(err.message || 'Löschen fehlgeschlagen');
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
