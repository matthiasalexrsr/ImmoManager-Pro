import { useState, useEffect, useMemo } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import { useEntities, useDataStore } from '../contexts/DataStoreContext';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import StatusBadge from '../components/StatusBadge';
import { useConfirm } from '../components/ConfirmDialog';

const STATUS_OPTIONS = [
  { value: 'open', label: 'Offen' },
  { value: 'paid', label: 'Bezahlt' },
  { value: 'overdue', label: 'Überfällig' },
  { value: 'partial', label: 'Teilweise bezahlt' },
  { value: 'cancelled', label: 'Storniert' },
];

const CATEGORY_LABELS = {
  instandhaltung: 'Instandhaltung', versicherung: 'Versicherung', verwaltung: 'Verwaltung',
  steuer: 'Steuer & Abgaben', energie: 'Energie & Versorger', sonstiges: 'Sonstiges',
};

const COLUMNS = [
  { key: 'invoice_number', label: 'Rechnungs-Nr.', filterType: 'text' },
  { key: 'supplier', label: 'Lieferant', filterType: 'text' },
  { key: 'property_name', label: 'Immobilie', filterType: 'text' },
  { key: 'category', label: 'Kategorie', filterType: 'select',
    render: v => CATEGORY_LABELS[v] || v || '—' },
  { key: 'invoice_date', label: 'Rechnungsdatum', type: 'date', filterType: 'dateRange' },
  { key: 'due_date', label: 'Fällig am', type: 'date', filterType: 'dateRange',
    render: (v, row) => {
      if (!v) return '—';
      const due = new Date(v);
      const today = new Date();
      const overdue = row.status !== 'paid' && row.status !== 'cancelled' && due < today;
      return <span style={{ color: overdue ? 'var(--danger)' : 'inherit', fontWeight: overdue ? 600 : 400 }}>{v}</span>;
    }},
  { key: 'net_amount', label: 'Netto (€)', type: 'number', align: 'right',
    render: v => v != null ? `${Number(v).toFixed(2)} €` : '—' },
  { key: 'vat_display', label: 'MwSt', align: 'right',
    render: (_, row) => row.vat_rate != null ? `${Number(row.vat_rate).toFixed(1)}% (${Number(row.vat_amount || 0).toFixed(2)} €)` : '—' },
  { key: 'gross_amount', label: 'Brutto (€)', type: 'number', align: 'right', filterType: 'numberRange',
    render: v => v != null ? <strong>{Number(v).toFixed(2)} €</strong> : '—' },
  { key: 'payment_reference', label: 'Zahlungsreferenz' },
  { key: 'status', label: 'Status', type: 'status', filterType: 'select',
    render: v => <StatusBadge status={v} /> },
];

export default function Invoices() {
  const { t } = useTranslation();
  const confirm = useConfirm();
  const store = useDataStore();
  const { items: properties } = useEntities('properties', '/properties');
  const { items: taxRates } = useEntities('taxRates', '/tax-rates');
  const [invoices, setInvoices] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(null);
  const [filter, setFilter] = useState('all');

  const refreshData = () => {
    setLoading(true);
    api.get('/invoices').catch(() => [])
      .then(inv => setInvoices(Array.isArray(inv) ? inv : []))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    let cancelled = false;
    api.get('/invoices').catch(err => { console.warn('[Invoices] invoices:', err.message); return []; })
      .then(data => { if (!cancelled) setInvoices(Array.isArray(data) ? data : []); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  const propMap = Object.fromEntries(properties.map(p => [p.id, p.name]));
  const enriched = invoices.map(inv => ({
    ...inv,
    property_name: propMap[inv.property_id] || '—',
    invoice_number: inv.invoice_number || inv.id?.toString().slice(0, 8),
  }));

  const filtered = useMemo(() => {
    if (filter === 'all') return enriched;
    if (filter === 'unpaid') return enriched.filter(i => i.status === 'open' || i.status === 'overdue' || i.status === 'partial');
    return enriched.filter(i => i.status === filter);
  }, [enriched, filter]);

  // Summary stats
  const totalOpen = enriched.filter(i => i.status === 'open').reduce((s, i) => s + (Number(i.gross_amount) || 0), 0);
  const totalOverdue = enriched.filter(i => i.status === 'overdue').reduce((s, i) => s + (Number(i.gross_amount) || 0), 0);
  const totalPaid = enriched.filter(i => i.status === 'paid').reduce((s, i) => s + (Number(i.gross_amount) || 0), 0);
  const totalVat = enriched.reduce((s, i) => s + (Number(i.vat_amount) || 0), 0);

  const defaultVatRate = taxRates.find(t => t.is_default)?.rate || 19;

  const fields = [
    { key: 'supplier', label: 'Lieferant', required: true },
    { key: 'invoice_number', label: 'Rechnungs-Nr.', placeholder: 'z.B. RE-2026-001' },
    { key: 'property_id', label: 'Immobilie', type: 'select',
      options: [{ value: '', label: '— Keine —' }, ...properties.map(p => ({ value: p.id, label: p.name }))] },
    { key: 'invoice_date', label: 'Rechnungsdatum', type: 'date', required: true },
    { key: 'due_date', label: 'Fälligkeitsdatum', type: 'date' },
    { key: 'net_amount', label: 'Netto (€)', type: 'number', required: true },
    { key: 'vat_rate', label: 'MwSt-Satz (%)', type: 'select',
      default: defaultVatRate,
      options: [
        ...taxRates.map(t => ({ value: t.rate, label: `${t.name} (${t.rate}%)` })),
        ...(taxRates.length === 0 ? [
          { value: 19, label: 'Regelsteuersatz (19%)' },
          { value: 7, label: 'Ermäßigt (7%)' },
          { value: 0, label: 'Steuerfrei (0%)' },
        ] : []),
      ]},
    { key: 'vat_amount', label: 'MwSt-Betrag (€)', type: 'number' },
    { key: 'gross_amount', label: 'Brutto (€)', type: 'number', required: true },
    { key: 'payment_terms', label: 'Zahlungsbedingungen', placeholder: 'z.B. 30 Tage netto' },
    { key: 'payment_reference', label: 'Zahlungsreferenz', placeholder: 'z.B. IBAN / Verwendungszweck' },
    { key: 'category', label: 'Kategorie', type: 'select', options: [
      { value: '', label: '— Keine —' },
      { value: 'instandhaltung', label: 'Instandhaltung' },
      { value: 'versicherung', label: 'Versicherung' },
      { value: 'verwaltung', label: 'Verwaltung' },
      { value: 'steuer', label: 'Steuer & Abgaben' },
      { value: 'energie', label: 'Energie & Versorger' },
      { value: 'sonstiges', label: 'Sonstiges' },
    ]},
    { key: 'notes', label: 'Notizen', type: 'textarea' },
    { key: 'status', label: 'Status', type: 'select', default: 'open', options: STATUS_OPTIONS },
  ];

  const handleSave = async (data) => {
    // Auto-calculate VAT and gross if net and rate are provided
    const net = Number(data.net_amount) || 0;
    const rate = Number(data.vat_rate) || 0;
    if (net > 0 && !data.vat_amount) {
      data.vat_amount = Number((net * rate / 100).toFixed(2));
    }
    if (net > 0 && !data.gross_amount) {
      data.gross_amount = Number((net + (Number(data.vat_amount) || 0)).toFixed(2));
    }

    if (modal === 'create') {
      await api.post('/invoices', data);
    } else {
      await api.put(`/invoices/${modal.id}`, data);
    }
    refreshData();
    if (store) store.invalidateRelated('invoices', 'contracts', 'receivables');
  };

  const handleDelete = async (row) => {
    if (!await confirm(`"${row.supplier}" ${t('modals.confirmDelete.body')}`)) return;
    await api.del(`/invoices/${row.id}`);
    refreshData();
    if (store) store.invalidateRelated('invoices', 'contracts', 'receivables');
  };

  const markPaid = async (row) => {
    await api.patch(`/invoices/${row.id}`, { status: 'paid' });
    refreshData();
    if (store) store.invalidateRelated('invoices', 'contracts', 'receivables');
  };

  if (loading) return <div className="page-loading">Lade Rechnungen...</div>;

  return (
    <div className="page">
      <h1 className="page-title">Rechnungen</h1>

      {/* Summary cards */}
      <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', marginBottom: '1.5rem' }}>
        <div className="panel" style={{ padding: '0.75rem 1rem', minWidth: '140px', textAlign: 'center' }}>
          <div style={{ fontSize: '1.4rem', fontWeight: 700 }}>{enriched.length}</div>
          <div className="text-muted" style={{ fontSize: '0.8rem' }}>Gesamt</div>
        </div>
        <div className="panel" style={{ padding: '0.75rem 1rem', minWidth: '140px', textAlign: 'center' }}>
          <div style={{ fontSize: '1.4rem', fontWeight: 700, color: 'var(--warning)' }}>{totalOpen.toFixed(2)} €</div>
          <div className="text-muted" style={{ fontSize: '0.8rem' }}>Offen</div>
        </div>
        <div className="panel" style={{ padding: '0.75rem 1rem', minWidth: '140px', textAlign: 'center' }}>
          <div style={{ fontSize: '1.4rem', fontWeight: 700, color: 'var(--danger)' }}>{totalOverdue.toFixed(2)} €</div>
          <div className="text-muted" style={{ fontSize: '0.8rem' }}>Überfällig</div>
        </div>
        <div className="panel" style={{ padding: '0.75rem 1rem', minWidth: '140px', textAlign: 'center' }}>
          <div style={{ fontSize: '1.4rem', fontWeight: 700, color: 'var(--success)' }}>{totalPaid.toFixed(2)} €</div>
          <div className="text-muted" style={{ fontSize: '0.8rem' }}>Bezahlt</div>
        </div>
        <div className="panel" style={{ padding: '0.75rem 1rem', minWidth: '140px', textAlign: 'center' }}>
          <div style={{ fontSize: '1.4rem', fontWeight: 700 }}>{totalVat.toFixed(2)} €</div>
          <div className="text-muted" style={{ fontSize: '0.8rem' }}>MwSt gesamt</div>
        </div>
      </div>

      {/* Filter tabs */}
      <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem', flexWrap: 'wrap' }}>
        {[
          { key: 'all', label: 'Alle' },
          { key: 'unpaid', label: 'Unbezahlt' },
          { key: 'open', label: 'Offen' },
          { key: 'overdue', label: 'Überfällig' },
          { key: 'paid', label: 'Bezahlt' },
          { key: 'cancelled', label: 'Storniert' },
        ].map(f => (
          <button
            key={f.key}
            className={`btn btn-sm ${filter === f.key ? 'btn-primary' : 'btn-secondary'}`}
            onClick={() => setFilter(f.key)}
          >{f.label}</button>
        ))}
      </div>

      <DataTable
        title="Rechnungen"
        columns={[...COLUMNS, {
          key: '_actions', label: '', sortable: false,
          render: (_, row) => (row.status === 'open' || row.status === 'overdue') ? (
            <button
              className="btn btn-sm btn-secondary"
              onClick={async (e) => {
                e.stopPropagation();
                if (await confirm(`"${row.supplier}" ${t('pages.invoices.markPaidConfirm') || 'als bezahlt markieren?'}`)) markPaid(row);
              }}
            >
              ✓ Bezahlt
            </button>
          ) : null,
        }]}
        data={filtered}
        onAdd={() => setModal('create')}
        onEdit={row => setModal(row)}
        onDelete={handleDelete}
      />

      {modal && (
        <FormModal
          title={modal === 'create' ? 'Rechnung erstellen' : 'Rechnung bearbeiten'}
          fields={fields}
          initial={modal === 'create' ? null : modal}
          onSave={handleSave}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  );
}
