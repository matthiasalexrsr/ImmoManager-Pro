import { useCallback, useMemo, useState } from 'react';
import BoundedReferencePicker from './BoundedReferencePicker';
import WorkflowCommandNotice from './WorkflowCommandNotice';
import useWorkflowCommand from './useWorkflowCommand';
import { ANCHORS, EVIDENCE_REQUIREMENTS, REQUIREMENTS } from './tenancyWorkflowModel';
import { workflowText } from './workflowCopy';
import './TenancyWorkflows.css';

const ROLES = ['eigentuemer', 'verwalter', 'techniker'];

function initialStep() {
  return {
    stable_key: '',
    position: 0,
    title: '',
    description: null,
    default_requirement: 'required',
    anchor: 'move_in_handover',
    offset_days: 0,
    assignee_user_id: null,
    assignee_role: null,
    depends_on_step_keys: [],
    evidence_requirement: 'none',
  };
}

export default function WorkflowTemplateCreateForm({
  locale = 'de-DE',
  principalKey = '',
  propertyLoader,
  unitLoaderForProperty,
  userLoader,
  prepareCreate,
  onCreated,
}) {
  const tr = useCallback((key, params) => workflowText(locale, key, params), [locale]);
  const [property, setProperty] = useState(null);
  const [unit, setUnit] = useState(null);
  const [direction, setDirection] = useState('move_in');
  const [step, setStep] = useState(initialStep);
  const [assignment, setAssignment] = useState('none');
  const [error, setError] = useState(null);
  const command = useWorkflowCommand(principalKey);
  const unitLoader = useMemo(
    () => property ? unitLoaderForProperty?.(property.id) : null,
    [property, unitLoaderForProperty],
  );

  const patch = changes => {
    setStep(current => ({ ...current, ...changes }));
    setError(null);
    if (command.state.phase !== 'unknown') command.reset();
  };

  const chooseAssignment = mode => {
    setAssignment(mode);
    if (mode === 'user') patch({ assignee_user_id: null, assignee_role: null });
    else if (mode === 'role') patch({ assignee_user_id: null, assignee_role: 'techniker' });
    else patch({ assignee_user_id: null, assignee_role: null });
  };

  const submit = event => {
    event.preventDefault();
    const stableKey = step.stable_key.trim();
    const title = step.title.trim();
    if (!property?.id || !stableKey || !/^[A-Za-z0-9_.:-]+$/.test(stableKey) || !title) {
      setError(tr('invalidStep'));
      return;
    }
    const steps = [{
      ...step,
      stable_key: stableKey,
      title,
      description: step.description?.trim() || null,
      offset_days: Number(step.offset_days),
      position: 0,
    }];
    const prepared = prepareCreate?.({
      property_id: property.id,
      unit_id: unit?.id || null,
      direction,
      steps,
    });
    if (!prepared?.payload || typeof prepared.send !== 'function') {
      setError(tr('missingAdapter'));
      return;
    }
    command.execute({
      label: 'create-workflow-template',
      payload: prepared.payload,
      send: prepared.send,
      onSuccess: result => {
        onCreated?.(result);
        setProperty(null);
        setUnit(null);
        setDirection('move_in');
        setStep(initialStep());
        setAssignment('none');
      },
    });
  };

  return (
    <form className="workflow-shell workflow-template-create" onSubmit={submit} aria-busy={command.busy}>
      <header className="workflow-shell__header">
        <div>
          <span className="workflow-eyebrow">{tr('eyebrow')}</span>
          <h2>{tr('templatesTitle')}</h2>
          <p className="workflow-muted">{tr('newTemplateDescription')}</p>
        </div>
      </header>
      <WorkflowCommandNotice state={command.state} locale={locale}
        onRetryExact={command.retryExact} onDismiss={command.reset} />
      {error && <div className="workflow-inline-error" role="alert">{error}</div>}

      <div className="workflow-form-grid">
        <BoundedReferencePicker label={tr('propertyScope')} locale={locale}
          value={property?.id || null} selectedItem={property} loadPage={propertyLoader}
          sourceKey="workflow-properties" getLabel={item => item.name || item.id}
          onChange={item => { setProperty(item); setUnit(null); }} required />
        <BoundedReferencePicker label={tr('unitScope')} locale={locale}
          value={unit?.id || null} selectedItem={unit} loadPage={unitLoader}
          sourceKey={property?.id || 'no-property'} getLabel={item => item.label || item.id}
          isSelectable={item => !property || item.property_id === property.id}
          disabled={!property} onChange={setUnit} />
        <label className="workflow-field">
          <span>{tr('mode')}</span>
          <select value={direction} onChange={event => setDirection(event.target.value)}
            disabled={command.busy || command.state.phase === 'unknown'}>
            <option value="move_in">{tr('move_in')}</option>
            <option value="move_out">{tr('move_out')}</option>
          </select>
        </label>
      </div>

      <div className="workflow-step-editor">
        <div className="workflow-form-grid">
          <label className="workflow-field">
            <span>{tr('stableKey')}</span>
            <input value={step.stable_key} onChange={event => patch({ stable_key: event.target.value })}
              placeholder="handover.schedule" disabled={command.busy || command.state.phase === 'unknown'} />
          </label>
          <label className="workflow-field">
            <span>{tr('title')}</span>
            <input value={step.title} onChange={event => patch({ title: event.target.value })}
              disabled={command.busy || command.state.phase === 'unknown'} />
          </label>
          <label className="workflow-field">
            <span>{tr('requirement')}</span>
            <select value={step.default_requirement} onChange={event => patch({ default_requirement: event.target.value })}>
              {REQUIREMENTS.map(value => <option key={value} value={value}>{tr(value)}</option>)}
            </select>
          </label>
          <label className="workflow-field">
            <span>{tr('anchor')}</span>
            <select value={step.anchor} onChange={event => patch({ anchor: event.target.value })}>
              {ANCHORS.map(value => <option key={value} value={value}>{tr(value)}</option>)}
            </select>
          </label>
          <label className="workflow-field">
            <span>{tr('offsetDays')}</span>
            <input type="number" value={step.offset_days} onChange={event => patch({ offset_days: event.target.value })} />
          </label>
          <label className="workflow-field">
            <span>{tr('evidenceRequirement')}</span>
            <select value={step.evidence_requirement} onChange={event => patch({ evidence_requirement: event.target.value })}>
              {EVIDENCE_REQUIREMENTS.map(value => <option key={value} value={value}>{tr(`evidence_${value}`)}</option>)}
            </select>
          </label>
          <label className="workflow-field workflow-field--wide">
            <span>{tr('description')}</span>
            <textarea value={step.description || ''} onChange={event => patch({ description: event.target.value || null })} />
          </label>
        </div>

        <fieldset className="workflow-fieldset">
          <legend>{tr('responsibility')}</legend>
          <div className="workflow-segmented">
            {['none', 'user', 'role'].map(mode => <label key={mode}>
              <input type="radio" name="new-template-assignment" checked={assignment === mode}
                onChange={() => chooseAssignment(mode)} />
              <span>{tr(mode)}</span>
            </label>)}
          </div>
          {assignment === 'user' && <BoundedReferencePicker label={tr('selectUser')} locale={locale}
            value={step.assignee_user_id} loadPage={userLoader} sourceKey="workflow-active-users"
            getLabel={item => item.full_name || item.username || item.id}
            isSelectable={item => item.is_active !== false && ROLES.includes(item.role)}
            onChange={item => patch({ assignee_user_id: item?.id || null, assignee_role: null })} required />}
          {assignment === 'role' && <label className="workflow-field workflow-field--compact">
            <span>{tr('selectRole')}</span>
            <select value={step.assignee_role || 'techniker'}
              onChange={event => patch({ assignee_role: event.target.value, assignee_user_id: null })}>
              {ROLES.map(role => <option key={role} value={role}>{role}</option>)}
            </select>
          </label>}
        </fieldset>
      </div>

      <footer className="workflow-actions">
        <button className="btn btn-primary" type="submit"
          disabled={command.busy || command.state.phase === 'unknown' || !property}>
          {command.busy ? tr('working') : tr('createTemplate')}
        </button>
      </footer>
    </form>
  );
}
