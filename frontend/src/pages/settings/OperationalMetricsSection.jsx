import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { Activity, RefreshCw } from 'lucide-react';
import { api } from '../../api';
import { useAuth } from '../../contexts/AuthContext';
import { useTranslation } from '../../i18n';
import './OperationalMetricsSection.css';

const groups = ['auth', 'administration', 'finance', 'property', 'people', 'files', 'operations', 'other', 'unmatched'];
const outcomes = ['success', 'redirect', 'client_error', 'server_error', 'aborted'];
const methods = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS', 'OTHER'];
const count = value => Number.isSafeInteger(value) && value >= 0;
const duration = value => Number.isFinite(value) && value >= 0;
const validAggregate = value => value && count(value.count) && duration(value.total_ms);
const validResponse = value => value?.scope === 'process_worker' && value.persistent === false
  && typeof value.started_at === 'string' && Number.isFinite(Date.parse(value.started_at))
  && duration(value.uptime_seconds) && duration(value.process?.cpu_seconds)
  && ['connected', 'unavailable', 'not_configured'].includes(value.database?.state)
  && typeof value.database.persistent === 'boolean' && duration(value.database.duration_ms)
  && ['sqlite', 'postgresql', 'sql', 'memory'].includes(value.database.backend)
  && (value.database.backend === 'memory' ? value.database.state === 'not_configured' && !value.database.persistent
    : value.database.state !== 'not_configured' && (value.database.backend === 'sqlite' || value.database.persistent))
  && value.database.check === 'connectivity_only'
  && count(value.requests?.completed) && count(value.requests.inflight) && count(value.requests.peak_inflight) && count(value.requests.exceptions) && count(value.requests.aborted)
  && Array.isArray(value.requests.series) && value.requests.series.length <= groups.length * methods.length * outcomes.length
  && value.requests.series.every(row => groups.includes(row.group) && methods.includes(row.method) && outcomes.includes(row.outcome) && validAggregate(row))
  && value.requests.series.reduce((sum, row) => sum + row.count, 0) === value.requests.completed
  && validAggregate(value.jobs?.operational_tick?.success) && validAggregate(value.jobs?.operational_tick?.error)
  && typeof value.scheduler?.automatic_enabled === 'boolean' && typeof value.scheduler.automatic_running === 'boolean';

export default function OperationalMetricsSection() {
  const auth = useAuth();
  const { t, locale } = useTranslation();
  const titleId = useId();
  const userId = auth?.user?.id;
  const role = auth?.role || auth?.user?.role;
  const allowed = !!userId && (role === 'eigentuemer' || (role === 'verwalter' && auth?.user?.portfolio_access !== 'selected'));
  const actor = `${userId}:${role}:${allowed}`;
  const [source, setSource] = useState({ actor, state: 'loading', data: null, error: null });
  const controller = useRef(null);
  const running = useRef(false);
  const text = key => t(`settings.operations.${key}`);

  const load = useCallback(async () => {
    if (!allowed || running.current) return;
    running.current = true;
    const request = new AbortController();
    controller.current = request;
    // An unsuccessful refresh clears old status; it cannot look healthy after
    // an outage or loss of installation-wide permission.
    setSource({ actor, state: 'loading', data: null, error: null });
    try {
      const value = await api.get('/admin/operational-metrics', { signal: request.signal });
      if (!validResponse(value)) throw new Error(t('settings.operations.invalidResponse'));
      if (!request.signal.aborted) setSource({ actor, state: 'ready', data: value, error: null });
    } catch (error) {
      if (!request.signal.aborted) setSource({ actor, state: 'error', data: null, error: error.message || t('settings.operations.loadError') });
    } finally {
      if (controller.current === request) running.current = false;
    }
  }, [actor, allowed, t]);

  useEffect(() => {
    running.current = false;
    void load();
    return () => controller.current?.abort();
  }, [load]);

  if (!allowed) return null;
  const current = source.actor === actor ? source : { state: 'loading', data: null, error: null };
  const data = current.data;
  const integer = value => new Intl.NumberFormat(locale).format(value);
  const decimal = value => new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }).format(value);
  const rows = groups.map(group => {
    const series = data?.requests.series.filter(row => row.group === group) || [];
    const total = series.reduce((sum, row) => sum + row.count, 0);
    return { group, total, failures: series.filter(row => row.outcome === 'server_error').reduce((sum, row) => sum + row.count, 0),
      mean: total ? series.reduce((sum, row) => sum + row.total_ms, 0) / total : 0 };
  }).filter(row => row.total > 0);
  const totalErrors = rows.reduce((sum, row) => sum + row.failures, 0);
  const totalAborted = data?.requests.aborted || 0;

  return <section className="panel operational-metrics" aria-labelledby={titleId} aria-busy={current.state === 'loading'}>
    <div className="panel-header operational-metrics-heading">
      <h2 id={titleId}><Activity size={18} aria-hidden="true" />{text('title')}</h2>
      <button type="button" className="btn btn-sm btn-secondary" onClick={load} disabled={current.state === 'loading'}>
        <RefreshCw size={15} aria-hidden="true" />{text('refresh')}
      </button>
    </div>
    <div className="panel-body settings-section">
      <p className="text-muted operational-metrics-note">{text('scopeHint')}</p>
      {current.state === 'loading' && <p role="status">{text('loading')}</p>}
      {current.error && <div className="alert-error" role="alert"><p>{text('loadError')}</p><p>{current.error}</p></div>}
      {data && <>
        <div className={`operational-metrics-health ${data.database.state === 'connected' && data.database.persistent ? 'is-connected' : 'is-degraded'}`} role={data.database.state !== 'connected' || !data.database.persistent ? 'status' : undefined}>
          <strong>{text(`database.${data.database.state}`)}</strong>
          <span>{text(`backend.${data.database.backend}`)} · {decimal(data.database.duration_ms)} ms</span>
          {data.database.backend !== 'memory' && <p>{text('connectivityHint')}</p>}
          {!data.database.persistent && <p>{text('memoryHint')}</p>}
        </div>
        <dl className="operational-metrics-summary">
          <div><dt>{text('completed')}</dt><dd>{integer(data.requests.completed)}</dd></div>
          <div><dt>{text('errors')}</dt><dd>{integer(totalErrors)}</dd></div>
          <div><dt>{text('aborted')}</dt><dd>{integer(totalAborted)}</dd></div>
          <div><dt>{text('inflight')}</dt><dd>{integer(data.requests.inflight)} / {integer(data.requests.peak_inflight)}</dd></div>
        </dl>
        <p className="text-muted operational-metrics-note">{text('inflightHint')}</p>
        <div className="operational-metrics-table" tabIndex={0} role="region" aria-label={text('requestTable')}>
          <table>
            <caption>{text('requestTable')}</caption>
            <thead><tr><th scope="col">{text('group')}</th><th scope="col">{text('completed')}</th><th scope="col">{text('errors')}</th><th scope="col">{text('mean')}</th></tr></thead>
            <tbody>{rows.map(row => <tr key={row.group}><th scope="row">{text(`groups.${row.group}`)}</th><td>{integer(row.total)}</td><td>{integer(row.failures)}</td><td>{decimal(row.mean)} ms</td></tr>)}</tbody>
          </table>
          {rows.length === 0 && <p>{text('empty')}</p>}
        </div>
        <p className="text-muted operational-metrics-note">{text('tableHint')}</p>
        <dl className="operational-metrics-details">
          <div><dt>{text('started')}</dt><dd>{new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'medium' }).format(new Date(data.started_at))}</dd></div>
          <div><dt>{text('uptime')}</dt><dd>{decimal(data.uptime_seconds / 3600)} h</dd></div>
          <div><dt>{text('cpu')}</dt><dd>{decimal(data.process.cpu_seconds)} s</dd></div>
          <div><dt>{text('exceptions')}</dt><dd>{integer(data.requests.exceptions)}</dd></div>
          <div><dt>{text('jobs')}</dt><dd>{integer(data.jobs.operational_tick.success.count)} / {integer(data.jobs.operational_tick.error.count)}</dd></div>
          <div><dt>{text('scheduler')}</dt><dd>{text(data.scheduler.automatic_running ? 'schedulerRunning' : data.scheduler.automatic_enabled ? 'schedulerStopped' : 'schedulerDisabled')}</dd></div>
        </dl>
        <p className="text-muted operational-metrics-note">{text('jobHint')}</p>
        <p className="text-muted operational-metrics-note">{text('privacyHint')}</p>
      </>}
    </div>
  </section>;
}
