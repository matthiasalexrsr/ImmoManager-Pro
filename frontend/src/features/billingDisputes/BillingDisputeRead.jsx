import { useCallback, useState } from 'react';
import { useAuth } from '../../contexts/AuthContext';
import { useTranslation } from '../../i18n';
import useWriteAccess from '../../hooks/useWriteAccess';
import { principalKey, queryString } from '../unitInventory/read';
import { DISPUTES, PAGE_SIZE, readCasePage, readStatus } from './disputeModel';
import { disputeText } from './disputeCopy';
import DisputeCaseDetail from './DisputeCaseDetail';
import useDisputeRead from './useDisputeRead';
import { DisputeFailure } from './DisputeOriginals';
import './BillingDisputes.css';

function ReadWorkspace({ periodId, principal, onNewCase, onEvent, generation = 0 }) {
  const { locale } = useTranslation(); const tr = key => disputeText(locale, key);
  const [stateFilter, setStateFilter] = useState(''); const [pages, setPages] = useState({ source: '', trail: [''] });
  const [caseId, setCaseId] = useState(null); const [retry, setRetry] = useState(0); const [fenced, setFenced] = useState(false);
  const onDenied = useCallback(() => { setFenced(true); setCaseId(null); }, []);
  const { canWrite, isAllowed } = useWriteAccess('/billing');
  const source = JSON.stringify([periodId, stateFilter, generation, retry]);
  const trail = pages.source === source ? pages.trail : [''];
  const status = useDisputeRead(`${DISPUTES}/periods/${encodeURIComponent(periodId)}/status`, principal,
    `${generation}:${retry}`, row => readStatus(row, periodId), onDenied);
  const list = useDisputeRead(`${DISPUTES}?${queryString({ period_id: periodId, state: stateFilter, after_id: trail.at(-1), page_size: PAGE_SIZE })}`,
    principal, `${generation}:${retry}`, row => readCasePage(row, periodId), onDenied);
  const refresh = () => { setFenced(false); setRetry(value => value + 1); };
  if (fenced) return <section className="billing-disputes panel" aria-label={tr('title')}><DisputeFailure error={{ statusCode: 403 }} tr={tr} onRetry={refresh} /></section>;
  return <section className="billing-disputes" aria-label={tr('title')}><h2>{tr('title')}</h2>
    <div className="dispute-actions"><button className="btn btn-secondary" type="button" onClick={refresh}>{tr('refresh')}</button>
      {canWrite && onNewCase && status.data && <button className="btn btn-primary" type="button" onClick={() => { if (isAllowed()) onNewCase(status.data); }}>{tr('newCase')}</button>}</div>
    <p>{tr('financial')}</p>{status.loading && <p role="status">{tr('loading')}</p>}
    {status.error && <DisputeFailure error={status.error} tr={tr} onRetry={refresh} />}
    {status.data && <><dl className="dispute-facts"><div><dt>{tr('count')}</dt><dd>{status.data.case_count}</dd></div><div><dt>{tr('openCount')}</dt><dd>{status.data.open_case_count}</dd></div></dl>
      {status.data.legacy_disputed_without_complete_case && <p className="dispute-legacy" role="status">{tr('legacy')}</p>}</>}
    <label>{tr('status')}<select value={stateFilter} onChange={event => setStateFilter(event.target.value)}><option value="">{tr('all')}</option>{['open', 'in_review', 'withdrawn', 'closed'].map(value => <option key={value} value={value}>{tr(value)}</option>)}</select></label>
    {list.loading && <p role="status">{tr('loading')}</p>}{list.error && <DisputeFailure error={list.error} tr={tr} onRetry={refresh} />}
    {list.data && <>{!list.data.items.length ? <p>{tr('emptyCases')}</p> : <ul className="dispute-case-list">{list.data.items.map(row => <li key={row.id}><span>{tr(row.case_kind)} · {tr(row.state)} · {tr('revision')} {row.revision}</span>
      <button className="btn btn-secondary" type="button" onClick={() => setCaseId(row.id)}>{tr('case')} · {row.statement_id || row.id}</button></li>)}</ul>}
      <nav className="dispute-actions" aria-label={tr('title')}><button type="button" className="btn btn-secondary" disabled={trail.length === 1} onClick={() => setPages({ source, trail: trail.slice(0, -1) })}>{tr('previous')}</button><span>{tr('page')} {trail.length}</span>
        <button type="button" className="btn btn-secondary" disabled={list.data.next_after_id === null} onClick={() => setPages({ source, trail: [...trail, list.data.next_after_id] })}>{tr('next')}</button></nav></>}
    {caseId && <DisputeCaseDetail key={caseId} caseId={caseId} periodId={periodId} principal={principal} generation={`${generation}:${retry}`} tr={tr} locale={locale}
      onDenied={onDenied} onClose={() => setCaseId(null)} onEvent={canWrite && onEvent ? (...args) => { if (isAllowed()) onEvent(...args); } : undefined} />}
  </section>;
}

export default function BillingDisputeRead(props) {
  const principal = principalKey(useAuth()?.user);
  if (!principal || !props.periodId) return null;
  return <ReadWorkspace key={`${principal}:${props.periodId}`} {...props} principal={principal} />;
}
