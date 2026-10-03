import { useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowUpRight, Bell, CheckSquare, Clock3, X } from 'lucide-react';
import { hintTarget } from './dashboardModel';
import SourceState from './DashboardSourceState';
import useDashboardContext from './useDashboardContext';

function Context({ selection, principal, onDenied, onClose, date, t, locale }) {
  const context = useDashboardContext(selection, principal, onDenied);
  return <section className="dashboard-home-context" aria-label={t('dashboardHome.context')} aria-busy={context.status === 'loading'}>
    <header><h3>{t('dashboardHome.context')}</h3><button className="btn btn-secondary btn-sm" onClick={onClose}><X size={14} aria-hidden="true" />{t('dashboardHome.closeContext')}</button></header>
    {context.error?.statusCode === 404 ? <p role="alert">{t('dashboardHome.contextUnavailable')}</p>
      : <SourceState source={context} name={t('dashboardHome.context')} onRetry={context.retry} t={t} locale={locale} />}
    {context.data && <><strong>{context.data.title}</strong><dl><dt>{t('ui.form.status')}</dt><dd>{context.data.status}</dd><dt>{t('dashboardHome.contextDate')}</dt><dd>{date(context.data.date)}</dd>
      <dt>{t('pages.dashboard.properties')}</dt><dd>{context.data.property ? <Link to={`/properties/${encodeURIComponent(context.data.property.id)}`}>{context.data.property.name}<ArrowUpRight size={14} aria-hidden="true" /></Link> : t('dashboardHome.noAssignment')}</dd>
      <dt>{t('pages.dashboard.units')}</dt><dd>{context.data.unit ? <Link to={`/units/${encodeURIComponent(context.data.unit.id)}`}>{context.data.unit.label}<ArrowUpRight size={14} aria-hidden="true" /></Link> : t('dashboardHome.noAssignment')}</dd></dl>
      <p className="dashboard-home-caption">{t('dashboardHome.contextCurrent')}</p></>}
  </section>;
}

const panels = [
  { family: 'tasks', title: 'pages.dashboard.openTasks', icon: CheckSquare, empty: 'pages.dashboard.noOpenTasks', to: '/tasks', link: 'dashboardHome.taskInventory' },
  { family: 'expiring_contracts', title: 'dashboardHome.next90Days', icon: Clock3, empty: 'dashboardHome.noExpiring', to: '/contracts', link: 'dashboardHome.contractInventory' },
  { family: 'notifications', title: 'pages.dashboard.notifications', icon: Bell, empty: 'pages.dashboard.noNotifications' },
];
const translatedValue = (t, prefix, value) => { const key = `dashboardHome.${prefix}.${value}`; const translated = t(key); return translated === key ? value : translated; };

export default function DashboardWorkHints({ summary, principal, onDenied, date, integer, t, locale, verifying, verify }) {
  const [selection, setSelection] = useState(null); const trigger = useRef(null); const heading = useRef(null);
  const selected = summary.status === 'ready' && selection?.source === summary.version ? selection : null;
  const busy = summary.status !== 'ready' || verifying;
  const open = async (event, family, type, id, rowId) => {
    const button = event.currentTarget;
    if (!await verify()) return;
    trigger.current = button; heading.current = document.getElementById(`dashboard-hints-${family}`);
    setSelection({ family, type, id, rowId, source: summary.version });
  };
  const close = () => {
    setSelection(null);
    (trigger.current?.isConnected ? trigger.current : heading.current)?.focus();
  };
  const navigate = async (family, direction) => { if (await verify()) { setSelection(null); summary.navigate(family, direction); } };
  const resize = async limit => { if (await verify()) { setSelection(null); void summary.reset(limit); } };
  return <>
    <div className="dashboard-home-hint-options"><p>{summary.data ? t('dashboardHome.summaryScope', { date: date(summary.data.as_of) }) : t('dashboardHome.unavailable')}</p><label htmlFor="dashboard-hint-limit">{t('dashboardHome.pageSize')}<select id="dashboard-hint-limit" value={summary.query.limit} disabled={summary.status === 'loading' || verifying} onChange={event => { void resize(Number(event.target.value)); }}>{[5, 10, 20].map(value => <option key={value} value={value}>{value}</option>)}</select></label></div>
    <div className="dashboard-home-activity-grid">{panels.map(panel => {
      const Icon = panel.icon; const page = summary.data?.work_hints[panel.family]; const trail = summary.trails[panel.family];
      return <section className="dashboard-home-panel" key={panel.family} aria-label={t(panel.title)} aria-busy={summary.status === 'loading'}>
        <header><div className="dashboard-home-panel-title"><Icon size={19} aria-hidden="true" /><h2 id={`dashboard-hints-${panel.family}`} tabIndex={-1}>{t(panel.title)}</h2></div>
          <p>{page ? t('dashboardHome.hintTotal', { count: integer(page.total) }) : t('dashboardHome.unavailable')}</p>{panel.family === 'expiring_contracts' && <p>{t('dashboardHome.contractScope')}</p>}</header>
        {page ? <>
          {page.items.length ? <ul className="dashboard-home-activity-list">{page.items.map(row => {
            const contextType = panel.family === 'tasks' ? 'task' : panel.family === 'expiring_contracts' ? 'contract' : ['task', 'contract'].includes(row.entity_type) && row.entity_id ? row.entity_type : null;
            const title = panel.family === 'expiring_contracts' ? row.contract_number : row.title;
            const target = panel.family === 'notifications' ? hintTarget(row) : null;
            const active = selected?.family === panel.family && selected.rowId === row.id;
            return <li key={row.id}>{contextType ? <button className="dashboard-home-hint-title" disabled={busy} aria-expanded={active} onClick={event => open(event, panel.family, contextType, panel.family === 'notifications' ? row.entity_id : row.id, row.id)}>{title}</button> : target ? <Link to={target}>{title}</Link> : <strong>{title}</strong>}
              <span>{panel.family === 'expiring_contracts' ? `${date(row.end_date)} · ${t('dashboardHome.remainingDays', { count: row.days_remaining })}` : panel.family === 'tasks' ? date(row.due_date) : translatedValue(t, 'severity', row.severity)}</span>
              {panel.family === 'tasks' && row.priority && <small className="dashboard-home-priority-label">{translatedValue(t, 'priority', row.priority)}</small>}
              {active && <Context selection={selected} principal={principal} onDenied={onDenied} onClose={close} date={date} t={t} locale={locale} />}
            </li>;
          })}</ul> : summary.status === 'ready' ? <p className="dashboard-home-empty">{t(page.total ? 'dashboardHome.emptyFollowingPage' : panel.empty)}</p> : null}
          <nav className="dashboard-home-paging" aria-label={t('dashboardHome.paging', { name: t(panel.title) })}><span>{t('dashboardHome.pageNumber', { count: integer(trail.length) })}</span>
            <button className="btn btn-secondary btn-sm" disabled={busy || trail.length === 1} onClick={() => { void navigate(panel.family, 'previous'); }}>{t('dashboardHome.previousPage')}</button>
            <button className="btn btn-secondary btn-sm" disabled={busy || !page.has_more} onClick={() => { void navigate(panel.family, 'next'); }}>{t('dashboardHome.nextPage')}</button>
            {trail.length > 1 && <button className="btn btn-secondary btn-sm" disabled={busy} onClick={() => { void navigate(panel.family, 'first'); }}>{t('dashboardHome.firstPage')}</button>}
          </nav>
        </> : <p className="dashboard-home-caption">{t(summary.status === 'error' ? 'dashboardHome.hintsUnavailable' : 'dashboardHome.loading')}</p>}
        {panel.to && <Link className="dashboard-home-text-link" to={panel.to}>{t(panel.link)}<ArrowUpRight size={14} aria-hidden="true" /></Link>}
      </section>;
    })}</div>
  </>;
}
