import { useEffect, useState } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import { parseSettlementSummary } from '../utils/billingSettlements';
import DataTable from './DataTable';
import CreditJournal from './CreditJournal';

/** Read-only settlement ledger: credits are available, not evidence of a payout. */
export default function BillingSettlementSummary({ period, contracts = {}, refreshKey = 0 }) {
  const { t, locale } = useTranslation();
  const [retry, setRetry] = useState(0);
  const [credit, setCredit] = useState(null);
  const [creditBusy, setCreditBusy] = useState(false);
  const [state, setState] = useState({ key: null, data: null, error: null });
  const periodId = period.id;
  const requestKey = `${periodId}:${refreshKey}:${retry}`;
  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;
    setState({ key: requestKey, data: null, error: null });
    api.get(`/billing/periods/${periodId}/settlements`, { signal })
      .then(body => {
        if (signal.aborted) return;
        const data = parseSettlementSummary(body, periodId);
        setState({ key: requestKey, data, error: null });
      })
      .catch(error => {
        if (!signal.aborted) setState({ key: requestKey, data: null, error });
      });
    return () => controller.abort();
  }, [periodId, requestKey]);

  const text = key => t(`pages.statements.settlements.${key}`);
  const current = state.key === requestKey ? state : { data: null, error: null };
  const { data, error } = current;
  const loading = !data && !error;
  const money = amount => new Intl.NumberFormat(locale, { style: 'currency', currency: 'EUR' }).format(amount);
  const rows = data?.settlements.map(row => ({ ...row,
    contract_label: contracts[row.contract_id]?.contract_number || row.contract_id,
  })) || [];
  const columns = [
    { key: 'contract_label', label: text('contract'), filterType: 'text' },
    { key: 'signed_amount', label: text(period.source_period_id ? 'delta' : 'amount'),
      type: 'number', align: 'right', render: money },
    { key: 'status', label: t('ui.form.status'), render: value => text(`status.${value}`) },
    { key: 'receivable_id', label: text('reference'), render: (value, row) => value
      ? `${text(row.kind === 'credit' ? 'historicalReference' : 'receivable')}: ${value}` : '—' },
    { key: 'credit_action', label: t('pages.statements.credits.title'), render: (_, row) =>
      <button type="button" className="btn btn-secondary" disabled={creditBusy} onClick={() => setCredit({ periodId, contractId: row.contract_id, sourceId: row.kind === 'credit' ? row.id : null })}>{t('pages.statements.credits.title')}</button> },
  ];

  return <section className="card billing-settlement-summary" aria-label={text('title')} style={{ marginBottom: '1rem', minWidth: 0 }}>
    <div className="card-header"><h2>{text('title')}</h2></div>
    <div className="card-body">
      {Number.isInteger(period.revision_number) && <p>{text('revision')}: {period.revision_number}</p>}
      {period.source_period_id && <p style={{ overflowWrap: 'anywhere' }}>{text('sourcePeriod')}: {period.source_period_id}</p>}
      {period.revision_notes && <p style={{ overflowWrap: 'anywhere' }}>{text('revisionNotes')}: {period.revision_notes}</p>}
      {period.source_period_id && <p>{text('deltaHelp')}</p>}
      {loading && <p role="status">{t('ui.table.loading')}</p>}
      {error && <>
        <div className="alert-error" role="alert">{error.code === 'INVALID_SETTLEMENT_RESPONSE'
          ? text('invalidResponse') : error.message || text('loadFailed')}</div>
        <button className="btn btn-secondary" onClick={() => setRetry(value => value + 1)}>{t('ui.buttons.retry')}</button>
      </>}
      {data && <>
        <div className="stats-grid" aria-label={text('totals')}>
          <div className="stat-card"><div className="stat-label">{text('debts')}</div>
            <div className="stat-value">{money(data.debts_total)}</div></div>
          <div className="stat-card"><div className="stat-label">{text('credits')}</div>
            <div className="stat-value">{money(data.credits_total)}</div></div>
          <div className="stat-card"><div className="stat-label">{text('net')}</div>
            <div className="stat-value">{money(data.net_amount)}</div></div>
        </div>
        <p>{text('notPaidOut')}</p>
        {rows.length ? <DataTable title={text('entries')} data={rows} columns={columns} /> : <p>{text('empty')}</p>}
        {credit?.periodId === periodId && <CreditJournal key={`${periodId}:${credit.contractId}`} {...credit} onBusyChange={setCreditBusy} onClose={() => setCredit(null)} />}
      </>}
    </div>
  </section>;
}
