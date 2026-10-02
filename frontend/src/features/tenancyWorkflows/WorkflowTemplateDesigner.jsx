import { useCallback, useEffect, useMemo, useState } from 'react';
import { ArrowDown, ArrowUp, Plus, Trash2 } from 'lucide-react';
import BoundedReferencePicker from './BoundedReferencePicker';
import WorkflowCommandNotice from './WorkflowCommandNotice';
import useWorkflowCommand from './useWorkflowCommand';
import {
  ANCHORS,
  EVIDENCE_REQUIREMENTS,
  REQUIREMENTS,
  actionAllowed,
  validateTemplateDraftSteps,
  validateTemplateVersion,
} from './tenancyWorkflowModel';
import { workflowText } from './workflowCopy';
import './TenancyWorkflows.css';

const ROLES = ['eigentuemer', 'verwalter', 'techniker'];

const cloneSteps = steps => steps.map(step => ({
  ...step,
  depends_on_step_keys: [...(step.depends_on_step_keys || [])],
}));

function localKey(step) {
  return step.id || step.stable_key;
}

function newStableKey() {
  if (typeof crypto?.randomUUID !== 'function') throw new Error('crypto.randomUUID unavailable');
  return `step-${crypto.randomUUID()}`;
}

function blankStep(position) {
  return {
    id: null,
    stable_key: newStableKey(),
    position,
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

function normalizedSteps(steps) {
  return steps.map((step, position) => ({
    ...step,
    position,
    title: step.title.trim(),
    description: step.description?.trim() || null,
    offset_days: Number(step.offset_days),
    assignee_user_id: step.assignee_user_id || null,
    assignee_role: step.assignee_role || null,
    depends_on_step_keys: [...step.depends_on_step_keys],
  }));
}

function responsibilityMode(step) {
  if (step.assignee_user_id) return 'user';
  if (step.assignee_role) return 'role';
  return 'none';
}

export default function WorkflowTemplateDesigner({
  version,
  locale = 'de-DE',
  principalKey = '',
  userLoader,
  prepareSave,
  preparePublish,
  onChanged,
  onReviewCurrent,
}) {
  const checked = useMemo(() => validateTemplateVersion(version), [version]);
  const [base, setBase] = useState(checked);
  const [steps, setSteps] = useState(() => cloneSteps(checked.steps));
  const [responsibilityModes, setResponsibilityModes] = useState(() => Object.fromEntries(
    checked.steps.map(step => [localKey(step), responsibilityMode(step)]),
  ));
  const [dirty, setDirty] = useState(false);
  const [localError, setLocalError] = useState(null);
  const command = useWorkflowCommand(principalKey);
  const tr = useCallback((key, params) => workflowText(locale, key, params), [locale]);

  useEffect(() => {
    if (checked.id !== base.id) {
      setBase(checked);
      setSteps(cloneSteps(checked.steps));
      setResponsibilityModes(Object.fromEntries(
        checked.steps.map(step => [localKey(step), responsibilityMode(step)]),
      ));
      setDirty(false);
      setLocalError(null);
      command.reset();
      return;
    }
    if (checked.revision !== base.revision) {
      setBase(checked);
      if (!dirty) {
        setSteps(cloneSteps(checked.steps));
        setResponsibilityModes(Object.fromEntries(
          checked.steps.map(step => [localKey(step), responsibilityMode(step)]),
        ));
      }
    }
  }, [base.id, base.revision, checked, command, dirty]);

  const editable = base.state === 'draft' && actionAllowed(base, 'edit_template');
  const publishable = base.state === 'draft' && actionAllowed(base, 'publish_template');

  const mutate = useCallback(updater => {
    setSteps(current => {
      const next = updater(cloneSteps(current));
      return next.map((step, position) => ({ ...step, position }));
    });
    setDirty(true);
    setLocalError(null);
    if (command.state.phase !== 'unknown') command.reset();
  }, [command]);

  const patchStep = (index, patch) => mutate(current => {
    current[index] = { ...current[index], ...patch };
    return current;
  });

  const moveStep = (index, delta) => mutate(current => {
    const target = index + delta;
    if (target < 0 || target >= current.length) return current;
    [current[index], current[target]] = [current[target], current[index]];
    return current;
  });

  const removeStep = index => mutate(current => {
    const removed = current[index]?.stable_key;
    return current
      .filter((_, itemIndex) => itemIndex !== index)
      .map(step => ({
        ...step,
        depends_on_step_keys: step.depends_on_step_keys.filter(key => key !== removed),
      }));
  });

  const setResponsibility = (index, mode) => {
    const key = localKey(steps[index]);
    setResponsibilityModes(current => ({ ...current, [key]: mode }));
    if (mode === 'user') patchStep(index, { assignee_user_id: null, assignee_role: null });
    else if (mode === 'role') patchStep(index, { assignee_user_id: null, assignee_role: 'techniker' });
    else patchStep(index, { assignee_user_id: null, assignee_role: null });
  };

  const toggleDependency = (index, key, enabled) => patchStep(index, {
    depends_on_step_keys: enabled
      ? [...new Set([...steps[index].depends_on_step_keys, key])]
      : steps[index].depends_on_step_keys.filter(item => item !== key),
  });

  const applySuccess = useCallback(result => {
    const next = validateTemplateVersion(result);
    setBase(next);
    setSteps(cloneSteps(next.steps));
    setResponsibilityModes(Object.fromEntries(
      next.steps.map(step => [localKey(step), responsibilityMode(step)]),
    ));
    setDirty(false);
    setLocalError(null);
    onChanged?.(next);
  }, [onChanged]);

  const runPrepared = useCallback((prepared, label) => {
    if (!prepared || typeof prepared.send !== 'function' || !prepared.payload) {
      setLocalError(tr('missingAdapter'));
      return;
    }
    command.execute({
      label,
      payload: prepared.payload,
      send: prepared.send,
      onSuccess: applySuccess,
    });
  }, [applySuccess, command, tr]);

  const save = () => {
    try {
      const nextSteps = normalizedSteps(steps);
      validateTemplateDraftSteps(nextSteps);
      setLocalError(null);
      runPrepared(prepareSave?.({ version: base, steps: nextSteps }), 'save-template');
    } catch (error) {
      setLocalError(tr(error.message === 'dependency_cycle' ? 'dependencyCycle' : 'invalidStep'));
    }
  };

  const publish = () => {
    if (dirty) return;
    runPrepared(preparePublish?.({ version: base }), 'publish-template');
  };

  const scopeLabel = base.unit_id ? tr('unitOverride') : tr('objectDefault');

  return (
    <section className="workflow-shell workflow-template" aria-busy={command.busy}>
      <header className="workflow-shell__header">
        <div>
          <span className="workflow-eyebrow">{tr('eyebrow')}</span>
          <h2>{tr('templatesTitle')}</h2>
          <p className="workflow-muted">
            {tr(base.direction)} · {tr('version', { version: base.version })} · {scopeLabel}
          </p>
        </div>
        <div className="workflow-badges">
          <span className={`workflow-badge workflow-badge--${base.state}`}>{tr(base.state)}</span>
          <span className="workflow-badge">{tr('stepCount', { count: steps.length })}</span>
        </div>
      </header>

      <WorkflowCommandNotice
        state={command.state}
        locale={locale}
        onRetryExact={command.retryExact}
        onReviewCurrent={() => onReviewCurrent?.({ version: base, localSteps: normalizedSteps(steps) })}
        onDismiss={command.reset}
      />
      {localError && <div className="workflow-inline-error" role="alert">{localError}</div>}
      {!editable && <p className="workflow-note">{tr('readOnlyTemplate')}</p>}

      <ol className="workflow-template__steps">
        {steps.map((step, index) => {
          const mode = responsibilityModes[localKey(step)] ?? responsibilityMode(step);
          return (
            <li key={localKey(step)} className="workflow-step-editor">
              <div className="workflow-step-editor__top">
                <div>
                  <span className="workflow-step-editor__index">{String(index + 1).padStart(2, '0')}</span>
                  <code>{step.stable_key}</code>
                </div>
                {editable && (
                  <div className="workflow-icon-actions">
                    <button type="button" aria-label={tr('moveUp')} disabled={index === 0 || command.busy} onClick={() => moveStep(index, -1)}>
                      <ArrowUp size={16} />
                    </button>
                    <button type="button" aria-label={tr('moveDown')} disabled={index === steps.length - 1 || command.busy} onClick={() => moveStep(index, 1)}>
                      <ArrowDown size={16} />
                    </button>
                    <button type="button" aria-label={tr('removeStep')} disabled={command.busy} onClick={() => removeStep(index)}>
                      <Trash2 size={16} />
                    </button>
                  </div>
                )}
              </div>

              <div className="workflow-form-grid">
                <label className="workflow-field workflow-field--wide">
                  <span>{tr('title')}</span>
                  <input value={step.title} disabled={!editable || command.busy} onChange={event => patchStep(index, { title: event.target.value })} />
                </label>
                <label className="workflow-field workflow-field--wide">
                  <span>{tr('description')}</span>
                  <textarea value={step.description || ''} disabled={!editable || command.busy}
                    onChange={event => patchStep(index, { description: event.target.value || null })} />
                </label>
                <label className="workflow-field">
                  <span>{tr('requirement')}</span>
                  <select value={step.default_requirement} disabled={!editable || command.busy}
                    onChange={event => patchStep(index, { default_requirement: event.target.value })}>
                    {REQUIREMENTS.map(value => <option key={value} value={value}>{tr(value)}</option>)}
                  </select>
                </label>
                <label className="workflow-field">
                  <span>{tr('anchor')}</span>
                  <select value={step.anchor} disabled={!editable || command.busy}
                    onChange={event => patchStep(index, { anchor: event.target.value })}>
                    {ANCHORS.map(value => <option key={value} value={value}>{tr(value)}</option>)}
                  </select>
                </label>
                <label className="workflow-field">
                  <span>{tr('offsetDays')}</span>
                  <input type="number" step="1" value={step.offset_days} disabled={!editable || command.busy}
                    onChange={event => patchStep(index, { offset_days: event.target.value })} />
                </label>
                <label className="workflow-field">
                  <span>{tr('evidenceRequirement')}</span>
                  <select value={step.evidence_requirement} disabled={!editable || command.busy}
                    onChange={event => patchStep(index, { evidence_requirement: event.target.value })}>
                    {EVIDENCE_REQUIREMENTS.map(value => (
                      <option key={value} value={value}>{tr(`evidence_${value}`)}</option>
                    ))}
                  </select>
                </label>
              </div>

              <fieldset className="workflow-fieldset" disabled={!editable || command.busy}>
                <legend>{tr('responsibility')}</legend>
                <div className="workflow-segmented">
                  {['none', 'user', 'role'].map(value => (
                    <label key={value}>
                      <input type="radio" name={`responsibility-${localKey(step)}`} value={value}
                        checked={mode === value} onChange={() => setResponsibility(index, value)} />
                      <span>{tr(value)}</span>
                    </label>
                  ))}
                </div>
                {mode === 'user' && (
                  <BoundedReferencePicker
                    label={tr('selectUser')}
                    locale={locale}
                    value={step.assignee_user_id}
                    onChange={item => patchStep(index, { assignee_user_id: item?.id || null, assignee_role: null })}
                    loadPage={userLoader}
                    getLabel={item => item.full_name || item.username || item.id}
                    getDescription={item => [item.role, item.email].filter(Boolean).join(' · ')}
                    isSelectable={item => item.is_active !== false && ROLES.includes(item.role)}
                    sourceKey="active-users"
                    disabled={!editable || command.busy}
                  />
                )}
                {mode === 'role' && (
                  <label className="workflow-field workflow-field--compact">
                    <span>{tr('selectRole')}</span>
                    <select value={step.assignee_role || 'techniker'} disabled={!editable || command.busy}
                      onChange={event => patchStep(index, { assignee_role: event.target.value, assignee_user_id: null })}>
                      {ROLES.map(role => <option key={role} value={role}>{role}</option>)}
                    </select>
                  </label>
                )}
              </fieldset>

              <fieldset className="workflow-fieldset" disabled={!editable || command.busy}>
                <legend>{tr('dependencies')}</legend>
                <div className="workflow-dependencies">
                  {steps.filter(candidate => candidate.stable_key !== step.stable_key).map(candidate => (
                    <label key={candidate.stable_key}>
                      <input type="checkbox" checked={step.depends_on_step_keys.includes(candidate.stable_key)}
                        onChange={event => toggleDependency(index, candidate.stable_key, event.target.checked)} />
                      <span>{candidate.title || candidate.stable_key}</span>
                    </label>
                  ))}
                </div>
              </fieldset>
            </li>
          );
        })}
      </ol>

      {editable && (
        <button type="button" className="workflow-add-step" disabled={command.busy}
          onClick={() => mutate(current => [...current, blankStep(current.length)])}>
          <Plus size={17} aria-hidden="true" /> {tr('addStep')}
        </button>
      )}

      <footer className="workflow-actions">
        {editable && (
          <button type="button" className="btn btn-primary" disabled={command.busy || !dirty || command.state.phase === 'unknown'} onClick={save}>
            {command.busy ? tr('working') : tr('save')}
          </button>
        )}
        {publishable && (
          <button type="button" className="btn btn-secondary" disabled={command.busy || dirty || command.state.phase === 'unknown'} onClick={publish}>
            {tr('publish')}
          </button>
        )}
      </footer>
    </section>
  );
}
