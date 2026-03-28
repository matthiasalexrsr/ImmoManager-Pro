import { useState, useEffect, useMemo } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import { useEntities, useDataStore } from '../contexts/DataStoreContext';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import StatusBadge from '../components/StatusBadge';
import { useConfirm } from '../components/ConfirmDialog';

export default function Bookings() {
  const { t } = useTranslation();
  const confirm = useConfirm();
  const store = useDataStore();
  const { items: accounts } = useEntities('accounts', '/accounts');
  const { items: categories } = useEntities('categories', '/categories');
  const { items: properties } = useEntities('properties', '/properties');
  const { items: units } = useEntities('units', '/units');
  const { items: tenants } = useEntities('tenants', '/tenants');

  const [bookings, setBookings] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(null);
  const [filter, setFilter] = useState('all');

  const noneOpt = t('ui.form.none') || '— Keine —';

  const refreshData = () => {
    setLoading(true);
    api.get('/bookings').catch(() => [])
      .then(data => setBookings(Array.isArray(data) ? data : []))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    let cancelled = false;
    api.get('/bookings').catch(err => { console.warn('[Bookings] load:', err.message); return []; })
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

  // Enriched data
  const enriched = bookings.map(b => ({
    ...b,
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
    { key: 'account_name', label: t('finance.accounts.form.name') || 'Konto', filterType: 'text' },
    { key: 'category_name', label: t('finance.bookings.form.category') || 'Kategorie', filterType: 'text' },
    { key: 'amount', label: t('finance.bookings.form.amount') || 'Betrag (€)', type: 'number', align: 'right', filterType: 'numberRange',
      render: v => {
        const n = Number(v);
        const cls = n < 0 ? 'text-red' : 'text-green';
        return <span className={cls}>{n.toFixed(2)} €</span>;
      }},
    { key: 'payment_text', label: t('finance.bookings.form.paymentText') || 'Buchungstext', filterType: 'text' },
    { key: 'property_name', label: t('portfolio.properties.form.name') || 'Immobilie', filterType: 'text' },
    { key: 'unit_label', label: t('units.list.columns.label') || 'Einheit', filterType: 'text', hidden: true },
    { key: 'tenant_name', label: t('tenantsContracts.tenants.title') || 'Mieter', filterType: 'text', hidden: true },
    { key: 'has_receipt', label: 'Beleg', filterType: 'text' },
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
      { value: 'matched', label: t('finance.bookings.status.matched') || 'Zugeordnet' },
      { value: 'booked', label: t('finance.bookings.status.booked') || 'Gebucht' },
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
      <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', marginBottom: '1.5rem' }}>
        <div className="panel" style={{ padding: '0.75rem 1rem', minWidth: '140px', textAlign: 'center' }}>
          <div style={{ fontSize: '1.4rem', fontWeight: 700 }}>{totalCount}</div>
          <div className="text-muted" style={{ fontSize: '0.8rem' }}>Gesamt</div>
        </div>
        <div className="panel" style={{ padding: '0.75rem 1rem', minWidth: '140px', textAlign: 'center' }}>
          <div style={{ fontSize: '1.4rem', fontWeight: 700, color: 'var(--success)' }}>{totalIncome.toFixed(2)} €</div>
          <div className="text-muted" style={{ fontSize: '0.8rem' }}>Einnahmen</div>
        </div>
        <div className="panel" style={{ padding: '0.75rem 1rem', minWidth: '140px', textAlign: 'center' }}>
          <div style={{ fontSize: '1.4rem', fontWeight: 700, color: 'var(--danger)' }}>{totalExpense.toFixed(2)} €</div>
          <div className="text-muted" style={{ fontSize: '0.8rem' }}>Ausgaben</div>
        </div>
        <div className="panel" style={{ padding: '0.75rem 1rem', minWidth: '140px', textAlign: 'center' }}>
          <div style={{ fontSize: '1.4rem', fontWeight: 700, color: noCategory > 0 ? 'var(--warning)' : undefined }}>{noCategory}</div>
          <div className="text-muted" style={{ fontSize: '0.8rem' }}>Ohne Kategorie</div>
        </div>
        <div className="panel" style={{ padding: '0.75rem 1rem', minWidth: '140px', textAlign: 'center' }}>
          <div style={{ fontSize: '1.4rem', fontWeight: 700, color: noReceipt > 0 ? 'var(--warning)' : undefined }}>{noReceipt}</div>
          <div className="text-muted" style={{ fontSize: '0.8rem' }}>Ohne Beleg</div>
        </div>
      </div>

      {/* Filter tabs */}
      <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem', flexWrap: 'wrap' }}>
        {[
          { key: 'all', label: 'Alle' },
          { key: 'open', label: 'Offen' },
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
