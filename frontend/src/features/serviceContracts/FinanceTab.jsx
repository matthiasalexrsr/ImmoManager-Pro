import { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '../../api';
import { useTranslation } from '../../i18n';
import FormModal from '../../components/FormModal';
import { useConfirm } from '../../components/ConfirmDialog';
import { formatDate, formatMoney } from '../../utils/format';
import { yearWindow } from './model';

// Expectation (planned instalments), bills and payments of one contract, each counted once (see the backend).
export default function FinanceTab({ contract, canWrite, today }) {
  const { t } = useTranslation();
  const confirm = useConfirm();
  const thisYear = Number((today || new Date().toISOString()).slice(0, 4));
  const [year, setYear] = useState(thisYear);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [actionError, setActionError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [modal, setModal] = useState(null);     // existingBill | newBill | payment | transfer
  const [choices, setChoices] = useState({});
  const [revision, setRevision] = useState(0);
  const base = `/service-contracts/${encodeURIComponent(contract.id)}`;

  useEffect(() => {
    const controller = new AbortController();
    const range = new URLSearchParams(yearWindow(year));
    const options = { signal: controller.signal };
    setError(null);
    Promise.all([
      api.get(`${base}/reconciliation?${range}`, options),
      api.get(`${base}/invoices`, options),
      api.get(`${base}/payments`, options),
    ]).then(([reconciliation, bills, payments]) => setData({ reconciliation, bills, payments }))
      .catch(failure => { if (failure.name !== 'AbortError') setError(failure.message); });
    return () => controller.abort();
  }, [base, year, revision]);

  const reload = () => setRevision(value => value + 1);
  const run = async (action, done) => {
    setActionError(null);
    setNotice(null);
    try { await action(); if (done) setNotice(done); reload(); } catch (failure) { setActionError(failure.message); }
  };

  const open = useCallback(kind => {
    setModal(kind);
    setChoices({});
    if (kind === 'existingBill') {
      api.list('/invoices').then(invoices => setChoices({ invoices })).catch(() => setChoices({ invoices: [] }));
    } else if (kind === 'payment') {
      api.get(`${base}/payment-candidates?limit=200`).then(found => setChoices({ candidates: found.items || [] }))
        .catch(failure => setChoices({ candidates: [], error: failure.message }));
    } else if (kind === 'transfer') {
      const properties = new Set(contract.property_ids);
      Promise.all([api.list('/billing/periods'), api.list('/billing/allocation-keys'), api.list('/properties')])
        .then(([periods, keys, props]) => setChoices({
          periods: periods.filter(p => properties.has(p.property_id) && ['draft', 'review'].includes(p.status)),
          keys, names: Object.fromEntries(props.map(p => [p.id, p.name])) }))
        .catch(() => setChoices({ periods: [], keys: [], names: {} }));
    }
  }, [base, contract.property_ids]);

  const billFields = kind => {
    const period = [
      { key: 'kind', label: t('serviceContracts.fields.billKind'), type: 'select', default: 'regular', required: true,
        options: [{ value: 'regular', label: t('serviceContracts.billKinds.regular') },
          { value: 'settlement', label: t('serviceContracts.billKinds.settlement') }] },
      { key: 'period_start', label: t('serviceContracts.fields.periodStart'), type: 'date', required: true },
      { key: 'period_end', label: t('serviceContracts.fields.periodEnd'), type: 'date', required: true },
      { key: 'advances_credited', label: t('serviceContracts.fields.advancesCredited'), type: 'number',
        hint: t('serviceContracts.hints.advancesCredited') },
      { key: 'consumption', label: t('serviceContracts.fields.consumption'), type: 'number' },
      { key: 'consumption_unit', label: t('serviceContracts.fields.consumptionUnit'), placeholder: 'kWh' },
    ];
    if (kind === 'existingBill') {
      const linked = new Set((data?.bills || []).map(b => b.invoice_id));
      return [{ key: 'invoice_id', label: t('serviceContracts.fields.invoice'), type: 'select', required: true,
        options: (choices.invoices || []).filter(i => !linked.has(i.id)).map(i => ({ value: i.id,
          label: `${formatDate(i.invoice_date)} · ${i.supplier} · ${formatMoney(i.gross_amount)}${i.invoice_number ? ` · ${i.invoice_number}` : ''}` })) },
      ...period];
    }
    return [
      { key: 'invoice_number', label: t('serviceContracts.fields.invoiceNumber') },
      { key: 'invoice_date', label: t('serviceContracts.fields.invoiceDate'), type: 'date', required: true },
      { key: 'due_date', label: t('serviceContracts.fields.dueDate'), type: 'date' },
      { key: 'net_amount', label: t('serviceContracts.fields.net'), type: 'number', required: true },
      { key: 'vat_rate', label: t('serviceContracts.fields.vatRate'), type: 'number', default: 19 },
      { key: 'gross_amount', label: t('serviceContracts.fields.gross'), type: 'number', required: true,
        hint: t('serviceContracts.hints.gross') },
      ...period];
  };

  const saveBill = async values => {
    const shared = { kind: values.kind, period_start: values.period_start, period_end: values.period_end,
      advances_credited: values.kind === 'settlement' ? (values.advances_credited || 0) : 0,
      consumption: values.consumption ?? null, consumption_unit: values.consumption_unit || null };
    if (modal === 'existingBill') {
      await api.post(`${base}/invoices`, { ...shared, invoice_id: values.invoice_id });
    } else {
      const gross = Number(values.gross_amount);
      const net = Number(values.net_amount);
      await api.post(`${base}/invoices`, { ...shared, invoice: {
        supplier: contract.provider_name, invoice_number: values.invoice_number || null,
        invoice_date: values.invoice_date, due_date: values.due_date || null, net_amount: net,
        vat_rate: values.vat_rate ?? 19, vat_amount: Math.round((gross - net) * 100) / 100, gross_amount: gross,
        property_id: contract.property_ids.length === 1 ? contract.property_ids[0] : null } });
    }
    reload();
  };

  const paymentFields = useMemo(() => [
    { key: 'booking_id', label: t('serviceContracts.fields.booking'), type: 'select', required: true,
      hint: choices.error || t('serviceContracts.hints.candidates'),
      options: (choices.candidates || []).map(c => ({ value: c.booking_id,
        label: `${formatDate(c.booking_date)} · ${formatMoney(c.amount)} · ${c.payment_text || '—'}` })) },
    { key: 'amount', label: t('serviceContracts.fields.allocated'), type: 'number', hint: t('serviceContracts.hints.allocated') },
    { key: 'service_contract_invoice_id', label: t('serviceContracts.fields.forBill'), type: 'select',
      options: (data?.bills || []).map(b => ({ value: b.id, label: `${formatDate(b.invoice.invoice_date)} · ${formatMoney(b.invoice.gross_amount)}` })) },
  ], [t, choices, data]);

  const transferFields = useMemo(() => [
    { key: 'billing_period_id', label: t('serviceContracts.fields.billingPeriod'), type: 'select', required: true,
      clearOnChange: ['allocation_key_id'],
      options: (choices.periods || []).map(p => ({ value: p.id, label: `${p.label} · ${choices.names?.[p.property_id] || ''}` })) },
    { key: 'allocation_key_id', label: t('serviceContracts.fields.allocationKey'), type: 'select', required: true,
      options: values => {
        const period = (choices.periods || []).find(p => p.id === values.billing_period_id);
        return (choices.keys || []).filter(k => period && k.property_id === period.property_id).map(k => ({ value: k.id, label: k.name }));
      } },
  ], [t, choices]);

  const r = data?.reconciliation;
  const money = value => formatMoney(value ?? 0);
  const cards = r ? [
    ['expected', t('serviceContracts.figures.expected'), r.expected],
    ['invoiced', t('serviceContracts.figures.invoiced'), r.invoiced],
    ['credited', t('serviceContracts.figures.credited'), r.credited],
    ['paid', t('serviceContracts.figures.paid'), r.paid],
    ['open', t('serviceContracts.figures.open'), r.open],
    ['costs', t('serviceContracts.figures.costs'), r.costs],
  ] : [];

  return (
    <div className="sc-finance">
      <div className="sc-finance-toolbar">
        <label htmlFor="sc-year">{t('serviceContracts.year')}</label>
        <select id="sc-year" value={year} onChange={e => setYear(Number(e.target.value))}>
          {[thisYear + 1, thisYear, thisYear - 1, thisYear - 2, thisYear - 3].map(y => <option key={y} value={y}>{y}</option>)}
        </select>
        {canWrite && <>
          <button type="button" className="btn btn-sm btn-secondary" onClick={() => open('newBill')}>{t('serviceContracts.newBill')}</button>
          <button type="button" className="btn btn-sm btn-secondary" onClick={() => open('existingBill')}>{t('serviceContracts.linkBill')}</button>
          <button type="button" className="btn btn-sm btn-secondary" onClick={() => open('payment')}>{t('serviceContracts.linkPayment')}</button>
          {contract.recoverable && <button type="button" className="btn btn-sm btn-primary" onClick={() => open('transfer')}>
            {t('serviceContracts.transfer')}</button>}
        </>}
      </div>
      {error && <div role="alert" className="alert alert-error">{error}</div>}
      {actionError && <div role="alert" className="alert alert-error">{actionError}</div>}
      {notice && <div role="status" className="alert alert-info">{notice}</div>}
      {r?.partial && <p className="text-muted">{t('serviceContracts.partialFigures')}</p>}
      {r && <div className="stats-grid sc-figures" data-testid="sc-figures">
        {cards.map(([key, label, value]) => (
          <div key={key} className={`stat-card ${key === 'open' && value > 0 ? 'stat-warning' : ''}`}>
            <div className="stat-label">{label}</div><div className="stat-value">{money(value)}</div>
          </div>
        ))}
      </div>}
      <p className="text-muted sc-note">{t('serviceContracts.figuresNote')}</p>

      <section className="panel">
        <div className="panel-header">{t('serviceContracts.bills')}</div>
        <div className="panel-body">
          {!data?.bills?.length ? <p className="empty-text">{t('serviceContracts.noBills')}</p> : (
            <div className="dossier-table-scroll" role="region" aria-label={t('serviceContracts.bills')} tabIndex={0}>
              <table className="simple-table sc-table">
                <thead><tr>
                  <th>{t('serviceContracts.fields.invoiceDate')}</th><th>{t('serviceContracts.fields.servicePeriod')}</th>
                  <th className="text-right">{t('serviceContracts.fields.gross')}</th>
                  <th className="text-right">{t('serviceContracts.fields.advancesCredited')}</th>
                  <th className="text-right">{t('serviceContracts.figures.paid')}</th>
                  <th className="text-right">{t('serviceContracts.figures.open')}</th>
                  <th>{t('serviceContracts.fields.billing')}</th><th><span className="sr-only">{t('serviceContracts.actions')}</span></th>
                </tr></thead>
                <tbody>
                  {data.bills.map(bill => (
                    <tr key={bill.id}>
                      <td>{formatDate(bill.invoice.invoice_date)}<div className="text-muted sc-small">{bill.invoice.invoice_number || bill.invoice.supplier}</div></td>
                      <td>{formatDate(bill.period_start)} – {formatDate(bill.period_end)}</td>
                      <td className="text-right">{formatMoney(bill.invoice.gross_amount)}</td>
                      <td className="text-right">{bill.kind === 'settlement' ? formatMoney(bill.advances_credited) : '—'}
                        {bill.kind === 'settlement' && bill.planned_advances !== bill.advances_credited &&
                          <div className="text-muted sc-small">{t('serviceContracts.plannedAdvances', { amount: formatMoney(bill.planned_advances) })}</div>}</td>
                      <td className="text-right">{formatMoney(bill.paid)}</td>
                      <td className="text-right">{formatMoney(bill.open)}</td>
                      <td>{bill.transfers.length ? bill.transfers.map(tr => `${tr.billing_period_label}: ${formatMoney(tr.amount)}`).join('; ') : '—'}</td>
                      <td>{canWrite && <button type="button" className="btn btn-sm btn-danger"
                        aria-label={`${t('serviceContracts.remove')}: ${formatDate(bill.invoice.invoice_date)}`}
                        onClick={async () => { if (!confirm || await confirm(t('serviceContracts.confirmUnlinkBill'))) run(() => api.del(`${base}/invoices/${encodeURIComponent(bill.id)}`)); }}>
                        {t('serviceContracts.remove')}</button>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </section>

      <section className="panel">
        <div className="panel-header">{t('serviceContracts.payments')}</div>
        <div className="panel-body">
          {!data?.payments?.length ? <p className="empty-text">{t('serviceContracts.noPayments')}</p> : (
            <div className="dossier-table-scroll" role="region" aria-label={t('serviceContracts.payments')} tabIndex={0}>
              <table className="simple-table sc-table">
                <thead><tr>
                  <th>{t('serviceContracts.fields.bookingDate')}</th><th>{t('serviceContracts.fields.paymentText')}</th>
                  <th className="text-right">{t('serviceContracts.fields.allocated')}</th>
                  <th><span className="sr-only">{t('serviceContracts.actions')}</span></th>
                </tr></thead>
                <tbody>
                  {data.payments.map(payment => (
                    <tr key={payment.id}>
                      <td>{formatDate(payment.booking.booking_date)}</td>
                      <td className="sc-break">{payment.booking.payment_text || '—'}</td>
                      <td className="text-right">{formatMoney(payment.amount)}</td>
                      <td>{canWrite && <button type="button" className="btn btn-sm btn-danger"
                        aria-label={`${t('serviceContracts.remove')}: ${formatDate(payment.booking.booking_date)}`}
                        onClick={() => run(() => api.del(`${base}/payments/${encodeURIComponent(payment.id)}`))}>
                        {t('serviceContracts.remove')}</button>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </section>

      {r?.instalments?.length > 0 && (
        <details className="panel sc-instalments">
          <summary className="panel-header">{t('serviceContracts.instalments', { count: r.instalments.length })}</summary>
          <ul className="panel-body sc-instalment-list">
            {r.instalments.map(item => <li key={item.due_date}><span>{formatDate(item.due_date)}</span><span>{formatMoney(item.amount)}</span></li>)}
          </ul>
        </details>
      )}

      {(modal === 'newBill' || modal === 'existingBill') && <FormModal
        title={modal === 'newBill' ? t('serviceContracts.newBill') : t('serviceContracts.linkBill')}
        fields={billFields(modal)} onSave={saveBill} onClose={() => setModal(null)} />}
      {modal === 'payment' && <FormModal title={t('serviceContracts.linkPayment')} fields={paymentFields}
        onSave={async values => {
          await api.post(`${base}/payments`, { booking_id: values.booking_id, amount: values.amount ?? null,
            service_contract_invoice_id: values.service_contract_invoice_id || null });
          reload();
        }} onClose={() => setModal(null)} />}
      {modal === 'transfer' && <FormModal title={t('serviceContracts.transfer')} fields={transferFields}
        onSave={async values => {
          const result = await api.post(`${base}/cost-transfers`, values);
          setNotice(t('serviceContracts.transferDone', { created: result.created.length, skipped: result.skipped.length }));
          reload();
        }} onClose={() => setModal(null)} />}
    </div>
  );
}
