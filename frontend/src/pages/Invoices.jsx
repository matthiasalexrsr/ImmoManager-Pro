import { useState, useEffect, useMemo, useRef } from 'react';
import { api } from '../api';
import { deriveAmounts } from '../utils/invoiceAmounts';
import { useTranslation } from '../i18n';
import { useEntities, useDataStore } from '../contexts/DataStoreContext';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import KpiAction from '../components/KpiAction';
import useAssistantHandoff from '../hooks/useAssistantHandoff';
import AssistantHandoffNotice from '../components/AssistantHandoffNotice';
import { useNavigate, useSearchParams } from 'react-router-dom';
import StatusBadge from '../components/StatusBadge';
import { useConfirm } from '../components/ConfirmDialog';
import { SearchIcon } from '../components/Icons';
import { formatDate, formatMoney, formatPercent } from '../utils/format';
import { Banknote, Copy as CopyIcon } from 'lucide-react';
import { duplicateOf } from '../utils/duplicate';
import { aktenwerkBulkAction, documentExchangeId, useAktenwerkReady } from '../features/aktenwerk/aktenwerkApi';

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
  // the number opens the invoice's review: checks, decision, payments, history
  { key: 'invoice_number', label: 'Rechnungs-Nr.', filterType: 'text', link: { kind: 'invoiceReview', idKey: 'id' } },
  { key: 'supplier', label: 'Lieferant', filterType: 'text', link: 'contact' },
  { key: 'property_name', label: 'Immobilie', filterType: 'text', link: 'property' },
  { key: 'category', hidden: true, label: 'Kategorie', filterType: 'select',
    render: v => CATEGORY_LABELS[v] || v || '—' },
  { key: 'invoice_date', hidden: true, label: 'Datum', type: 'date', filterType: 'dateRange' },
  { key: 'payment_due_on', label: 'Fällig am', type: 'date', filterType: 'dateRange',
    render: (v, row) => {
      if (!v) return '—';
      const overdue = row.payment_summary.overdue;
      return <span style={{ color: overdue ? 'var(--danger)' : 'inherit', fontWeight: overdue ? 600 : 400 }}>{formatDate(v)}</span>;
    }},
  { key: 'net_amount', hidden: true, label: 'Netto (€)', type: 'number', sum: true, align: 'right',
    render: v => formatMoney(v) },
  { key: 'vat_display', hidden: true, label: 'MwSt', align: 'right',
    render: (_, row) => row.vat_rate != null ? `${formatMoney(row.vat_amount)} (${formatPercent(row.vat_rate)})` : '—' },
  { key: 'gross_amount', label: 'Brutto (€)', type: 'number', sum: true, align: 'right', filterType: 'numberRange',
    render: v => v != null ? <strong>{formatMoney(v)}</strong> : '—' },
  { key: 'paid_amount', hidden: true, label: 'Zugeordnet bezahlt (€)', type: 'number', sum: true, align: 'right', render: formatMoney },
  { key: 'open_amount', label: 'Restbetrag (€)', type: 'number', align: 'right', render: value => value == null ? 'Ungeklärt' : formatMoney(value) },
  { key: 'payment_reference', hidden: true, label: 'Zahlungsreferenz' },
  { key: 'payment_status', label: 'Zahlungsstand', filterType: 'select', render: (value, row) => <span title={row.payment_summary.note || undefined}>
    {value === 'unclear' ? <span className="badge badge-yellow">Ungeklärt</span>
      : value === 'awaiting_review' ? <span className="badge badge-yellow">Freigabe offen</span>
      : value === 'credit_note' ? <span className="badge badge-gray">Gutschrift</span>
        : value === 'overpaid' ? <span className="badge badge-yellow">Überzahlt</span>
          : <StatusBadge status={value} />}
    {row.payment_summary.note && <span className="td-sub td-clamp">{row.payment_summary.note}</span>}
  </span> },
  { key: 'status', label: 'Manueller Status', hidden: true, type: 'status', filterType: 'select',
    render: v => <StatusBadge status={v} /> },
];

export default function Invoices() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const { t } = useTranslation();
  const confirm = useConfirm();
  const store = useDataStore();
  const { items: properties } = useEntities('properties', '/properties');
  const { items: taxRates } = useEntities('taxRates', '/tax-rates');
  const [invoices, setInvoices] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);
  const [attempt, setAttempt] = useState(0);
  const [modal, setModal] = useState(null);
  // values of a duplicated invoice for the New form (null: an empty form)
  const [prefill, setPrefill] = useState(null);
  const assistantHandoff = useAssistantHandoff('invoice', values => { setPrefill(values); setModal('create'); });
  const assistantSaved = useRef(false);
  useEffect(() => { assistantSaved.current = false; }, [assistantHandoff.identifier]);
  const aktenwerkReady = useAktenwerkReady();
  const filter = params.get('status') || 'all';
  const propertyId = params.get('property_id') || '';
  const setFilter = value => setParams(current => {
    const next = new URLSearchParams(current);
    if (value === 'all') next.delete('status'); else next.set('status', value);
    return next;
  });
  const [drilldown, setDrilldown] = useState(0);
  const openSources = key => { setFilter(key); setDrilldown(value => value + 1); };

  const refreshData = () => setAttempt(value => value + 1);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setLoadError(null);
    api.list('/invoices/overview', { signal: controller.signal })
      .then(data => {
        if (!Array.isArray(data) || data.some(row => !row.payment_summary
          || !Number.isFinite(row.payment_summary.paid)
          || !(row.payment_summary.open === null || Number.isFinite(row.payment_summary.open)))) {
          throw new Error('Rechnungen und Zahlungsstände konnten nicht vollständig gelesen werden.');
        }
        if (!controller.signal.aborted) setInvoices(data);
      })
      .catch(failure => { if (!controller.signal.aborted) setLoadError(failure.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [attempt]);

  const propMap = Object.fromEntries(properties.map(p => [p.id, p.name]));
  const enriched = invoices.filter(inv => !propertyId || inv.property_id === propertyId).map(inv => ({
    ...inv,
    property_name: propMap[inv.property_id] || '—',
    invoice_number: inv.invoice_number || inv.id?.toString().slice(0, 8),
    payment_status: inv.payment_summary.status,
    paid_amount: inv.payment_summary.paid,
    open_amount: inv.payment_summary.open,
    payment_due_on: inv.payment_summary.due_on || inv.due_date,
  }));

  const filtered = useMemo(() => {
    if (filter === 'all') return enriched;
    if (filter === 'unpaid') return enriched.filter(i => i.open_amount > 0);
    if (filter === 'unclear') return enriched.filter(i => i.open_amount === null);
    if (filter === 'payments') return enriched.filter(i => i.paid_amount !== 0);
    return enriched.filter(i => i.payment_status === filter);
  }, [enriched, filter]);

  // Summary stats
  const sum = (rows, key) => rows.reduce((s, i) => s + Math.round((Number(i[key]) || 0) * 100), 0) / 100;
  const totalOpen = sum(enriched, 'open_amount');
  const totalOverdue = sum(enriched.filter(i => i.payment_summary.overdue), 'open_amount');
  const totalPaid = sum(enriched, 'paid_amount');
  const unclearCount = enriched.filter(i => i.open_amount === null).length;
  const totalVat = sum(enriched, 'vat_amount');

  const defaultVatRate = taxRates.find(t => t.is_default)?.rate ?? 19;

  const fields = [
    { key: 'supplier', label: 'Lieferant', required: true },
    { key: 'invoice_number', label: 'Rechnungs-Nr.', placeholder: 'z.B. RE-2026-001' },
    { key: 'property_id', label: 'Immobilie', type: 'select',
      options: [{ value: '', label: '— Keine —' }, ...properties.map(p => ({ value: p.id, label: p.name }))] },
    { key: 'invoice_date', label: 'Rechnungsdatum', type: 'date', required: true },
    { key: 'due_date', label: 'Fälligkeitsdatum', type: 'date' },
    { key: 'performance_start', label: 'Leistung von', type: 'date' },
    { key: 'performance_end', label: 'Leistung bis', type: 'date' },
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
    if (modal === 'create' && assistantHandoff.identifier) {
      await assistantHandoff.save(data);
      assistantSaved.current = true;
      store?.invalidateRelated('invoices', 'documents');
      return;
    }
    // Fill only missing amounts. An explicitly entered zero belongs to the invoice.
    const net = Number(data.net_amount) || 0;
    const rate = Number(data.vat_rate) || 0;
    if (net > 0 && (data.vat_amount == null || data.vat_amount === '')) {
      data.vat_amount = Number((net * rate / 100).toFixed(2));
    }
    if (net > 0 && (data.gross_amount == null || data.gross_amount === '')) {
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
    if (!await confirm(`"${row.supplier}" ${t('modals.confirmDelete.body')}`, { action: 'delete' })) return;
    await api.del(`/invoices/${row.id}`);
    refreshData();
    if (store) store.invalidateRelated('invoices', 'contracts', 'receivables');
  };

  // only the first load replaces the page; a reload keeps the table and an open form ("Speichern & weiteren")
  if (loading && invoices.length === 0 && !modal) return <div className="page-loading">Lade Rechnungen...</div>;

  return (
    <div className="page">
      <h1 className="page-title">Rechnungen</h1>
      <AssistantHandoffNotice handoff={assistantHandoff} onClose={() => { setModal(null); setPrefill(null); assistantHandoff.clear(); }} />
      {propertyId && <p role="status">Immobilienfilter: {propMap[propertyId] || `Unbekannte Immobilie (${propertyId})`}
        {' '}<button type="button" className="btn btn-sm btn-secondary" onClick={() => setParams(current => {
          const next = new URLSearchParams(current); next.delete('property_id'); return next;
        })}>Immobilienfilter entfernen</button>
      </p>}
      {loadError && <p className="alert-error" role="alert">Rechnungen konnten nicht aktualisiert werden. {loadError}<button type="button" className="btn btn-secondary" onClick={refreshData}>Erneut laden</button></p>}

      {/* Summary cards */}
      {!loadError && <div className="kpi-row">
        <KpiAction label="Gesamt" value={enriched.length} onClick={() => openSources('all')} />
        <KpiAction label="Offen" value={formatMoney(totalOpen)} color="var(--warning)" onClick={() => openSources('unpaid')} />
        <KpiAction label="Überfällig" value={formatMoney(totalOverdue)} color="var(--danger)" onClick={() => openSources('overdue')} />
        <KpiAction label="Bezahlt" value={formatMoney(totalPaid)} color="var(--success)" onClick={() => openSources('payments')} />
        {unclearCount > 0 && <KpiAction label="Zahlungsstand ungeklärt" value={unclearCount} onClick={() => openSources('unclear')} />}
        <KpiAction label="MwSt gesamt" value={formatMoney(totalVat)} onClick={() => openSources('all')} />
      </div>}
      {!loadError && <p className="text-muted">„Offen“ enthält die nachgewiesenen Restbeträge einschließlich überfälliger Rechnungen. „Bezahlt“ zeigt zugeordnete Zahlungen. Ungeklärte Beträge sind gesondert ausgewiesen.</p>}

      {/* Filter tabs */}
      <div className="filter-chips">
        {[
          { key: 'all', label: 'Alle' },
          { key: 'unpaid', label: 'Unbezahlt' },
          { key: 'open', label: 'Offen' },
          { key: 'overdue', label: 'Überfällig' },
          { key: 'partial', label: 'Teilbezahlt' },
          { key: 'paid', label: 'Bezahlt' },
          { key: 'payments', label: 'Mit Zahlungen' },
          { key: 'unclear', label: 'Ungeklärt' },
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
        columns={COLUMNS}
        data={filtered}
        drilldownKey={drilldown}
        viewConfig={{ column_filters: { workflow_filter: filter, property_id: propertyId } }}
        onApplyView={config => setParams(current => {
          const next = new URLSearchParams(current);
          const saved = config.column_filters || {};
          if (!saved.workflow_filter || saved.workflow_filter === 'all') next.delete('status'); else next.set('status', saved.workflow_filter);
          if (saved.property_id) next.set('property_id', saved.property_id); else next.delete('property_id');
          return next;
        })}
        rowName={row => `${row.supplier || 'Rechnung'} ${row.invoice_number || ''}`.trim()}
        // the invoice's document (received through the invoice review) for the document management system
        bulkActions={aktenwerkReady ? [aktenwerkBulkAction(row => documentExchangeId(row.source_document_id))] : []}
        onAdd={values => { setPrefill(values || null); setModal('create'); }}
        onEdit={row => setModal(row)}
        onDelete={handleDelete}
        rowActions={row => [{
          label: 'Dubletten prüfen',
          icon: <SearchIcon size={15} />,
          onClick: () => navigate(`/duplicate-check?kind=invoice&id=${encodeURIComponent(row.id)}`),
        }, {
          label: 'Duplizieren', write: true, icon: <CopyIcon size={15} />,
          // a new invoice of the same supplier: its own number, state and document
          onClick: () => { setPrefill(duplicateOf(row, ['invoice_number', 'status', 'source_document_id', 'payment_reference'])); setModal('create'); },
        }, ...(!['paid', 'cancelled', 'rejected', 'credit_note', 'overpaid'].includes(row.payment_status) ? [{
          label: 'Zahlung zuordnen',
          write: true, icon: <Banknote size={15} />,
          onClick: () => navigate(`/invoice-review/${encodeURIComponent(row.id)}#ir-payment`),
        }] : [])]}
      />

      {modal && (
        <FormModal
          title={modal === 'create' ? 'Rechnung erstellen' : 'Rechnung bearbeiten'}
          repeatKeep={assistantHandoff.identifier ? undefined : ['property_id', 'invoice_date', 'vat_rate', 'category']}
          fields={assistantHandoff.identifier ? fields.filter(field => !['invoice_number', 'payment_reference', 'category', 'notes'].includes(field.key))
            .map(field => field.key === 'status' ? { ...field, options: [{ value: 'open', label: 'Offen' }] } : field) : fields}
          initial={modal === 'create' ? prefill : modal}
          derive={deriveAmounts}
          onSave={handleSave}
          onClose={() => { setModal(null); setPrefill(null);
            if (assistantSaved.current) { assistantSaved.current = false; navigate(assistantHandoff.returnHref); }
            else if (assistantHandoff.identifier) assistantHandoff.clear(); }}
        />
      )}
    </div>
  );
}
