import { useEffect, useState } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import { parseOwnerCostShare } from '../utils/billingOwnerShare';
import DataTable from './DataTable';

/** Saved landlord allocation, never a tenant receivable or an available credit. */
export default function BillingOwnerShare({ periodId, refreshKey = '', units = {} }) {
  const { t, locale } = useTranslation();
  const [retry, setRetry] = useState(0);
  const [state, setState] = useState({ key: null, loading: true, data: null, error: null });
  const requestKey = `${periodId}:${refreshKey}:${retry}`;
  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;
    setState({ key: requestKey, loading: true, data: null, error: null });
    api.get(`/billing/periods/${periodId}`, { signal }).then(body => {
      if (signal.aborted) return;
      const data = parseOwnerCostShare(body, periodId);
      setState({ key: requestKey, loading: false, data, error: null });
    }).catch(error => {
      if (!signal.aborted) setState({ key: requestKey, loading: false, data: null, error });
    });
    return () => controller.abort();
  }, [periodId, requestKey]);
  const text = key => t(`pages.statements.ownerShare.${key}`);
  const money = amount => new Intl.NumberFormat(locale, { style: 'currency', currency: 'EUR' }).format(amount);
  const current = state.key === requestKey ? state : { loading: true, data: null, error: null };
  const { data, loading, error } = current;
  const rows = data?.line_items.map(row => ({ ...row, unit_label: units[row.unit_id]?.label || row.unit_id || '—' })) || [];
  const columns = [
    { key: 'description', label: t('ui.form.description') },
    { key: 'unit_label', label: text('unit') },
    { key: 'reason', label: text('reason'), render: value => text(value) },
    { key: 'allocated_amount', label: text('amount'), render: money, align: 'right', type: 'number' },
  ];
  const totals = [['total_amount', 'total'], ['recoverable_vacancy_amount', 'vacancy'],
    ['non_recoverable_amount', 'nonRecoverable'], ['property_cost_total', 'propertyCosts'], ['tenant_cost_total', 'tenantCosts']];
  return <section className="card billing-owner-share" aria-label={text('title')} style={{ marginBottom: '1rem', minWidth: 0 }}>
    <div className="card-header"><h2>{text('title')}</h2></div>
    <div className="card-body">
      <p>{text('notTenantDebt')}</p>
      {loading && <p role="status">{t('ui.table.loading')}</p>}
      {error && <>
        <div className="alert-error" role="alert">{error.code === 'INVALID_OWNER_SHARE'
          ? text('invalidResponse') : error.message || text('loadFailed')}</div>
        <button className="btn btn-secondary" onClick={() => setRetry(value => value + 1)}>{t('ui.buttons.retry')}</button>
      </>}
      {!loading && !error && !data && <p>{text('notCalculated')}</p>}
      {data && <>
        <p>{text('snapshotHelp')}</p>
        <div className="stats-grid">
          {totals.map(([key, label]) => <div className="stat-card" key={key}>
            <div className="stat-label">{text(label)}</div><div className="stat-value">{money(data[key])}</div>
          </div>)}
        </div>
        {Object.keys(data.vacant_unit_days).length > 0 && <div>
          <h3>{text('vacantDays')}</h3>
          <dl>{Object.entries(data.vacant_unit_days).map(([unitId, days]) => <div key={unitId}>
            <dt style={{ overflowWrap: 'anywhere' }}>{units[unitId]?.label || unitId}</dt><dd>{days}</dd>
          </div>)}</dl>
        </div>}
        {rows.length > 0 && <DataTable title={text('lineItems')} data={rows} columns={columns} />}
      </>}
    </div>
  </section>;
}
