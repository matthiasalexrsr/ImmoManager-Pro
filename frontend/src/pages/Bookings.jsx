import { useState, useEffect, useMemo } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import { useEntities, useDataStore } from '../contexts/DataStoreContext';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import StatusBadge from '../components/StatusBadge';
import { useConfirm } from '../components/ConfirmDialog';
import { useToast } from '../components/Toast';
import { formatMoney } from '../utils/format';

export default function Bookings() {
  const { t } = useTranslation();
  const confirm = useConfirm();
  const toast = useToast();
  const store = useDataStore();
  const { items: contracts } = useEntities('contracts', '/contracts');
  const { items: accounts } = useEntities('accounts', '/accounts');
  const { items: categories } = useEntities('categories', '/categories');
  const { items: properties } = useEntities('properties', '/properties');
  const { items: units } = useEntities('units', '/units');
  const { items: tenants } = useEntities('tenants', '/tenants');

  const [bookings, setBookings] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(null);
  const [filter, setFilter] = useState('all');
  const [allocations, setAllocations] = useState([]);
  const [split, setSplit] = useState(null);

  const noneOpt = t('ui.form.none') || '— Keine —';

  // Which contract a tenant payment pays (a transfer may pay flat and garage together).
  const loadAllocations = () => api.get('/bookings/allocations').then(a => setAllocations(a || [])).catch(() => setAllocations([]));

  const refreshData = () => {
    setLoading(true);
    loadAllocations();
    api.list('/bookings').catch(() => [])
      .then(data => setBookings(Array.isArray(data) ? data : []))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    let cancelled = false;
    loadAllocations();
    api.list('/bookings').catch(err => { console.warn('[Bookings] load:', err.message); return []; })
      .then(data => { if (!cancelled) setBookings(Array.isArray(data) ? data : []); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  // Lookup maps
  const accountMap = Object.fromEntries(accounts.map(a => [a.id, a.name]));
  const categoryMap = Object.fromEntries(categories.map(c => [c.id, c.name]));
  const propertyMap = Object.fromEntries(properties.map(p => [p.id, p.name]));
  const unitMap = Object.fromEntries(units.map(u => [u.id, u.label]));
  const tenantMap = Object.fromEntries(tenants.map(tn => [tn.id, tn.full_name]));
  const contractNumber = Object.fromEntries(contracts.map(c => [c.id, c.contract_number]));
  const allocationsByBooking = {};
  allocations.forEach(a => { (allocationsByBooking[a.booking_id] ||= []).push(a); });

  // Short label for the list (contract numbers), the amounts per contract as tooltip.
  const allocationInfo = (b) => {
    if (!b.tenant_id) return { label: '—', detail: '', unassigned: 0 };
    const own = allocationsByBooking[b.id] || [];
    const rest = Math.round((Number(b.amount) - own.reduce((s, a) => s + Number(a.amount), 0)) * 100) / 100;
    const parts = own.map(a => `${contractNumber[a.contract_id] || '?'}: ${formatMoney(a.amount)}`);
    if (rest) parts.push(`nicht zugeordnet: ${formatMoney(rest)}`);
    return {
      label: own.map(a => contractNumber[a.contract_id] || '?').join(' + ') || '—',
      detail: parts.join('\n'),
      unassigned: rest,
    };
  };

  // Enriched data
  const enriched = bookings.map(b => ({
    ...b,
    ...(info => ({ allocation_label: info.label, allocation_detail: info.detail, unassigned: info.unassigned }))(allocationInfo(b)),
    account_name: accountMap[b.account_id] || '—',
    category_name: categoryMap[b.category_id] || '—',
    property_name: propertyMap[b.property_id] || '—',
    unit_label: unitMap[b.unit_id] || '—',
    tenant_name: tenantMap[b.tenant_id] || '—',
    has_receipt: b.receipt_url ? '✓ Vorhanden' : '—',
  }));

  // Filtered data
  const filtered = useMemo(() => {
    switch (filter) {
      case 'open': return enriched.filter(b => b.status === 'open');
      case 'unassigned': return enriched.filter(b => b.unassigned);
      case 'no_category': return enriched.filter(b => !b.category_id);
      case 'no_receipt': return enriched.filter(b => !b.receipt_url);
      case 'income': return enriched.filter(b => Number(b.amount) > 0);
      case 'expense': return enriched.filter(b => Number(b.amount) < 0);
      default: return enriched;
    }
  }, [enriched, filter]);

  // Summary stats
  const totalCount = enriched.length;
  const totalIncome = enriched.filter(b => Number(b.amount) > 0).reduce((s, b) => s + Number(b.amount), 0);
  const totalExpense = enriched.filter(b => Number(b.amount) < 0).reduce((s, b) => s + Math.abs(Number(b.amount)), 0);
  const noCategory = enriched.filter(b => !b.category_id).length;
  const noReceipt = enriched.filter(b => !b.receipt_url).length;

  const columns = [
    { key: 'booking_date', label: t('finance.bookings.form.date') || 'Datum', type: 'date', filterType: 'dateRange' },
    { key: 'account_name', hidden: true, label: t('finance.accounts.form.name') || 'Konto', filterType: 'text' },
    { key: 'category_name', label: t('finance.bookings.form.category') || 'Kategorie', filterType: 'text' },
    { key: 'amount', label: t('finance.bookings.form.amount') || 'Betrag (€)', type: 'number', align: 'right', filterType: 'numberRange',
      render: v => {
        const n = Number(v);
        const cls = n < 0 ? 'text-red' : 'text-green';
        return <span className={cls}>{formatMoney(n)}</span>;
      }},
    { key: 'payment_text', label: t('finance.bookings.form.paymentText') || 'Buchungstext', filterType: 'text' },
    { key: 'property_name', label: t('portfolio.properties.form.name') || 'Immobilie', filterType: 'text' },
    { key: 'unit_label', label: t('units.list.columns.label') || 'Einheit', filterType: 'text', hidden: true },
    { key: 'tenant_name', label: t('tenantsContracts.tenants.title') || 'Mieter', filterType: 'text', hidden: true },
    { key: 'allocation_label', label: 'Vertrag', filterType: 'text',
      render: (v, row) => (row.tenant_id
        ? (
          <span className="cell-inline" title={row.allocation_detail}>
            <span>{v}</span>
            {row.unassigned !== 0 && <span className="badge badge-yellow">offen {formatMoney(row.unassigned)}</span>}
            <button className="btn btn-sm btn-ghost btn-link" onClick={() => openSplit(row)}>Aufteilen</button>
          </span>
        )
        : v) },
    { key: 'has_receipt', hidden: true, label: 'Beleg', filterType: 'text' },
    { key: 'status', label: t('ui.form.status') || 'Status', type: 'status', filterType: 'select',
      render: v => <StatusBadge status={v} /> },
  ];

  const fields = [
    { key: 'account_id', label: t('finance.accounts.form.name') || 'Konto', required: true, type: 'select',
      options: accounts.map(a => ({ value: a.id, label: a.name })) },
    { key: 'category_id', label: t('finance.bookings.form.category') || 'Kategorie', type: 'select',
      options: [{ value: '', label: noneOpt }, ...categories.map(c => ({ value: c.id, label: c.name }))] },
    { key: 'property_id', label: t('portfolio.properties.form.name') || 'Immobilie', type: 'select',
      options: [{ value: '', label: noneOpt }, ...properties.map(p => ({ value: p.id, label: p.name }))] },
    { key: 'unit_id', label: t('units.list.columns.label') || 'Einheit', type: 'select',
      options: [{ value: '', label: noneOpt }, ...units.map(u => ({ value: u.id, label: u.label }))] },
    { key: 'tenant_id', label: t('tenantsContracts.tenants.title') || 'Mieter', type: 'select',
      options: [{ value: '', label: noneOpt }, ...tenants.map(tn => ({ value: tn.id, label: tn.full_name }))] },
    { key: 'booking_date', label: t('finance.bookings.form.bookingDate') || 'Buchungsdatum', type: 'date', required: true },
    { key: 'amount', label: t('finance.bookings.form.amount') || 'Betrag (€)', type: 'number', required: true },
    { key: 'payment_text', label: t('finance.bookings.form.paymentText') || 'Buchungstext' },
    { key: 'receipt_url', label: t('finance.bookings.form.receiptUrl') || 'Beleg-URL', placeholder: '/belege/beleg.pdf' },
    { key: 'status', label: t('ui.form.status') || 'Status', type: 'select', default: 'open', options: [
      { value: 'open', label: t('ui.filterChips.open') || 'Offen' },
      { value: 'matched', label: t('status.booking.matched') || 'Zugeordnet' },
      { value: 'booked', label: t('status.booking.booked') || 'Gebucht' },
    ]},
  ];

  const handleSave = async (data) => {
    if (modal === 'create') {
      await api.post('/bookings', data);
    } else {
      await api.put(`/bookings/${modal.id}`, data);
    }
    refreshData();
    if (store) store.invalidateRelated('bookings', 'accounts', 'categories');
  };

  const openSplit = (row) => {
    const own = allocationsByBooking[row.id] || [];
    const tenantContracts = contracts.filter(c => c.tenant_id === row.tenant_id);
    setSplit({ booking: row, values: Object.fromEntries(tenantContracts.map(c => [c.id,
      String(own.find(a => a.contract_id === c.id)?.amount ?? '')])) });
  };

  const saveSplit = async () => {
    const items = Object.entries(split.values)
      .filter(([, v]) => v !== '' && Number(v) !== 0)
      .map(([contract_id, v]) => ({ contract_id, amount: Number(v) }));
    try {
      await api.put(`/bookings/${split.booking.id}/allocations`, items);
      setSplit(null);
      loadAllocations();
      toast.success('Zuordnung gespeichert');
    } catch (err) {
      toast.error(err.message);
    }
  };

  const handleDelete = async (row) => {
    if (!await confirm(`"${row.payment_text || row.id}" ${t('modals.confirmDelete.body')}`)) return;
    await api.del(`/bookings/${row.id}`);
    refreshData();
    if (store) store.invalidateRelated('bookings', 'accounts', 'categories');
  };

  if (loading) return <div className="page-loading">Lade Buchungen...</div>;

  return (
    <div className="page">
      <h1 className="page-title">{t('finance.bookings.title') || 'Buchungen'}</h1>

      {/* Summary cards */}
      <div className="kpi-row">
        <div className="kpi">
          <div className="kpi-value">{totalCount}</div>
          <div className="kpi-label">Gesamt</div>
        </div>
        <div className="kpi">
          <div className="kpi-value" style={{ color: 'var(--success)' }}>{formatMoney(totalIncome)}</div>
          <div className="kpi-label">Einnahmen</div>
        </div>
        <div className="kpi">
          <div className="kpi-value" style={{ color: 'var(--danger)' }}>{formatMoney(totalExpense)}</div>
          <div className="kpi-label">Ausgaben</div>
        </div>
        <div className="kpi">
          <div className="kpi-value" style={{ color: noCategory > 0 ? 'var(--warning)' : undefined }}>{noCategory}</div>
          <div className="kpi-label">Ohne Kategorie</div>
        </div>
        <div className="kpi">
          <div className="kpi-value" style={{ color: noReceipt > 0 ? 'var(--warning)' : undefined }}>{noReceipt}</div>
          <div className="kpi-label">Ohne Beleg</div>
        </div>
      </div>

      {/* Filter tabs */}
      <div className="filter-chips">
        {[
          { key: 'all', label: 'Alle' },
          { key: 'open', label: 'Offen' },
          { key: 'unassigned', label: 'Nicht zugeordnet' },
          { key: 'no_category', label: 'Ohne Kategorie' },
          { key: 'no_receipt', label: 'Ohne Beleg' },
          { key: 'income', label: 'Einnahmen' },
          { key: 'expense', label: 'Ausgaben' },
        ].map(f => (
          <button
            key={f.key}
            className={`btn btn-sm ${filter === f.key ? 'btn-primary' : 'btn-secondary'}`}
            onClick={() => setFilter(f.key)}
          >{f.label}</button>
        ))}
      </div>

      <DataTable
        title={t('finance.bookings.title') || 'Buchungen'}
        columns={columns}
        data={filtered}
        onAdd={() => setModal('create')}
        onEdit={row => setModal(row)}
        onDelete={handleDelete}
      />

      {split && (
        <div className="modal-overlay" onClick={() => setSplit(null)} role="presentation">
          <div className="modal" role="dialog" aria-modal="true" aria-label="Zahlung aufteilen" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h2>Zahlung aufteilen ({formatMoney(split.booking.amount)})</h2>
              <button onClick={() => setSplit(null)} className="btn-close" aria-label="Schließen">✕</button>
            </div>
            <div className="modal-body">
              {Object.keys(split.values).length === 0 && <p className="text-muted">Der Mieter hat keine Verträge.</p>}
              {Object.entries(split.values).map(([contractId, value]) => (
                <div key={contractId} className="form-group">
                  <label htmlFor={`split-${contractId}`}>Vertrag {contractNumber[contractId]} (€)</label>
                  <input id={`split-${contractId}`} type="number" step="0.01" value={value}
                    onChange={e => setSplit(s => ({ ...s, values: { ...s.values, [contractId]: e.target.value } }))} />
                </div>
              ))}
              <p className="text-muted">Was keinem Vertrag zugeordnet wird, bleibt „nicht zugeordnet“.</p>
              <div className="modal-footer">
                <button className="btn btn-secondary" onClick={() => setSplit(null)}>Abbrechen</button>
                <button className="btn btn-primary" onClick={saveSplit}>Speichern</button>
              </div>
            </div>
          </div>
        </div>
      )}

      {modal && (
        <FormModal
          title={modal === 'create' ? 'Buchung erstellen' : 'Buchung bearbeiten'}
          fields={fields}
          initial={modal === 'create' ? null : modal}
          onSave={handleSave}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  );
}
