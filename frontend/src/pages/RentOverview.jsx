import { useState, useEffect } from 'react';
import { api } from '../api';
import DataTable from '../components/DataTable';
import StatusBadge from '../components/StatusBadge';
import { useTranslation } from '../i18n';

const COLUMNS = [
  { key: 'contract_number', label: 'Vertrag', filterType: 'text' },
  { key: 'tenant_name', label: 'Mieter', filterType: 'text' },
  { key: 'unit_label', label: 'Einheit', filterType: 'text' },
  { key: 'due_date', label: 'Fällig', type: 'date', filterType: 'dateRange' },
  { key: 'amount_due', label: 'Forderung (€)', type: 'number', align: 'right', filterType: 'numberRange',
    render: v => v != null ? `${Number(v).toFixed(2)} €` : '—' },
  { key: 'amount_paid', label: 'Bezahlt (€)', type: 'number', align: 'right',
    render: v => v != null ? `${Number(v).toFixed(2)} €` : '—' },
  { key: 'remaining', label: 'Offen (€)', type: 'number', align: 'right',
    render: (v, row) => {
      const remaining = (row.amount_due || 0) - (row.amount_paid || 0);
      const cls = remaining > 0 ? 'text-red' : remaining < 0 ? 'text-green' : '';
      return <span className={cls}>{remaining.toFixed(2)} €</span>;
    }},
  { key: 'status', label: 'Status', type: 'status', filterType: 'select' },
];

export default function RentOverview() {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);
  const { t } = useTranslation();
  const [error, setError] = useState(null);

  useEffect(() => {
    Promise.all([
      api.get('/receivables').catch(() => []),
      api.get('/contracts').catch(() => []),
      api.get('/tenants').catch(() => []),
      api.get('/units').catch(() => []),
    ]).then(([receivables, contracts, tenants, units]) => {
      const contractMap = Object.fromEntries(contracts.map(c => [c.id, c]));
      const tenantMap = Object.fromEntries(tenants.map(t => [t.id, t]));
      const unitMap = Object.fromEntries(units.map(u => [u.id, u]));

      const enriched = receivables.map(r => {
        const contract = contractMap[r.contract_id] || {};
        const tenant = tenantMap[contract.tenant_id] || {};
        const unit = unitMap[contract.unit_id] || {};
        return {
          ...r,
          contract_number: contract.contract_number || '—',
          tenant_name: tenant.full_name || '—',
          unit_label: unit.label || '—',
          remaining: (r.amount_due || 0) - (r.amount_paid || 0),
        };
      });
      setData(enriched);
    }).catch(e => setError(e.message)).finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="page-loading">{t('pages.loading')}</div>;
  if (error) return <div className="page"><div className="alert alert-error">{error}</div></div>;

  const totalDue = data.reduce((s, r) => s + (r.amount_due || 0), 0);
  const totalPaid = data.reduce((s, r) => s + (r.amount_paid || 0), 0);
  const totalOpen = totalDue - totalPaid;
  const overdueCount = data.filter(r => r.status === 'overdue').length;

  return (
    <div className="page">
      <div className="stats-grid" style={{ marginBottom: '1rem' }}>
        <div className="stat-card">
          <div className="stat-label">{t('pages.rentOverview.totalReceivables')}</div>
          <div className="stat-value">{totalDue.toFixed(2)} €</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">{t('pages.rentOverview.paid')}</div>
          <div className="stat-value text-green">{totalPaid.toFixed(2)} €</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">{t('pages.rentOverview.open')}</div>
          <div className="stat-value text-red">{totalOpen.toFixed(2)} €</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">{t('pages.rentOverview.overdue')}</div>
          <div className="stat-value">{overdueCount} <StatusBadge status="overdue" /></div>
        </div>
      </div>
      <DataTable title={t('pages.rentOverview.title')} columns={COLUMNS} data={data} />
    </div>
  );
}
