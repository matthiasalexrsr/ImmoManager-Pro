import { useState, useEffect, useLayoutEffect, useRef, useId } from 'react';
import { CircleAlert, LoaderCircle } from 'lucide-react';
import { useTranslation } from '../i18n';
import { CloseIcon } from './Icons';
import { bindEditRevision, snapshotRevision } from '../editRevision';
import EditConflictPanel from './EditConflictPanel';
import FormDraftPanel from './FormDraftPanel';
import useFormDraft from '../hooks/useFormDraft';
import './SharedComponents.css';

const initialValues = (fields, initial) => Object.fromEntries(fields.map(field =>
  [field.key, initial?.[field.key] ?? field.default ?? '']));

function reachableControls(modal) {
  return [...modal.querySelectorAll('button, a[href], input:not([type="hidden"]), select, textarea, [tabindex]:not([tabindex="-1"])')]
    .filter(element => {
      if (element.tabIndex < 0 || element.matches(':disabled') || element.closest('[hidden], [inert], [aria-hidden="true"]')) return false;
      for (let node = element; node && node !== modal.parentElement; node = node.parentElement) {
        const style = getComputedStyle(node);
        if (style.display === 'none' || style.visibility === 'hidden') return false;
      }
      return true;
    });
}

export default function FormModal({ title, fields, initial, onSave, onClose, onSaved, children, saveDisabled = false, closeOnSave = true, saveLabel, onValuesChange, draftConfig }) {
  const { t } = useTranslation();
  const [values, setValues] = useState(() => initialValues(fields, initial));
  const valuesListener = useRef(onValuesChange);
  useLayoutEffect(() => { valuesListener.current = onValuesChange; }, [onValuesChange]);
  useEffect(() => { valuesListener.current?.(values); }, [values]);
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);
  const [closing, setClosing] = useState(false);
  const [businessSaved, setBusinessSaved] = useState(false);
  const original = useRef(initial);
  const editRevision = useRef(snapshotRevision(initial));
  const modalRef = useRef(null);
  const errorRef = useRef(null);
  const primaryAction = useRef(null);
  const submitting = useRef(false);
  const closePending = useRef(false);
  const savedNotified = useRef(false);
  const wasSaving = useRef(false);
  const instanceId = useId();
  const initialSignature = JSON.stringify(initial ?? null);
  const previousInitial = useRef(initialSignature);
  const draft = useFormDraft({ config: draftConfig, fields, values, original, editRevision,
    onRestore: saved => {
      setValues(current => ({ ...current, ...saved.values }));
      const revision = saved.edit_revision;
      original.current = revision ? { ...saved.original_values, id: revision.id, updated_at: revision.updatedAt } : saved.original_values;
      editRevision.current = revision ? Object.freeze({ ...revision, source: Object.freeze({ ...original.current }) }) : null;
      setError(null);
      primaryAction.current?.focus();
    } });
  // A background autosave must not swallow a deliberate click. prepareSubmit
  // waits for that request and marks the latest values pending before onSave.
  const draftReady = !draft.enabled || ['ready', 'saved', 'restored', 'saving'].includes(draft.status);
  const notifySaved = () => { if (!savedNotified.current) { savedNotified.current = true; onSaved?.(); } };
  const completeSave = async () => { if (await draft.complete()) { notifySaved(); onClose(); } };
  const requestClose = async () => {
    if (submitting.current || closePending.current) return;
    if (!draft.enabled || businessSaved) { if (businessSaved) notifySaved(); onClose(); return; }
    closePending.current = true;
    setClosing(true);
    try { if (await draft.flush()) onClose(); }
    finally { closePending.current = false; setClosing(false); }
  };
  const closeListener = useRef(requestClose);
  useLayoutEffect(() => { closeListener.current = requestClose; });

  useEffect(() => {
    const changed = previousInitial.current !== initialSignature;
    // A background refresh of the same record cannot silently replace the
    // draft or upgrade its original revision. Reconciliation is explicit.
    const replace = changed && (!editRevision.current || original.current?.id !== initial?.id);
    previousInitial.current = initialSignature;
    if (replace) {
      original.current = initial;
      editRevision.current = snapshotRevision(initial);
      setError(null);
    }
    setValues(current => {
      const next = replace ? initialValues(fields, initial) : { ...current };
      if (!replace) fields.forEach(field => {
        if (!(field.key in next) || field.type === 'hidden' && !field.render) next[field.key] = original.current?.[field.key] ?? field.default ?? '';
      });
      return Object.keys(next).length === Object.keys(current).length
        && Object.keys(next).every(key => Object.is(next[key], current[key])) ? current : next;
    });
  }, [initial, initialSignature, fields]);

  useEffect(() => {
    const opener = document.activeElement;
    const modal = modalRef.current;
    if (!modal) return;
    const controls = reachableControls(modal);
    (controls.find(element => element.matches('input, select, textarea')) || controls[0] || modal).focus();
    return () => { if (opener?.isConnected && typeof opener.focus === 'function') opener.focus(); };
  }, []);

  useLayoutEffect(() => {
    if (saving) modalRef.current?.focus();
    else if (error) errorRef.current?.focus();
    else if (wasSaving.current) {
      (primaryAction.current && !primaryAction.current.disabled ? primaryAction.current : modalRef.current)?.focus();
    }
    wasSaving.current = saving;
  }, [saving, error]);

  useEffect(() => {
    const handler = event => {
      if (event.key === 'Escape' && !event.defaultPrevented && !submitting.current) void closeListener.current();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, []);

  const trapFocus = event => {
    if (event.key !== 'Tab') return;
    const modal = modalRef.current;
    const controls = reachableControls(modal);
    const first = controls[0], last = controls.at(-1);
    if (!first) { event.preventDefault(); modal.focus(); return; }
    if (!controls.includes(document.activeElement)) { event.preventDefault(); (event.shiftKey ? last : first).focus(); }
    else if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  };

  const handleSubmit = async event => {
    event.preventDefault();
    if (submitting.current || saveDisabled || businessSaved || closing || !draftReady) return;
    if (!event.currentTarget.checkValidity()) {
      setError({ message: t('ui.form.invalidFields') });
      event.currentTarget.reportValidity();
      return;
    }
    submitting.current = true;
    setSaving(true);
    setError(null);
    try {
      if (draft.enabled && !await draft.prepareSubmit()) return;
      const cleaned = {};
      fields.forEach(field => {
        let value = values[field.key];
        if (field.type === 'number') value = value === '' || value == null ? (field.required ? '' : null) : Number(value);
        else if (value === '') value = field.required ? value : null;
        cleaned[field.key] = value;
      });
      await onSave(bindEditRevision(cleaned, editRevision.current));
      if (draft.enabled) {
        setBusinessSaved(true);
        if (await draft.complete()) { notifySaved(); if (closeOnSave) onClose(); }
      } else { notifySaved(); if (closeOnSave) onClose(); }
    } catch (err) {
      setError({ message: err.message || t('ui.form.saveFailed'), details: err.details,
        isEditConflict: err.isEditConflict, resourcePath: err.resourcePath });
      if (draft.enabled) await draft.failedSubmit(err);
    } finally {
      submitting.current = false;
      setSaving(false);
    }
  };

  const changeField = (field, value, detail) => setValues(current => ({
    ...current, [field.key]: value, ...field.onChange?.(value, current, detail),
  }));

  const renderField = field => {
    if (field.type === 'hidden' && !field.render) return <input type="hidden" key={field.key} name={field.key} value={values[field.key] ?? ''} />;
    const inputId = `form-field-${field.key}-${instanceId}`;
    const hint = field.hint ?? field.helpText;
    const detail = Array.isArray(error?.details) && error.details.find(item => Array.isArray(item?.loc) && item.loc.at(-1) === field.key);
    const fieldError = typeof detail?.msg === 'string' ? detail.msg : null;
    const common = {
      id: inputId, name: field.key, required: field.required, disabled: field.disabled || saving || closing || businessSaved,
      'aria-invalid': fieldError ? true : undefined,
      'aria-describedby': [hint && `${inputId}-hint`, fieldError && `${inputId}-error`].filter(Boolean).join(' ') || undefined,
    };
    return <div key={field.key} className={`form-group shared-form-field ${field.render || ['textarea', 'multiselect'].includes(field.type) ? 'shared-form-field-wide' : ''}`}>
      {!field.render && <label htmlFor={inputId}>{field.label}{field.required && ' *'}</label>}
      {field.render ? field.render({ value: values[field.key] ?? '', values,
        onChange: (value, detail) => changeField(field, value, detail), inputProps: common })
        : ['select', 'multiselect'].includes(field.type) ? <select {...common}
        value={field.type === 'multiselect' ? values[field.key] || [] : values[field.key] ?? ''}
        multiple={field.type === 'multiselect'}
        onChange={event => changeField(field, field.type === 'multiselect' ? [...event.target.selectedOptions].map(option => option.value) : event.target.value)}>
        {field.type !== 'multiselect' && <option value="">{t('ui.form.pleaseSelect')}</option>}
        {field.options?.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
      </select> : field.type === 'textarea' ? <textarea {...common} value={values[field.key] ?? ''}
        onChange={event => changeField(field, event.target.value)} rows={field.rows || 3} placeholder={field.placeholder} readOnly={field.readOnly} />
        : <input {...common} type={field.type || 'text'} value={values[field.key] ?? ''}
          onChange={event => changeField(field, event.target.value)} step={field.step ?? (field.type === 'number' ? '0.01' : undefined)}
          min={field.min} max={typeof field.max === 'function' ? field.max(values) : field.max}
          minLength={field.minLength} maxLength={field.maxLength} pattern={field.pattern}
          placeholder={field.placeholder} autoComplete={field.autoComplete} readOnly={field.readOnly} />}
      {hint && <small id={`${inputId}-hint`} className="shared-form-hint">{hint}</small>}
      {fieldError && <small id={`${inputId}-error`} className="shared-form-field-error">{fieldError}</small>}
    </div>;
  };

  const sections = [];
  fields.forEach(field => {
    const section = field.section || null;
    if (!sections.length || sections.at(-1).label !== section) sections.push({ label: section, fields: [] });
    sections.at(-1).fields.push(field);
  });

  return <div className="modal-overlay shared-form-overlay" role="presentation" onClick={event => { if (event.target === event.currentTarget) requestClose(); }}>
    <div className="modal shared-form-modal" ref={modalRef} tabIndex={-1} onKeyDown={trapFocus}
      role="dialog" aria-modal="true" aria-labelledby={`${instanceId}-title`} aria-busy={saving}>
      <div className="modal-header"><h3 id={`${instanceId}-title`}>{title}</h3>
        <button type="button" onClick={requestClose} className="btn-close" aria-label={t('ui.buttons.close')} disabled={saving || closing}><CloseIcon size={18} /></button>
      </div>
      <form onSubmit={handleSubmit} aria-busy={saving}>
        <div className="modal-body">
          <FormDraftPanel draft={draft} businessSaved={businessSaved} onComplete={completeSave} />
          {error && <div className="alert-error shared-form-error" role="alert" ref={errorRef} tabIndex={-1}><CircleAlert size={18} aria-hidden="true" /><span>{error.message}</span></div>}
          {error?.isEditConflict && <EditConflictPanel error={error} fields={fields} original={original.current} draft={values}
            onReconcile={(nextValues, current) => {
              setValues(nextValues);
              original.current = current;
              editRevision.current = snapshotRevision(current);
              setError(null);
              primaryAction.current?.focus();
            }} />}
          <fieldset className="shared-modal-body-fields" disabled={saving || closing || businessSaved}>
            {children}
            {sections.map((section, index) => {
              const content = <div className={`shared-form-fields ${section.fields.filter(field => field.type !== 'hidden').length === 1 ? 'shared-form-fields-single' : ''}`}>{section.fields.map(renderField)}</div>;
              return section.label ? <fieldset key={index} className="form-section"><legend className="form-section-label">{section.label}</legend>{content}</fieldset> : <div key={index}>{content}</div>;
            })}
          </fieldset>
        </div>
        <div className="modal-footer">
          <span className="shared-form-required">{fields.some(field => field.required && field.type !== 'hidden') && `* ${t('ui.form.required')}`}</span>
          <div className="shared-form-actions">{draft.enabled && !businessSaved && ['error', 'conflict', 'available', 'uncertain'].includes(draft.status) && <button type="button" className="btn btn-secondary" disabled={saving || closing} onClick={onClose}>{t('formDraft.closeUnsaved')}</button>}<button type="button" onClick={requestClose} className="btn btn-secondary" disabled={saving || closing}>{t(businessSaved ? 'ui.buttons.close' : 'ui.buttons.cancel')}</button>
            <button type="submit" ref={primaryAction} className="btn btn-primary" disabled={saving || closing || saveDisabled || businessSaved || !draftReady}>
              {saving && <LoaderCircle size={16} className="shared-component-spinner" aria-hidden="true" />}
              <span aria-live="polite">{saving ? `${saveLabel || t('ui.buttons.save')}...` : saveLabel || t('ui.buttons.save')}</span>
            </button></div>
        </div>
      </form>
    </div>
  </div>;
}
