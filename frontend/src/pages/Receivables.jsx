import { useState, useEffect } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import { useEntities, useDataStore } from '../contexts/DataStoreContext';
import DataTable from '../components/DataTable';
import { PartyLink } from '../features/partyWorkspace/PartyWorkspace';
import FormModal from '../components/FormModal';
import StatusBadge from '../components/StatusBadge';
import { useConfirm } from '../components/ConfirmDialog';
import useEffectiveSettings from '../hooks/useEffectiveSettings';
import { defaultDueDate } from '../utils/settingDefaults';
import { formatMoney } from '../utils/format';
import { Link, useSearchParams } from 'react-router-dom';
import { entityHref } from '../utils/entityLinks';
import { dunningText } from '../features/dunning/dunningText';
import './receivablesLinks.css';
import ReceivableSettlement from '../features/ReceivableSettlement';
import SepaDebitDialog from '../features/sepaDebit/SepaDebitDialog';
import { useCanWrite } from '../contexts/AuthContext';

export default function Receivables() {
  const [params, setParams] = useSearchParams();
  const { t, locale } = useTranslation();
  const confirm = useConfirm();
  const { prefs } = useEffectiveSettings(params.get('property_id'));
  const store = useDataStore();
  const contractState = useEntities('contracts', '/contracts');
  const contracts = contractState.items;
  const { items: tenants } = useEntities('tenants', '/tenants');
  const [receivables, setReceivables] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [modal, setModal] = useState(null);
  const [sepaOpen, setSepaOpen] = useState(false);
  const canDebit = useCanWrite('/receivables/sepa-debits/files');
  const [deleteError, setDeleteError] = useState(null);
  const [attempt, setAttempt] = useState(0);
  const statementId = params.get('statement_id') || '';

  const refreshData = () => setAttempt(value => value + 1);

  useEffect(() => {
    const controller = new AbortController();
    setError(null); setLoading(true);
    api.list(`/receivables${statementId ? `?${new URLSearchParams({ statement_id: statementId })}` : ''}`, { signal: controller.signal })
      .then(data => { if (!Array.isArray(data)) throw new Error('Forderungen konnten nicht gelesen werden.'); if (!controller.signal.aborted) setReceivables(data); })
      .catch(e => { if (!controller.signal.aborted) setError(e.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [attempt, statementId]);

  const contractMap = Object.fromEntries(contracts.map(c => [c.id, c]));
  const tenantMap = Object.fromEntries(tenants.map(tn => [tn.id, tn.full_name]));

  const enriched = receivables.map(r => ({
    ...r,
    contract_label: contractMap[r.contract_id]?.contract_number || '—',
    tenant_id: contractMap[r.contract_id]?.tenant_id || null,
    tenant_name: tenantMap[contractMap[r.contract_id]?.tenant_id] || '—',
  }));
  const selectedStatus = params.get('status') || '';
  const unpaid = row => ['open', 'overdue', 'partial'].includes(row.status);
  const filtered = enriched.filter(row => {
    const contract = contractMap[row.contract_id];
    if (selectedStatus === 'unpaid' && (!unpaid(row) || Number(row.amount_due) <= 0)) return false;
    if (selectedStatus === 'credits' && (!unpaid(row) || Number(row.amount_due) >= 0)) return false;
    if (selectedStatus === 'overdue' && (!unpaid(row) || Number(row.amount_due) <= 0 || !(row.status === 'overdue' || row.due_date < new Date().toLocaleDateString('sv-SE')))) return false;
    if (selectedStatus === 'dunning' && (!row.dunning_level || ['archived', 'cancelled', 'canceled', 'closed', 'done', 'finalized', 'paid'].includes((row.status || '').toLowerCase()))) return false;
    if (selectedStatus && !['unpaid', 'credits', 'overdue', 'dunning'].includes(selectedStatus) && row.status !== selectedStatus) return false;
    return (!params.get('contract_id') || row.contract_id === params.get('contract_id'))
      && (!statementId || row.statement_id === statementId)
      && (!params.get('tenant_id') || row.tenant_id === params.get('tenant_id'))
      && (!params.get('property_id') || contract?.property_id === params.get('property_id'))
      && (!params.get('unit_id') || contract?.unit_id === params.get('unit_id'))
      && (!params.get('date_from') || row.due_date >= params.get('date_from'))
      && (!params.get('date_to') || row.due_date <= params.get('date_to'));
  });

  const origin = row => (row.statement_id
    ? <Link to={`/statements?${new URLSearchParams({ statement_id: row.statement_id })}`}>Einzelabrechnung öffnen</Link>
    : row.kind === 'other' ? 'Sonstige Forderung' : 'Direkte Forderung');
  const COLUMNS = [
    { key: 'contract_label', label: t('tenantsContracts.contracts.title'), filterType: 'text',
      render: (value, row) => value !== '—' && row.contract_id
        ? <span className="receivable-record-links">
          <Link to={entityHref('contract', row.contract_id)}>{value}</Link>
          {row.dunning_level && <Link className="receivable-record-links__secondary"
            to={entityHref('dunningCase', row.contract_id)}>{dunningText(locale, 'openDunningCase')}</Link>}
        </span> : value || '—' },
    { key: 'tenant_name', label: 'Mieter', filterType: 'text',
      render: (v, row) => row.tenant_id && v !== '—' ? <PartyLink tenantId={row.tenant_id}>{v}</PartyLink> : v },
    // what the claim is for, its origin beneath (the origin's own column can still be shown)
    { key: 'description', label: t('ui.form.description'), filterType: 'text', render: (value, row) => <span className="cell-stack">
      <span className="cell-text" title={value?.length > 24 ? value : undefined}>{value || '—'}</span>
      <span className="td-sub">{origin(row)}</span></span> },
    { key: 'statement_id', hidden: true, label: 'Herkunft', render: (_, row) => origin(row) },
    { key: 'amount_due', label: t('finance.bookings.amount'), type: 'number', sum: true, align: 'right',
      render: v => formatMoney(v) },
    { key: 'residual', label: 'Belegbarer Rest', render: (_, row) => <ReceivableSettlement receivable={row} onChanged={() => store.invalidateRelated('bookings', 'receivables', 'deposits', 'contracts')} /> },
    { key: 'due_date', label: t('finance.receivables.dueDate'), type: 'date', filterType: 'dateRange' },
    { key: 'status', label: 'Status', type: 'status', filterType: 'select',
      render: v => <StatusBadge status={v} /> },
  ];

  const fields = [
    { key: 'contract_id', label: t('tenantsContracts.contracts.title'), required: true, type: 'select',
      options: contracts.map(c => ({ value: c.id, label: c.contract_number })) },
    { key: 'amount_due', label: t('finance.bookings.amount') + ' (€)', type: 'number', required: true },
    { key: 'due_date', label: t('finance.receivables.dueDate'), type: 'date', required: true, default: prefs ? defaultDueDate(prefs.default_due_day) : undefined },
    { key: 'status', label: 'Status', type: 'select', default: 'open', options: [
      { value: 'open', label: t('status.payment.open') },
      { value: 'paid', label: t('status.payment.paid') },
      { value: 'overdue', label: t('status.payment.overdue') },
      { value: 'cancelled', label: t('status.payment.cancelled') },
    ]},
    { key: 'kind', label: 'Art', type: 'select', options: [
      { value: '', label: 'Miete oder Nachforderung (kein eigener Ertrag)' },
      { value: 'other', label: 'Sonstige Forderung (Schaden, Schlüssel …)' },
    ], hint: 'Eine sonstige Forderung zählt im Periodenergebnis als Ertrag. Rückstände der Miete stecken dort schon im Mietsoll.' },
    { key: 'description', label: t('ui.form.description'), type: 'textarea' },
  ];

  const handleSave = async (data) => {
    if (modal === 'create') {
      await api.post('/receivables', data);
    } else {
      await api.put(`/receivables/${modal.id}`, data);
    }
    refreshData();
    if (store) store.invalidateRelated('receivables', 'contracts', 'bookings');
  };

  const handleDelete = async (row) => {
    if (!await confirm(`${t('modals.confirmDelete.body')}`, { action: 'delete' })) return;
    setDeleteError(null);
    try {
      await api.del(`/receivables/${row.id}`);
      refreshData();
      if (store) store.invalidateRelated('receivables', 'contracts', 'bookings');
    } catch (err) {
      setDeleteError(err.message || t('pages.deleteFailed'));
    }
  };

  // only the first load replaces the page; a reload keeps the table and an open form
  if (!modal && (loading && receivables.length === 0 || contractState.loading)) return <div className="page-loading">{t('ui.table.loading')}</div>;
  if (!modal && (error || contractState.error)) return <div className="page"><div className="alert alert-error" role="alert">{error || contractState.error}<button type="button" className="btn btn-secondary" onClick={() => { setAttempt(value => value + 1); contractState.reload?.(); }}>Erneut laden</button></div></div>;

  return (
    <div className="page">
      {statementId && <p role="status">Forderungen und Guthaben dieser Einzelabrechnung.{' '}
        <Link to={`/statements?${new URLSearchParams({ statement_id: statementId })}`}>Zur Abrechnung</Link>{' '}
        <button className="btn btn-sm btn-secondary" onClick={() => setParams(current => {
          const next = new URLSearchParams(current); next.delete('statement_id'); return next;
        })}>Abrechnungsfilter entfernen</button></p>}
      {canDebit && <div className="toolbar receivables-toolbar">
        <button type="button" className="btn btn-secondary" onClick={() => setSepaOpen(true)}>SEPA-Lastschriftdatei erstellen</button>
        <span className="text-muted">Datei für das Online-Banking mit den offenen Mieten der Lastschriftzahler.</span>
      </div>}
      {sepaOpen && <SepaDebitDialog onClose={() => setSepaOpen(false)} />}
      <div className="filter-chips">{[['', 'Alle Vorgänge'], ['unpaid', 'Offene Forderungen'], ['credits', 'Offene Guthaben']].map(([value, label]) => <button type="button" key={value} className={`btn btn-sm ${selectedStatus === value ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setParams(current => { const next = new URLSearchParams(current); if (value) next.set('status', value); else next.delete('status'); return next; })}>{label}</button>)}</div>
      {deleteError && (
        <div className="alert alert-error" style={{ marginBottom: '1rem' }}>
          {deleteError}
          <button onClick={() => setDeleteError(null)} style={{ marginLeft: '1rem', cursor: 'pointer' }}>✕</button>
        </div>
      )}
      <DataTable
        title={t('finance.receivables.openReceivables')}
        columns={COLUMNS}
        data={filtered}
        viewConfig={{ column_filters: Object.fromEntries(params) }}
        onApplyView={config => setParams(Object.fromEntries(Object.entries(config.column_filters || {}).filter(([key, value]) => ['status', 'statement_id', 'contract_id', 'tenant_id', 'property_id', 'unit_id', 'date_from', 'date_to'].includes(key) && value)))}
        onAdd={() => setModal('create')}
        onEdit={row => setModal(row)}
        onDelete={handleDelete}
      />
      {modal && (
        <FormModal
          title={modal === 'create' ? 'Forderung erstellen' : 'Forderung bearbeiten'}
          fields={fields}
          initial={modal === 'create' ? null : modal}
          onSave={handleSave}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  );
}
