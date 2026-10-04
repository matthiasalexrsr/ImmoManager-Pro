import { useEffect, useRef, useState } from 'react';
import { DISPUTES, PAGE_SIZE, permittedEvents, readCase, readEvent, readJournal } from './disputeModel';
import { DisputeFailure, EventOriginal, OriginalSnapshot } from './DisputeOriginals';
import useDisputeRead from './useDisputeRead';

function OriginalEventRead({ caseId, eventId, principal, generation, tr, locale, onDenied, onCorrection, onClose }) {
  const [retry, setRetry] = useState(0);
  const state = useDisputeRead(`${DISPUTES}/${encodeURIComponent(caseId)}/events/${encodeURIComponent(eventId)}`, principal,
    `${generation}:${retry}`, row => readEvent(row, caseId), onDenied);
  return <section aria-label={tr('originalEvent')} className="dispute-original-event"><h3>{tr('originalEvent')}</h3>
    <button className="btn btn-secondary" type="button" onClick={onClose}>{tr('close')}</button>
    {state.loading && <p role="status">{tr('loading')}</p>}
    {state.error && <DisputeFailure error={state.error} tr={tr} onRetry={() => setRetry(value => value + 1)} />}
    {state.data && <><EventOriginal event={state.data} tr={tr} locale={locale} onDenied={onDenied} />
      {onCorrection && <button className="btn btn-secondary" type="button" onClick={() => onCorrection(state.data)}>{tr('action_correction')}</button>}</>}
  </section>;
}

function Chronicle({ caseId, principal, generation, tr, locale, onDenied, onCorrection }) {
  const [pages, setPages] = useState({ source: '', trail: [0] }); const [retry, setRetry] = useState(0);
  const [eventId, setEventId] = useState(null);
  const source = JSON.stringify([caseId, generation, retry]); const trail = pages.source === source ? pages.trail : [0];
  const after = trail.at(-1);
  const state = useDisputeRead(`${DISPUTES}/${encodeURIComponent(caseId)}/journal?after=${after}&page_size=${PAGE_SIZE}`,
    principal, `${generation}:${retry}`, page => readJournal(page, caseId, after), onDenied);
  return <section aria-label={tr('history')} className="dispute-chronicle"><h3>{tr('history')}</h3>
    {state.loading && <p role="status">{tr('loading')}</p>}
    {state.error && <DisputeFailure error={state.error} tr={tr} onRetry={() => setRetry(value => value + 1)} />}
    {state.data && <>{!state.data.items.length ? <p>{tr('noHistory')}</p> : <ol>{state.data.items.map(event => <li key={event.id}>
      <EventOriginal event={event} tr={tr} locale={locale} onDenied={onDenied} />
      <button type="button" className="btn btn-secondary" onClick={() => setEventId(event.id)}>{tr('showOriginal')} · {tr('revision')} {event.revision}</button>
    </li>)}</ol>}
    <nav className="dispute-actions" aria-label={tr('history')}><button className="btn btn-secondary" type="button" disabled={trail.length === 1} onClick={() => setPages({ source, trail: trail.slice(0, -1) })}>{tr('previous')}</button>
      <span>{tr('page')} {trail.length}</span><button className="btn btn-secondary" type="button" disabled={state.data.next_after === null} onClick={() => setPages({ source, trail: [...trail, state.data.next_after] })}>{tr('next')}</button></nav></>}
    {eventId && <OriginalEventRead key={eventId} caseId={caseId} eventId={eventId} principal={principal} generation={generation} tr={tr} locale={locale}
      onDenied={onDenied} onCorrection={onCorrection} onClose={() => setEventId(null)} />}
  </section>;
}

export default function DisputeCaseDetail({ caseId, periodId, principal, generation, tr, locale, onDenied, onClose, onEvent }) {
  const [retry, setRetry] = useState(0); const heading = useRef(null);
  const state = useDisputeRead(`${DISPUTES}/${encodeURIComponent(caseId)}`, principal, `${generation}:${retry}`,
    row => readCase(row, caseId, periodId), onDenied);
  useEffect(() => { if (state.data) heading.current?.focus(); }, [state.data]);
  const row = state.data;
  return <section className="dispute-case panel" aria-label={tr('case')}>
    <h2 ref={heading} tabIndex={-1}>{tr('case')}</h2><button type="button" className="btn btn-secondary" onClick={onClose}>{tr('close')}</button>
    {state.loading && <p role="status">{tr('loading')}</p>}
    {state.error && <DisputeFailure error={state.error} tr={tr} onRetry={() => setRetry(value => value + 1)} />}
    {row && <><dl className="dispute-facts"><div><dt>{tr('chooseType')}</dt><dd>{tr(row.case_kind)}</dd></div><div><dt>{tr('status')}</dt><dd>{tr(row.state)}</dd></div><div><dt>{tr('revision')}</dt><dd>{row.revision}</dd></div></dl>
      <p>{row.case_kind === 'property_review' ? tr('propertyParty') : row.party_binding_note || tr('partyUnknown')}</p>
      <p>{tr('financial')}</p>
      <details><summary>{tr('technical')}</summary><dl>{[['case', row.id], ['sourceStatement', row.statement_id], ['originalContract', row.contract_id], ['originalUnit', row.unit_id], ['snapshotHash', row.snapshot_hash], ['originalHash', row.original_hash]].map(([name, value]) => value && <div key={name}><dt>{tr(name)}</dt><dd>{value}</dd></div>)}</dl></details>
      <OriginalSnapshot key={row.original_hash} snapshot={row.original_snapshot} locale={locale} tr={tr} />
      {onEvent && <div className="dispute-actions">{permittedEvents(row.state, row.case_kind).filter(kind => kind !== 'correction').map(kind => <button type="button" className="btn btn-secondary" key={kind} onClick={() => onEvent(row, kind)}>{tr(`action_${kind}`)}</button>)}</div>}
      <Chronicle key={row.id} caseId={caseId} principal={principal} generation={`${generation}:${retry}`} tr={tr} locale={locale} onDenied={onDenied}
        onCorrection={onEvent ? event => onEvent(row, 'correction', event) : undefined} />
    </>}
  </section>;
}
