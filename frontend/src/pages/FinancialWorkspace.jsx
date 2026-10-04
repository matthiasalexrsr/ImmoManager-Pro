import { useCallback, useEffect, useRef, useState } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { useTranslation } from '../i18n';
import ReferenceChoice from '../features/unitInventory/ReferenceChoice';
import { principalKey } from '../features/unitInventory/read';
import { financialWorkspaceApi } from '../features/financialWorkspace/financialWorkspaceApi';
import {
  filterIdentity,
  formatMoneyString,
  normalizeFilters,
  exclusionTextKey,
} from '../features/financialWorkspace/financialWorkspaceModel';
import { financialText } from '../features/financialWorkspace/financialWorkspaceText';
import '../features/financialWorkspace/FinancialWorkspace.css';

function todayIso() {
  const now = new Date();
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 10);
}

function initialDraft() {
  return {
    date_from: '',
    date_to: '',
    as_of: todayIso(),
    basis: 'confirmed_cash',
    portfolio: null,
    properties: [],
    unit: null,
    account: null,
  };
}

function errorKind(error) {
  if (error?.statusCode === 422) return 'filterConflict';
  if (error?.statusCode === 409) return 'sourceChanged';
  if ([401, 403, 404].includes(error?.statusCode)) return 'accessChanged';
  if (['invalid_cash_report', 'invalid_cash_sources'].includes(error?.message)) return 'invalidResponse';
  return 'requestFailed';
}

function AggregateTable({ title, rows, label, locale, tr }) {
  return <section className="financial-workspace__analysis-card">
    <h3>{title}</h3>
    {!rows.length ? <p className="financial-workspace__muted">—</p> :
      <div className="financial-workspace__analysis-scroll" tabIndex={0}>
        <table>
          <thead><tr><th>{title}</th><th>{tr('income')}</th><th>{tr('expense')}</th><th>{tr('net')}</th><th>{tr('count')}</th></tr></thead>
          <tbody>{rows.map((row, index) => <tr key={label.key(row, index)}>
            <th scope="row">{label.text(row)}</th>
            <td>{formatMoneyString(row.income, locale)}</td>
            <td>{formatMoneyString(row.expense, locale)}</td>
            <td>{formatMoneyString(row.net, locale)}</td>
            <td>{row.count}</td>
          </tr>)}</tbody>
        </table>
      </div>}
  </section>;
}

function AppliedSummary({ applied, tr }) {
  if (!applied) return null;
  return <div className="financial-workspace__applied" aria-label={tr('applied')}>
    <strong>{tr('applied')}:</strong>
    <span>{tr(applied.filters.basis)}</span>
    {applied.filters.date_from && <span>{applied.filters.date_from}</span>}
    {applied.filters.date_to && <span>→ {applied.filters.date_to}</span>}
    <span>{tr('asOf')}: {applied.filters.as_of}</span>
    {applied.labels.portfolio && <span>{applied.labels.portfolio}</span>}
    {applied.labels.properties.map((name, index) => <span key={`${index}:${name}`}>{name}</span>)}
    {applied.labels.unit && <span>{applied.labels.unit}</span>}
    {applied.labels.account && <span>{applied.labels.account}</span>}
  </div>;
}

function FinancialWorkspaceInner({ principal }) {
  const { locale } = useTranslation();
  const tr = (key, params) => financialText(locale, key, params);
  const [draft, setDraft] = useState(initialDraft);
  const [propertyCandidate, setPropertyCandidate] = useState('');
  const [applied, setApplied] = useState(null);
  const [filterError, setFilterError] = useState(null);
  const [reportRevision, setReportRevision] = useState(0);
  const [reportState, setReportState] = useState({ key: null, loading: false, data: null, error: null });
  const [sourceTrail, setSourceTrail] = useState([null]);
  const [sourceIndex, setSourceIndex] = useState(0);
  const [sourceRevision, setSourceRevision] = useState(0);
  const [sourceState, setSourceState] = useState({ key: null, loading: false, data: null, error: null });
  const [exportState, setExportState] = useState({ busy: false, error: null });
  const exportController = useRef(null);

  const appliedKey = applied ? filterIdentity(applied.filters) : '';
  const reportKey = applied ? JSON.stringify([principal, appliedKey, reportRevision]) : '';
  const forgetPrivate = useCallback(() => {
    exportController.current?.abort();
    setDraft(initialDraft());
    setPropertyCandidate('');
    setApplied(null);
    setFilterError(null);
    setReportState({ key: null, loading: false, data: null, error: null });
    setSourceTrail([null]);
    setSourceIndex(0);
    setSourceState({ key: null, loading: false, data: null, error: null });
    setExportState({ busy: false, error: null });
  }, []);

  useEffect(() => {
    if (!applied || !principal) return undefined;
    const controller = new AbortController();
    setReportState({ key: reportKey, loading: true, data: null, error: null });
    financialWorkspaceApi.report(applied.filters, { signal: controller.signal })
      .then(data => {
        if (!controller.signal.aborted) setReportState({ key: reportKey, loading: false, data, error: null });
      })
      .catch(error => {
        if (controller.signal.aborted) return;
        if ([401, 403, 404].includes(error?.statusCode)) {
          forgetPrivate();
          return;
        }
        setReportState({ key: reportKey, loading: false, data: null, error });
      });
    return () => controller.abort();
  }, [applied, forgetPrivate, principal, reportKey]);

  const report = reportState.key === reportKey ? reportState.data : null;
  const reportLoading = Boolean(applied) && (reportState.key !== reportKey || reportState.loading);
  const reportError = reportState.key === reportKey ? reportState.error : null;

  useEffect(() => {
    setSourceTrail([null]);
    setSourceIndex(0);
    setSourceState({ key: null, loading: false, data: null, error: null });
  }, [appliedKey, report?.source_hash]);

  const sourceCursor = sourceTrail[sourceIndex] || null;
  const sourceKey = report
    ? JSON.stringify([principal, appliedKey, report.source_hash, sourceCursor, sourceRevision])
    : '';

  useEffect(() => {
    if (!report || !applied || !principal) return undefined;
    const controller = new AbortController();
    setSourceState({ key: sourceKey, loading: true, data: null, error: null });
    financialWorkspaceApi.sources(applied.filters, {
      sourceHash: report.source_hash,
      after: sourceCursor,
      limit: 50,
      signal: controller.signal,
    }).then(data => {
      if (!controller.signal.aborted) setSourceState({ key: sourceKey, loading: false, data, error: null });
    }).catch(error => {
      if (controller.signal.aborted) return;
      if ([401, 403, 404].includes(error?.statusCode)) {
        forgetPrivate();
        return;
      }
      setSourceState({ key: sourceKey, loading: false, data: null, error });
    });
    return () => controller.abort();
  }, [applied, forgetPrivate, principal, report, sourceCursor, sourceKey]);

  useEffect(() => {
    exportController.current?.abort();
    setExportState({ busy: false, error: null });
  }, [appliedKey]);

  useEffect(() => () => exportController.current?.abort(), []);

  const sourcePage = sourceState.key === sourceKey ? sourceState.data : null;
  const sourceLoading = Boolean(report) && (sourceState.key !== sourceKey || sourceState.loading);
  const sourceError = sourceState.key === sourceKey ? sourceState.error : null;

  const changePortfolio = (_id, row) => {
    setDraft(current => ({ ...current, portfolio: row || null, properties: [], unit: null, account: null }));
    setPropertyCandidate('');
  };

  const addProperty = (_id, row) => {
    if (!row) return;
    setDraft(current => current.properties.some(item => item.id === row.id)
      ? current
      : { ...current, properties: [...current.properties, row], unit: null });
    setPropertyCandidate('');
  };

  const removeProperty = id => {
    setDraft(current => ({ ...current, properties: current.properties.filter(row => row.id !== id), unit: null }));
  };

  const apply = event => {
    event.preventDefault();
    try {
      const filters = normalizeFilters(draft);
      setFilterError(null);
      setApplied({
        filters,
        labels: {
          portfolio: draft.portfolio?.name || null,
          properties: draft.properties.map(row => row.name || row.label || tr('custom')),
          unit: draft.unit?.label || null,
          account: draft.account?.name || null,
        },
      });
      setReportRevision(value => value + 1);
    } catch (error) {
      setFilterError(error.message);
    }
  };

  const reloadCurrentSources = () => {
    setSourceTrail([null]);
    setSourceIndex(0);
    setSourceRevision(0);
    setReportRevision(value => value + 1);
  };

  const exportCsv = async () => {
    if (!applied || exportState.busy) return;
    exportController.current?.abort();
    const controller = new AbortController();
    exportController.current = controller;
    setExportState({ busy: true, error: null });
    try {
      await financialWorkspaceApi.exportCsv(applied.filters, { signal: controller.signal });
      if (!controller.signal.aborted) setExportState({ busy: false, error: null });
    } catch (error) {
      if (!controller.signal.aborted) {
        if ([401, 403, 404].includes(error?.statusCode)) forgetPrivate();
        else setExportState({ busy: false, error });
      }
    } finally {
      if (exportController.current === controller) exportController.current = null;
    }
  };

  const sourceFailureKind = sourceError ? errorKind(sourceError) : null;
  const reportFailureKind = reportError ? errorKind(reportError) : null;
  const singleProperty = draft.properties.length === 1 ? draft.properties[0] : null;

  return <div className="page financial-workspace">
    <header className="financial-workspace__header">
      <div>
        <span className="financial-workspace__eyebrow">{tr('paymentBasis')}</span>
        <h1>{tr('title')}</h1>
        <p>{tr('subtitle')}</p>
      </div>
      <p className="financial-workspace__scope-note">{tr('notPeriodResult')}</p>
    </header>

    <form className="financial-workspace__filters" onSubmit={apply}>
      <h2>{tr('filters')}</h2>
      <div className="financial-workspace__date-grid">
        <label>{tr('dateFrom')}<input type="date" value={draft.date_from}
          onChange={event => setDraft(current => ({ ...current, date_from: event.target.value }))} /></label>
        <label>{tr('dateTo')}<input type="date" value={draft.date_to}
          onChange={event => setDraft(current => ({ ...current, date_to: event.target.value }))} /></label>
        <label>{tr('asOf')}<input type="date" required value={draft.as_of}
          onChange={event => setDraft(current => ({ ...current, as_of: event.target.value }))} /></label>
        <label>{tr('basis')}<select value={draft.basis}
          onChange={event => setDraft(current => ({ ...current, basis: event.target.value }))}>
          <option value="confirmed_cash">{tr('confirmed_cash')}</option>
          <option value="recorded_bookings">{tr('recorded_bookings')}</option>
        </select></label>
      </div>
      {draft.basis === 'recorded_bookings' && <p className="financial-workspace__hint">{tr('recordedHint')}</p>}

      <div className="financial-workspace__reference-grid">
        <ReferenceChoice kind="portfolios" label={tr('portfolio')} principal={principal}
          value={draft.portfolio?.id || ''} onChange={changePortfolio} />
        <ReferenceChoice kind="accounts" label={tr('account')} principal={principal}
          value={draft.account?.id || ''} filters={draft.portfolio ? { portfolio_id: draft.portfolio.id } : {}}
          onChange={(_id, row) => setDraft(current => ({ ...current, account: row || null }))} />
        <ReferenceChoice kind="properties" label={tr('addProperty')} principal={principal}
          value={propertyCandidate} filters={draft.portfolio ? { portfolio_id: draft.portfolio.id } : {}}
          onChange={(id, row) => { setPropertyCandidate(id); addProperty(id, row); }} />
        {singleProperty ? <ReferenceChoice kind="units" label={tr('unit')} principal={principal}
          value={draft.unit?.id || ''}
          filters={{
            ...(draft.portfolio ? { portfolio_id: draft.portfolio.id } : {}),
            property_id: singleProperty.id,
          }}
          onChange={(_id, row) => setDraft(current => ({ ...current, unit: row || null }))} />
          : <fieldset className="inventory-reference financial-workspace__reference-placeholder" disabled>
            <legend>{tr('unit')}</legend>
            <p>{tr('unitNeedsProperty')}</p>
          </fieldset>}
      </div>

      <div className="financial-workspace__selected-properties">
        <strong>{tr('properties')}:</strong>
        {!draft.properties.length && <span>{tr('noProperties')}</span>}
        {draft.properties.map(row => <span className="financial-workspace__selection-chip" key={row.id}>
          {row.name || row.label || tr('custom')}
          <button type="button" onClick={() => removeProperty(row.id)} aria-label={`${tr('remove')} ${row.name || row.label || ''}`}>×</button>
        </span>)}
      </div>
      {!singleProperty && <p className="financial-workspace__hint">{tr('unitNeedsProperty')}</p>}
      {filterError && <div className="alert alert-error" role="alert">
        {filterError === 'invalid_date_range' ? tr('filterConflict') : filterError}
      </div>}
      <button type="submit" className="btn btn-primary">{tr('apply')}</button>
    </form>

    <AppliedSummary applied={applied} tr={tr} />

    {reportLoading && <p className="financial-workspace__loading" role="status">{tr('loading')}</p>}
    {reportError && <div className="alert alert-error" role="alert">
      {reportFailureKind === 'filterConflict' ? tr('filterConflict')
        : reportFailureKind === 'invalidResponse' ? tr('invalidResponse')
        : reportError.message}
      <button type="button" className="btn btn-secondary" onClick={() => setReportRevision(value => value + 1)}>{tr('retry')}</button>
    </div>}

    {report && <>
      <section className="financial-workspace__metrics" aria-label={tr('paymentBasis')}>
        {[['income', report.income], ['expense', report.expense], ['net', report.net]].map(([key, value]) => <article key={key}>
          <span>{tr(key)}</span><strong>{formatMoneyString(value, locale)}</strong>
        </article>)}
        <article><span>{tr('sourceCount')}</span><strong>{report.source_count}</strong></article>
        <article><span>{tr('excludedCount')}</span><strong>{report.excluded_count}</strong></article>
      </section>

      {report.source_count === 0 && report.excluded_count === 0
        ? <p className="financial-workspace__empty">{tr('empty')}</p>
        : <div className="financial-workspace__analyses">
          <AggregateTable title={tr('months')} rows={report.months} locale={locale} tr={tr}
            label={{ key: row => row.month, text: row => row.month }} />
          <AggregateTable title={tr('categories')} rows={report.categories} locale={locale} tr={tr}
            label={{ key: (row, index) => row.category_id || `category-${index}`, text: row => row.name || tr('noCategory') }} />
          <AggregateTable title={tr('locations')} rows={report.locations} locale={locale} tr={tr}
            label={{ key: (row, index) => `${row.property_id || 'none'}:${row.unit_id || index}`,
              text: row => `${row.property_name || tr('noProperty')} · ${row.unit_label || tr('noUnit')}` }} />
        </div>}

      <section className="financial-workspace__sources">
        <div className="financial-workspace__section-heading">
          <div><h2>{tr('sources')}</h2><p>{tr('exportFresh')}</p></div>
          <button type="button" className="btn btn-secondary" disabled={exportState.busy}
            onClick={() => void exportCsv()}>{tr(exportState.busy ? 'exporting' : 'exportCsv')}</button>
        </div>
        {exportState.error && <div className="alert alert-error" role="alert">{exportState.error.message}</div>}
        {sourceLoading && <p role="status">{tr('loading')}</p>}
        {sourceError && <div className="alert alert-error" role="alert">
          {sourceFailureKind === 'sourceChanged' ? tr('sourceChanged')
            : sourceFailureKind === 'filterConflict' ? tr('filterConflict')
            : sourceFailureKind === 'invalidResponse' ? tr('invalidResponse') : tr('sourceError')}
          {sourceFailureKind === 'sourceChanged'
            ? <button type="button" className="btn btn-secondary" onClick={reloadCurrentSources}>{tr('reloadSources')}</button>
            : <button type="button" className="btn btn-secondary" onClick={() => setSourceRevision(value => value + 1)}>{tr('retry')}</button>}
        </div>}
        {sourcePage && <div className="financial-workspace__table-scroll" tabIndex={0} role="region" aria-label={tr('sources')}>
          <table><thead><tr>
            <th>{tr('bookingDate')}</th><th>{tr('source')}</th><th>{tr('category')}</th>
            <th>{tr('location')}</th><th>{tr('amount')}</th><th>{tr('state')}</th><th>{tr('receipt')}</th>
          </tr></thead><tbody>{sourcePage.items.map(row => <tr key={row.id} className={!row.included ? 'is-excluded' : ''}>
            <td>{row.booking_date}</td>
            <td><strong>{row.account_name}</strong>{row.payment_text && <small>{row.payment_text}</small>}</td>
            <td>{row.category_name || tr('noCategory')}</td>
            <td>{row.property_name || tr('noProperty')}{row.unit_label ? ` · ${row.unit_label}` : ` · ${tr('noUnit')}`}</td>
            <td>{formatMoneyString(row.amount, locale)}</td>
            <td>{tr(exclusionTextKey(row.exclusion_reason))}</td>
            <td>{row.receipt_url ? tr('receipt') : '—'}</td>
          </tr>)}</tbody></table>
        </div>}
        {sourcePage && <nav className="financial-workspace__pager" aria-label={tr('sources')}>
          <button type="button" className="btn btn-secondary" disabled={sourceIndex === 0}
            onClick={() => setSourceIndex(value => Math.max(0, value - 1))}>{tr('previous')}</button>
          <span>{tr('page')} {sourceIndex + 1}</span>
          <button type="button" className="btn btn-secondary" disabled={!sourcePage.has_more}
            onClick={() => {
              const next = sourcePage.next_after;
              setSourceTrail(current => [...current.slice(0, sourceIndex + 1), next]);
              setSourceIndex(value => value + 1);
            }}>{tr('next')}</button>
        </nav>}
      </section>

      <details className="financial-workspace__technical">
        <summary>{tr('technical')}</summary>
        <dl><div><dt>{tr('sourceHash')}</dt><dd><code>{report.source_hash}</code></dd></div></dl>
      </details>
    </>}
  </div>;
}

export default function FinancialWorkspace() {
  const auth = useAuth();
  const principal = principalKey(auth?.user);
  if (!principal) return null;
  return <FinancialWorkspaceInner key={principal} principal={principal} />;
}
