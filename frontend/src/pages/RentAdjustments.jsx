import { useState, useEffect, useCallback } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import { useEntities, useDataStore } from '../contexts/DataStoreContext';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import StatusBadge from '../components/StatusBadge';
import { useConfirm } from '../components/ConfirmDialog';
import { useToast } from '../components/Toast';
import { useCanWrite } from '../contexts/AuthContext';
import { formatMoney, formatPercent } from '../utils/format';

const COLUMNS = [
  { key: 'contract_number', label: 'Vertrag', filterType: 'text', link: 'contract' },
  { key: 'adjustment_type', label: 'Art', filterType: 'select',
    render: v => v === 'index' ? 'Indexmiete' : v === 'stepped' ? 'Staffelmiete' : v || '—' },
  { key: 'effective_date', label: 'Wirksamkeit', type: 'date', filterType: 'dateRange' },
  { key: 'previous_rent', label: 'Bisherige Miete (€)', type: 'number', align: 'right',
    render: v => formatMoney(v) },
  { key: 'new_rent', label: 'Neue Miete (€)', type: 'number', align: 'right',
    render: v => formatMoney(v) },
  { key: 'increase_percent', label: 'Erhöhung (%)', type: 'number', align: 'right',
    render: v => formatPercent(v) },
  { key: 'status', label: 'Status', type: 'status', filterType: 'select',
    render: v => <StatusBadge status={v} /> },
];

export default function RentAdjustments() {
  const { t } = useTranslation();
  const confirm = useConfirm();
  const toast = useToast();
  const canWrite = useCanWrite();
  const store = useDataStore();
  const contractState = useEntities('contracts', '/contracts');
  const contracts = contractState.items;
  const [adjustments, setAdjustments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(null);
  const [deleteError, setDeleteError] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [loaded, setLoaded] = useState(false);
  const [revision, setRevision] = useState(0);
  const choicesReady = !contractState.loading && !contractState.error;

  const refreshData = useCallback(() => setRevision(value => value + 1), []);
  useEffect(() => {
    const request = new AbortController();
    setLoading(true);
    api.list('/rent-adjustments', { signal: request.signal }).then(data => {
      if (request.signal.aborted) return;
      if (!Array.isArray(data)) throw new Error('Mietanpassungen konnten nicht vollständig gelesen werden.');
      setAdjustments(data); setLoaded(true); setLoadError(null);
    }).catch(error => { if (!request.signal.aborted) setLoadError(error.message || 'Mietanpassungen konnten nicht geladen werden.'); })
      .finally(() => { if (!request.signal.aborted) setLoading(false); });
    return () => request.abort();
  }, [revision]);

  // Applying writes the new rent into the contract's rent history from its effective date.
  const runAction = async (row, action) => {
    try {
      const res = await api.post(`/rent-adjustments/${row.id}/${action}`, {});
      (res?.warnings || []).forEach(w => toast.warning(w));
      toast.success(action === 'apply' ? 'Mietanpassung angewendet' : 'Mietanpassung zurückgenommen');
      refreshData();
      if (store) store.invalidateRelated('rent_adjustments', 'contracts');
    } catch (err) {
      toast.error(err.message);
    }
  };

  const columns = [...COLUMNS, { key: 'actions', label: '', render: (_, row) => !canWrite || !choicesReady ? null : (row.status === 'applied'
    ? <button className="btn btn-sm btn-secondary" onClick={() => runAction(row, 'revert')}>Zurücknehmen</button>
    : row.status !== 'rejected' && (
      <button className="btn btn-sm btn-primary" onClick={() => runAction(row, 'apply')}>Anwenden</button>)) }];

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
    if (!choicesReady) throw new Error('Bitte zuerst die Vertragsauswahl erneut laden.');
    if (modal === 'create') {
      await api.post('/rent-adjustments', data);
    } else {
      await api.put(`/rent-adjustments/${modal.id}`, data);
    }
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

  // only the first load replaces the page; a reload keeps the table and an open form
  if (loading && !loaded && !modal) return <div className="page-loading">{t('ui.table.loading')}</div>;
  if (loadError && !loaded && !modal) return <div className="page"><p className="alert-error" role="alert">{loadError}{' '}
    <button type="button" className="btn btn-secondary btn-sm" onClick={refreshData}>Erneut laden</button></p></div>;

  return (
    <div className="page">
      {loadError && <p className="alert-error" role="alert">Mietanpassungen konnten nicht aktualisiert werden. {loadError} Angezeigt wird der zuletzt geladene Stand.{' '}
        <button type="button" className="btn btn-secondary btn-sm" onClick={refreshData}>Erneut laden</button></p>}
      {contractState.error && <p className="alert-error" role="alert">Die Vertragsauswahl ist nicht verfügbar. {contractState.error}{' '}
        <button type="button" className="btn btn-secondary btn-sm" onClick={contractState.reload}>Auswahl erneut laden</button></p>}
      {deleteError && (
        <div className="alert alert-error" style={{ marginBottom: '1rem' }}>
          {deleteError}
          <button onClick={() => setDeleteError(null)} style={{ marginLeft: '1rem', cursor: 'pointer' }}>✕</button>
        </div>
      )}
      <DataTable
        title="Mietanpassungen"
        columns={columns}
        data={enriched}
        onAdd={choicesReady ? () => setModal('create') : undefined}
        onEdit={choicesReady ? row => setModal(row) : undefined}
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
