import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowUpRight, Building2, Home, Wallet, FileCheck2, RefreshCw, Clock3, Bell, Wrench, CheckSquare, Plus, ChevronDown, Layers3 } from 'lucide-react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, PieChart, Pie, Cell, Legend, LineChart, Line, CartesianGrid } from 'recharts';
import { api } from '../api';
import { useAuth } from '../contexts/AuthContext';
import { useTranslation } from '../i18n';
import './Dashboard.css';

const colors = ['var(--chart-1, #28776f)', 'var(--chart-2, #365f87)', 'var(--chart-3, #8b611d)', 'var(--chart-4, #96758e)', 'var(--chart-5, #708478)', 'var(--chart-6, #b34746)'];
const finite = value => typeof value === 'number' && Number.isFinite(value);
const count = value => Number.isInteger(value) && value >= 0;
const near = (a, b) => Math.abs(a - b) <= .011;
const bucketKeys = ['current', 'days1to30', 'days31to60', 'days61to90', 'days90plus'];
const statKeys = ['portfolio_count', 'property_count', 'unit_count', 'tenant_count', 'active_contracts', 'account_count', 'open_maintenance', 'overdue_maintenance', 'document_count', 'open_tasks', 'unread_notifications', 'open_rent_charges', 'overdue_rent_charges', 'open_receivables', 'overdue_receivables', 'draft_billing_periods', 'billing_preflight_blockers'];
const list = (data, validate) => Array.isArray(data) && data.every(item => item && typeof item === 'object' && validate(item));
const notificationTarget = item => {
  const routes = { property: '/properties', unit: '/units', contract: '/contracts', tenant: '/tenants', receivable: '/receivables', rent_charge: '/rent-charges', task: '/tasks', maintenance: '/maintenance', invoice: '/invoices', document: '/documents', billing_period: '/statements' };
  const path = routes[item.entity_type];
  return path && item.entity_id && ['property', 'unit'].includes(item.entity_type) ? `${path}/${encodeURIComponent(item.entity_id)}` : path;
};
const titled = item => typeof item.id === 'string' && typeof item.title === 'string';
const sourceConfig = {
  stats: { path: '/dashboard/stats', valid: data => data && statKeys.every(key => count(data[key])) },
  units: { path: '/units', all: true, valid: data => list(data, item => typeof item.id === 'string' && typeof item.status === 'string') },
  tasks: { path: '/tasks?status=open&limit=5&sort_by=due_date&sort_order=asc', valid: data => list(data, titled) },
  notifications: { path: '/notifications?status=unread&limit=5', valid: data => list(data, titled) },
  cashflow: { path: '/reports/cashflow', valid: data => data && ['incomeTotal', 'expenseTotal', 'netTotal'].every(key => finite(data[key])) && data.incomeTotal >= 0 && data.expenseTotal >= 0 && near(data.incomeTotal - data.expenseTotal, data.netTotal) },
  aging: { path: '/reports/receivables-aging', valid: data => data && finite(data.openTotal) && data.openTotal >= 0 && bucketKeys.every(key => finite(data.buckets?.[key]) && data.buckets[key] >= 0) && near(bucketKeys.reduce((sum, key) => sum + data.buckets[key], 0), data.openTotal) },
  maintenance: { path: '/reports/maintenance-costs', valid: data => data && count(data.openCases) && finite(data.totalEstimatedCost) && list(data.categories, item => typeof item.category === 'string' && finite(item.estimatedCost)) && near(data.categories.reduce((sum, item) => sum + item.estimatedCost, 0), data.totalEstimatedCost) },
  forecast: { path: '/reports/liquidity-forecast?months=6', valid: data => data && finite(data.current_balance) && list(data.forecast, item => /^\d{4}-\d{2}$/.test(item.month) && ['projected_balance', 'projected_income', 'projected_expense'].every(key => finite(item[key]))) },
  expiring: { path: '/reports/contracts-expiring?days=90', valid: data => data && count(data.count) && list(data.contracts, item => typeof item.contractId === 'string' && typeof item.contractNumber === 'string' && typeof item.endDate === 'string' && count(item.daysRemaining)) && data.count === data.contracts.length },
  finance: { path: '/reports/finance', valid: data => data && finite(data.uncategorizedTotal) && finite(data.bookingsTotal) && list(data.totalsByCategory, item => typeof item.categoryName === 'string' && finite(item.total)) && near(data.totalsByCategory.reduce((sum, item) => sum + item.total, data.uncategorizedTotal), data.bookingsTotal) },
  audit: { path: '/audit?limit=10', lazy: true, valid: data => list(Array.isArray(data) ? data : data?.items, item => typeof item.action === 'string') },
};

function useDashboardSources(t) {
  const [sources, setSources] = useState(() => Object.fromEntries(Object.keys(sourceConfig).map(key => [key, { status: 'idle', data: null, error: null }])));
  const controllers = useRef({});
  const mounted = useRef(false);
  const reload = useCallback(async key => {
    controllers.current[key]?.abort();
    const controller = new AbortController();
    controllers.current[key] = controller;
    setSources(previous => ({ ...previous, [key]: { status: 'loading', data: null, error: null } }));
    try {
      const config = sourceConfig[key];
      const data = await (config.all ? api.getAll : api.get)(config.path, { signal: controller.signal });
      if (!config.valid(data)) throw new Error(t('dashboardHome.invalidResponse'));
      if (mounted.current && !controller.signal.aborted) setSources(previous => ({ ...previous, [key]: { status: 'ready', data, error: null, loadedAt: new Date() } }));
    } catch (error) {
      if (mounted.current && !controller.signal.aborted) setSources(previous => ({ ...previous, [key]: { status: 'error', data: null, error: error.message || t('dashboardHome.loadError') } }));
    }
  }, [t]);
  useEffect(() => {
    mounted.current = true;
    Object.entries(sourceConfig).filter(([, config]) => !config.lazy).forEach(([key]) => { void reload(key); });
    const requests = controllers.current;
    return () => { mounted.current = false; Object.values(requests).forEach(controller => controller.abort()); };
  }, [reload]);
  const reloadAll = () => Object.keys(sourceConfig).filter(key => !sourceConfig[key].lazy || sources[key].status !== 'idle').forEach(key => { void reload(key); });
  return { sources, reload, reloadAll };
}

function SourceState({ source, name, onRetry, t }) {
  if (source.status === 'ready') return null;
  if (source.status !== 'error') return <p className="dashboard-home-state" role="status">{t('dashboardHome.loading')} <span>{name}</span></p>;
  return <div className="dashboard-home-state dashboard-home-error" role="alert"><div><strong>{name}: {t('dashboardHome.loadError')}</strong><p>{source.error}</p></div><button className="btn btn-secondary btn-sm" onClick={onRetry}><RefreshCw size={15} aria-hidden="true" />{t('dashboardHome.retry')}</button></div>;
}

function Metric({ icon, label, value, hint, to, action, pending }) {
  const Icon = icon;
  return <article className="dashboard-home-metric" aria-label={label} aria-busy={pending}><div className="dashboard-home-metric-label"><span>{label}</span><Icon size={19} aria-hidden="true" /></div><strong>{value ?? '—'}</strong><p>{hint}</p><Link to={to}>{action}<ArrowUpRight size={15} aria-hidden="true" /></Link></article>;
}

function ValuesTable({ title, rows, headers, t }) {
  return <details className="dashboard-home-values"><summary>{t('dashboardHome.chartValues')}</summary><div className="dashboard-home-table-scroll" tabIndex={0} role="region" aria-label={`${title}: ${t('dashboardHome.chartValues')}`}><table><caption>{title}</caption><thead><tr>{headers.map(header => <th key={header} scope="col">{header}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={index}>{row.map((value, cell) => cell === 0 ? <th key={cell} scope="row">{value}</th> : <td key={cell}>{value}</td>)}</tr>)}</tbody></table></div></details>;
}

function ReportChart({ kind, rows, format, series }) {
  if (kind === 'line') return <ResponsiveContainer width="100%" height={240}><LineChart data={rows}><CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" /><XAxis dataKey="name" tick={{ fontSize: 11 }} /><YAxis tick={{ fontSize: 11 }} /><Tooltip formatter={format} /><Legend />{series.map((name, index) => <Line key={name} dataKey={`values.${index}`} name={name} stroke={colors[index]} strokeWidth={index ? 1 : 2} dot={false} isAnimationActive={false} strokeDasharray={index ? '4 2' : undefined} />)}</LineChart></ResponsiveContainer>;
  const data = rows.map(row => ({ name: row.name, value: row.values[0] }));
  if (kind === 'pie') return <ResponsiveContainer width="100%" height={240}><PieChart><Pie data={data.filter(row => row.value > 0)} dataKey="value" nameKey="name" innerRadius={50} outerRadius={80} isAnimationActive={false}>{data.filter(row => row.value > 0).map((_, index) => <Cell key={index} fill={colors[index % colors.length]} />)}</Pie><Tooltip formatter={format} /><Legend /></PieChart></ResponsiveContainer>;
  const horizontal = kind === 'horizontal';
  return <ResponsiveContainer width="100%" height={240}><BarChart data={data} layout={horizontal ? 'vertical' : 'horizontal'}><CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" /><XAxis type={horizontal ? 'number' : 'category'} dataKey={horizontal ? undefined : 'name'} tick={{ fontSize: 11 }} /><YAxis type={horizontal ? 'category' : 'number'} dataKey={horizontal ? 'name' : undefined} width={horizontal ? 100 : 60} tick={{ fontSize: 11 }} /><Tooltip formatter={format} /><Bar dataKey="value" isAnimationActive={false} radius={horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0]}>{data.map((row, index) => <Cell key={index} fill={row.value < 0 ? colors[5] : colors[index % colors.length]} />)}</Bar></BarChart></ResponsiveContainer>;
}

function Report({ title, hint, source, onRetry, rows, chartRows = rows, headers, kind, format, t }) {
  return <section className="dashboard-home-panel dashboard-home-report" aria-label={title}><header><h2>{title}</h2><p>{hint}</p></header><SourceState source={source} name={title} onRetry={onRetry} t={t} />{source.status === 'ready' && (rows.length ? <><div className="dashboard-home-chart" aria-hidden="true">{chartRows.length ? <ReportChart rows={chartRows} kind={kind} format={format} series={headers.slice(1)} /> : <p className="dashboard-home-empty">{t('dashboardHome.noCategoryBalances')}</p>}</div><ValuesTable title={title} rows={rows.map(row => [row.name, ...row.values.map(format)])} headers={headers} t={t} /></> : <p className="dashboard-home-empty">{t('dashboardHome.noReportRows')}</p>)}</section>;
}

export default function Dashboard() {
  const { t, locale } = useTranslation();
  const { isReadonly, isAdmin } = useAuth() || {};
  const { sources, reload, reloadAll } = useDashboardSources(t);
  const [view, setView] = useState('work');
  const [auditOpen, setAuditOpen] = useState(false);
  const ready = key => sources[key].status === 'ready';
  const stats = sources.stats.data;
  const money = value => finite(value) ? new Intl.NumberFormat(locale, { style: 'currency', currency: 'EUR' }).format(value) : '—';
  const integer = value => count(value) ? new Intl.NumberFormat(locale).format(value) : '—';
  const date = value => value && !Number.isNaN(Date.parse(value)) ? new Intl.DateTimeFormat(locale).format(new Date(value.includes('T') ? value : `${value}T00:00:00`)) : t('dashboardHome.noDueDate');
  const units = sources.units.data || [];
  const occupied = units.filter(unit => ['occupied', 'rented'].includes(unit.status)).length;
  const reserved = units.filter(unit => unit.status === 'reserved').length;
  const vacant = units.filter(unit => unit.status === 'vacant').length;
  const other = units.length - occupied - reserved - vacant;
  const occupancyRate = ready('units') && units.length ? Math.round(occupied / units.length * 100) : null;
  const occupancyRows = [
    { name: t('pages.dashboard.occupied'), values: [occupied] },
    { name: t('pages.dashboard.reserved'), values: [reserved] },
    { name: t('pages.dashboard.vacant'), values: [vacant] },
    { name: t('dashboardHome.otherUnitStatuses'), values: [other] },
  ];
  const aging = sources.aging.data;
  const agedAmount = ready('aging') ? bucketKeys.slice(1).reduce((sum, key) => sum + aging.buckets[key], 0) : null;
  const cashflow = sources.cashflow.data;
  const cashflowRows = ready('cashflow') ? ['income', 'expenses', 'net'].map((key, index) => ({ name: t(`pages.dashboard.${key}`), values: [cashflow[['incomeTotal', 'expenseTotal', 'netTotal'][index]]] })) : [];
  const agingRows = ready('aging') ? ['agingCurrent', 'aging1to30', 'aging31to60', 'aging61to90', 'aging90plus'].map((key, index) => ({ name: t(`pages.dashboard.${key}`), values: [aging.buckets[bucketKeys[index]]] })) : [];
  const maintenanceRows = sources.maintenance.data?.categories.map(item => ({ name: item.category, values: [item.estimatedCost] })) || [];
  const categoryRows = sources.finance.data?.totalsByCategory.map(item => ({ name: item.categoryName, values: [item.total] })) || [];
  const financeRows = ready('finance') ? [...categoryRows, { name: t('dashboardHome.uncategorized'), values: [sources.finance.data.uncategorizedTotal] }, { name: t('dashboardHome.bookingTotal'), values: [sources.finance.data.bookingsTotal] }] : [];
  const financePie = categoryRows.slice(0, 8).map(item => ({ ...item, values: [Math.abs(item.values[0])] })).filter(item => item.values[0] > 0);
  const forecastRows = sources.forecast.data?.forecast.map(item => ({ name: item.month, values: [item.projected_balance, item.projected_income, item.projected_expense] })) || [];
  const priorities = [];
  if (agedAmount > 0) priorities.push({ key: 'overdue', to: '/rent-overview', icon: Wallet, title: t('dashboardHome.overdueTitle'), hint: t('dashboardHome.obligationScope'), value: money(agedAmount), tone: 'urgent' });
  if (ready('stats') && stats.overdue_maintenance > 0) priorities.push({ key: 'overdueMaintenance', to: '/maintenance', icon: Wrench, title: t('dashboardHome.overdueMaintenance'), hint: t('dashboardHome.maintenanceHint'), value: integer(stats.overdue_maintenance), tone: 'urgent' });
  if (ready('stats') && stats.billing_preflight_blockers > 0) priorities.push({ key: 'blockers', to: '/statements', icon: FileCheck2, title: t('dashboardHome.billingTitle'), hint: t('dashboardHome.billingHint'), value: integer(stats.billing_preflight_blockers), tone: 'attention' });
  if (ready('stats') && stats.open_rent_charges + stats.overdue_rent_charges > 0) priorities.push({ key: 'payments', to: '/rent-charges', icon: Wallet, title: t('dashboardHome.paymentsTitle'), hint: t('dashboardHome.paymentsHint'), value: integer(stats.open_rent_charges + stats.overdue_rent_charges), tone: 'attention' });
  if (ready('stats') && stats.open_tasks > 0) priorities.push({ key: 'tasks', to: '/tasks', icon: CheckSquare, title: t('pages.dashboard.openTasks'), hint: t('dashboardHome.taskHint'), value: integer(stats.open_tasks) });
  if (ready('units') && vacant > 0) priorities.push({ key: 'vacancy', to: '/units', icon: Home, title: t('dashboardHome.vacancyTitle'), hint: t('dashboardHome.vacancyHint'), value: integer(vacant) });
  if (ready('maintenance') && sources.maintenance.data.openCases > 0 && !priorities.some(item => item.key === 'overdueMaintenance')) priorities.push({ key: 'maintenance', to: '/maintenance', icon: Wrench, title: t('dashboardHome.maintenanceTitle'), hint: t('dashboardHome.maintenanceHint'), value: integer(sources.maintenance.data.openCases) });
  if (ready('stats') && stats.draft_billing_periods > 0 && !priorities.some(item => item.key === 'blockers')) priorities.push({ key: 'drafts', to: '/statements', icon: FileCheck2, title: t('dashboardHome.draftBilling'), hint: t('dashboardHome.draftBillingHint'), value: integer(stats.draft_billing_periods) });
  const prioritySources = ['stats', 'units', 'aging', 'maintenance'];
  const tasks = [...(sources.tasks.data || [])].sort((a, b) => String(a.due_date || '9999').localeCompare(String(b.due_date || '9999')));
  const panels = [
    { key: 'tasks', title: t('pages.dashboard.openTasks'), to: '/tasks', icon: CheckSquare, empty: t('pages.dashboard.noOpenTasks'), hint: t('dashboardHome.previewLimit') },
    { key: 'expiring', title: t('dashboardHome.next90Days'), to: '/contracts', icon: Clock3, empty: t('dashboardHome.noExpiring'), hint: t('dashboardHome.contractScope') },
    { key: 'notifications', title: t('pages.dashboard.notifications'), to: null, icon: Bell, empty: t('pages.dashboard.noNotifications'), hint: t('dashboardHome.previewLimit') },
  ];
  const inventory = [['portfolio_count', '/portfolios', 'pages.dashboard.portfolios'], ['property_count', '/properties', 'pages.dashboard.properties'], ['unit_count', '/units', 'pages.dashboard.units'], ['tenant_count', '/tenants', 'pages.dashboard.tenants'], ['active_contracts', '/contracts', 'pages.dashboard.activeContracts'], ['account_count', '/accounts', 'pages.dashboard.accounts'], ['open_maintenance', '/maintenance', 'pages.dashboard.openMaintenance'], ['document_count', '/documents', 'dashboardHome.documents']];
  const sourceName = key => t(`dashboardHome.sources.${key}`);
  const reportProps = key => ({ source: sources[key], onRetry: () => reload(key), t });
  const headings = [t('dashboardHome.category'), t('dashboardHome.amount')];
  const activateView = (event, next) => {
    if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) {
      event.preventDefault();
      const target = event.key === 'Home' ? 'work' : event.key === 'End' ? 'analysis' : next;
      setView(target);
      document.getElementById(`dashboard-home-tab-${target}`)?.focus();
    }
  };

  return <div className="page dashboard-home">
    <header className="dashboard-home-heading"><div><span className="dashboard-home-eyebrow">{t('dashboardHome.workspace')}</span><h1>{t('dashboardHome.title')}</h1><p>{t('dashboardHome.intro')}</p></div><div className="dashboard-home-refresh"><button className="btn btn-secondary" onClick={reloadAll}><RefreshCw size={16} aria-hidden="true" />{t('dashboardHome.refresh')}</button>{ready('stats') && <small>{t('dashboardHome.loadedAt', { time: new Intl.DateTimeFormat(locale, { hour: '2-digit', minute: '2-digit' }).format(sources.stats.loadedAt) })}</small>}</div></header>
    <SourceState source={sources.stats} name={sourceName('stats')} onRetry={() => reload('stats')} t={t} />
    <section className="dashboard-home-metrics" aria-label={t('dashboardHome.keyFigures')}>
      <Metric icon={Building2} label={t('pages.dashboard.properties')} value={ready('stats') ? integer(stats.property_count) : null} hint={ready('stats') ? t('dashboardHome.portfolioCount', { count: integer(stats.portfolio_count) }) : t('dashboardHome.unavailable')} to="/properties" action={t('dashboardHome.openInventory')} pending={sources.stats.status === 'loading'} />
      <Metric icon={Home} label={t('dashboardHome.occupiedUnits')} value={ready('units') ? `${integer(occupied)} / ${integer(units.length)}` : null} hint={occupancyRate == null ? t('dashboardHome.noOccupancy') : t('dashboardHome.occupancyRate', { count: occupancyRate })} to="/units" action={t('dashboardHome.openUnits')} pending={sources.units.status === 'loading'} />
      <Metric icon={Wallet} label={t('dashboardHome.openAmount')} value={ready('aging') ? money(aging.openTotal) : null} hint={t('dashboardHome.obligationScope')} to="/rent-overview" action={t('dashboardHome.openPayments')} pending={sources.aging.status === 'loading'} />
      <Metric icon={FileCheck2} label={t('dashboardHome.draftBilling')} value={ready('stats') ? integer(stats.draft_billing_periods) : null} hint={t('dashboardHome.draftBillingHint')} to="/statements" action={t('dashboardHome.openBilling')} pending={sources.stats.status === 'loading'} />
    </section>
    {['units', 'aging'].filter(key => sources[key].status === 'error').map(key => <SourceState key={key} source={sources[key]} name={sourceName(key)} onRetry={() => reload(key)} t={t} />)}
    {ready('stats') && stats.portfolio_count === 0 && <section className="dashboard-home-start"><Layers3 size={25} aria-hidden="true" /><div><h2>{t('dashboardHome.startTitle')}</h2><p>{t('dashboardHome.startHint')}</p></div><Link className="btn btn-primary" to="/portfolios">{t('dashboardHome.openPortfolios')}<ArrowUpRight size={16} aria-hidden="true" /></Link></section>}
    <nav className="dashboard-home-tabs" role="tablist" aria-label={t('dashboardHome.view')}>{['work', 'analysis'].map((key, index) => <button id={`dashboard-home-tab-${key}`} key={key} role="tab" aria-selected={view === key} aria-controls={`dashboard-home-panel-${key}`} tabIndex={view === key ? 0 : -1} onClick={() => setView(key)} onKeyDown={event => activateView(event, index === 0 ? 'analysis' : 'work')}>{t(key === 'work' ? 'dashboardHome.workTab' : 'dashboardHome.analysisTab')}</button>)}</nav>
    <section role="tabpanel" id={`dashboard-home-panel-${view}`} aria-labelledby={`dashboard-home-tab-${view}`} tabIndex={0}>
      {view === 'work' && <>
        <div className="dashboard-home-work-grid"><section className="dashboard-home-panel dashboard-home-priorities" aria-label={t('dashboardHome.priorities')}><header><div><span className="dashboard-home-eyebrow">{t('dashboardHome.nextSteps')}</span><h2>{t('dashboardHome.priorities')}</h2></div><p>{t('dashboardHome.prioritiesHint')}</p></header><div className="dashboard-home-priority-list">{priorities.map(item => { const Icon = item.icon; return <Link key={item.key} to={item.to} className={`dashboard-home-priority ${item.tone || ''}`}><span className="dashboard-home-action-icon"><Icon size={19} aria-hidden="true" /></span><span><strong>{item.title}</strong><small>{item.hint}</small></span><b>{item.value}</b><ArrowUpRight size={17} aria-hidden="true" /></Link>; })}</div>{!priorities.length && prioritySources.every(ready) && <p className="dashboard-home-empty">{t('dashboardHome.noPriorities')}</p>}{!prioritySources.every(ready) && <p className="dashboard-home-caption">{t('dashboardHome.prioritiesIncomplete')}</p>}<Link className="dashboard-home-text-link" to="/calendar">{t('dashboardHome.calendar')}<ArrowUpRight size={15} aria-hidden="true" /></Link></section>
          <aside className="dashboard-home-panel dashboard-home-quick" aria-label={t('dashboardHome.quickActions')}><header><h2>{t('dashboardHome.quickActions')}</h2><p>{t(isReadonly ? 'dashboardHome.readonlyHint' : 'dashboardHome.quickHint')}</p></header><Link to="/properties"><Building2 size={19} aria-hidden="true" />{t('dashboardHome.openInventory')}<ArrowUpRight size={15} aria-hidden="true" /></Link><Link to="/bookings"><Wallet size={19} aria-hidden="true" />{t('dashboardHome.reviewBookings')}<ArrowUpRight size={15} aria-hidden="true" /></Link><Link to="/tasks"><CheckSquare size={19} aria-hidden="true" />{t('dashboardHome.openTasks')}<ArrowUpRight size={15} aria-hidden="true" /></Link>{isAdmin && !isReadonly && <Link className="dashboard-home-create" to="/contract-wizard"><Plus size={19} aria-hidden="true" />{t('dashboardHome.createContract')}<ArrowUpRight size={15} aria-hidden="true" /></Link>}</aside></div>
        <div className="dashboard-home-activity-grid">{panels.map(panel => { const Icon = panel.icon; const rows = panel.key === 'tasks' ? tasks : panel.key === 'expiring' ? sources.expiring.data?.contracts || [] : sources.notifications.data || []; return <section className="dashboard-home-panel" key={panel.key} aria-label={panel.title}><header><div className="dashboard-home-panel-title"><Icon size={19} aria-hidden="true" /><h2>{panel.title}</h2></div><p>{panel.hint}</p></header><SourceState source={sources[panel.key]} name={panel.title} onRetry={() => reload(panel.key)} t={t} />{ready(panel.key) && (rows.length ? <ul className="dashboard-home-activity-list">{rows.slice(0, 5).map(row => <li key={row.id || row.contractId}>{panel.key === 'notifications' ? (notificationTarget(row) ? <Link to={notificationTarget(row)}>{row.title}</Link> : <strong>{row.title}</strong>) : <Link to={panel.to}>{panel.key === 'expiring' ? row.contractNumber : row.title}</Link>}<span>{panel.key === 'expiring' ? `${date(row.endDate)} · ${t('dashboardHome.remainingDays', { count: row.daysRemaining })}` : panel.key === 'tasks' ? date(row.due_date) : t(`dashboardHome.severity.${row.severity}`) === `dashboardHome.severity.${row.severity}` ? row.severity : t(`dashboardHome.severity.${row.severity}`)}</span>{panel.key === 'tasks' && row.priority && <small className="dashboard-home-priority-label">{t(`dashboardHome.priority.${row.priority}`) === `dashboardHome.priority.${row.priority}` ? row.priority : t(`dashboardHome.priority.${row.priority}`)}</small>}</li>)}</ul> : <p className="dashboard-home-empty">{panel.empty}</p>)}<>{panel.to ? <Link className="dashboard-home-text-link" to={panel.to}>{t('dashboardHome.all')}<ArrowUpRight size={14} aria-hidden="true" /></Link> : <p className="dashboard-home-caption">{t('dashboardHome.notificationHint')}</p>}</></section>; })}</div>
        <section className="dashboard-home-panel dashboard-home-inventory" aria-label={t('dashboardHome.inventory')}><header><h2>{t('dashboardHome.inventory')}</h2><p>{t('dashboardHome.liveData')}</p></header><div>{inventory.map(([key, to, label]) => <Link to={to} key={key}><span>{t(label)}</span><strong>{ready('stats') ? integer(stats[key]) : '—'}</strong><ArrowUpRight size={15} aria-hidden="true" /></Link>)}</div></section>
        <details className="dashboard-home-panel dashboard-home-workflows"><summary>{t('dashboardHome.workflows')}<ChevronDown size={17} aria-hidden="true" /></summary><p>{t('dashboardHome.workflowHint')}</p><div>{[['/properties', 'dashboardHome.openInventory'], ['/units', 'dashboardHome.openUnits'], ['/contracts', 'dashboardHome.openContracts'], ['/rent-charges', 'dashboardHome.openPayments'], ['/statements', 'dashboardHome.openBilling'], ['/maintenance', 'dashboardHome.maintenanceTitle']].map(([to, label]) => <Link key={to} to={to}>{t(label)}<ArrowUpRight size={14} aria-hidden="true" /></Link>)}</div></details>
      </>}
      {view === 'analysis' && <div className="dashboard-home-reports">
        <Report title={t('pages.dashboard.occupancyChart')} hint={t('dashboardHome.occupancyScope')} {...reportProps('units')} headers={[t('ui.form.status'), t('pages.dashboard.units')]} rows={ready('units') && units.length ? occupancyRows : []} kind="pie" format={integer} />
        <Report title={t('pages.dashboard.cashflow')} hint={t('dashboardHome.cashflowScope')} {...reportProps('cashflow')} headers={headings} rows={cashflowRows} kind="bar" format={money} />
        <Report title={t('pages.dashboard.receivablesAging')} hint={t('dashboardHome.obligationScope')} {...reportProps('aging')} headers={headings} rows={agingRows} kind="bar" format={money} />
        <Report title={t('analyticsLabels.forecast')} hint={t('dashboardHome.forecastScope')} {...reportProps('forecast')} headers={[t('dashboardHome.category'), t('pages.dashboard.balance'), t('pages.dashboard.income'), t('pages.dashboard.expenses')]} rows={forecastRows} kind="line" format={money} />
        <Report title={t('pages.dashboard.maintenanceCosts')} hint={t('dashboardHome.estimatedScope')} {...reportProps('maintenance')} headers={headings} rows={maintenanceRows} chartRows={maintenanceRows.slice(0, 8)} kind="horizontal" format={money} />
        <Report title={t('dashboardHome.categoryVolume')} hint={t('dashboardHome.categoryScope')} {...reportProps('finance')} headers={headings} rows={financeRows} chartRows={financePie} kind="pie" format={money} />
      </div>}
    </section>
    {isAdmin && <section className="dashboard-home-panel dashboard-home-audit"><button className="dashboard-home-disclosure" aria-expanded={auditOpen} aria-controls="dashboard-home-audit" onClick={() => { if (!auditOpen && sources.audit.status === 'idle') void reload('audit'); setAuditOpen(previous => !previous); }}>{t('pages.dashboard.recentActivity')}<ChevronDown size={17} aria-hidden="true" /></button>{auditOpen && <div id="dashboard-home-audit"><SourceState source={sources.audit} name={sourceName('audit')} onRetry={() => reload('audit')} t={t} />{ready('audit') && <ValuesTable title={t('pages.dashboard.recentActivity')} t={t} headers={[t('pages.dashboard.auditAction'), t('pages.dashboard.auditArea'), t('pages.dashboard.auditUser'), t('pages.dashboard.auditTime')]} rows={(Array.isArray(sources.audit.data) ? sources.audit.data : sources.audit.data.items).map(entry => [t(`dashboardHome.auditActions.${entry.action}`) === `dashboardHome.auditActions.${entry.action}` ? entry.action : t(`dashboardHome.auditActions.${entry.action}`), entry.entity_type?.replaceAll('_', ' ') || '—', entry.username || '—', entry.timestamp && !Number.isNaN(Date.parse(entry.timestamp)) ? new Intl.DateTimeFormat(locale, { dateStyle: 'short', timeStyle: 'short' }).format(new Date(entry.timestamp)) : '—'])} />}</div>}</section>}
  </div>;
}
