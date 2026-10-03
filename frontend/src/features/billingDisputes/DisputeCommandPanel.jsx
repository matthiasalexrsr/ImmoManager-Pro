import { useEffect, useId, useRef, useState } from 'react';
import { useTranslation } from '../../i18n';
import { denied, DISPUTES, permittedEvents, readCase, readEvent, readStatement, readStatus } from './disputeModel';
import { disputeText } from './disputeCopy';
import { DisputeFailure, EventOriginal, OriginalEvidence, OriginalSnapshot } from './DisputeOriginals';
import DisputeReferenceChoice from './DisputeReferenceChoice';
import OriginalEvidencePicker from './OriginalEvidencePicker';
import useDisputeCommand from './useDisputeCommand';
import useDisputeRead from './useDisputeRead';

function DraftControls({ state, tr, t }) {
  const { draft, phase, cleanup } = state;
  const available = draft.status === 'available'; const pending = Boolean(draft.draft?.submission_pending);
  return <section className="dispute-draft" aria-label={t('formDraft.title')}>
    <p role="status">{phase === 'saved' ? tr('saved') : t(`formDraft.status.${draft.status}`)}</p>
    {available && <><p>{t(pending ? 'formDraft.pendingRestore' : 'formDraft.restoreHint')}</p>
      {!draft.schemaMatches && <p role="alert">{t('formDraft.schemaChanged')}</p>}
      <div className="dispute-actions"><button type="button" className="btn btn-secondary" disabled={!draft.schemaMatches} onClick={draft.restore}>{t(pending ? 'formDraft.restoreAfterReview' : 'formDraft.restore')}</button>
        {!pending && <button type="button" className="btn btn-secondary" onClick={draft.discard}>{t('formDraft.discard')}</button>}</div></>}
    {draft.error && <p role="alert">{draft.error}</p>}
    {phase === 'saved' && <><p>{t('formDraft.cleanupHint')}</p><button type="button" className="btn btn-secondary" onClick={cleanup}>{t('formDraft.cleanupRetry')}</button></>}
    {['error', 'conflict'].includes(draft.status) && !['unknown', 'confirming', 'saved'].includes(phase) && <button type="button" className="btn btn-secondary" onClick={draft.status === 'conflict' ? draft.inspect : draft.retry}>{t(draft.status === 'conflict' ? 'formDraft.inspect' : 'ui.buttons.retry')}</button>}
  </section>;
}

function Source({ state, periodId, caseId, principal, tr, locale, onDenied, children }) {
  const { command, change, locked } = state; const [retry, setRetry] = useState(0);
  const path = caseId ? `${DISPUTES}/${encodeURIComponent(caseId)}` : command.case_kind === 'property_review'
    ? `${DISPUTES}/periods/${encodeURIComponent(periodId)}/status`
    : command.statement_id ? `/billing/statements/${encodeURIComponent(command.statement_id)}` : null;
  const read = useDisputeRead(path, principal, retry, row => caseId ? readCase(row, caseId, periodId)
    : command.case_kind === 'property_review' ? readStatus(row, periodId) : readStatement(row, command.statement_id, periodId), onDenied);
  const source = read.data;
  const snapshot = caseId ? source?.original_snapshot : command.case_kind === 'property_review' ? source?.property_review_original : source;
  const allowed = !caseId || source && permittedEvents(source.state, source.case_kind).includes(command.kind);
  const matches = Boolean(source && allowed && (caseId ? source.revision === command.expected_revision : command.case_kind === 'property_review'
    ? source.property_review_snapshot_hash === command.expected_snapshot_hash && snapshot
    : source.revision === command.expected_statement_revision && source.snapshot_hash === command.expected_snapshot_hash));
  const adopt = () => change(caseId ? { expected_revision: source.revision } : command.case_kind === 'property_review'
    ? { expected_snapshot_hash: source.property_review_snapshot_hash, line_item_refs: [] }
    : { expected_statement_revision: source.revision, expected_snapshot_hash: source.snapshot_hash, line_item_refs: [] });
  return <>
    {!caseId && <><label>{tr('chooseType')}<select disabled={locked} value={command.case_kind} onChange={event => change({ case_kind: event.target.value, statement_id: null, expected_statement_revision: null, expected_snapshot_hash: null, line_item_refs: [] })}>
      <option value="tenant_statement">{tr('tenant_statement')}</option><option value="property_review">{tr('property_review')}</option></select></label>
      {command.case_kind === 'tenant_statement' && <DisputeReferenceChoice kind="statements" label={tr('chooseStatement')} filters={{ period_id: periodId }} principal={principal} value={command.statement_id || ''} tr={tr} onDenied={onDenied} disabled={locked}
        onChange={id => change({ statement_id: id || null, expected_statement_revision: null, expected_snapshot_hash: null, line_item_refs: [] })} />}</>}
    {path && read.loading && <p role="status">{tr('loading')}</p>}
    {path && read.error && <DisputeFailure error={read.error} tr={tr} onRetry={() => setRetry(value => value + 1)} />}
    {source && <>{caseId && <p>{tr('case')} · {tr('revision')} {source.revision}</p>}<p>{command.case_kind === 'property_review' || source.case_kind === 'property_review' ? tr('propertyParty') : source.party_binding_note || tr('partyUnknown')}</p>
      {!allowed && <p role="alert">{tr('actionUnavailable')}</p>}
      {!matches && snapshot && allowed && <><p role="status">{tr('sourceChanged')}</p><button className="btn btn-secondary" type="button" disabled={locked} onClick={adopt}>{tr('adoptSource')}</button></>}
      {!snapshot && <p role="alert">{tr('ownerOriginalMissing')}</p>}
      {snapshot && <OriginalSnapshot key={JSON.stringify([snapshot.id || snapshot.period_id, snapshot.revision])} snapshot={snapshot} tr={tr} locale={locale} selected={command.line_item_refs || []}
        onSelect={!caseId && command.case_kind === 'tenant_statement' && matches ? refs => change({ line_item_refs: refs }) : undefined} disabled={locked} />}
      <button type="button" className="btn btn-secondary" disabled={locked} onClick={() => setRetry(value => value + 1)}>{tr('refresh')}</button></>}
    {children(matches)}
  </>;
}

function CorrectionSource({ command, caseId, principal, disabled, change, tr, locale, onDenied, children }) {
  const [choice, setChoice] = useState(null);
  const statementId = command.correction_statement_id;
  const originalEvent = useDisputeRead(command.corrects_event_id ? `${DISPUTES}/${encodeURIComponent(caseId)}/events/${encodeURIComponent(command.corrects_event_id)}` : null,
    principal, 0, row => readEvent(row, caseId), onDenied);
  const selected = choice?.id === statementId ? choice : null;
  const statement = useDisputeRead(selected ? `/billing/statements/${encodeURIComponent(statementId)}` : null,
    principal, selected?.billing_period_id, row => {
      readStatement(row, statementId, selected.billing_period_id);
      if (row.contract_id !== selected.contract_id || row.unit_id !== selected.unit_id || row.revision !== selected.revision || row.snapshot_hash !== selected.snapshot_hash) throw new Error('invalidDisputeResponse');
      return row;
    }, onDenied);
  const correction = command.kind === 'correction'; const link = command.kind === 'correction_link';
  return <>
    {correction && <>{originalEvent.loading && <p role="status">{tr('loading')}</p>}{originalEvent.error && <DisputeFailure error={originalEvent.error} tr={tr} />}
      {originalEvent.data && <section aria-label={tr('correctionTarget')}><h3>{tr('correctionTarget')}</h3><EventOriginal event={originalEvent.data} tr={tr} locale={locale} onDenied={onDenied} /></section>}</>}
    {link && <><DisputeReferenceChoice kind="statements" filters={{ dispute_case_id: caseId }} label={tr('statementLink')} principal={principal} value={statementId || ''} disabled={disabled} tr={tr} onDenied={onDenied} onResolved={setChoice} onChange={id => change({ correction_statement_id: id || null })} />
      {selected && statement.loading && <p role="status">{tr('loading')}</p>}{selected && statement.error && <DisputeFailure error={statement.error} tr={tr} />}
      {statement.data && <OriginalSnapshot key={statement.data.id} snapshot={statement.data} locale={locale} tr={tr} />}</>}
    {children(!correction && !link || correction && Boolean(originalEvent.data) || link && Boolean(statement.data))}
  </>;
}

/** Domain preview is reviewed, durably prepared, then confirmed byte-for-byte. */
export default function DisputeCommandPanel({ periodId, propertyId, caseId = '', principal, initialCommand, onDenied, onSaved, onClose }) {
  const { locale, t } = useTranslation(); const tr = key => disputeText(locale, key); const titleId = useId(); const reasonId = useId(); const dateId = useId(); const heading = useRef(null);
  const state = useDisputeCommand({ periodId, caseId, initialCommand, onDenied, onSaved, onClose });
  const { command, review, phase, error, locked, enabled, change } = state;
  useEffect(() => { heading.current?.focus(); }, []);
  useEffect(() => { if (denied({ statusCode: state.draft.errorStatus })) onDenied?.(); }, [state.draft.errorStatus, onDenied]);
  const validInputs = Boolean(command?.reason?.trim() && /^\d{4}-\d{2}-\d{2}$/.test(command?.[caseId ? 'observed_on' : 'received_on'] || ''));
  const editable = ['editing', 'conflict'].includes(phase);
  const previewButton = sourcesMatch => <button className="btn btn-primary" type="button" disabled={!enabled || !validInputs || !sourcesMatch} onClick={state.preview}>{tr('preview')}</button>;
  return <section className="billing-disputes dispute-command panel" aria-labelledby={titleId} aria-busy={['preparing', 'confirming'].includes(phase)}>
    <h2 id={titleId} ref={heading} tabIndex={-1}>{tr(caseId ? 'newEvent' : 'newCase')}{caseId && command ? ` · ${tr(command.kind)}` : ''}</h2>
    <p>{tr('financial')}</p><DraftControls state={state} tr={tr} t={t} />
    {error && <DisputeFailure error={error} tr={tr} />}
    {phase === 'conflict' && <p role="alert">{tr('conflict')}</p>}
    {command && editable && <><label htmlFor={reasonId}>{tr('reason')}</label><textarea id={reasonId} value={command.reason} disabled={locked} required onChange={event => change({ reason: event.target.value })} />
      <label htmlFor={dateId}>{tr(caseId ? 'observed' : 'received')}</label><input id={dateId} type="date" value={command[caseId ? 'observed_on' : 'received_on']} disabled={locked} required onChange={event => change({ [caseId ? 'observed_on' : 'received_on']: event.target.value })} />
      <OriginalEvidencePicker propertyId={propertyId} principal={principal} value={command.evidence_version_ids} onChange={ids => change({ evidence_version_ids: ids })} disabled={locked} tr={tr} onDenied={onDenied} />
      <Source state={state} periodId={periodId} caseId={caseId} principal={principal} tr={tr} locale={locale} onDenied={onDenied}>
        {matches => caseId ? <CorrectionSource command={command} periodId={periodId} caseId={caseId} principal={principal} disabled={locked} change={change} tr={tr} locale={locale} onDenied={onDenied}>{correct => previewButton(matches && correct)}</CorrectionSource> : previewButton(matches)}
      </Source></>}
    {review && ['review', 'unknown', 'confirming'].includes(phase) && <section className="dispute-preview" aria-label={tr('review')}><h3>{tr('review')}</h3>
      <p>{tr(command.kind || 'opened')}</p><p className="dispute-reason">{command.reason}</p><p>{tr('actualDate')}: {command.received_on || command.observed_on}</p>
      {caseId && <p>{tr('case')} · {tr('revision')} {command.expected_revision}</p>}
      {command.line_item_refs?.length > 0 && <p>{tr('positions')}: {command.line_item_refs.map(index => index + 1).join(', ')}</p>}
      <p>{review.binding.party_binding_note || tr(command.case_kind === 'property_review' || review.binding.case_kind === 'property_review' ? 'propertyParty' : 'partyUnknown')}</p>
      <OriginalSnapshot snapshot={review.binding.original_snapshot} selected={command.line_item_refs || []} tr={tr} locale={locale} />
      {review.correction && <section aria-label={tr('statementLink')}><h4>{tr('statementLink')}</h4><pre>{JSON.stringify(review.correction, null, 2)}</pre></section>}
      {command.corrects_event_id && <p>{tr('correctionTarget')}: <code>{command.corrects_event_id}</code></p>}
      <OriginalEvidence items={review.evidence} tr={tr} locale={locale} onDenied={onDenied} />
      <details><summary>{tr('technical')}</summary><pre>{JSON.stringify({ request: command, preview_hash: review.preview_hash }, null, 2)}</pre></details>
      {phase === 'unknown' && <p role="alert">{tr('unknown')}</p>}
      <div className="dispute-actions">{phase === 'review' && <button type="button" className="btn btn-secondary" disabled={!enabled} onClick={() => change({})}>{tr('edit')}</button>}
        <button type="button" className="btn btn-primary" disabled={phase === 'confirming' || !state.canWrite || !state.draft.enabled} onClick={state.confirm}>{tr(phase === 'unknown' ? 'exactRetry' : 'confirm')}</button></div>
    </section>}
    <button type="button" className="btn btn-secondary" disabled={['preparing', 'confirming'].includes(phase)} onClick={state.close}>{tr('close')}</button>
  </section>;
}
