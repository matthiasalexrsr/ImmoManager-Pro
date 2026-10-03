import { useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowUpRight, Building2, Home, Wallet, FileCheck2, RefreshCw, Wrench, CheckSquare, Plus, ChevronDown, Layers3 } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { useTranslation } from '../i18n';
import DashboardBoundary from '../features/dashboardHome/DashboardBoundary';
import useDashboardSummary from '../features/dashboardHome/useDashboardSummary';
import useDashboardReports, { bucketKeys } from '../features/dashboardHome/useDashboardReports';
import DashboardWorkHints from '../features/dashboardHome/DashboardWorkHints';
import SourceState from '../features/dashboardHome/DashboardSourceState';
import { Metric, Report, ValuesTable } from '../features/dashboardHome/DashboardReports';
import { count } from '../features/dashboardHome/dashboardModel';
import './Dashboard.css';
const finite = value => typeof value === 'number' && Number.isFinite(value);

export default function Dashboard() {
  return <DashboardBoundary>{props => <DashboardWorkspace key={props.principal} {...props} />}</DashboardBoundary>;
}

function DashboardWorkspace({ principal, onDenied, verify, verifying }) {
  const { t, locale } = useTranslation();
  const { isReadonly, isAdmin } = useAuth() || {};
  const summary = useDashboardSummary(principal, onDenied);
  const reports = useDashboardReports(principal, onDenied);
  const sources = { ...reports.sources, stats: summary };
  const reload = async key => { if (key === 'stats') { if (await verify()) summary.retry(); } else void reports.reload(key); };
  const reloadAll = async () => { if (await verify()) { void summary.reset(); reports.reloadAll(); } };
  const retrySummary = async () => { if (await verify()) summary.retry(); };
  const restartSummary = async () => { if (await verify()) void summary.reset(); };
  const [view, setView] = useState('work');
  const [auditOpen, setAuditOpen] = useState(false);
  const ready = key => sources[key].status === 'ready';
  const available = key => Boolean(sources[key].data);
  const stats = sources.stats.data;
  const money = value => finite(value) ? new Intl.NumberFormat(locale, { style: 'currency', currency: 'EUR' }).format(value) : '—';
  const integer = value => count(value) ? new Intl.NumberFormat(locale).format(value) : '—';
  const date = value => value && !Number.isNaN(Date.parse(value)) ? new Intl.DateTimeFormat(locale).format(new Date(value.includes('T') ? value : `${value}T00:00:00`)) : t('dashboardHome.noDueDate');
  const occupancy = stats?.occupancy;
  const occupied = occupancy?.occupied; const reserved = occupancy?.reserved; const vacant = occupancy?.vacant; const other = occupancy?.other;
  const occupancyRate = occupancy?.total ? Math.round(occupied / occupancy.total * 100) : null;
  const occupancyRows = occupancy ? [
    { name: t('pages.dashboard.occupied'), values: [occupied] },
    { name: t('pages.dashboard.reserved'), values: [reserved] },
    { name: t('pages.dashboard.vacant'), values: [vacant] },
    { name: t('dashboardHome.otherUnitStatuses'), values: [other] },
  ] : [];
  const aging = sources.aging.data;
  const agedAmount = ready('aging') ? bucketKeys.slice(1).reduce((sum, key) => sum + aging.buckets[key], 0) : null;
  const cashflow = sources.cashflow.data;
  const cashflowRows = available('cashflow') ? ['income', 'expenses', 'net'].map((key, index) => ({ name: t(`pages.dashboard.${key}`), values: [cashflow[['incomeTotal', 'expenseTotal', 'netTotal'][index]]] })) : [];
  const agingRows = available('aging') ? ['agingCurrent', 'aging1to30', 'aging31to60', 'aging61to90', 'aging90plus'].map((key, index) => ({ name: t(`pages.dashboard.${key}`), values: [aging.buckets[bucketKeys[index]]] })) : [];
  const maintenanceRows = sources.maintenance.data?.categories.map(item => ({ name: item.category, values: [item.estimatedCost] })) || [];
  const categoryRows = sources.finance.data?.totalsByCategory.map(item => ({ name: item.categoryName, values: [item.total] })) || [];
  const financeRows = available('finance') ? [...categoryRows, { name: t('dashboardHome.uncategorized'), values: [sources.finance.data.uncategorizedTotal] }, { name: t('dashboardHome.bookingTotal'), values: [sources.finance.data.bookingsTotal] }] : [];
  const financePie = categoryRows.slice(0, 8).map(item => ({ ...item, values: [Math.abs(item.values[0])] })).filter(item => item.values[0] > 0);
  const forecastRows = sources.forecast.data?.forecast.map(item => ({ name: item.month, values: [item.projected_balance, item.projected_income, item.projected_expense] })) || [];
  const priorities = [];
  if (agedAmount > 0) priorities.push({ key: 'overdue', to: '/rent-overview', icon: Wallet, title: t('dashboardHome.overdueTitle'), hint: t('dashboardHome.obligationScope'), value: money(agedAmount), tone: 'urgent' });
  if (ready('stats') && stats.overdue_maintenance > 0) priorities.push({ key: 'overdueMaintenance', to: '/maintenance', icon: Wrench, title: t('dashboardHome.overdueMaintenance'), hint: t('dashboardHome.maintenanceHint'), value: integer(stats.overdue_maintenance), tone: 'urgent' });
  if (ready('stats') && stats.billing_presence.blockers > 0) priorities.push({ key: 'blockers', to: '/statements', icon: FileCheck2, title: t('dashboardHome.billingTitle'), hint: t('dashboardHome.billingHint'), value: integer(stats.billing_presence.blockers), tone: 'attention' });
  if (ready('stats') && stats.open_rent_charges + stats.overdue_rent_charges > 0) priorities.push({ key: 'payments', to: '/rent-charges', icon: Wallet, title: t('dashboardHome.paymentsTitle'), hint: t('dashboardHome.paymentsHint'), value: integer(stats.open_rent_charges + stats.overdue_rent_charges), tone: 'attention' });
  if (ready('stats') && stats.open_tasks > 0) priorities.push({ key: 'tasks', to: '/tasks', icon: CheckSquare, title: t('pages.dashboard.openTasks'), hint: t('dashboardHome.taskHint'), value: integer(stats.open_tasks) });
  if (ready('stats') && vacant > 0) priorities.push({ key: 'vacancy', to: '/units', icon: Home, title: t('dashboardHome.vacancyTitle'), hint: t('dashboardHome.vacancyHint'), value: integer(vacant) });
  if (ready('maintenance') && sources.maintenance.data.openCases > 0 && !priorities.some(item => item.key === 'overdueMaintenance')) priorities.push({ key: 'maintenance', to: '/maintenance', icon: Wrench, title: t('dashboardHome.maintenanceTitle'), hint: t('dashboardHome.maintenanceHint'), value: integer(sources.maintenance.data.openCases) });
  if (ready('stats') && stats.draft_billing_periods > 0 && !priorities.some(item => item.key === 'blockers')) priorities.push({ key: 'drafts', to: '/statements', icon: FileCheck2, title: t('dashboardHome.draftBilling'), hint: t('dashboardHome.draftBillingHint'), value: integer(stats.draft_billing_periods) });
  const prioritySources = ['stats', 'aging', 'maintenance'];
  const inventory = [['portfolio_count', '/portfolios', 'pages.dashboard.portfolios'], ['property_count', '/properties', 'pages.dashboard.properties'], ['unit_count', '/units', 'pages.dashboard.units'], ['tenant_count', '/tenants', 'pages.dashboard.tenants'], ['active_contracts', '/contracts', 'pages.dashboard.activeContracts'], ['account_count', '/accounts', 'pages.dashboard.accounts'], ['open_maintenance', '/maintenance', 'pages.dashboard.openMaintenance'], ['document_count', '/documents', 'dashboardHome.documents']];
  const sourceName = key => t(`dashboardHome.sources.${key}`);
  const reportProps = key => ({ source: sources[key], onRetry: () => reload(key), t, locale });
  const headings = [t('dashboardHome.category'), t('dashboardHome.amount')];
  const activateView = (event, next) => {
    if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) {
      event.preventDefault();
      const target = event.key === 'Home' ? 'work' : event.key === 'End' ? 'analysis' : next;
      if (target === 'analysis') reports.loadAnalysis();
      setView(target);
      document.getElementById(`dashboard-home-tab-${target}`)?.focus();
    }
  };

  return <div className="page dashboard-home">
    <header className="dashboard-home-heading"><div><span className="dashboard-home-eyebrow">{t('dashboardHome.workspace')}</span><h1>{t('dashboardHome.title')}</h1><p>{t('dashboardHome.intro')}</p></div><div className="dashboard-home-refresh"><button className="btn btn-secondary" disabled={verifying} onClick={() => { void reloadAll(); }}><RefreshCw size={16} aria-hidden="true" />{t('dashboardHome.refresh')}</button>{summary.loadedAt && <small>{t('dashboardHome.loadedAt', { time: new Intl.DateTimeFormat(locale, { hour: '2-digit', minute: '2-digit' }).format(sources.stats.loadedAt) })}</small>}</div></header>
    <>{verifying && <p className="dashboard-home-state" role="status">{t('dashboardHome.checkingAccess')}</p>}<SourceState source={summary} name={sourceName('stats')} onRetry={() => { void retrySummary(); }} onReset={() => { void restartSummary(); }} t={t} locale={locale} /></>
    <section className="dashboard-home-metrics" aria-label={t('dashboardHome.keyFigures')}>
      <Metric icon={Building2} label={t('pages.dashboard.properties')} value={available('stats') ? integer(stats.property_count) : null} hint={available('stats') ? t('dashboardHome.portfolioCount', { count: integer(stats.portfolio_count) }) : t('dashboardHome.unavailable')} to="/properties" action={t('dashboardHome.openInventory')} pending={sources.stats.status === 'loading'} />
      <Metric icon={Home} label={t('dashboardHome.occupiedUnits')} value={occupancy ? `${integer(occupied)} / ${integer(occupancy.total)}` : null} hint={!occupancy ? t('dashboardHome.unavailable') : occupancyRate == null ? t('dashboardHome.noOccupancy') : t('dashboardHome.occupancyRate', { count: occupancyRate })} to="/units" action={t('dashboardHome.openUnits')} pending={summary.status === 'loading'} />
      <Metric icon={Wallet} label={t('dashboardHome.openAmount')} value={available('aging') ? money(aging.openTotal) : null} hint={t('dashboardHome.obligationScope')} to="/rent-overview" action={t('dashboardHome.openPayments')} pending={sources.aging.status === 'loading'} />
      <Metric icon={FileCheck2} label={t('dashboardHome.draftBilling')} value={available('stats') ? integer(stats.draft_billing_periods) : null} hint={t('dashboardHome.draftBillingHint')} to="/statements" action={t('dashboardHome.openBilling')} pending={sources.stats.status === 'loading'} />
    </section>
    <p className="dashboard-home-caption">{t('dashboardHome.separateReports')}</p>{sources.aging.status !== 'ready' && <SourceState source={sources.aging} name={sourceName('aging')} onRetry={() => reload('aging')} t={t} locale={locale} />}
    {ready('stats') && stats.portfolio_count === 0 && <section className="dashboard-home-start"><Layers3 size={25} aria-hidden="true" /><div><h2>{t('dashboardHome.emptyScopeTitle')}</h2><p>{t('dashboardHome.emptyScopeHint')}</p></div><Link className="btn btn-primary" to="/portfolios">{t('dashboardHome.openPortfolios')}<ArrowUpRight size={16} aria-hidden="true" /></Link></section>}
    <nav className="dashboard-home-tabs" role="tablist" aria-label={t('dashboardHome.view')}>{['work', 'analysis'].map((key, index) => <button id={`dashboard-home-tab-${key}`} key={key} role="tab" aria-selected={view === key} aria-controls={`dashboard-home-panel-${key}`} tabIndex={view === key ? 0 : -1} onClick={() => { if (key === 'analysis') reports.loadAnalysis(); setView(key); }} onKeyDown={event => activateView(event, index === 0 ? 'analysis' : 'work')}>{t(key === 'work' ? 'dashboardHome.workTab' : 'dashboardHome.analysisTab')}</button>)}</nav>
    <section role="tabpanel" id={`dashboard-home-panel-${view}`} aria-labelledby={`dashboard-home-tab-${view}`} tabIndex={0}>
      {view === 'work' && <>
        <div className="dashboard-home-work-grid"><section className="dashboard-home-panel dashboard-home-priorities" aria-label={t('dashboardHome.priorities')}><header><div><span className="dashboard-home-eyebrow">{t('dashboardHome.nextSteps')}</span><h2>{t('dashboardHome.priorities')}</h2></div><p>{t('dashboardHome.prioritiesHint')}</p></header><div className="dashboard-home-priority-list">{priorities.map(item => { const Icon = item.icon; return <Link key={item.key} to={item.to} className={`dashboard-home-priority ${item.tone || ''}`}><span className="dashboard-home-action-icon"><Icon size={19} aria-hidden="true" /></span><span><strong>{item.title}</strong><small>{item.hint}</small></span><b>{item.value}</b><ArrowUpRight size={17} aria-hidden="true" /></Link>; })}</div>{!priorities.length && prioritySources.every(ready) && <p className="dashboard-home-empty">{t('dashboardHome.noPriorities')}</p>}{!prioritySources.every(ready) && <p className="dashboard-home-caption">{t('dashboardHome.prioritiesIncomplete')}</p>}{sources.maintenance.status !== 'ready' && <SourceState source={sources.maintenance} name={sourceName('maintenance')} onRetry={() => reload('maintenance')} t={t} locale={locale} />}<Link className="dashboard-home-text-link" to="/calendar">{t('dashboardHome.calendar')}<ArrowUpRight size={15} aria-hidden="true" /></Link></section>
          <aside className="dashboard-home-panel dashboard-home-quick" aria-label={t('dashboardHome.quickActions')}><header><h2>{t('dashboardHome.quickActions')}</h2><p>{t(isReadonly ? 'dashboardHome.readonlyHint' : 'dashboardHome.quickHint')}</p></header><Link to="/properties"><Building2 size={19} aria-hidden="true" />{t('dashboardHome.openInventory')}<ArrowUpRight size={15} aria-hidden="true" /></Link><Link to="/bookings"><Wallet size={19} aria-hidden="true" />{t('dashboardHome.reviewBookings')}<ArrowUpRight size={15} aria-hidden="true" /></Link><Link to="/tasks"><CheckSquare size={19} aria-hidden="true" />{t('dashboardHome.openTasks')}<ArrowUpRight size={15} aria-hidden="true" /></Link>{isAdmin && !isReadonly && <Link className="dashboard-home-create" to="/contract-wizard"><Plus size={19} aria-hidden="true" />{t('dashboardHome.createContract')}<ArrowUpRight size={15} aria-hidden="true" /></Link>}</aside></div>
        <DashboardWorkHints summary={summary} principal={principal} onDenied={onDenied} date={date} integer={integer} t={t} locale={locale} verifying={verifying} verify={verify} />
        <section className="dashboard-home-panel dashboard-home-inventory" aria-label={t('dashboardHome.inventory')}><header><h2>{t('dashboardHome.inventory')}</h2><p>{t('dashboardHome.liveData')}</p></header><div>{inventory.map(([key, to, label]) => <Link to={to} key={key}><span>{t(label)}</span><strong>{available('stats') ? integer(stats[key]) : '—'}</strong><ArrowUpRight size={15} aria-hidden="true" /></Link>)}</div></section>
        <details className="dashboard-home-panel dashboard-home-workflows"><summary>{t('dashboardHome.workflows')}<ChevronDown size={17} aria-hidden="true" /></summary><p>{t('dashboardHome.workflowHint')}</p><div>{[['/properties', 'dashboardHome.openInventory'], ['/units', 'dashboardHome.openUnits'], ['/contracts', 'dashboardHome.openContracts'], ['/rent-charges', 'dashboardHome.openPayments'], ['/statements', 'dashboardHome.openBilling'], ['/maintenance', 'dashboardHome.maintenanceTitle']].map(([to, label]) => <Link key={to} to={to}>{t(label)}<ArrowUpRight size={14} aria-hidden="true" /></Link>)}</div></details>
      </>}
      {view === 'analysis' && <><p className="dashboard-home-caption">{t('dashboardHome.separateReports')}</p><div className="dashboard-home-reports">
        <Report title={t('pages.dashboard.occupancyChart')} hint={t('dashboardHome.occupancyScope')} {...reportProps('stats')} headers={[t('ui.form.status'), t('pages.dashboard.units')]} rows={occupancy?.total ? occupancyRows : []} kind="pie" format={integer} />
        <Report title={t('pages.dashboard.cashflow')} hint={t('dashboardHome.cashflowScope')} {...reportProps('cashflow')} headers={headings} rows={cashflowRows} kind="bar" format={money} />
        <Report title={t('pages.dashboard.receivablesAging')} hint={t('dashboardHome.obligationScope')} {...reportProps('aging')} headers={headings} rows={agingRows} kind="bar" format={money} />
        <Report title={t('analyticsLabels.forecast')} hint={t('dashboardHome.forecastScope')} {...reportProps('forecast')} headers={[t('dashboardHome.category'), t('pages.dashboard.balance'), t('pages.dashboard.income'), t('pages.dashboard.expenses')]} rows={forecastRows} kind="line" format={money} />
        <Report title={t('pages.dashboard.maintenanceCosts')} hint={t('dashboardHome.estimatedScope')} {...reportProps('maintenance')} headers={headings} rows={maintenanceRows} chartRows={maintenanceRows.slice(0, 8)} kind="horizontal" format={money} />
        <Report title={t('dashboardHome.categoryVolume')} hint={t('dashboardHome.categoryScope')} {...reportProps('finance')} headers={headings} rows={financeRows} chartRows={financePie} kind="pie" format={money} />
      </div></>}
    </section>
    {isAdmin && <section className="dashboard-home-panel dashboard-home-audit"><button className="dashboard-home-disclosure" aria-expanded={auditOpen} aria-controls="dashboard-home-audit" onClick={() => { if (!auditOpen && sources.audit.status === 'idle') void reload('audit'); setAuditOpen(previous => !previous); }}>{t('pages.dashboard.recentActivity')}<ChevronDown size={17} aria-hidden="true" /></button>{auditOpen && <div id="dashboard-home-audit"><SourceState source={sources.audit} name={sourceName('audit')} onRetry={() => reload('audit')} t={t} locale={locale} />{available('audit') && <ValuesTable title={t('pages.dashboard.recentActivity')} t={t} headers={[t('pages.dashboard.auditAction'), t('pages.dashboard.auditArea'), t('pages.dashboard.auditUser'), t('pages.dashboard.auditTime')]} rows={(Array.isArray(sources.audit.data) ? sources.audit.data : sources.audit.data.items).map(entry => [t(`dashboardHome.auditActions.${entry.action}`) === `dashboardHome.auditActions.${entry.action}` ? entry.action : t(`dashboardHome.auditActions.${entry.action}`), entry.entity_type?.replaceAll('_', ' ') || '—', entry.username || '—', entry.timestamp && !Number.isNaN(Date.parse(entry.timestamp)) ? new Intl.DateTimeFormat(locale, { dateStyle: 'short', timeStyle: 'short' }).format(new Date(entry.timestamp)) : '—'])} />}</div>}</section>}
  </div>;
}
