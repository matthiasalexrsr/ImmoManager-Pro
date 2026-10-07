import { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { useTranslation } from '../i18n';
import StatusBadge from '../components/StatusBadge';
import DashboardWorkflow from '../components/DashboardWorkflow';
import { ArrowRightIcon } from '../components/Icons';
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, Legend, LineChart, Line, CartesianGrid,
} from 'recharts';
import { formatDate, formatDateTime, formatMoney, formatMoneyCompact, formatNumber } from '../utils/format';
import './dashboard.css';

const CHART_COLORS = ['var(--color-primary)', 'var(--color-success)', 'var(--color-warning)', 'var(--color-danger)', '#8b5cf6', '#0891b2'];
const PIE_COLORS = ['var(--color-primary)', 'var(--color-warning)', 'var(--color-border)'];
const FALLBACKS = {
  'pages.dashboard.occupancyChart': 'Belegung',
  'pages.dashboard.cashflow12': 'Zahlungsfluss · 12 Monate',
  'pages.dashboard.receivablesAging': 'Alter offener Forderungen',
  'analyticsLabels.forecast': 'Liquiditätsprognose',
  'pages.dashboard.maintenanceCosts': 'Instandhaltungskosten',
  'pages.dashboard.financeByCategory': 'Finanzen nach Kategorie',
  'pages.dashboard.occupied': 'Vermietet', 'pages.dashboard.reserved': 'Reserviert',
  'pages.dashboard.vacant': 'Frei', 'pages.dashboard.income': 'Einnahmen',
  'pages.dashboard.expenses': 'Ausgaben', 'pages.dashboard.net': 'Netto',
  'pages.dashboard.balance': 'Saldo', 'pages.dashboard.agingCurrent': 'Aktuell',
  'pages.dashboard.aging1to30': '1–30 Tage', 'pages.dashboard.aging31to60': '31–60 Tage',
  'pages.dashboard.aging61to90': '61–90 Tage', 'pages.dashboard.aging90plus': '90+ Tage',
  'pages.dashboard.noUnits': 'Noch keine Einheiten vorhanden.',
  'pages.dashboard.noBookings': 'Keine Buchungen vorhanden.',
  'pages.dashboard.noReceivables': 'Keine offenen Forderungen.',
  'pages.dashboard.noForecast': 'Keine Prognosedaten verfügbar.',
  'pages.dashboard.noMaintenanceCosts': 'Keine Instandhaltungskosten vorhanden.',
  'pages.dashboard.noFinanceData': 'Keine Finanzdaten vorhanden.',
};
const record = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const numeric = value => (typeof value === 'number' || (typeof value === 'string' && value.trim() !== '')) && Number.isFinite(Number(value));
const validStats = value => record(value) && ['property_count', 'unit_count', 'occupied_units', 'active_contracts'].every(key => numeric(value[key]) && Number(value[key]) >= 0);
const validCashflow = value => record(value) && ['incomeTotal', 'expenseTotal', 'netTotal'].every(key => numeric(value[key]));
const validAging = value => record(value) && numeric(value.openTotal) && record(value.buckets) && ['current', 'days1to30', 'days31to60', 'days61to90', 'days90plus'].every(key => numeric(value.buckets[key]));
const validContracts = value => record(value) && Array.isArray(value.contracts);
const validMaintenance = value => record(value) && Array.isArray(value.categories);
const validForecast = value => record(value) && Array.isArray(value.forecast);
const validFinance = value => record(value) && Array.isArray(value.totalsByCategory);
const validAudit = value => Array.isArray(value) || (record(value) && Array.isArray(value.items));
const asArray = value => Array.isArray(value) ? value : [];
const fmt = value => formatMoney(value);

function useDashboardSource(path, validate, enabled = true) {
  const [state, setState] = useState({ status: 'idle', data: null });
  const [revision, setRevision] = useState(0);
  const retry = useCallback(() => setRevision(value => value + 1), []);
  useEffect(() => {
    if (!enabled) return undefined;
    const request = new AbortController();
    async function load() {
      setState({ status: 'loading', data: null });
      try {
        const data = await api.get(path, { signal: request.signal });
        if (!validate(data)) throw new Error('Ungültige Dashboarddaten');
        if (!request.signal.aborted) setState({ status: 'success', data });
      } catch {
        if (!request.signal.aborted) setState({ status: 'error', data: null });
      }
    }
    load();
    return () => request.abort();
  }, [path, validate, enabled, revision]);
  return { ...state, retry };
}

function SourceState({ source, label, singular = false }) {
  if (source.status === 'success') return null;
  if (source.status === 'error') return (
    <div className="dashboard-source-error" role="alert">
      <span>{label} {singular ? 'konnte' : 'konnten'} nicht geladen werden.</span>
      <button type="button" onClick={source.retry}>Erneut versuchen</button>
    </div>
  );
  return <p className="dashboard-source-loading" role="status">{label} {singular ? 'wird' : 'werden'} geladen…</p>;
}

function ChartPanel({ title, source, label, singular = false, children }) {
  return <section className="dashboard-card dashboard-chart" aria-label={title}>
    <div className="dashboard-card-heading"><h2>{title}</h2></div>
    <SourceState source={source} label={label} singular={singular} />
    {source.status === 'success' && <div className="dashboard-chart-body">{children}</div>}
  </section>;
}

function Inventory({ source, stats }) {
  const known = source.status === 'success';
  const occupancy = known && stats.units > 0 ? Math.round(stats.unitsOccupied / stats.units * 100) : null;
  const metrics = [
    { label: 'Immobilien', value: stats.properties, detail: `${formatNumber(stats.portfolios)} Portfolios`, to: '/properties' },
    { label: 'Einheiten', value: stats.units, detail: `${formatNumber(stats.unitsOccupied)} vermietet · ${formatNumber(stats.unitsReserved)} reserviert`, to: '/units' },
    { label: 'Aktive Verträge', value: stats.contractsActive, detail: `${formatNumber(stats.tenants)} Parteien im Bestand`, to: '/contracts' },
    { label: 'Belegung', value: occupancy === null ? '—' : `${occupancy} %`, detail: stats.units > 0 ? `${formatNumber(Math.max(0, stats.units - stats.unitsOccupied - stats.unitsReserved))} freie Einheiten` : 'Noch keine Einheiten', to: '/units' },
  ];
  return <section className="dashboard-inventory" aria-label="Bestand im Überblick">
    <div className="dashboard-metrics">{metrics.map(metric => <Link key={metric.label} to={metric.to} className="dashboard-metric">
      <span>{metric.label}</span><strong>{known ? (typeof metric.value === 'number' ? formatNumber(metric.value) : metric.value) : '—'}</strong>
      <small>{known ? metric.detail : 'Noch nicht verfügbar'}</small>
    </Link>)}</div>
    <SourceState source={source} label="Bestandsdaten" />
  </section>;
}

function FinanceOverview({ cashflow, aging, stats, known }) {
  return <section className="dashboard-card dashboard-finance" aria-labelledby="dashboard-finance-heading">
    <div className="dashboard-card-heading"><h2 id="dashboard-finance-heading">Finanzen im Überblick</h2><span>Letzte 12 Monate</span></div>
    <SourceState source={cashflow} label="Zahlungsübersicht" singular />
    {cashflow.status === 'success' && <>
      <p className="dashboard-finance-label">Einnahmen abzüglich Ausgaben</p>
      <strong className={`dashboard-finance-total ${Number(cashflow.data.netTotal) < 0 ? 'is-negative' : ''}`}>{formatMoney(cashflow.data.netTotal)}</strong>
      <dl className="dashboard-finance-breakdown"><div><dt>Einnahmen</dt><dd>{formatMoney(cashflow.data.incomeTotal)}</dd></div><div><dt>Ausgaben</dt><dd>{formatMoney(cashflow.data.expenseTotal)}</dd></div></dl>
    </>}
    <div className="dashboard-finance-open"><SourceState source={aging} label="Forderungsübersicht" singular />
      {aging.status === 'success' && <Link to="/receivables"><span>Offene Forderungen <small>Aktueller Bestand · alle Fälligkeiten</small></span><strong>{formatMoney(aging.data.openTotal)}</strong><ArrowRightIcon size={16} /></Link>}
    </div>
    <div className="dashboard-card-footer"><Link to="/bookings">Buchungen ansehen <ArrowRightIcon size={14} /></Link><Link to="/accounts">{known ? `${formatNumber(stats.accounts)} Konten` : 'Konten'}</Link></div>
  </section>;
}

function ActivityCard({ title, source, sourceLabel, empty, to, linkLabel, children, subtitle }) {
  return <section className="dashboard-card dashboard-activity" aria-label={title}>
    <div className="dashboard-card-heading"><h2>{title}</h2>{subtitle && <span>{subtitle}</span>}</div>
    <SourceState source={source} label={sourceLabel} />
    {source.status === 'success' && (children || <p className="dashboard-empty">{empty}</p>)}
    <div className="dashboard-card-footer"><Link to={to}>{linkLabel} <ArrowRightIcon size={14} /></Link></div>
  </section>;
}

function normalizeStats(s) {
  return {
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
      };
}

export default function Dashboard() {
  const { t: translate, locale } = useTranslation();
  const t = (key, params) => {
    const value = translate(key, params);
    return !value || value === key ? (FALLBACKS[key] || key) : value;
  };
  const [dashView, setDashView] = useState('work');
  const [auditOpen, setAuditOpen] = useState(false);
  const inventory = useDashboardSource('/dashboard/stats', validStats);
  const taskSource = useDashboardSource('/tasks?status=open&limit=5', Array.isArray);
  const notificationSource = useDashboardSource('/notifications?status=unread&limit=5', Array.isArray);
  const cashflowSource = useDashboardSource('/reports/cashflow?months=12', validCashflow);
  const agingSource = useDashboardSource('/reports/receivables-aging', validAging);
  const expiringSource = useDashboardSource('/reports/contracts-expiring?days=90', validContracts);
  const maintenanceSource = useDashboardSource('/reports/maintenance-costs', validMaintenance, dashView === 'analysis');
  const forecastSource = useDashboardSource('/reports/liquidity-forecast?months=6', validForecast, dashView === 'analysis');
  const financeSource = useDashboardSource('/reports/finance', validFinance, dashView === 'analysis');
  const stats = inventory.status === 'success' ? normalizeStats(inventory.data) : {};
  const tasks = asArray(taskSource.data);
  const notifications = asArray(notificationSource.data);
  const cashflow = cashflowSource.data;
  const aging = agingSource.data;
  const expiring = expiringSource.data;
  const maintCosts = maintenanceSource.data;
  const forecast = forecastSource.data;
  const financeReport = financeSource.data;
  const now = new Date();
  const dateLabel = new Intl.DateTimeFormat(locale || 'de-DE', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' }).format(now);
  const isoDate = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
  const workflowProps = { stats, expiring, notifications, t, statsReady: inventory.status === 'success', complete: [inventory, expiringSource, notificationSource].every(source => source.status === 'success') };

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
    name: String(c.categoryName || 'Ohne Kategorie'),
    value: Math.abs(c.total),
  })) || [];


  return <div className="page dashboard-page">
    <header className="dashboard-header">
      <div><p className="dashboard-eyebrow">Ihr Arbeitsstart</p><h1>Verwaltungsübersicht</h1><p>Offene Vorgänge, Termine und Ihr Bestand an einem Ort.</p></div>
      <div className="dashboard-header-side"><time dateTime={isoDate}>{dateLabel}</time><Link to="/tasks" className="btn btn-primary">Aufgaben öffnen <ArrowRightIcon size={15} /></Link></div>
    </header>
    <div className="dashboard-view-switch" aria-label="Dashboardansichten">
      <button type="button" aria-pressed={dashView === 'work'} onClick={() => setDashView('work')}>Arbeit</button>
      <button type="button" aria-pressed={dashView === 'analysis'} onClick={() => setDashView('analysis')}>Analyse</button>
    </div>
    <Inventory source={inventory} stats={stats} />
    {dashView === 'work' && <>
      <div className="dashboard-start-grid"><DashboardWorkflow {...workflowProps} section="attention" /><FinanceOverview cashflow={cashflowSource} aging={agingSource} stats={stats} known={inventory.status === 'success'} /></div>
      <div className="dashboard-activity-grid">
        <ActivityCard title="Offene Aufgaben" source={taskSource} sourceLabel="Aufgaben" empty="Keine offenen Aufgaben." to="/tasks" linkLabel="Alle Aufgaben" subtitle="Bis zu fünf offene Einträge">
          {tasks.length > 0 && <ul className="dashboard-item-list">{tasks.map(task => <li key={task.id}><div><strong>{task.title}</strong><small>{task.due_date ? `Fällig am ${formatDate(task.due_date)}` : 'Ohne Fälligkeitsdatum'}</small></div><StatusBadge status={task.priority} /></li>)}</ul>}
        </ActivityCard>
        <ActivityCard title="Vertragsfristen" source={expiringSource} sourceLabel="Vertragsfristen" empty="Keine Vertragsenddaten in diesem Zeitraum." to="/contracts" linkLabel="Verträge öffnen" subtitle="Enddatum in den nächsten 90 Tagen">
          {expiring?.contracts.length > 0 && <ul className="dashboard-item-list">{expiring.contracts.slice(0, 5).map(contract => <li key={contract.contractId}><div><strong>{contract.contractNumber}</strong><small>{formatDate(contract.endDate)}</small></div><span className="dashboard-date-note">{contract.daysRemaining} Tage</span></li>)}</ul>}
        </ActivityCard>
        <ActivityCard title="Ungelesene Hinweise" source={notificationSource} sourceLabel="Hinweise" empty="Keine ungelesenen Hinweise." to="/messages" linkLabel="Alle Hinweise" subtitle="Bis zu fünf Einträge">
          {notifications.length > 0 && <ul className="dashboard-item-list">{notifications.map(item => <li key={item.id}><strong>{item.title}</strong><StatusBadge status={item.severity} /></li>)}</ul>}
        </ActivityCard>
      </div>
      <DashboardWorkflow {...workflowProps} section="areas" />
    </>}
      {dashView === 'analysis' && (
        <>
          {/* Charts Row 1 */}
          <div className="dashboard-charts">
            <ChartPanel title={t('pages.dashboard.occupancyChart')} source={inventory} label="Bestandsdaten">
              {occupancyData.length > 0 ? (
                <ResponsiveContainer width="100%" height={220}>
                  <PieChart>
                    <Pie data={occupancyData} dataKey="value" nameKey="name"
                      cx="50%" cy="50%" innerRadius={50} outerRadius={80}
                      paddingAngle={2}>
                      {occupancyData.map((_, i) => (
                        <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip formatter={v => v} />
                    <Legend formatter={(name, entry) => `${name}: ${entry?.payload?.value ?? ''}`} />
                  </PieChart>
                </ResponsiveContainer>
              ) : <p className="chart-empty">{t('pages.dashboard.noUnits')}</p>}
            </ChartPanel>

            <ChartPanel title={t('pages.dashboard.cashflow12')} source={cashflowSource} label="Zahlungsübersicht" singular>
              {cashflowData.length > 0 ? (
                <ResponsiveContainer width="100%" height={220}>
                  <BarChart data={cashflowData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="name" tick={{ fontSize: 12 }} />
                    <YAxis tick={{ fontSize: 11 }} tickFormatter={v => formatMoneyCompact(v)} width={72} />
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

            <ChartPanel title={t('pages.dashboard.receivablesAging')} source={agingSource} label="Forderungsübersicht" singular>
              {agingData.some(d => d.value > 0) ? (
                <ResponsiveContainer width="100%" height={220}>
                  <BarChart data={agingData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                    <YAxis tick={{ fontSize: 11 }} tickFormatter={v => formatMoneyCompact(v)} width={72} />
                    <Tooltip formatter={v => fmt(v)} />
                    <Bar dataKey="value" fill="#d97706" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              ) : <p className="chart-empty">{t('pages.dashboard.noReceivables')}</p>}
            </ChartPanel>
          </div>

          {/* Charts Row 2 */}
          <div className="dashboard-charts">
            <ChartPanel title={t('analyticsLabels.forecast')} source={forecastSource} label="Liquiditätsprognose" singular>
              {forecastData.length > 0 ? (
                <ResponsiveContainer width="100%" height={220}>
                  <LineChart data={forecastData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                    <YAxis tick={{ fontSize: 11 }} tickFormatter={v => formatMoneyCompact(v)} width={72} />
                    <Tooltip formatter={v => fmt(v)} />
                    <Legend />
                    <Line type="monotone" dataKey={forecastBalanceLabel} stroke="#2563eb" strokeWidth={2} dot={false} />
                    <Line type="monotone" dataKey={forecastIncomeLabel} stroke="#16a34a" strokeWidth={1} dot={false} strokeDasharray="4 2" />
                    <Line type="monotone" dataKey={forecastExpenseLabel} stroke="#dc2626" strokeWidth={1} dot={false} strokeDasharray="4 2" />
                  </LineChart>
                </ResponsiveContainer>
              ) : <p className="chart-empty">{t('pages.dashboard.noForecast')}</p>}
            </ChartPanel>

            <ChartPanel title={t('pages.dashboard.maintenanceCosts')} source={maintenanceSource} label="Instandhaltungskosten">
              {maintData.length > 0 ? (
                <ResponsiveContainer width="100%" height={220}>
                  <BarChart data={maintData} layout="vertical">
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis type="number" tick={{ fontSize: 11 }} tickFormatter={v => formatMoneyCompact(v)} />
                    <YAxis type="category" dataKey="category" tick={{ fontSize: 11 }} width={100} />
                    <Tooltip formatter={v => fmt(v)} />
                    <Bar dataKey="estimatedCost" fill="#8b5cf6" radius={[0, 4, 4, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              ) : <p className="chart-empty">{t('pages.dashboard.noMaintenanceCosts')}</p>}
            </ChartPanel>

            <ChartPanel title={t('pages.dashboard.financeByCategory')} source={financeSource} label="Finanzbericht" singular>
              {financeData.length > 0 ? (
                <ResponsiveContainer width="100%" height={220}>
                  <PieChart>
                    <Pie data={financeData} dataKey="value" nameKey="name"
                      cx="50%" cy="45%" outerRadius={70}>
                      {financeData.map((_, i) => (
                        <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip formatter={v => fmt(v)} />
                    <Legend iconSize={10} wrapperStyle={{ fontSize: 11 }} />
                  </PieChart>
                </ResponsiveContainer>
              ) : <p className="chart-empty">{t('pages.dashboard.noFinanceData')}</p>}
            </ChartPanel>
          </div>
        </>
      )}


    <section className="dashboard-audit">
      <button type="button" className="dashboard-audit-toggle" aria-expanded={auditOpen} aria-controls="dashboard-audit-content" onClick={() => setAuditOpen(value => !value)}><span>Letzte Aktivitäten</span><span aria-hidden="true">{auditOpen ? '−' : '+'}</span></button>
      {auditOpen && <div id="dashboard-audit-content"><RecentAuditLog /></div>}
    </section>
  </div>;
}

function RecentAuditLog() {
  const source = useDashboardSource('/audit?limit=10', validAudit);
  const entries = Array.isArray(source.data) ? source.data : source.data?.items || [];
  const labels = { create: 'Erstellt', update: 'Aktualisiert', patch: 'Geändert', delete: 'Gelöscht' };
  return <>
    <SourceState source={source} label="Aktivitäten" />
    {source.status === 'success' && (entries.length ? <div className="dashboard-audit-scroll"><table><thead><tr><th>Aktion</th><th>Bereich</th><th>Benutzer</th><th>Zeitpunkt</th></tr></thead><tbody>{entries.map((entry, index) => <tr key={entry.id || index}><td>{labels[entry.action] || entry.action}</td><td>{entry.entity_type?.replace(/_/g, ' ')}</td><td>{entry.username || '—'}</td><td>{formatDateTime(entry.timestamp)}</td></tr>)}</tbody></table></div> : <p className="dashboard-empty">Keine Aktivitäten vorhanden.</p>)}
  </>;
}
