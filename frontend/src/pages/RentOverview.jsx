import { useState, useEffect } from 'react';
import { api } from '../api';
import DataTable from '../components/DataTable';
import StatusBadge from '../components/StatusBadge';
import { useTranslation } from '../i18n';
import { useAuth } from '../contexts/AuthContext';
import { useDataStore } from '../contexts/DataStoreContext';
import FormModal from '../components/FormModal';

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
  const auth = useAuth();
  const cache = useDataStore();
  const [records, setRecords] = useState({ rent_charge: [], receivable: [] });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [revision, setRevision] = useState(0);
  const [tab, setTab] = useState('rent_charge');
  const [paymentModal, setPaymentModal] = useState(null);
  const [history, setHistory] = useState(null);
  const [success, setSuccess] = useState(false);
  const [onlyOpen, setOnlyOpen] = useState(true);

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
  const startPayment = row => {
    setSuccess(false);
    const now = new Date();
    const localDate = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
    setPaymentModal({ row, key: crypto.randomUUID(), initial: { amount: row.remaining, payment_date: localDate } });
  };
  const handleRecordPayment = async values => {
    await api.post(endpoint(paymentModal.row), { ...values, idempotency_key: paymentModal.key });
    setSuccess(true);
    cache?.invalidateRelated('rent_charges', 'receivables');
    setRevision(value => value + 1);
  };
  const showHistory = async row => {
    setHistory({ row, loading: true, payments: [] });
    try {
      const payments = await api.get(endpoint(row));
      setHistory(current => current?.row.id === row.id ? { row, payments, loading: false } : current);
    } catch (err) {
      setHistory(current => current?.row.id === row.id ? { row, error: err.message, payments: [], loading: false } : current);
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
        {!auth?.isReadonly && <button className="btn btn-sm btn-primary"
          disabled={row.remaining <= 0 || ['paid', 'cancelled', 'void'].includes(row.status)}
          onClick={() => startPayment(row)}>{text('recordPayment')}</button>}
        <button className="btn btn-sm btn-secondary" onClick={() => showHistory(row)}>{text('history')}</button>
      </div>
    ) },
  ];
  const data = records[tab];
  // Separate ledger totals avoid counting an obligation in both tabs.
  const active = data.filter(row => !['cancelled', 'void'].includes(row.status));
  const sum = key => active.reduce((total, row) => total + row[key], 0);

  return (
    <div className="page">
      <div className="page-header"><div><h1>{text('title')}</h1><p>{text('description')}</p></div></div>
      <div className="tab-bar" role="tablist" aria-label={text('title')}>
        {['rent_charge', 'receivable'].map(type => <button key={type} role="tab" aria-selected={tab === type}
          className={`detail-tab ${tab === type ? 'active' : ''}`} onClick={() => setTab(type)}>
          {text(type === 'rent_charge' ? 'charges' : 'receivables')} ({records[type].length})
        </button>)}
      </div>
      <label className="rent-open-filter"><input type="checkbox" checked={onlyOpen}
        onChange={event => setOnlyOpen(event.target.checked)} /> {text('onlyOpen')}</label>
      {success && <div role="status" className="alert alert-success">{text('paymentSaved')}</div>}
      {error && <div role="alert" className="alert alert-error">{error} <button className="btn btn-secondary"
        onClick={() => setRevision(value => value + 1)}>{text('retry')}</button></div>}
      {loading ? <div className="page-loading">{t('pages.loading')}</div> : !error && <>
        <div className="stats-grid rent-summary">
          {[['totalReceivables', 'total_due'], ['paid', 'amount_paid'], ['open', 'remaining']].map(([label, key]) => (
            <div className="stat-card" key={key}><div className="stat-label">{text(label)}</div>
              <div className="stat-value">{fmt(sum(key))}</div></div>
          ))}
        </div>
        <DataTable title={text(tab === 'rent_charge' ? 'charges' : 'receivables')} columns={columns}
          data={onlyOpen ? data.filter(row => row.remaining > 0 && !['paid', 'cancelled', 'void'].includes(row.status)) : data} />
      </>}
      {paymentModal && <FormModal title={`${text('recordPayment')} — ${paymentModal.row.tenant_name}`}
        fields={[
          { key: 'amount', label: text('paymentAmount'), type: 'number', required: true, min: 0.01, max: paymentModal.row.remaining },
          { key: 'payment_date', label: text('paymentDate'), type: 'date', required: true },
          { key: 'note', label: text('note'), type: 'textarea' },
        ]}
        initial={paymentModal.initial} onSave={handleRecordPayment} onClose={() => setPaymentModal(null)} />}
      {history && <div className="rent-payment-history" role="region" aria-label={text('history')}>
        <div className="page-header"><h2>{text('history')} — {history.row.tenant_name} ({history.row.month})</h2>
          <button className="btn btn-secondary" onClick={() => setHistory(null)}>{t('ui.buttons.close')}</button></div>
        {history.loading ? <p>{t('pages.loading')}</p> : history.error ? <p role="alert">{history.error}</p>
          : <DataTable title={text('history')} data={history.payments} columns={[
            { key: 'payment_date', label: text('paymentDate'), type: 'date' },
            { key: 'amount', label: text('paymentAmount'), render: value => fmt(Number(value)) },
            { key: 'note', label: text('note') },
          ]} />}
      </div>}
    </div>
  );
}
