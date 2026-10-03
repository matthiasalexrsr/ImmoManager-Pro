import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ArrowRight, CheckCircle2 } from 'lucide-react';
import BoundedReferencePicker from './BoundedReferencePicker';
import WorkflowCommandNotice from './WorkflowCommandNotice';
import WorkflowTechnicalDetails from './WorkflowTechnicalDetails';
import useWorkflowCommand from './useWorkflowCommand';
import { validateTenancyChange } from './tenancyWorkflowModel';
import { workflowText } from './workflowCopy';
import './TenancyWorkflows.css';

const initialForm = {
  mode: 'turnover',
  previous_contract_id: null,
  next_contract_id: null,
  move_out_handover_date: '',
  move_in_handover_date: '',
  move_out_template_version_id: null,
  move_in_template_version_id: null,
};

function formatDate(value, locale) {
  if (!value) return '';
  const parsed = /^\d{4}-\d{2}-\d{2}$/.test(value)
    ? new Date(`${value}T00:00:00Z`)
    : new Date(value);
  if (!Number.isFinite(parsed.getTime())) return String(value);
  return new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeZone: 'UTC' }).format(parsed);
}

function contractLabel(contract, fallback) {
  return contract.label || contract.contract_number || fallback;
}

function contractDescription(contract, locale) {
  const dates = [contract.start_date, contract.end_date].filter(Boolean).map(value => formatDate(value, locale));
  return dates.join(' → ');
}

function previewFacts(value) {
  if (!value || typeof value !== 'object') return null;
  return {
    preview_hash: typeof value.preview_hash === 'string' ? value.preview_hash : null,
    anchors: value.anchors && typeof value.anchors === 'object' ? value.anchors : null,
    affected_steps: Array.isArray(value.affected_steps) ? value.affected_steps : null,
    source_etags: value.source_etags && typeof value.source_etags === 'object' ? value.source_etags : null,
    conflicts: Array.isArray(value.conflicts) ? value.conflicts : null,
  };
}

export default function TenancyChangeStartForm({
  propertyId,
  unitId,
  propertyLabel = null,
  unitLabel = null,
  locale = 'de-DE',
  principalKey = '',
  loadContracts,
  loadTemplates,
  onPreview,
  normalizePreview = previewFacts,
  prepareCreate,
  onCreated,
}) {
  const [form, setForm] = useState(initialForm);
  const [selectedPrevious, setSelectedPrevious] = useState(null);
  const [selectedNext, setSelectedNext] = useState(null);
  const [selectedOutTemplate, setSelectedOutTemplate] = useState(null);
  const [selectedInTemplate, setSelectedInTemplate] = useState(null);
  const [preview, setPreview] = useState(null);
  const [previewView, setPreviewView] = useState(null);
  const [previewError, setPreviewError] = useState(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const request = useRef(null);
  const command = useWorkflowCommand(principalKey);
  const tr = useCallback((key, params) => workflowText(locale, key, params), [locale]);

  useEffect(() => () => request.current?.abort(), []);
  useEffect(() => {
    request.current?.abort();
    setForm(initialForm);
    setSelectedPrevious(null);
    setSelectedNext(null);
    setSelectedOutTemplate(null);
    setSelectedInTemplate(null);
    setPreview(null);
    setPreviewView(null);
    setPreviewError(null);
  }, [principalKey, propertyId, unitId]);

  const needsOut = form.mode === 'move_out' || form.mode === 'turnover';
  const needsIn = form.mode === 'move_in' || form.mode === 'turnover';

  const changeForm = useCallback(patch => {
    setForm(current => ({ ...current, ...patch }));
    setPreview(null);
    setPreviewView(null);
    setPreviewError(null);
    if (command.state.phase !== 'unknown') command.reset();
  }, [command]);

  const validForPreview = (!needsOut || (form.previous_contract_id && form.move_out_template_version_id))
    && (!needsIn || (form.next_contract_id && form.move_in_template_version_id));

  const scopedTemplate = useCallback((template, direction) => (
    template?.property_id === propertyId
      && (template.unit_id == null || template.unit_id === unitId)
      && template.direction === direction
      && template.state === 'published'
  ), [propertyId, unitId]);

  const previewPayload = useMemo(() => ({
    property_id: propertyId,
    unit_id: unitId,
    previous_contract_id: needsOut ? form.previous_contract_id : null,
    next_contract_id: needsIn ? form.next_contract_id : null,
    mode: form.mode,
    move_out_handover_date: needsOut && form.move_out_handover_date ? form.move_out_handover_date : null,
    move_in_handover_date: needsIn && form.move_in_handover_date ? form.move_in_handover_date : null,
    move_out_template_version_id: needsOut ? form.move_out_template_version_id : null,
    move_in_template_version_id: needsIn ? form.move_in_template_version_id : null,
  }), [form, needsIn, needsOut, propertyId, unitId]);

  const runPreview = async () => {
    if (!validForPreview || typeof onPreview !== 'function') {
      setPreviewError(tr('missingAdapter'));
      return;
    }
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setPreviewLoading(true);
    setPreviewError(null);
    try {
      const result = await onPreview(previewPayload, { signal: controller.signal });
      if (controller.signal.aborted) return;
      if (!result || typeof result.preview_hash !== 'string' || !result.preview_hash) {
        throw new Error('invalid_preview_response');
      }
      setPreview(result);
      setPreviewView(normalizePreview?.(result) || { preview_hash: result.preview_hash });
    } catch (error) {
      if (!controller.signal.aborted) setPreviewError(error.message);
    } finally {
      if (!controller.signal.aborted) setPreviewLoading(false);
    }
  };

  const start = () => {
    if (!preview) {
      setPreviewError(tr('previewFirst'));
      return;
    }
    const prepared = prepareCreate?.({ form: previewPayload, preview });
    if (!prepared || !prepared.payload || typeof prepared.send !== 'function') {
      setPreviewError(tr('missingAdapter'));
      return;
    }
    command.execute({
      label: 'create-tenancy-change',
      payload: prepared.payload,
      send: prepared.send,
      onSuccess: result => {
        const change = validateTenancyChange(result);
        onCreated?.(change);
        setForm(initialForm);
        setSelectedPrevious(null);
        setSelectedNext(null);
        setSelectedOutTemplate(null);
        setSelectedInTemplate(null);
        setPreview(null);
        setPreviewView(null);
        setPreviewError(null);
      },
    });
  };

  const templateLoader = direction => args => loadTemplates?.({ ...args, direction, propertyId, unitId });
  const contractLoader = args => loadContracts?.({ ...args, propertyId, unitId });

  return (
    <section className="workflow-shell workflow-start" aria-busy={previewLoading || command.busy}>
      <header className="workflow-shell__header">
        <div>
          <span className="workflow-eyebrow">{tr('eyebrow')}</span>
          <h2>{tr('startTitle')}</h2>
          <p className="workflow-muted">
            {propertyLabel || tr('propertyUnavailable')} · {unitLabel || tr('unitUnavailable')}
          </p>
        </div>
      </header>

      <WorkflowCommandNotice state={command.state} locale={locale}
        onRetryExact={command.retryExact} onDismiss={command.reset} />
      {previewError && <div className="workflow-inline-error" role="alert">{previewError}</div>}

      <div className="workflow-start__mode" role="group" aria-label={tr('mode')}>
        {['move_out', 'move_in', 'turnover'].map(mode => (
          <button key={mode} type="button" className={form.mode === mode ? 'is-active' : ''}
            disabled={previewLoading || command.busy || command.state.phase === 'unknown'}
            onClick={() => changeForm({ mode })}>{tr(mode)}</button>
        ))}
      </div>

      <div className="workflow-start__columns">
        {needsOut && (
          <section className="workflow-start__lane">
            <h3>{tr('move_out')}</h3>
            <BoundedReferencePicker label={tr('previousContract')} locale={locale}
              value={form.previous_contract_id} selectedItem={selectedPrevious}
              loadPage={contractLoader} sourceKey={`${propertyId}:${unitId}:previous`}
              getLabel={item => contractLabel(item, tr('contractUnavailable'))}
              getDescription={item => contractDescription(item, locale)}
              disabled={previewLoading || command.busy}
              onChange={item => { setSelectedPrevious(item); changeForm({ previous_contract_id: item?.id || null }); }} required />
            <label className="workflow-field">
              <span>{tr('moveOutHandoverDate')}</span>
              <input type="date" value={form.move_out_handover_date}
                disabled={previewLoading || command.busy}
                onChange={event => changeForm({ move_out_handover_date: event.target.value })} />
            </label>
            <BoundedReferencePicker label={tr('moveOutTemplate')} locale={locale}
              value={form.move_out_template_version_id} selectedItem={selectedOutTemplate}
              loadPage={templateLoader('move_out')} sourceKey={`${propertyId}:${unitId}:move_out`} searchEnabled={false}
              getLabel={item => `${tr('version', { version: item.version })} · ${item.unit_id ? tr('unitOverride') : tr('objectDefault')}`} getDescription={item => tr(item.state)}
              isSelectable={item => scopedTemplate(item, 'move_out')} disabled={previewLoading || command.busy}
              onChange={item => { setSelectedOutTemplate(item); changeForm({ move_out_template_version_id: item?.id || null }); }} required />
          </section>
        )}

        {form.mode === 'turnover' && <div className="workflow-start__bridge" aria-hidden="true"><ArrowRight /></div>}

        {needsIn && (
          <section className="workflow-start__lane">
            <h3>{tr('move_in')}</h3>
            <BoundedReferencePicker label={tr('nextContract')} locale={locale}
              value={form.next_contract_id} selectedItem={selectedNext}
              loadPage={contractLoader} sourceKey={`${propertyId}:${unitId}:next`}
              getLabel={item => contractLabel(item, tr('contractUnavailable'))}
              getDescription={item => contractDescription(item, locale)}
              disabled={previewLoading || command.busy}
              onChange={item => { setSelectedNext(item); changeForm({ next_contract_id: item?.id || null }); }} required />
            <label className="workflow-field">
              <span>{tr('moveInHandoverDate')}</span>
              <input type="date" value={form.move_in_handover_date}
                disabled={previewLoading || command.busy}
                onChange={event => changeForm({ move_in_handover_date: event.target.value })} />
            </label>
            <BoundedReferencePicker label={tr('moveInTemplate')} locale={locale}
              value={form.move_in_template_version_id} selectedItem={selectedInTemplate}
              loadPage={templateLoader('move_in')} sourceKey={`${propertyId}:${unitId}:move_in`} searchEnabled={false}
              getLabel={item => `${tr('version', { version: item.version })} · ${item.unit_id ? tr('unitOverride') : tr('objectDefault')}`} getDescription={item => tr(item.state)}
              isSelectable={item => scopedTemplate(item, 'move_in')} disabled={previewLoading || command.busy}
              onChange={item => { setSelectedInTemplate(item); changeForm({ move_in_template_version_id: item?.id || null }); }} required />
          </section>
        )}
      </div>

      <div className="workflow-actions">
        <button type="button" className="btn btn-secondary"
          disabled={!validForPreview || previewLoading || command.busy || command.state.phase === 'unknown'}
          onClick={runPreview}>
          {previewLoading ? tr('loading') : tr('preview')}
        </button>
      </div>

      {preview && (
        <section className="workflow-preview" aria-label={tr('preview')}>
          <div className="workflow-preview__heading">
            <CheckCircle2 size={19} aria-hidden="true" />
            <strong>{tr('previewReady')}</strong>
          </div>
          {previewView?.anchors && (
            <FactGroup title={tr('anchors')} value={previewView.anchors}
              labelFor={key => tr(key)} formatValue={value => formatDate(value, locale)} />
          )}
          {previewView?.affected_steps && (
            <div>
              <h4>{tr('affectedSteps')}</h4>
              <ul>{previewView.affected_steps.map((step, index) => (
                <li key={step.id || step.template_step_key || index}>{step.title || step.title_snapshot || tr('stepNumber', { number: index + 1 })}</li>
              ))}</ul>
            </div>
          )}
          <div>
            <h4>{tr('previewConflicts')}</h4>
            {previewView?.conflicts?.length
              ? <ul>{previewView.conflicts.map((item, index) => <li key={index}>{item.message || String(item)}</li>)}</ul>
              : <p>{tr('noConflicts')}</p>}
          </div>
          <WorkflowTechnicalDetails locale={locale} rows={[
            { label: tr('checksum'), value: preview.preview_hash },
            { label: tr('sourceEtags'), value: previewView?.source_etags },
            { label: tr('propertyScope'), value: propertyId },
            { label: tr('unitScope'), value: unitId },
          ]} />
          <button type="button" className="btn btn-primary"
            disabled={command.busy || command.state.phase === 'unknown'} onClick={start}>
            {command.busy ? tr('working') : tr('confirmStart')}
          </button>
        </section>
      )}
    </section>
  );
}

function FactGroup({ title, value, labelFor = key => key, formatValue = item => String(item) }) {
  return (
    <div>
      <h4>{title}</h4>
      <dl className="workflow-facts">
        {Object.entries(value).map(([key, item]) => (
          <div key={key}>
            <dt>{labelFor(key)}</dt>
            <dd>{item == null ? '—' : formatValue(item)}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
