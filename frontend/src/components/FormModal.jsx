import { useState, useEffect, useRef, useCallback } from 'react';
import { useTranslation } from '../i18n';
import { CloseIcon } from './Icons';
import { codeLabel } from '../utils/codeLabels';

const isBooleanSelect = f => f.type === 'select' && f.options?.length === 2
  && f.options.every(o => o.value === 'true' || o.value === 'false');

// Selects hold strings: true/false and numbers come back as 'true'/'false'/'12'.
const toFieldValue = (f, v) => (f.type === 'select' && (typeof v === 'boolean' || typeof v === 'number') ? String(v) : v);

// Long forms get two columns; free text and explicitly wide fields span both.
const WIDE_FORM_FIELDS = 8;
const spansRow = f => f.full || f.type === 'textarea';
// In two columns, full-width fields (notes, descriptions) go last so the pairs above stay aligned.
const ordered = list => [...list.filter(f => !spansRow(f)), ...list.filter(spansRow)];

export default function FormModal({ title, fields, initial, onSave, onClose }) {
  const { t } = useTranslation();
  const tr = (key, fallback) => { const text = t(key); return !text || text === key ? fallback : text; };
  // Inline prefill objects are recreated by several callers; that is not a new form.
  const initialKey = initial?.id != null ? `record:${initial.id}` : `prefill:${JSON.stringify(initial ?? null)}`;
  const [values, setValues] = useState(() => Object.fromEntries(fields.map(f =>
    [f.key, toFieldValue(f, initial?.[f.key] ?? f.default ?? '')])));
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);
  // Typed input is never thrown away silently: closing an edited form asks first.
  const [dirty, setDirty] = useState(false);
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  const modalRef = useRef(null);
  const formRef = useRef(null);
  const pressStartedOnOverlay = useRef(false);
  const sessionRef = useRef({ key: initialKey, id: initial?.id, updatedAt: initial?.updated_at });

  useEffect(() => {
    const changedRecord = sessionRef.current.key !== initialKey;
    if (changedRecord) {
      sessionRef.current = { key: initialKey, id: initial?.id, updatedAt: initial?.updated_at };
      setError(null);
      setDirty(false);
      setConfirmDiscard(false);
    }
    setValues(current => {
      const addedFields = fields.filter(f => !Object.prototype.hasOwnProperty.call(current, f.key));
      if (!changedRecord && addedFields.length === 0) return current;
      const next = changedRecord ? {} : { ...current };
      (changedRecord ? fields : addedFields).forEach(f => {
        next[f.key] = toFieldValue(f, initial?.[f.key] ?? f.default ?? '');
      });
      return next;
    });
  }, [initialKey, initial, fields]);

  const update = (key, value, extra) => {
    setDirty(true);
    setConfirmDiscard(false);
    setValues(current => ({ ...current, [key]: value, ...extra }));
  };

  const requestClose = useCallback(() => {
    if (saving) return;
    if (dirty && !confirmDiscard) setConfirmDiscard(true);
    else onClose();
  }, [saving, dirty, confirmDiscard, onClose]);

  // Escape closes (or asks first); a second Escape on the question returns to editing.
  // Ctrl/Cmd+Enter saves from any field, including multi-line notes.
  useEffect(() => {
    const handler = (e) => {
      if (e.key === 'Escape') {
        if (confirmDiscard) setConfirmDiscard(false);
        else requestClose();
      } else if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && modalRef.current?.contains(document.activeElement)) {
        e.preventDefault();
        formRef.current?.requestSubmit();
      }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [requestClose, confirmDiscard]);

  // Focus trap
  useEffect(() => {
    const modal = modalRef.current;
    if (!modal) return;
    const query = () => modal.querySelectorAll(
      'button, [href], input:not([type="hidden"]), select, textarea, [tabindex]:not([tabindex="-1"])'
    );
    const focusable = query();
    // Start in the first field to fill in, not on the close button in the header.
    const firstField = modal.querySelector('.modal-body :is(input:not([type="hidden"]), select, textarea):not(:disabled)');
    if (focusable.length > 0 && !modal.contains(document.activeElement)) (firstField || focusable[0]).focus();

    const trapFocus = (e) => {
      // the footer swaps its buttons for the discard question, so look the controls up each time
      const current = query();
      if (e.key !== 'Tab' || current.length === 0) return;
      const first = current[0];
      const last = current[current.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    modal.addEventListener('keydown', trapFocus);
    return () => modal.removeEventListener('keydown', trapFocus);
  }, [fields]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const cleaned = {};
      fields.forEach(f => {
        let v = values[f.key];
        if (f.type === 'number') {
          if (v === '' || v === null || v === undefined) {
            v = f.required ? '' : null;
          } else {
            v = Number(v);
          }
        } else if (v === '') {
          v = f.required ? v : null;
        } else if (isBooleanSelect(f)) {
          v = v === 'true';
        }
        cleaned[f.key] = v;
      });
      // the state the record was opened in: the server refuses to save over someone else's newer change
      if (sessionRef.current.id && sessionRef.current.updatedAt) cleaned.updated_at = sessionRef.current.updatedAt;
      await onSave(cleaned);
      setDirty(false);
      onClose();
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  const wide = fields.filter(f => f.type !== 'hidden').length >= WIDE_FORM_FIELDS;
  const arrange = wide ? ordered : list => list;

  return (
    // Only a click that starts and ends on the backdrop closes: selecting text in a field
    // and releasing the mouse outside the dialog must not end the form.
    <div className="modal-overlay" role="presentation"
      onMouseDown={e => { pressStartedOnOverlay.current = e.target === e.currentTarget; }}
      onClick={e => { if (pressStartedOnOverlay.current && e.target === e.currentTarget) requestClose(); pressStartedOnOverlay.current = false; }}>
      <div
        className={`modal${wide ? ' modal-wide' : ''}`}
        ref={modalRef}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <div className="modal-header">
          <h3>{title}</h3>
          <button type="button" onClick={requestClose} className="btn-close" aria-label={t('ui.buttons.close')}>
            <CloseIcon size={18} />
          </button>
        </div>
        <form ref={formRef} onSubmit={handleSubmit}>
          <div className="modal-body">
            {error && <div className="alert-error" role="alert">{error}</div>}
            {(() => {
              const renderField = (f) => {
                if (f.type === 'hidden') {
                  return <input type="hidden" key={f.key} name={f.key} value={values[f.key] || ''} />;
                }
                const inputId = `form-field-${f.key}`;
                const options = typeof f.options === 'function' ? f.options(values) : f.options;
                return (
                  <div key={f.key} className={`form-group${spansRow(f) ? ' form-group-full' : ''}`}>
                    <label htmlFor={inputId}>{f.label}{f.required && ' *'}</label>
                    {f.type === 'select' ? (
                      <select
                        id={inputId}
                        value={values[f.key] ?? ''}
                        onChange={e => update(f.key, e.target.value,
                          Object.fromEntries((f.clearOnChange || []).map(key => [key, ''])))}
                        required={f.required}
                      >
                        <option value="">{t('ui.form.pleaseSelect')}</option>
                        {options?.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                        {/* A stored value the list does not offer (imported, older data) stays selectable instead of being lost. */}
                        {values[f.key] !== '' && values[f.key] != null && !options?.some(o => String(o.value) === String(values[f.key])) && (
                          <option value={values[f.key]}>{codeLabel(String(values[f.key]))}</option>
                        )}
                      </select>
                    ) : f.type === 'textarea' ? (
                      <textarea
                        id={inputId}
                        value={values[f.key] || ''}
                        onChange={e => update(f.key, e.target.value)}
                        required={f.required}
                        rows={3}
                      />
                    ) : (
                      <input
                        id={inputId}
                        type={f.type || 'text'}
                        value={values[f.key] ?? ''}
                        onChange={e => update(f.key, e.target.value)}
                        required={f.required}
                        step={f.type === 'number' ? '0.01' : undefined}
                        placeholder={f.placeholder}
                      />
                    )}
                    {f.hint && <small className="form-hint">{f.hint}</small>}
                  </div>
                );
              };

              // Group fields by section (preserve order, backward compatible)
              const sections = [];
              let currentSection = null;
              fields.forEach(f => {
                const section = f.section || null;
                if (section !== currentSection || sections.length === 0) {
                  sections.push({ label: section, fields: [] });
                  currentSection = section;
                }
                sections[sections.length - 1].fields.push(f);
              });

              return sections.map((section, i) => (
                section.label ? (
                  <fieldset key={i} className="form-section">
                    <legend className="form-section-label">{section.label}</legend>
                    <div className={wide ? 'form-grid' : undefined}>{arrange(section.fields).map(renderField)}</div>
                  </fieldset>
                ) : (
                  <div key={i} className={wide ? 'form-grid' : undefined}>{arrange(section.fields).map(renderField)}</div>
                )
              ));
            })()}
          </div>
          {confirmDiscard ? (
            <div className="modal-footer modal-discard" role="alertdialog" aria-modal="false" aria-labelledby="form-discard-question">
              <span id="form-discard-question" className="modal-discard-question">{tr('ui.form.discardQuestion', 'Ungespeicherte Änderungen verwerfen?')}</span>
              <button type="button" onClick={() => setConfirmDiscard(false)} className="btn btn-secondary" autoFocus>{tr('ui.form.keepEditing', 'Weiter bearbeiten')}</button>
              <button type="button" onClick={onClose} className="btn btn-danger">{tr('ui.form.discard', 'Verwerfen')}</button>
            </div>
          ) : (
            <div className="modal-footer">
              <span className="modal-shortcut-hint" aria-hidden="true">{dirty ? tr('ui.form.saveShortcut', 'Strg+Enter speichert') : ''}</span>
              <button type="button" onClick={requestClose} className="btn btn-secondary">{t('ui.buttons.cancel')}</button>
              <button type="submit" className="btn btn-primary" disabled={saving}>
                {saving ? `${t('ui.buttons.save')}...` : t('ui.buttons.save')}
              </button>
            </div>
          )}
        </form>
      </div>
    </div>
  );
}
