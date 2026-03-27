import { useState, useEffect, useRef } from 'react';
import { useTranslation } from '../i18n';
import { CloseIcon } from './Icons';

export default function FormModal({ title, fields, initial, onSave, onClose }) {
  const { t } = useTranslation();
  const [values, setValues] = useState({});
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);
  const modalRef = useRef(null);

  useEffect(() => {
    const init = {};
    fields.forEach(f => {
      init[f.key] = initial?.[f.key] ?? f.default ?? '';
    });
    setValues(init);
  }, [initial, fields]);

  // Escape key to close
  useEffect(() => {
    const handler = (e) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  // Focus trap
  useEffect(() => {
    const modal = modalRef.current;
    if (!modal) return;
    const focusable = modal.querySelectorAll(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    );
    if (focusable.length > 0) focusable[0].focus();

    const trapFocus = (e) => {
      if (e.key !== 'Tab' || focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
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
        }
        cleaned[f.key] = v;
      });
      await onSave(cleaned);
      onClose();
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose} role="presentation">
      <div
        className="modal"
        ref={modalRef}
        onClick={e => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <div className="modal-header">
          <h3>{title}</h3>
          <button onClick={onClose} className="btn-close" aria-label={t('ui.buttons.close')}>
            <CloseIcon size={18} />
          </button>
        </div>
        <form onSubmit={handleSubmit}>
          <div className="modal-body">
            {error && <div className="alert-error" role="alert">{error}</div>}
            {(() => {
              const renderField = (f) => {
                if (f.type === 'hidden') {
                  return <input type="hidden" key={f.key} name={f.key} value={values[f.key] || ''} />;
                }
                const inputId = `form-field-${f.key}`;
                return (
                  <div key={f.key} className="form-group">
                    <label htmlFor={inputId}>{f.label}{f.required && ' *'}</label>
                    {f.type === 'select' ? (
                      <select
                        id={inputId}
                        value={values[f.key] || ''}
                        onChange={e => setValues({ ...values, [f.key]: e.target.value })}
                        required={f.required}
                      >
                        <option value="">{t('ui.form.pleaseSelect')}</option>
                        {f.options?.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                      </select>
                    ) : f.type === 'textarea' ? (
                      <textarea
                        id={inputId}
                        value={values[f.key] || ''}
                        onChange={e => setValues({ ...values, [f.key]: e.target.value })}
                        required={f.required}
                        rows={3}
                      />
                    ) : (
                      <input
                        id={inputId}
                        type={f.type || 'text'}
                        value={values[f.key] ?? ''}
                        onChange={e => setValues({ ...values, [f.key]: e.target.value })}
                        required={f.required}
                        step={f.type === 'number' ? '0.01' : undefined}
                        placeholder={f.placeholder}
                      />
                    )}
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
                    {section.fields.map(renderField)}
                  </fieldset>
                ) : (
                  <div key={i}>{section.fields.map(renderField)}</div>
                )
              ));
            })()}
          </div>
          <div className="modal-footer">
            <button type="button" onClick={onClose} className="btn btn-secondary">{t('ui.buttons.cancel')}</button>
            <button type="submit" className="btn btn-primary" disabled={saving}>
              {saving ? `${t('ui.buttons.save')}...` : t('ui.buttons.save')}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
