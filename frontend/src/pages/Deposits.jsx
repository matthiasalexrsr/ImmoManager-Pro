import { useState, useEffect } from 'react';
import { api } from '../api';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import StatusBadge from '../components/StatusBadge';
import { useTranslation } from '../i18n';

const COLUMNS = [
  { key: 'contract_label', label: 'Vertrag', filterType: 'text' },
  { key: 'amount', label: 'Betrag (€)', type: 'number', align: 'right',
    render: v => v != null ? `${Number(v).toFixed(2)} €` : '—' },
  { key: 'status', label: 'Status', type: 'status', filterType: 'select' },
  { key: 'held_date', label: 'Hinterlegt am', type: 'date' },
  { key: 'return_date', label: 'Rückgabe', type: 'date' },
  { key: 'deductions', label: 'Abzüge (€)', type: 'number', align: 'right',
    render: v => v != null ? `${Number(v).toFixed(2)} €` : '—' },
];

export default function Deposits() {
  const { t } = useTranslation();
  const [deposits, setDeposits] = useState([]);
  const [contracts, setContracts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(null);

  const loadData = () => {
    Promise.all([
      api.get('/deposits').catch(err => { console.warn('[Deposits]', err.message); return []; }),
      api.get('/contracts').catch(err => { console.warn('[Deposits] contracts:', err.message); return []; }),
    ]).then(([deps, ctrcts]) => {
      const contractMap = Object.fromEntries(ctrcts.map(c => [c.id, c]));
      const enriched = (Array.isArray(deps) ? deps : []).map(d => ({
        ...d,
        contract_label: contractMap[d.contract_id]?.contract_number || '—',
      }));
      setDeposits(enriched);
      setContracts(ctrcts);
    }).finally(() => setLoading(false));
  };

  useEffect(() => { loadData(); }, []);

  const handleSave = async (data) => {
    if (modal === 'create') {
      await api.post('/deposits', data);
    } else {
      await api.put(`/deposits/${modal.id}`, data);
    }
    loadData();
  };

  const handleDelete = async (row) => {
    if (!window.confirm(t('pages.confirmDelete', { name: row.contract_label || row.id }))) return;
    await api.del(`/deposits/${row.id}`);
    loadData();
  };

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

  const tableColumns = COLUMNS.map(col => ({
    ...col,
    render: col.render || (col.type === 'status' ? (val) => <StatusBadge status={val} /> : undefined),
  }));

  if (loading) return <div className="page-loading">{t('pages.loading')}</div>;

  return (
    <div className="page">
      <DataTable
        title="Kautionen"
        columns={tableColumns}
        data={deposits}
        onAdd={() => setModal('create')}
        onEdit={(row) => setModal(row)}
        onDelete={handleDelete}
      />
      {modal && (
        <FormModal
          title={modal === 'create' ? t('comp.formModal.create', { title: 'Kaution' }) : t('comp.formModal.editTitle', { title: 'Kaution' })}
          fields={fields}
          initial={modal === 'create' ? null : modal}
          onSave={handleSave}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  );
}
