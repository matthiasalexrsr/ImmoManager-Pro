import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { useTranslation } from '../i18n';
import { useToast } from '../components/Toast';
import StatusBadge from '../components/StatusBadge';
import DashboardWorkflow from '../components/DashboardWorkflow';
import {
  PortfolioIcon, PropertyIcon, UnitIcon, TenantIcon,
  ContractIcon, AccountIcon, MaintenanceIcon, ChartIcon,
  ArrowRightIcon,
} from '../components/Icons';
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, Legend, LineChart, Line, CartesianGrid,
} from 'recharts';

const CHART_COLORS = ['#2563eb', '#16a34a', '#d97706', '#dc2626', '#8b5cf6', '#0891b2'];
const PIE_COLORS = ['#16a34a', '#d97706', '#e2e8f0']; // occupied, reserved, vacant

function StatCard({ icon, label, value, to, color }) {
  const Ico = icon;
  return (
    <Link to={to} className={`stat-card ${color || ''}`}>
      <div className="stat-icon">
        <Ico size={22} />
      </div>
      <div className="stat-info">
        <div className="stat-value">{value ?? '\u2014'}</div>
        <div className="stat-label">{label}</div>
      </div>
    </Link>
  );
}

function ChartPanel({ title, children }) {
  return (
    <div className="panel chart-panel">
      <div className="panel-header">{title}</div>
      <div className="panel-body chart-body">{children}</div>
    </div>
  );
}

function fmt(v) {
  return new Intl.NumberFormat('de-DE', { style: 'currency', currency: 'EUR' }).format(v);
}

function asArray(value) {
  return Array.isArray(value) ? value : [];
}

export default function Dashboard() {
  const { t } = useTranslation();
  const [stats, setStats] = useState({});
  const [tasks, setTasks] = useState([]);
  const [notifications, setNotifications] = useState([]);
  const [loading, setLoading] = useState(true);
  const [cashflow, setCashflow] = useState(null);
  const [aging, setAging] = useState(null);
  const [maintCosts, setMaintCosts] = useState(null);
  const [forecast, setForecast] = useState(null);
  const [expiring, setExpiring] = useState(null);
  const [financeReport, setFinanceReport] = useState(null);
  const [dashView, setDashView] = useState('work');
  const [auditOpen, setAuditOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const safeFetch = (path, fallback) =>
      api.get(path).catch(err => {
        console.warn(`[Dashboard] Failed to load ${path}:`, err.message);
        return fallback;
      });

    Promise.all([
      safeFetch('/dashboard/stats', {}),
      safeFetch('/tasks?status=open&limit=5', []),
      safeFetch('/notifications?status=unread&limit=5', []),
      safeFetch('/reports/cashflow', null),
      safeFetch('/reports/receivables-aging', null),
      safeFetch('/reports/maintenance-costs', null),
      safeFetch('/reports/liquidity-forecast?months=6', null),
      safeFetch('/reports/contracts-expiring?days=90', null),
      safeFetch('/reports/finance', null),
    ]).then(([
      dashStats,
      openTasks, notifs,
      cf, ag, mc, fc, exp, fin,
    ]) => {
      if (cancelled) return;
      const s = dashStats || {};
      setStats({
        portfolios: s.portfolio_count || 0,
        properties: s.property_count || 0,
        units: s.unit_count || 0,
        unitsOccupied: s.occupied_units || 0,
        unitsReserved: s.reserved_units || 0,
        tenants: s.tenant_count || 0,
        contracts: s.contract_count || 0,
        contractsActive: s.active_contracts || 0,
        accounts: s.account_count || 0,
        openMaintenance: s.open_maintenance || 0,
        invoices: s.invoice_count || 0,
        openInvoices: s.open_invoices || 0,
        paidInvoices: s.paid_invoices || 0,
        receivables: s.receivable_count || 0,
        openReceivables: s.open_receivables || 0,
        paidReceivables: s.paid_receivables || 0,
        overdueReceivables: s.overdue_receivables || 0,
        dunningReceivables: s.dunning_receivables || 0,
        documents: s.document_count || 0,
        missingContractDocuments: s.active_contracts_missing_documents || 0,
        overdueMaintenance: s.overdue_maintenance || 0,
        activeEscalationRules: s.active_escalation_rules || 0,
        maintenanceEscalationCandidates: s.maintenance_escalation_candidates || 0,
        tasks: s.task_count || 0,
        openTasks: s.open_tasks || 0,
        notifications: s.notification_count || 0,
        unreadNotifications: s.unread_notifications || 0,
        rentCharges: s.rent_charge_count || 0,
        openRentCharges: s.open_rent_charges || 0,
        overdueRentCharges: s.overdue_rent_charges || 0,
        billingPeriods: s.billing_period_count || 0,
        draftBillingPeriods: s.draft_billing_periods || 0,
        finalizedBillingPeriods: s.finalized_billing_periods || 0,
        billingPreflightPeriodsChecked: s.billing_preflight_periods_checked || 0,
        billingPreflightBlockers: s.billing_preflight_blockers || 0,
        billingPreflightWarnings: s.billing_preflight_warnings || 0,
        allocationKeys: s.allocation_key_count || 0,
        utilityStatements: s.utility_statement_count || 0,
        draftUtilityStatements: s.draft_utility_statements || 0,
        finalizedUtilityStatements: s.finalized_utility_statements || 0,
      });
      setTasks(asArray(openTasks));
      setNotifications(asArray(notifs));
      setCashflow(cf);
      setAging(ag);
      setMaintCosts(mc);
      setForecast(fc);
      setExpiring(exp);
      setFinanceReport(fin);
    }).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  if (loading) return <div className="page-loading">{t('pages.loading')}</div>;

  const occupancyRate = stats.units > 0
    ? Math.round((stats.unitsOccupied / stats.units) * 100)
    : 0;

  // Occupancy pie data
  const occupancyData = stats.units > 0 ? [
    { name: t('pages.dashboard.occupied'), value: stats.unitsOccupied },
    { name: t('pages.dashboard.reserved'), value: stats.unitsReserved || 0 },
    { name: t('pages.dashboard.vacant'), value: Math.max(0, stats.units - stats.unitsOccupied - (stats.unitsReserved || 0)) },
  ].filter(d => d.value > 0) : [];

  // Cashflow bar data
  const cashflowData = cashflow ? [
    { name: t('pages.dashboard.income'), value: cashflow.incomeTotal },
    { name: t('pages.dashboard.expenses'), value: cashflow.expenseTotal },
    { name: t('pages.dashboard.net'), value: cashflow.netTotal },
  ] : [];

  // Aging bar data
  const agingData = aging ? [
    { name: t('pages.dashboard.agingCurrent'), value: aging.buckets.current },
    { name: t('pages.dashboard.aging1to30'), value: aging.buckets.days1to30 },
    { name: t('pages.dashboard.aging31to60'), value: aging.buckets.days31to60 },
    { name: t('pages.dashboard.aging61to90'), value: aging.buckets.days61to90 },
    { name: t('pages.dashboard.aging90plus'), value: aging.buckets.days90plus },
  ] : [];

  // Maintenance costs by category
  const maintData = maintCosts?.categories?.slice(0, 8) || [];

  // Liquidity forecast line data
  const forecastBalanceLabel = t('pages.dashboard.balance');
  const forecastIncomeLabel = t('pages.dashboard.income');
  const forecastExpenseLabel = t('pages.dashboard.expenses');
  const forecastData = forecast?.forecast?.map(f => ({
    name: f.month,
    [forecastBalanceLabel]: f.projected_balance,
    [forecastIncomeLabel]: f.projected_income,
    [forecastExpenseLabel]: f.projected_expense,
  })) || [];

  // Finance by category (top 8)
  const financeData = financeReport?.totalsByCategory?.slice(0, 8).map(c => ({
    name: c.categoryName.length > 15 ? c.categoryName.slice(0, 15) + '...' : c.categoryName,
    value: Math.abs(c.total),
  })) || [];

  return (
    <div className="page">
      <h1 className="page-title">{t('pages.dashboard.title')}</h1>

      {/* Dashboard mode toggle */}
      <div className="tab-bar" style={{ marginBottom: '1.25rem' }}>
        <button
          className={`detail-tab ${dashView === 'work' ? 'active' : ''}`}
          onClick={() => setDashView('work')}
        >
          {t('pages.dashboard.workTab') || 'Arbeit'}
        </button>
        <button
          className={`detail-tab ${dashView === 'analysis' ? 'active' : ''}`}
          onClick={() => setDashView('analysis')}
        >
          {t('pages.dashboard.analysisTab') || 'Analyse'}
        </button>
      </div>

      {/* KPI Cards — always visible */}
      <div className="stats-grid">
        <StatCard icon={PortfolioIcon} label={t('pages.dashboard.portfolios')} value={stats.portfolios} to="/portfolios" />
        <StatCard icon={PropertyIcon} label={t('pages.dashboard.properties')} value={stats.properties} to="/properties" />
        <StatCard icon={UnitIcon} label={t('pages.dashboard.units')} value={`${stats.unitsOccupied}/${stats.units}`} to="/units" color="stat-highlight" />
        <StatCard icon={TenantIcon} label={t('pages.dashboard.tenants')} value={stats.tenants} to="/tenants" />
        <StatCard icon={ContractIcon} label={t('pages.dashboard.activeContracts')} value={stats.contractsActive} to="/contracts" />
        <StatCard icon={AccountIcon} label={t('pages.dashboard.accounts')} value={stats.accounts} to="/accounts" />
        <StatCard icon={MaintenanceIcon} label={t('pages.dashboard.openMaintenance')} value={stats.openMaintenance} to="/maintenance" color={stats.openMaintenance > 0 ? 'stat-warning' : ''} />
        <StatCard icon={ChartIcon} label={t('pages.dashboard.occupancy')} value={`${occupancyRate}%`} to="/units" color="stat-highlight" />
      </div>

      {dashView === 'work' && (
        <>
          <DashboardWorkflow
            stats={stats}
            aging={aging}
            expiring={expiring}
            notifications={notifications}
            t={t}
          />

          {/* Activity Panels */}
          <div className="dashboard-panels">
            <div className="panel">
              <h3>{t('pages.dashboard.openTasks')}</h3>
              {tasks.length === 0 ? <p className="empty-text">{t('pages.dashboard.noOpenTasks')}</p> : (
                <ul className="activity-list">
                  {tasks.map(tk => (
                    <li key={tk.id}>
                      <span className="activity-title">{tk.title}</span>
                      {tk.due_date && <span className="activity-date">{tk.due_date}</span>}
                      <StatusBadge status={tk.priority} />
                    </li>
                  ))}
                </ul>
              )}
              <Link to="/tasks" className="panel-link">
                {t('tasks.list.title')} <ArrowRightIcon size={14} />
              </Link>
            </div>

            <div className="panel">
              <h3>{t('dashboard.widgets.contractTerms')}</h3>
              {!expiring?.contracts?.length ? <p className="empty-text">{t('emptyStates.generic.title')}</p> : (
                <ul className="activity-list">
                  {expiring.contracts.slice(0, 5).map(c => (
                    <li key={c.contractId}>
                      <span className="activity-title">{c.contractNumber}</span>
                      <span className="activity-date">{c.endDate}</span>
                      <StatusBadge status={c.daysRemaining <= 30 ? 'overdue' : 'warning'} />
                      <span className="text-muted" style={{ fontSize: '0.75rem' }}>
                        {c.daysRemaining} {t('pages.dashboard.days')}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
              <Link to="/contracts" className="panel-link">
                {t('tenantsContracts.contracts.title')} <ArrowRightIcon size={14} />
              </Link>
            </div>

            <div className="panel">
              <h3>{t('pages.dashboard.notifications')}</h3>
              {notifications.length === 0 ? <p className="empty-text">{t('pages.dashboard.noNotifications')}</p> : (
                <ul className="activity-list">
                  {notifications.map(n => (
                    <li key={n.id}>
                      <span className="activity-title">{n.title}</span>
                      <StatusBadge status={n.severity} />
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </>
      )}

      {dashView === 'analysis' && (
        <>
          {/* Charts Row 1 */}
          <div className="dashboard-charts">
            <ChartPanel title={t('pages.dashboard.occupancyChart')}>
              {occupancyData.length > 0 ? (
                <ResponsiveContainer width="100%" height={220}>
                  <PieChart>
                    <Pie data={occupancyData} dataKey="value" nameKey="name"
                      cx="50%" cy="50%" innerRadius={50} outerRadius={80}
                      paddingAngle={2} label={({ name, value }) => `${name}: ${value}`}>
                      {occupancyData.map((_, i) => (
                        <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip formatter={v => v} />
                    <Legend />
                  </PieChart>
                </ResponsiveContainer>
              ) : <p className="chart-empty">{t('pages.dashboard.noUnits')}</p>}
            </ChartPanel>

            <ChartPanel title={t('pages.dashboard.cashflow')}>
              {cashflowData.length > 0 ? (
                <ResponsiveContainer width="100%" height={220}>
                  <BarChart data={cashflowData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="name" tick={{ fontSize: 12 }} />
                    <YAxis tick={{ fontSize: 11 }} tickFormatter={v => `${(v / 1000).toFixed(0)}k`} />
                    <Tooltip formatter={v => fmt(v)} />
                    <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                      {cashflowData.map((entry, i) => (
                        <Cell key={i} fill={entry.value >= 0 ? '#16a34a' : '#dc2626'} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              ) : <p className="chart-empty">{t('pages.dashboard.noBookings')}</p>}
            </ChartPanel>

            <ChartPanel title={t('pages.dashboard.receivablesAging')}>
              {agingData.some(d => d.value > 0) ? (
                <ResponsiveContainer width="100%" height={220}>
                  <BarChart data={agingData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                    <YAxis tick={{ fontSize: 11 }} tickFormatter={v => `${(v / 1000).toFixed(0)}k`} />
                    <Tooltip formatter={v => fmt(v)} />
                    <Bar dataKey="value" fill="#d97706" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              ) : <p className="chart-empty">{t('pages.dashboard.noReceivables')}</p>}
            </ChartPanel>
          </div>

          {/* Charts Row 2 */}
          <div className="dashboard-charts">
            <ChartPanel title={t('analyticsLabels.forecast')}>
              {forecastData.length > 0 ? (
                <ResponsiveContainer width="100%" height={220}>
                  <LineChart data={forecastData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                    <YAxis tick={{ fontSize: 11 }} tickFormatter={v => `${(v / 1000).toFixed(0)}k`} />
                    <Tooltip formatter={v => fmt(v)} />
                    <Legend />
                    <Line type="monotone" dataKey={forecastBalanceLabel} stroke="#2563eb" strokeWidth={2} dot={false} />
                    <Line type="monotone" dataKey={forecastIncomeLabel} stroke="#16a34a" strokeWidth={1} dot={false} strokeDasharray="4 2" />
                    <Line type="monotone" dataKey={forecastExpenseLabel} stroke="#dc2626" strokeWidth={1} dot={false} strokeDasharray="4 2" />
                  </LineChart>
                </ResponsiveContainer>
              ) : <p className="chart-empty">{t('pages.dashboard.noForecast')}</p>}
            </ChartPanel>

            <ChartPanel title={t('pages.dashboard.maintenanceCosts')}>
              {maintData.length > 0 ? (
                <ResponsiveContainer width="100%" height={220}>
                  <BarChart data={maintData} layout="vertical">
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis type="number" tick={{ fontSize: 11 }} tickFormatter={v => `${v.toFixed(0)} \u20AC`} />
                    <YAxis type="category" dataKey="category" tick={{ fontSize: 11 }} width={100} />
                    <Tooltip formatter={v => fmt(v)} />
                    <Bar dataKey="estimatedCost" fill="#8b5cf6" radius={[0, 4, 4, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              ) : <p className="chart-empty">{t('pages.dashboard.noMaintenanceCosts')}</p>}
            </ChartPanel>

            <ChartPanel title={t('pages.dashboard.financeByCategory')}>
              {financeData.length > 0 ? (
                <ResponsiveContainer width="100%" height={220}>
                  <PieChart>
                    <Pie data={financeData} dataKey="value" nameKey="name"
                      cx="50%" cy="50%" outerRadius={80}
                      label={({ name }) => name}>
                      {financeData.map((_, i) => (
                        <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip formatter={v => fmt(v)} />
                  </PieChart>
                </ResponsiveContainer>
              ) : <p className="chart-empty">{t('pages.dashboard.noFinanceData')}</p>}
            </ChartPanel>
          </div>
        </>
      )}

      {/* Recent Audit Log — collapsible */}
      <div className="panel" style={{ marginTop: '1.5rem' }}>
        <div
          className="panel-header"
          style={{ cursor: 'pointer', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}
          onClick={() => setAuditOpen(prev => !prev)}
        >
          <span>{t('pages.dashboard.recentActivity') || 'Letzte Aktivitäten'}</span>
          <span style={{ fontSize: '0.8rem', color: 'var(--color-text-muted)' }}>{auditOpen ? '▲' : '▼'}</span>
        </div>
        {auditOpen && <RecentAuditLog />}
      </div>
    </div>
  );
}

function RecentAuditLog() {
  const { t } = useTranslation();
  const [entries, setEntries] = useState([]);
  const toast = useToast();
  useEffect(() => {
    api.get('/audit?limit=10').then(data => setEntries(Array.isArray(data) ? data : data?.items || [])).catch(() => { toast.error(t('pages.dashboard.auditLoadError') || 'Audit-Log konnte nicht geladen werden'); });
  }, [toast, t]);

  const actionLabels = {
    create: t('pages.dashboard.auditCreated') || 'Erstellt',
    update: t('pages.dashboard.auditUpdated') || 'Aktualisiert',
    patch: t('pages.dashboard.auditChanged') || 'Geändert',
    delete: t('pages.dashboard.auditDeleted') || 'Gelöscht',
  };

  if (entries.length === 0) return <div className="panel-body"><p className="empty-text">{t('pages.dashboard.noActivity') || 'Keine Aktivitäten'}</p></div>;

  return (
    <div className="panel-body">
      <table style={{ width: '100%', fontSize: '0.85rem', borderCollapse: 'collapse' }}>
        <thead>
          <tr style={{ borderBottom: '1px solid var(--border-color)' }}>
            <th style={{ textAlign: 'left', padding: '4px 8px' }}>{t('pages.dashboard.auditAction') || 'Aktion'}</th>
            <th style={{ textAlign: 'left', padding: '4px 8px' }}>{t('pages.dashboard.auditArea') || 'Bereich'}</th>
            <th style={{ textAlign: 'left', padding: '4px 8px' }}>{t('pages.dashboard.auditUser') || 'Benutzer'}</th>
            <th style={{ textAlign: 'left', padding: '4px 8px' }}>{t('pages.dashboard.auditTime') || 'Zeitpunkt'}</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((e, i) => (
            <tr key={i} style={{ borderBottom: '1px solid var(--border-color)' }}>
              <td style={{ padding: '4px 8px' }}>
                <StatusBadge status={e.action === 'delete' ? 'cancelled' : e.action === 'create' ? 'active' : 'warning'} />
                {' '}{actionLabels[e.action] || e.action}
              </td>
              <td style={{ padding: '4px 8px' }}>{e.entity_type?.replace(/_/g, ' ')}</td>
              <td style={{ padding: '4px 8px' }}>{e.username || '—'}</td>
              <td style={{ padding: '4px 8px', color: 'var(--text-secondary)' }}>
                {e.timestamp ? new Date(e.timestamp).toLocaleString('de-DE') : '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
