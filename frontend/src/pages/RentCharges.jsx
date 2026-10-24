import { useState, useEffect, useCallback } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import { useEntities, useDataStore } from '../contexts/DataStoreContext';
import DataTable from '../components/DataTable';
import { PartyLink } from '../features/partyWorkspace/PartyWorkspace';
import FormModal from '../components/FormModal';
import StatusBadge from '../components/StatusBadge';
import { useConfirm } from '../components/ConfirmDialog';
import { formatMoney, formatMonth } from '../utils/format';

const money = value => formatMoney(value);

export default function RentCharges() {
  const { t } = useTranslation();
  const confirm = useConfirm();
  const store = useDataStore();
  const contractState = useEntities('contracts', '/contracts');
  const tenantState = useEntities('tenants', '/tenants');
  const contracts = contractState.items, tenants = tenantState.items;
  const [charges, setCharges] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [modal, setModal] = useState(null);
  const [deleteError, setDeleteError] = useState(null);
  const [loaded, setLoaded] = useState(false);
  const [revision, setRevision] = useState(0);
  const lookupErrors = [contractState.error, tenantState.error].filter(Boolean);
  const choicesReady = !contractState.loading && !tenantState.loading && !lookupErrors.length;

  const refreshData = useCallback(() => setRevision(value => value + 1), []);
  useEffect(() => {
    const request = new AbortController();
    setLoading(true);
    api.list('/rent-charges', { signal: request.signal }).then(data => {
      if (request.signal.aborted) return;
      if (!Array.isArray(data)) throw new Error('Sollstellungen konnten nicht vollständig gelesen werden.');
      setCharges(data); setLoaded(true); setError(null);
    }).catch(error => { if (!request.signal.aborted) setError(error.message || 'Sollstellungen konnten nicht geladen werden.'); })
      .finally(() => { if (!request.signal.aborted) setLoading(false); });
    return () => request.abort();
  }, [revision]);

  const contractMap = Object.fromEntries(contracts.map(c => [c.id, c]));
  const tenantMap = Object.fromEntries(tenants.map(tn => [tn.id, tn.full_name]));

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
      tenant_id: contractMap[c.contract_id]?.tenant_id || null,
      tenant_name: tenantMap[contractMap[c.contract_id]?.tenant_id] || '—',
      total_due: totalDue,
      remaining: Math.max(0, totalDue - paid),
    };
  });

  const COLUMNS = [
    { key: 'contract_label', label: 'Vertrag', filterType: 'text', link: { kind: 'contract', idKey: 'contract_id' } },
    { key: 'tenant_name', label: 'Mieter', filterType: 'text',
      render: (v, row) => row.tenant_id && v !== '—' ? <PartyLink tenantId={row.tenant_id}>{v}</PartyLink> : v },
    { key: 'month', label: 'Monat', filterType: 'text', render: v => formatMonth(v) },
    { key: 'cold_rent', label: 'Kaltmiete', type: 'number', sum: true, align: 'right', render: money },
    { key: 'service_charge', hidden: true, label: 'Betriebskosten', type: 'number', sum: true, align: 'right', render: money },
    { key: 'heating_charge', hidden: true, label: 'Heizkosten', type: 'number', sum: true, align: 'right', render: money },
    { key: 'other_charges', hidden: true, label: 'Sonstige', type: 'number', align: 'right', render: money },
    { key: 'total_due', label: 'Soll gesamt', type: 'number', sum: true, align: 'right', render: v => <strong>{money(v)}</strong> },
    { key: 'amount_paid', label: 'Bezahlt', type: 'number', sum: true, align: 'right', render: money },
    { key: 'remaining', label: 'Offen', type: 'number', sum: true, align: 'right', render: money },
    { key: 'status', label: 'Status', type: 'status', filterType: 'select',
      render: v => <StatusBadge status={v} /> },
  ];

  const numberDefaults = { type: 'number', required: true, default: 0 };
  const fields = [
    { key: 'contract_id', label: t('tenantsContracts.contracts.title'), required: true, type: 'select',
      options: contracts.map(c => ({ value: c.id, label: c.contract_number })) },
    { key: 'month', label: 'Monat', type: 'month', required: true, placeholder: 'JJJJ-MM' },
    { key: 'cold_rent', label: 'Kaltmiete (EUR)', ...numberDefaults },
    { key: 'service_charge', label: 'Betriebskosten (EUR)', ...numberDefaults },
    { key: 'heating_charge', label: 'Heizkosten (EUR)', ...numberDefaults },
    { key: 'other_charges', label: 'Sonstige Kosten (EUR)', ...numberDefaults },
    { key: 'amount_paid', label: 'Bereits bezahlt (EUR)', ...numberDefaults },
    { key: 'status', label: 'Status', type: 'select', default: 'open', options: [
      { value: 'open', label: t('status.payment.open') },
      { value: 'partial', label: t('status.payment.partiallyPaid') || 'Teilweise bezahlt' },
      { value: 'paid', label: t('status.payment.paid') },
      { value: 'overdue', label: t('status.payment.overdue') },
    ]},
  ];

  const handleSave = async (data) => {
    if (!choicesReady) throw new Error('Bitte zuerst die Vertrags- und Mieterauswahl erneut laden.');
    if (modal === 'create') {
      await api.post('/rent-charges', data);
    } else {
      await api.put(`/rent-charges/${modal.id}`, data);
    }
    refreshData();
    if (store) store.invalidateRelated('rent_charges', 'contracts');
  };

  const handleDelete = async (row) => {
    if (!await confirm(`${t('modals.confirmDelete.body')}`, { action: 'delete' })) return;
    setDeleteError(null);
    try {
      await api.del(`/rent-charges/${row.id}`);
      refreshData();
      if (store) store.invalidateRelated('rent_charges', 'contracts');
    } catch (err) {
      setDeleteError(err.message || t('pages.deleteFailed'));
    }
  };

  // only the first load replaces the page; a reload keeps the table and an open form
  if (loading && !loaded && !modal) return <div className="page-loading">{t('ui.table.loading')}</div>;
  if (error && !loaded && !modal) return <div className="page"><p className="alert-error" role="alert">{error}{' '}
    <button type="button" className="btn btn-secondary btn-sm" onClick={refreshData}>Erneut laden</button></p></div>;

  return (
    <div className="page">
      {error && <p className="alert-error" role="alert">Sollstellungen konnten nicht aktualisiert werden. {error} Angezeigt wird der zuletzt geladene Stand.{' '}
        <button type="button" className="btn btn-secondary btn-sm" onClick={refreshData}>Erneut laden</button></p>}
      {lookupErrors.length > 0 && <p className="alert-error" role="alert">Die Vertrags- oder Mieterauswahl ist nicht verfügbar. {lookupErrors.join(' · ')}{' '}
        <button type="button" className="btn btn-secondary btn-sm" onClick={() => { contractState.reload(); tenantState.reload(); }}>Auswahl erneut laden</button></p>}
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
        onAdd={choicesReady ? () => setModal('create') : undefined}
        onEdit={choicesReady ? row => setModal(row) : undefined}
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
