import { useState, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import { ArrowUpRight, CircleCheck, History, ReceiptText, Wallet, X } from 'lucide-react';
import { api } from '../api';
import DataTable from '../components/DataTable';
import StatusBadge from '../components/StatusBadge';
import { useTranslation } from '../i18n';
import useWriteAccess from '../hooks/useWriteAccess';
import { useDataStore } from '../contexts/DataStoreContext';
import FormModal from '../components/FormModal';
import BankPaymentModal from '../components/BankPaymentModal';
import './FinanceWorkspace.css';

const LEDGERS = ['rent_charge', 'receivable'];

function enrich(items, type, contracts, tenants, units) {
  const contractMap = Object.fromEntries(contracts.map(row => [row.id, row]));
  const tenantMap = Object.fromEntries(tenants.map(row => [row.id, row]));
  const unitMap = Object.fromEntries(units.map(row => [row.id, row]));
  return items.map(item => {
    const contract = contractMap[item.contract_id];
    const total = type === 'rent_charge'
      ? ['cold_rent', 'service_charge', 'heating_charge', 'other_charges'].reduce((sum, key) => sum + Number(item[key] || 0), 0)
      : Number(item.amount_due || 0);
    const paid = Number(item.amount_paid || 0);
    return {
      ...item, entityType: type,
      tenant_id: contract?.tenant_id, property_id: contract?.property_id, unit_id: contract?.unit_id,
      contract_number: contract?.contract_number || '—',
      tenant_name: tenantMap[contract?.tenant_id]?.full_name || '—',
      unit_label: unitMap[contract?.unit_id]?.label || '—',
      month: item.month || item.due_date?.slice(0, 7) || '—',
      total_due: total, amount_paid: paid, remaining: Math.round((total - paid) * 100) / 100,
    };
  });
}

export default function RentOverview() {
  const { t, locale } = useTranslation();
  const cache = useDataStore();
  const [records, setRecords] = useState({ rent_charge: [], receivable: [] });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [revision, setRevision] = useState(0);
  const [tab, setTab] = useState('rent_charge');
  const [paymentModal, setPaymentModal] = useState(null);
  const [history, setHistory] = useState(null);
  const [reversalModal, setReversalModal] = useState(null);
  const { canWrite, isAllowed, requireWrite } = useWriteAccess('/rent-charges', () => { setPaymentModal(null); setReversalModal(null); });
  const historyRequest = useRef(0);
  const historyPanel = useRef(null);
  const historyOrigin = useRef(null);
  const tabButtons = useRef({});
  const [success, setSuccess] = useState(false);
  const [onlyOpen, setOnlyOpen] = useState(true);

  const historyOpenRequest = history?.openRequest;
  useEffect(() => {
    if (!historyOpenRequest) return;
    historyPanel.current?.focus({ preventScroll: true });
    const reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    historyPanel.current?.scrollIntoView?.({ block: 'start', behavior: reducedMotion ? 'auto' : 'smooth' });
  }, [historyOpenRequest]);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    Promise.all(['/rent-charges', '/receivables', '/contracts', '/tenants', '/units']
      .map(path => api.getAll(path, { signal: controller.signal })))
      .then(([charges, receivables, contracts, tenants, units]) => {
        if (controller.signal.aborted) return;
        setRecords({
          rent_charge: enrich(charges, 'rent_charge', contracts, tenants, units),
          receivable: enrich(receivables, 'receivable', contracts, tenants, units),
        });
      })
      .catch(err => { if (!controller.signal.aborted) setError(err.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [revision]);

  const fmt = value => new Intl.NumberFormat(locale, { style: 'currency', currency: 'EUR' }).format(value || 0);
  const text = key => t(`pages.rentOverview.${key}`);
  const endpoint = row => `/${row.entityType === 'rent_charge' ? 'rent-charges' : 'receivables'}/${row.id}/payments`;
  const startPayment = (row, kind = 'manual') => {
    if (!isAllowed()) return;
    setSuccess(false);
    const now = new Date();
    const localDate = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
    setPaymentModal({ row, kind, key: crypto.randomUUID(), initial: { amount: row.remaining, payment_date: localDate } });
  };
  const handleRecordPayment = async values => {
    requireWrite();
    await api.post(endpoint(paymentModal.row), { ...values, idempotency_key: paymentModal.key });
    setSuccess(paymentModal.kind === 'bank' ? 'allocationSaved' : 'paymentSaved');
    cache?.invalidateRelated('rent_charges', 'receivables', 'bookings');
    setRevision(value => value + 1);
  };
  const showHistory = async (row, event) => {
    if (event?.currentTarget) historyOrigin.current = event.currentTarget;
    const request = ++historyRequest.current;
    setHistory({ row, loading: true, payments: [], openRequest: request });
    try {
      const payments = await api.get(endpoint(row));
      setHistory(current => request === historyRequest.current && current?.row.id === row.id
        && current.row.entityType === row.entityType ? { ...current, payments, loading: false } : current);
    } catch (err) {
      setHistory(current => request === historyRequest.current && current?.row.id === row.id
        && current.row.entityType === row.entityType ? { ...current, error: err.message, payments: [], loading: false } : current);
    }
  };
  const closeHistory = () => {
    historyRequest.current += 1;
    setHistory(null);
    const origin = historyOrigin.current;
    (origin?.isConnected ? origin : tabButtons.current[tab])?.focus();
    historyOrigin.current = null;
  };
  const handleTabKeyDown = (event, type) => {
    const index = LEDGERS.indexOf(type);
    const nextIndex = { ArrowRight: (index + 1) % LEDGERS.length,
      ArrowLeft: (index + LEDGERS.length - 1) % LEDGERS.length,
      Home: 0, End: LEDGERS.length - 1 }[event.key];
    if (nextIndex === undefined) return;
    event.preventDefault();
    const next = LEDGERS[nextIndex];
    setTab(next);
    tabButtons.current[next]?.focus();
  };
  const startReversal = payment => {
    if (!isAllowed()) return;
    setReversalModal({ row: history.row, payment, key: crypto.randomUUID(),
      initial: { reversal_date: new Date().toLocaleDateString('sv-SE') } });
  };
  const handleReversal = async values => {
    requireWrite();
    const reason = values.reason?.trim();
    if (!reason) throw new Error(text('reasonRequired'));
    const row = reversalModal.row;
    await api.post(`${endpoint(row)}/${reversalModal.payment.id}/reversal`, {
      ...values, reason, idempotency_key: reversalModal.key,
    });
    setSuccess('reversalSaved');
    cache?.invalidateRelated('rent_charges', 'receivables', 'bookings');
    setRevision(value => value + 1);
    const request = ++historyRequest.current;
    try {
      const payments = await api.get(endpoint(row));
      setHistory(current => request === historyRequest.current && current?.row.id === row.id
        && current.row.entityType === row.entityType ? { ...current, payments, error: null, loading: false } : current);
    } catch (err) {
      setHistory(current => request === historyRequest.current && current?.row.id === row.id
        && current.row.entityType === row.entityType ? { ...current, error: err.message, loading: false } : current);
    }
  };
  const columns = [
    { key: 'contract_number', label: text('contract'), filterType: 'text' },
    { key: 'tenant_name', label: text('tenant'), filterType: 'text' },
    { key: 'unit_label', label: text('unit'), filterType: 'text' },
    { key: 'month', label: text('month'), filterType: 'text' },
    { key: 'total_due', label: text('totalReceivables'), type: 'number', render: fmt },
    { key: 'amount_paid', label: text('paid'), type: 'number', render: fmt },
    { key: 'remaining', label: text('open'), type: 'number', render: fmt },
    { key: 'status', label: text('status'), filterType: 'select', render: value => <StatusBadge status={value} /> },
    { key: 'actions', label: text('actions'), render: (_, row) => (
      <div className="rent-payment-actions">
        {canWrite && <button className="btn btn-sm btn-primary"
          disabled={row.remaining <= 0 || ['paid', 'cancelled', 'void'].includes(row.status)}
          onClick={() => startPayment(row)}>{text('recordPayment')}</button>}
        {canWrite && <button className="btn btn-sm btn-secondary"
          disabled={row.remaining <= 0 || ['paid', 'cancelled', 'void'].includes(row.status)}
          onClick={() => startPayment(row, 'bank')}>{text('allocateBooking')}</button>}
        <button className="btn btn-sm btn-secondary" onClick={event => showHistory(row, event)}>{text('history')}</button>
      </div>
    ) },
  ];
  const data = records[tab];
  // Separate ledger totals avoid counting an obligation in both tabs.
  const active = data.filter(row => !['cancelled', 'void'].includes(row.status));
  const sum = key => active.reduce((total, row) => total + row[key], 0);

  return (
    <div className="page finance-workspace">
      <div className="page-header finance-workspace-header"><div><h1>{text('title')}</h1><p>{text('description')}</p></div>
        <Link className="btn btn-primary finance-workspace-action" to="/rent-charges"><ReceiptText size={17} aria-hidden="true" />{text('manageCharges')}<ArrowUpRight size={16} aria-hidden="true" /></Link>
      </div>
      {success && <div role="status" className="alert alert-success">{text(success)}</div>}
      {error && <div role="alert" className="alert alert-error">{error} <button className="btn btn-secondary"
        onClick={() => setRevision(value => value + 1)}>{text('retry')}</button></div>}
      <div className="finance-workspace-controls">
        <div className="finance-workspace-tabs" role="tablist" aria-label={text('title')} aria-orientation="horizontal">
          {LEDGERS.map(type => <button key={type} type="button" role="tab" id={`rent-overview-tab-${type}`}
            ref={element => { tabButtons.current[type] = element; }} aria-selected={tab === type}
            aria-controls={`rent-overview-panel-${type}`} tabIndex={tab === type ? 0 : -1}
            className={`finance-workspace-tab ${tab === type ? 'active' : ''}`} onClick={() => setTab(type)}
            onKeyDown={event => handleTabKeyDown(event, type)}>
            {text(type === 'rent_charge' ? 'charges' : 'receivables')} <span>({records[type].length})</span>
          </button>)}
        </div>
        <label className="rent-open-filter finance-workspace-filter"><input type="checkbox" checked={onlyOpen}
          onChange={event => setOnlyOpen(event.target.checked)} /><span>{text('onlyOpen')}</span></label>
      </div>
      {LEDGERS.map(type => <div key={type} className="finance-workspace-panel" role="tabpanel"
        id={`rent-overview-panel-${type}`} aria-labelledby={`rent-overview-tab-${type}`} hidden={tab !== type}
        tabIndex={0} aria-busy={loading}>
        {tab === type && (loading ? <div className="page-loading finance-workspace-loading" role="status">{t('pages.loading')}</div> : !error && <>
          <div className="stats-grid rent-summary finance-workspace-summary">
            {[['totalReceivables', 'total_due', ReceiptText], ['paid', 'amount_paid', CircleCheck], ['open', 'remaining', Wallet]].map(([label, key, icon]) => {
              const Icon = icon;
              return <div className={`stat-card finance-workspace-stat ${key === 'remaining' ? 'finance-workspace-stat-open' : ''}`} key={key}>
                <div className="stat-label"><span>{text(label)}</span><Icon size={19} strokeWidth={1.6} aria-hidden="true" /></div>
                <div className="stat-value">{fmt(sum(key))}</div>
              </div>;
            })}
          </div>
          <DataTable title={text(type === 'rent_charge' ? 'charges' : 'receivables')} columns={columns}
            data={onlyOpen ? data.filter(row => row.remaining > 0 && !['paid', 'cancelled', 'void'].includes(row.status)) : data} />
        </>)}
      </div>)}
      {paymentModal?.kind === 'bank' && <BankPaymentModal row={paymentModal.row}
        onSave={handleRecordPayment} onClose={() => setPaymentModal(null)} />}
      {paymentModal?.kind === 'manual' && <FormModal title={`${text('recordPayment')} — ${paymentModal.row.tenant_name}`}
        fields={[
          { key: 'amount', label: text('paymentAmount'), type: 'number', required: true, min: 0.01, max: paymentModal.row.remaining },
          { key: 'payment_date', label: text('paymentDate'), type: 'date', required: true },
          { key: 'note', label: text('note'), type: 'textarea' },
        ]}
        initial={paymentModal.initial} onSave={handleRecordPayment} onClose={() => setPaymentModal(null)} />}
      {reversalModal && canWrite && <FormModal title={`${text('reversePayment')} — ${fmt(Number(reversalModal.payment.amount))}`}
        fields={[
          { key: 'reversal_date', label: text('reversalDate'), type: 'date', required: true },
          { key: 'reason', label: text('reversalReason'), type: 'textarea', required: true },
        ]} initial={reversalModal.initial} onSave={handleReversal} onClose={() => setReversalModal(null)}>
        <p>{text(reversalModal.payment.booking_id ? 'reverseAllocationHelp' : 'reversalHelp')}</p>
      </FormModal>}
      {history && <div className="rent-payment-history finance-workspace-history" role="region" aria-label={text('history')}
        ref={historyPanel} tabIndex={-1} aria-busy={history.loading}>
        <div className="page-header finance-workspace-history-header"><div><h2><History size={19} aria-hidden="true" />{text('history')} — {history.row.tenant_name} ({history.row.month})</h2>
          <p>{history.row.contract_number} · {history.row.unit_label}</p></div>
          <button className="btn btn-secondary" onClick={closeHistory}><X size={16} aria-hidden="true" />{t('ui.buttons.close')}</button></div>
        {history.loading ? <p className="finance-workspace-history-loading" role="status">{t('pages.loading')}</p> : history.error ? <div className="finance-workspace-history-error" role="alert"><p>{history.error}</p><button className="btn btn-secondary" onClick={() => showHistory(history.row)}>{text('retry')}</button></div>
          : <DataTable title={text('history')} data={history.payments} columns={[
            { key: 'payment_date', label: text('paymentDate'), type: 'date' },
            { key: 'amount', label: text('paymentAmount'), type: 'number', render: value => fmt(Number(value)) },
            { key: 'note', label: text('note') },
            { key: 'source', label: text('paymentSource'), render: (_, receipt) => text(receipt.booking_id ? 'bankLinked' : 'manualPayment') },
            { key: 'reversal', label: text('status'), render: value => value ? `${text('reversed')} · ${value.reversal_date} · ${value.reason}` : text('posted') },
            ...(canWrite ? [{ key: 'actions', label: text('actions'), render: (_, receipt) => !receipt.reversal
              && <button className="btn btn-sm btn-secondary" onClick={() => startReversal(receipt)}>{text('reversePayment')}</button> }] : []),
          ]} />}
      </div>}
    </div>
  );
}
