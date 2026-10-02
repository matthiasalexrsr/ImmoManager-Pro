import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { CheckCircle2, Circle, FileCheck2, Link2, LockKeyhole, RefreshCw } from 'lucide-react';
import EvidenceLinkDialog from './EvidenceLinkDialog';
import WorkflowCommandNotice from './WorkflowCommandNotice';
import WorkflowTechnicalDetails from './WorkflowTechnicalDetails';
import useWorkflowCommand from './useWorkflowCommand';
import {
  actionAllowed,
  displayEvidenceReference,
  validateTenancyChange,
} from './tenancyWorkflowModel';
import { workflowText } from './workflowCopy';
import './TenancyWorkflows.css';

function statusIcon(state) {
  if (state === 'completed' || state === 'not_applicable') return <CheckCircle2 size={18} aria-hidden="true" />;
  if (state === 'blocked') return <LockKeyhole size={18} aria-hidden="true" />;
  return <Circle size={18} aria-hidden="true" />;
}

function evidenceAction(step, canLinkEvidence) {
  if (!actionAllowed(step, 'link_document')) return false;
  if (typeof canLinkEvidence === 'function') return canLinkEvidence(step);
  return true;
}

function formatDate(value, locale) {
  if (!value) return '—';
  const parsed = /^\d{4}-\d{2}-\d{2}$/.test(value)
    ? new Date(`${value}T00:00:00Z`)
    : new Date(value);
  if (!Number.isFinite(parsed.getTime())) return String(value);
  return new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeZone: 'UTC' }).format(parsed);
}

function formatDateTime(value, locale) {
  if (!value) return '—';
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return String(value);
  return new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' }).format(date);
}

function evidenceTypeKey(link) {
  if (link.kind === 'document_version') return 'evidence_document_original';
  if (link.kind === 'handover_protocol') return 'evidence_handover_protocol';
  return 'evidence_meter_reading';
}

function normalizedReanchor(value) {
  if (!value || typeof value !== 'object') return null;
  return {
    preview_hash: typeof value.preview_hash === 'string' ? value.preview_hash : null,
    affected_steps: Array.isArray(value.affected_steps) ? value.affected_steps : [],
  };
}

export default function TenancyChangeFile({
  change,
  propertyLabel = null,
  unitLabel = null,
  previousContractLabel = null,
  nextContractLabel = null,
  assigneeNames = {},
  locale = 'de-DE',
  principalKey = '',
  prepareStepMutation,
  prepareTaskLink,
  prepareCancel,
  prepareComplete,
  onReanchorPreview,
  normalizeReanchorPreview = normalizedReanchor,
  prepareReanchor,
  prepareEvidenceLink,
  prepareUnlinkEvidence,
  canLinkEvidence,
  canSelectEvidence,
  loadDocuments,
  loadDocumentVersions,
  loadHandoverProtocols,
  loadMeterReadings,
  onChanged,
  onReviewCurrent,
  onOpenTask,
}) {
  const checked = useMemo(() => validateTenancyChange(change), [change]);
  const [base, setBase] = useState(checked);
  const [exceptionReasons, setExceptionReasons] = useState({});
  const [cancelReason, setCancelReason] = useState('');
  const [evidenceStep, setEvidenceStep] = useState(null);
  const [reanchorOpen, setReanchorOpen] = useState(false);
  const [reanchorDates, setReanchorDates] = useState(() => ({
    move_out_handover_date: checked.move_out_handover_date || '',
    move_in_handover_date: checked.move_in_handover_date || '',
  }));
  const [reanchorPreview, setReanchorPreview] = useState(null);
  const [reanchorView, setReanchorView] = useState(null);
  const [reanchorError, setReanchorError] = useState(null);
  const [reanchorLoading, setReanchorLoading] = useState(false);
  const request = useRef(null);
  const command = useWorkflowCommand(principalKey);
  const tr = useCallback((key, params) => workflowText(locale, key, params), [locale]);

  useEffect(() => () => request.current?.abort(), []);
  useEffect(() => {
    if (checked.id !== base.id || checked.revision !== base.revision) {
      setBase(checked);
      if (command.state.phase !== 'unknown') {
        setReanchorDates({
          move_out_handover_date: checked.move_out_handover_date || '',
          move_in_handover_date: checked.move_in_handover_date || '',
        });
        setReanchorPreview(null);
        setReanchorView(null);
      }
    }
  }, [base.id, base.revision, checked, command.state.phase]);

  const applyChange = useCallback(result => {
    const next = validateTenancyChange(result);
    setBase(next);
    setReanchorDates({
      move_out_handover_date: next.move_out_handover_date || '',
      move_in_handover_date: next.move_in_handover_date || '',
    });
    setReanchorPreview(null);
    setReanchorView(null);
    setReanchorError(null);
    setCancelReason('');
    onChanged?.(next);
    return next;
  }, [onChanged]);

  const runPrepared = useCallback((prepared, label) => {
    if (!prepared || !prepared.payload || typeof prepared.send !== 'function') {
      setReanchorError(tr('missingAdapter'));
      return;
    }
    command.execute({
      label,
      payload: prepared.payload,
      send: prepared.send,
      onSuccess: result => {
        const next = typeof prepared.apply === 'function' ? prepared.apply(result, base) : result;
        return applyChange(next);
      },
    });
  }, [applyChange, base, command, tr]);

  const mutateStep = (step, patch, label) => {
    runPrepared(prepareStepMutation?.({ change: base, step, patch }), label);
  };

  const linkTask = step => {
    runPrepared(prepareTaskLink?.({ change: base, step }), 'link-task');
  };

  const cancel = () => {
    const reason = cancelReason.trim();
    if (!reason) return;
    runPrepared(prepareCancel?.({ change: base, reason }), 'cancel-tenancy-change');
  };

  const complete = () => {
    runPrepared(prepareComplete?.({ change: base }), 'complete-tenancy-change');
  };

  const updateReanchorDate = (field, value) => {
    setReanchorDates(current => ({ ...current, [field]: value }));
    setReanchorPreview(null);
    setReanchorView(null);
    setReanchorError(null);
    if (command.state.phase !== 'unknown') command.reset();
  };

  const previewReanchor = async () => {
    if (typeof onReanchorPreview !== 'function') {
      setReanchorError(tr('missingAdapter'));
      return;
    }
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setReanchorLoading(true);
    setReanchorError(null);
    try {
      const result = await onReanchorPreview({ change: base, dates: reanchorDates }, { signal: controller.signal });
      if (controller.signal.aborted) return;
      if (!result || typeof result.preview_hash !== 'string' || !result.preview_hash) {
        throw new Error('invalid_reanchor_preview');
      }
      setReanchorPreview(result);
      setReanchorView(normalizeReanchorPreview?.(result) || { preview_hash: result.preview_hash, affected_steps: [] });
    } catch (error) {
      if (!controller.signal.aborted) setReanchorError(error.message);
    } finally {
      if (!controller.signal.aborted) setReanchorLoading(false);
    }
  };

  const applyReanchor = () => {
    if (!reanchorPreview) return;
    runPrepared(prepareReanchor?.({ change: base, dates: reanchorDates, preview: reanchorPreview }), 'reanchor-tenancy-change');
  };

  const requiredSteps = base.steps.filter(step => step.requirement === 'required');
  const satisfiedRequired = requiredSteps.filter(step => ['completed', 'not_applicable'].includes(step.state)).length;
  const directions = base.mode === 'turnover' ? ['move_out', 'move_in'] : [base.mode];
  const stepTitleById = useMemo(
    () => new Map(base.steps.map(step => [step.id, step.title_snapshot])),
    [base.steps],
  );

  return (
    <section className="workflow-shell workflow-change" aria-busy={command.busy || reanchorLoading}>
      <header className="workflow-shell__header">
        <div>
          <span className="workflow-eyebrow">{tr('eyebrow')}</span>
          <h2>{tr('changeTitle')}</h2>
          <p className="workflow-muted">
            {tr(base.mode)} · {propertyLabel || tr('propertyUnavailable')} · {unitLabel || tr('unitUnavailable')}
          </p>
        </div>
        <div className="workflow-badges">
          <span className={`workflow-badge workflow-badge--${base.state}`}>{tr(base.state)}</span>
          <span className="workflow-badge">{satisfiedRequired}/{requiredSteps.length} {tr('required')}</span>
        </div>
      </header>

      <WorkflowCommandNotice state={command.state} locale={locale}
        onRetryExact={command.retryExact}
        onReviewCurrent={() => onReviewCurrent?.({ change: base })}
        onDismiss={command.reset} />
      {reanchorError && <div className="workflow-inline-error" role="alert">{reanchorError}</div>}

      <div className="workflow-change__summary">
        <dl className="workflow-facts">
          <div><dt>{tr('previousContract')}</dt><dd>{base.previous_contract_id ? (previousContractLabel || tr('contractUnavailable')) : '—'}</dd></div>
          <div><dt>{tr('nextContract')}</dt><dd>{base.next_contract_id ? (nextContractLabel || tr('contractUnavailable')) : '—'}</dd></div>
          <div><dt>{tr('moveOutHandoverDate')}</dt><dd>{formatDate(base.move_out_handover_date, locale)}</dd></div>
          <div><dt>{tr('moveInHandoverDate')}</dt><dd>{formatDate(base.move_in_handover_date, locale)}</dd></div>
        </dl>
        <p className="workflow-note">{tr('originalsStay')}</p>
        <WorkflowTechnicalDetails locale={locale} rows={[
          { label: tr('technicalIdentifier'), value: base.id },
          { label: tr('revision'), value: base.revision },
          { label: 'ETag', value: base.etag },
          { label: tr('checksum'), value: base.snapshot_sha256 },
          { label: tr('propertyScope'), value: base.property_id },
          { label: tr('unitScope'), value: base.unit_id },
          { label: tr('previousContract'), value: base.previous_contract_id },
          { label: tr('nextContract'), value: base.next_contract_id },
        ]} />
      </div>

      {directions.map(direction => (
        <section key={direction} className="workflow-change__lane">
          <header>
            <h3>{tr(direction)}</h3>
            <span>{base.steps.filter(step => step.direction === direction).length}</span>
          </header>
          <div className="workflow-change__steps">
            {base.steps.filter(step => step.direction === direction).map(step => (
              <article key={step.id} className={`workflow-step-card workflow-step-card--${step.state}`}>
                <header>
                  <div className="workflow-step-card__state">
                    {statusIcon(step.state)}
                    <div>
                      <h4>{step.title_snapshot}</h4>
                      <span>{tr(step.state)} · {tr(step.requirement)}</span>
                    </div>
                  </div>
                  <span className="workflow-badge">{tr(step.anchor)} {step.offset_days >= 0 ? '+' : ''}{step.offset_days}</span>
                </header>

                {step.description_snapshot && <p>{step.description_snapshot}</p>}
                <dl className="workflow-step-card__dates">
                  <div><dt>{tr('dueDate')}</dt><dd>{formatDate(step.due_date, locale)}</dd></div>
                  <div><dt>{tr('originalDueDate')}</dt><dd>{formatDate(step.original_due_date, locale)}</dd></div>
                </dl>

                {step.blocked_by_step_ids.length > 0 && (
                  <p className="workflow-blocked"><LockKeyhole size={15} aria-hidden="true" />
                    {tr('blockedBy')}: {step.blocked_by_step_ids
                      .map(id => stepTitleById.get(id) || tr('unnamedStep'))
                      .join(', ')}</p>
                )}

                <div className="workflow-step-card__responsibility">
                  <strong>{tr('responsibility')}:</strong>{' '}
                  {step.assignee_user_id
                    ? (assigneeNames[step.assignee_user_id] || tr('user'))
                    : tr(`role_${step.assignee_role}`)}
                </div>

                <section className="workflow-step-card__evidence">
                  <h5><FileCheck2 size={15} aria-hidden="true" /> {tr('evidence')}</h5>
                  {step.evidence_requirement && <p className="workflow-muted">{tr(`evidence_${step.evidence_requirement}`)}</p>}
                  {step.evidence_links.length === 0
                    ? <p>{tr('noEvidence')}</p>
                    : <ul>{step.evidence_links.map(link => (
                      <li key={link.id}>
                        <div className="workflow-evidence-main">
                          <strong>{tr(evidenceTypeKey(link))}</strong>
                          <small>
                            {tr(step.direction)} · {tr('evidenceLinkedAt')} {formatDateTime(link.created_at, locale)}
                          </small>
                          <WorkflowTechnicalDetails locale={locale} rows={[
                            { label: tr('technicalIdentifier'), value: link.id },
                            { label: tr('evidenceReference'), value: displayEvidenceReference(link) },
                            { label: tr('checksum'), value: link.snapshot_sha256 },
                          ]} />
                        </div>
                        {typeof prepareUnlinkEvidence === 'function' && actionAllowed(step, 'link_document') && (
                          <button type="button" className="workflow-link-button"
                            aria-label={tr('removeEvidence')}
                            disabled={command.busy || command.state.phase === 'unknown'}
                            onClick={() => runPrepared(
                              prepareUnlinkEvidence({ change: base, step, link }),
                              'unlink-evidence',
                            )}>
                            ×
                          </button>
                        )}
                      </li>
                    ))}</ul>}
                  {evidenceAction(step, canLinkEvidence) && (
                    <button type="button" className="btn btn-secondary btn-sm"
                      disabled={command.busy || command.state.phase === 'unknown'}
                      onClick={() => setEvidenceStep(step)}>
                      <Link2 size={15} aria-hidden="true" /> {tr('addEvidence')}
                    </button>
                  )}
                </section>

                {step.state === 'not_applicable' && (
                  <p className="workflow-exception"><strong>{tr('exceptionReason')}:</strong> {step.not_applicable_reason}</p>
                )}
                {step.completed_at && (
                  <p className="workflow-muted">{tr('completedAt')}: {formatDateTime(step.completed_at, locale)}</p>
                )}

                <WorkflowTechnicalDetails locale={locale} rows={[
                  { label: tr('technicalIdentifier'), value: step.id },
                  { label: tr('templateKey'), value: step.template_step_key },
                  { label: tr('revision'), value: step.revision },
                  { label: 'ETag', value: step.etag },
                  { label: tr('task'), value: step.task_id },
                  { label: tr('user'), value: step.assignee_user_id },
                  { label: tr('completedBy'), value: step.completed_by },
                ]} />

                <footer className="workflow-step-card__actions">
                  {step.task_id
                    ? <button type="button" className="btn btn-secondary btn-sm" onClick={() => onOpenTask?.(step.task_id)}>
                      {tr('openTask')}
                    </button>
                    : actionAllowed(step, 'link_task') && (
                      <button type="button" className="btn btn-secondary btn-sm"
                        disabled={command.busy || command.state.phase === 'unknown'} onClick={() => linkTask(step)}>
                        {tr('createTask')}
                      </button>
                    )}

                  {actionAllowed(step, 'complete_step') && !['completed', 'not_applicable'].includes(step.state) && (
                    <>
                      {step.state === 'open' && (
                        <button type="button" className="btn btn-secondary btn-sm"
                          disabled={command.busy || command.state.phase === 'unknown'}
                          onClick={() => mutateStep(step, { state: 'in_progress' }, 'start-step')}>
                          {tr('markInProgress')}
                        </button>
                      )}
                      <button type="button" className="btn btn-primary btn-sm"
                        disabled={command.busy || command.state.phase === 'unknown'}
                        onClick={() => mutateStep(step, { state: 'completed' }, 'complete-step')}>
                        {tr('completeStep')}
                      </button>
                    </>
                  )}
                </footer>

                {actionAllowed(step, 'complete_step') && !['completed', 'not_applicable'].includes(step.state) && (
                  <div className="workflow-not-applicable">
                    <label>
                      <span>{tr('exceptionReason')}</span>
                      <input value={exceptionReasons[step.id] || ''}
                        disabled={command.busy || command.state.phase === 'unknown'}
                        onChange={event => setExceptionReasons(current => ({ ...current, [step.id]: event.target.value }))} />
                    </label>
                    <button type="button" className="btn btn-secondary btn-sm"
                      disabled={command.busy || command.state.phase === 'unknown' || !(exceptionReasons[step.id] || '').trim()}
                      onClick={() => mutateStep(step, {
                        state: 'not_applicable',
                        not_applicable_reason: exceptionReasons[step.id].trim(),
                      }, 'not-applicable-step')}>
                      {tr('notApplicable')}
                    </button>
                  </div>
                )}
              </article>
            ))}
          </div>
        </section>
      ))}

      {actionAllowed(base, 'reanchor') && (
        <section className="workflow-reanchor">
          <button type="button" className="workflow-reanchor__toggle" disabled={command.busy}
            onClick={() => setReanchorOpen(value => !value)}>
            <RefreshCw size={16} aria-hidden="true" /> {tr('reanchorTitle')}
          </button>
          {reanchorOpen && (
            <div className="workflow-reanchor__body">
              <div className="workflow-form-grid">
                {base.mode !== 'move_in' && (
                  <label className="workflow-field">
                    <span>{tr('moveOutHandoverDate')}</span>
                    <input type="date" value={reanchorDates.move_out_handover_date}
                      disabled={reanchorLoading || command.busy}
                      onChange={event => updateReanchorDate('move_out_handover_date', event.target.value)} />
                  </label>
                )}
                {base.mode !== 'move_out' && (
                  <label className="workflow-field">
                    <span>{tr('moveInHandoverDate')}</span>
                    <input type="date" value={reanchorDates.move_in_handover_date}
                      disabled={reanchorLoading || command.busy}
                      onChange={event => updateReanchorDate('move_in_handover_date', event.target.value)} />
                  </label>
                )}
              </div>
              <button type="button" className="btn btn-secondary"
                disabled={reanchorLoading || command.busy || command.state.phase === 'unknown'}
                onClick={previewReanchor}>{reanchorLoading ? tr('loading') : tr('previewReanchor')}</button>
              {reanchorPreview && (
                <div className="workflow-preview">
                  <div className="workflow-preview__heading">
                    <CheckCircle2 size={19} aria-hidden="true" />
                    <strong>{tr('previewReady')}</strong>
                  </div>
                  <h4>{tr('changedSteps')}</h4>
                  {reanchorView?.affected_steps?.length
                    ? <ul>{reanchorView.affected_steps.map((item, index) => (
                      <li key={item.step_id || item.id || index}>
                        <strong>{stepTitleById.get(item.step_id) || tr('unnamedStep')}</strong>
                        {item.current_due_date && item.new_due_date ? ` · ${formatDate(item.current_due_date, locale)} → ${formatDate(item.new_due_date, locale)}` : ''}
                      </li>
                    ))}</ul>
                    : <p>{tr('noChanges')}</p>}
                  <WorkflowTechnicalDetails locale={locale} rows={[
                    { label: tr('checksum'), value: reanchorPreview.preview_hash },
                    { label: tr('revision'), value: reanchorPreview.change_revision },
                    { label: tr('sourceEtags'), value: reanchorPreview.source_etags },
                    { label: tr('changedSteps'), value: reanchorPreview.affected_steps?.map(item => item.step_id) },
                  ]} />
                  <button type="button" className="btn btn-primary"
                    disabled={command.busy || command.state.phase === 'unknown'} onClick={applyReanchor}>
                    {tr('applyReanchor')}
                  </button>
                </div>
              )}
            </div>
          )}
        </section>
      )}

      {actionAllowed(base, 'edit_change') && !['completed', 'cancelled'].includes(base.state) && (
        <section className="workflow-cancel">
          <label className="workflow-field">
            <span>{tr('cancelReason')}</span>
            <input value={cancelReason}
              disabled={command.busy || command.state.phase === 'unknown'}
              onChange={event => setCancelReason(event.target.value)} />
          </label>
          <button type="button" className="btn btn-secondary"
            disabled={command.busy || command.state.phase === 'unknown' || !cancelReason.trim()}
            onClick={cancel}>
            {tr('cancelChange')}
          </button>
        </section>
      )}

      {actionAllowed(base, 'complete_change') && (
        <footer className="workflow-actions workflow-actions--end">
          <button type="button" className="btn btn-primary"
            disabled={command.busy || command.state.phase === 'unknown'} onClick={complete}>
            {tr('completeChange')}
          </button>
        </footer>
      )}

      {evidenceStep && (
        <EvidenceLinkDialog
          step={evidenceStep}
          locale={locale}
          principalKey={principalKey}
          propertyId={base.property_id}
          unitId={base.unit_id}
          contractId={evidenceStep.direction === 'move_out' ? base.previous_contract_id : base.next_contract_id}
          loadDocuments={loadDocuments}
          loadDocumentVersions={loadDocumentVersions}
          loadHandoverProtocols={loadHandoverProtocols}
          loadMeterReadings={loadMeterReadings}
          canSelectEvidence={canSelectEvidence}
          prepareLink={({ step, selection }) => prepareEvidenceLink?.({ change: base, step, selection })}
          onLinked={result => {
            const next = result?.id === base.id && result?.steps ? result : null;
            if (next) applyChange(next);
            else onReviewCurrent?.({ change: base, reason: 'evidence-linked' });
          }}
          onClose={() => setEvidenceStep(null)}
        />
      )}
    </section>
  );
}
