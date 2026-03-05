import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { useTranslation } from '../i18n';
import StatusBadge from '../components/StatusBadge';
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

  useEffect(() => {
    const safeFetch = (path, fallback) =>
      api.get(path).catch(err => {
        console.warn(`[Dashboard] Failed to load ${path}:`, err.message);
        return fallback;
      });

    Promise.all([
      safeFetch('/portfolios', []),
      safeFetch('/properties', []),
      safeFetch('/units', []),
      safeFetch('/tenants', []),
      safeFetch('/contracts', []),
      safeFetch('/accounts', []),
      safeFetch('/tasks?status=open&limit=5', []),
      safeFetch('/maintenance?status=open&limit=5', []),
      safeFetch('/notifications?status=unread&limit=5', []),
      safeFetch('/reports/cashflow', null),
      safeFetch('/reports/receivables-aging', null),
      safeFetch('/reports/occupancy', null),
      safeFetch('/reports/maintenance-costs', null),
      safeFetch('/reports/liquidity-forecast?months=6', null),
      safeFetch('/reports/contracts-expiring?days=90', null),
      safeFetch('/reports/finance', null),
    ]).then(([
      portfolios, properties, units, tenants, contracts, accounts,
      openTasks, maintenance, notifs,
      cf, ag, , mc, fc, exp, fin,
    ]) => {
      setStats({
        portfolios: portfolios.length,
        properties: properties.length,
        units: units.length,
        unitsOccupied: units.filter(u => u.status === 'occupied').length,
        unitsReserved: units.filter(u => u.status === 'reserved').length,
        tenants: tenants.length,
        contracts: contracts.length,
        contractsActive: contracts.filter(c => c.status === 'active').length,
        accounts: accounts.length,
        openMaintenance: maintenance.length,
      });
      setTasks(openTasks);
      setNotifications(notifs);
      setCashflow(cf);
      setAging(ag);
      setMaintCosts(mc);
      setForecast(fc);
      setExpiring(exp);
      setFinanceReport(fin);
    }).finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="page-loading">{t('ui.table.loading')}</div>;

  const occupancyRate = stats.units > 0
    ? Math.round((stats.unitsOccupied / stats.units) * 100)
    : 0;

  // Occupancy pie data
  const occupancyData = stats.units > 0 ? [
    { name: t('units.form.status.rented'), value: stats.unitsOccupied },
    { name: t('units.form.status.reserved'), value: stats.unitsReserved || 0 },
    { name: t('units.form.status.vacant'), value: stats.units - stats.unitsOccupied - (stats.unitsReserved || 0) },
  ].filter(d => d.value > 0) : [];

  // Cashflow bar data
  const cashflowData = cashflow ? [
    { name: t('dashboard.cashflow.income') || 'Einnahmen', value: cashflow.incomeTotal },
    { name: t('dashboard.cashflow.expenses') || 'Ausgaben', value: cashflow.expenseTotal },
    { name: t('dashboard.cashflow.net') || 'Netto', value: cashflow.netTotal },
  ] : [];

  // Aging bar data
  const agingData = aging ? [
    { name: t('dashboard.aging.current') || 'Aktuell', value: aging.buckets.current },
    { name: '1-30 T.', value: aging.buckets.days1to30 },
    { name: '31-60 T.', value: aging.buckets.days31to60 },
    { name: '61-90 T.', value: aging.buckets.days61to90 },
    { name: '90+ T.', value: aging.buckets.days90plus },
  ] : [];

  // Maintenance costs by category
  const maintData = maintCosts?.categories?.slice(0, 8) || [];

  // Liquidity forecast line data
  const forecastBalanceLabel = t('finance.accounts.balance') || 'Saldo';
  const forecastIncomeLabel = t('dashboard.cashflow.income') || 'Einnahmen';
  const forecastExpenseLabel = t('dashboard.cashflow.expenses') || 'Ausgaben';
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
      <h1 className="page-title">Dashboard</h1>

      {/* KPI Cards */}
      <div className="stats-grid">
        <StatCard icon={PortfolioIcon} label={t('portfolio.list.plural')} value={stats.portfolios} to="/portfolios" />
        <StatCard icon={PropertyIcon} label={t('properties.list.title')} value={stats.properties} to="/properties" />
        <StatCard icon={UnitIcon} label={t('units.list.title')} value={`${stats.unitsOccupied}/${stats.units}`} to="/units" color="stat-highlight" />
        <StatCard icon={TenantIcon} label={t('tenantsContracts.tenants.title')} value={stats.tenants} to="/tenants" />
        <StatCard icon={ContractIcon} label={t('tenantsContracts.contracts.title')} value={stats.contractsActive} to="/contracts" />
        <StatCard icon={AccountIcon} label={t('finance.accounts.title')} value={stats.accounts} to="/accounts" />
        <StatCard icon={MaintenanceIcon} label={t('dashboard.kpis.openMaintenanceCases')} value={stats.openMaintenance} to="/maintenance" color={stats.openMaintenance > 0 ? 'stat-warning' : ''} />
        <StatCard icon={ChartIcon} label={t('dashboard.kpis.occupancyRate')} value={`${occupancyRate}%`} to="/units" color="stat-highlight" />
      </div>

      {/* Charts Row 1 */}
      <div className="dashboard-charts">
        {/* Occupancy Pie */}
        <ChartPanel title={t('dashboard.widgets.vacancyByProperty')}>
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
          ) : <p className="chart-empty">{t('emptyStates.generic.title')}</p>}
        </ChartPanel>

        {/* Cashflow Bar */}
        <ChartPanel title={t('dashboard.kpis.cashflowMonthly')}>
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
          ) : <p className="chart-empty">{t('emptyStates.generic.title')}</p>}
        </ChartPanel>

        {/* Receivables Aging */}
        <ChartPanel title={t('finance.receivables.openReceivables')}>
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
          ) : <p className="chart-empty">{t('emptyStates.generic.title')}</p>}
        </ChartPanel>
      </div>

      {/* Charts Row 2 */}
      <div className="dashboard-charts">
        {/* Liquidity Forecast */}
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
          ) : <p className="chart-empty">{t('emptyStates.generic.title')}</p>}
        </ChartPanel>

        {/* Maintenance Costs by Category */}
        <ChartPanel title={t('reports.standard.maintenanceCosts')}>
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
          ) : <p className="chart-empty">{t('emptyStates.generic.title')}</p>}
        </ChartPanel>

        {/* Finance by Category */}
        <ChartPanel title={t('dashboard.widgets.costsByCategory')}>
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
          ) : <p className="chart-empty">{t('emptyStates.generic.title')}</p>}
        </ChartPanel>
      </div>

      {/* Activity Panels */}
      <div className="dashboard-panels">
        <div className="panel">
          <h3>{t('dashboard.widgets.tasksDue')}</h3>
          {tasks.length === 0 ? <p className="empty-text">{t('emptyStates.generic.title')}</p> : (
            <ul className="activity-list">
              {tasks.map(t => (
                <li key={t.id}>
                  <span className="activity-title">{t.title}</span>
                  {t.due_date && <span className="activity-date">{t.due_date}</span>}
                  <StatusBadge status={t.priority} />
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
                    {c.daysRemaining} Tage
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
          <h3>{t('topBar.notifications')}</h3>
          {notifications.length === 0 ? <p className="empty-text">{t('emptyStates.generic.title')}</p> : (
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
    </div>
  );
}
