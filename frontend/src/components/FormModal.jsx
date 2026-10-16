import { useState, useEffect, useLayoutEffect, useRef, useCallback } from 'react';
import { Link, useInRouterContext, useNavigate } from 'react-router-dom';
import { useTranslation } from '../i18n';
import { CloseIcon } from './Icons';
import { codeLabel } from '../utils/codeLabels';
import { onlyChoices, prerequisiteFor } from '../utils/prerequisites';
import { api } from '../api';
import { useAuth } from '../contexts/AuthContext';
import { formContext } from '../utils/workspaceClient';
import useFormDraft from '../hooks/useFormDraft';
import './workspace.css';
import DuplicateHints from './DuplicateHints';
import DraftDefaults from './DraftDefaults';

const isBooleanSelect = f => f.type === 'select' && f.options?.length === 2
  && f.options.every(o => o.value === 'true' || o.value === 'false');

// Selects hold strings: true/false and numbers come back as 'true'/'false'/'12'.
const toFieldValue = (f, v) => (f.type === 'select' && (typeof v === 'boolean' || typeof v === 'number') ? String(v) : v);

// Today as the date input writes it (local calendar day, not UTC: 00:30 on the 1st is still the 1st).
const localToday = () => {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
};

// Long forms get two columns; free text and explicitly wide fields span both.
const WIDE_FORM_FIELDS = 8;
const spansRow = f => f.full || f.type === 'textarea';
// In two columns, full-width fields (notes, descriptions) go last so the pairs above stay aligned.
const ordered = list => [...list.filter(f => !spansRow(f)), ...list.filter(spansRow)];

// repeatKeep: for a new record, offer "Speichern & weiteren" and keep these fields for the next
// entry (a series of bookings on one account, readings of one day); every other field starts over.
export default function FormModal({ title, fields, initial, onSave, onClose, repeatKeep, draftContext, draftAnchor, autosave = true,
  onSaveNext, saveNextLabel = 'Speichern & nächster Beleg', onDraftRebase }) {
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
  const repeatable = Array.isArray(repeatKeep) && initial?.id == null;
  const [savedCount, setSavedCount] = useState(0);
  const draft = useFormDraft({ fields, initial, enabled: autosave, context: draftContext, anchor: draftAnchor });
  const sessionKey = `${draft.sessionKey}:${initialKey}`;
  // Loading an extra field changes the draft schema, not the record being edited.
  const owner = useAuth()?.user?.id;
  const formIdentity = `${owner || ''}:${draftContext || formContext(window.location.pathname)}:${initialKey}:${draftAnchor?.kind || ''}:${draftAnchor?.id || ''}`;
  const [recoverySource, setRecoverySource] = useState(null);
  const [draftBusy, setDraftBusy] = useState(false);
  const draftWaiting = draft.enabled && (draft.status === 'loading' || Boolean(draft.recovery));
  const fieldDisabled = saving || draftWaiting || draftBusy || (draft.enabled && !draft.ready);
  const modalRef = useRef(null);
  const formRef = useRef(null);
  const againRef = useRef(null);
  const pressStartedOnOverlay = useRef(false);
  const sessionRef = useRef({ key: sessionKey, formIdentity, id: initial?.id, updatedAt: initial?.updated_at });
  const activeSession = useRef(null);
  const savingRef = useRef(false);
  const leaveRef = useRef(null);
  const unloadRef = useRef(null);
  useLayoutEffect(() => {
    activeSession.current = sessionKey;
    return () => { activeSession.current = null; };
  }, [sessionKey]);
  const isCurrentSession = () => activeSession.current === sessionKey;

  useEffect(() => {
    const changedRecord = sessionRef.current.formIdentity !== formIdentity;
    sessionRef.current.key = sessionKey;
    if (changedRecord) {
      sessionRef.current = { key: sessionKey, formIdentity, id: initial?.id, updatedAt: initial?.updated_at };
      setError(null);
      setDirty(false);
      setConfirmDiscard(false);
      leaveRef.current = null;
      savingRef.current = false; setSaving(false); setDraftBusy(false); setRecoverySource(null);
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
  }, [sessionKey, formIdentity, initial, fields]);

  useEffect(() => {
    if (dirty && draft.ready && !draft.recovery) draft.stage(values);
    // A changed schema gets its own private writer after preparation. Keep the
    // current edits; ordinary typing is already staged synchronously by update.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft.sessionKey, draft.ready]);

  // A required choice with one possibility is made already (the only portfolio, property or
  // account); it does not count as an edit, so closing still needs no confirmation.
  useEffect(() => {
    const picks = onlyChoices(fields, values);
    if (Object.keys(picks).length) setValues(current => ({ ...current, ...picks }));
  }, [fields, values]);

  // after "Speichern & weiteren": continue in the first required field that starts over
  // (the amount of the next booking), else in the first field that starts over
  useEffect(() => {
    if (!savedCount) return;
    const keep = new Set(repeatKeep);
    const cleared = fields.filter(f => f.type !== 'hidden' && !keep.has(f.key));
    const next = cleared.find(f => f.required) || cleared[0];
    const element = next && modalRef.current?.querySelector(`#form-field-${next.key}`);
    (element || modalRef.current?.querySelector('.modal-body :is(input:not([type="hidden"]), select, textarea)'))?.focus();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [savedCount]);

  const update = (key, value, extra) => {
    setDirty(true);
    setConfirmDiscard(false);
    const next = { ...values, [key]: value, ...extra };
    draft.stage(next);
    setValues(next);
  };

  const requestLeave = useCallback(action => {
    if (savingRef.current) return;
    if (dirty) { leaveRef.current = action; setConfirmDiscard(true); }
    else action();
  }, [dirty]);

  const requestClose = useCallback(() => {
    requestLeave(onClose);
  }, [requestLeave, onClose]);

  // Reloading or closing the browser also protects an unsaved draft.
  useEffect(() => {
    if (!dirty) return;
    const beforeUnload = event => { event.preventDefault(); event.returnValue = ''; };
    unloadRef.current = beforeUnload;
    window.addEventListener('beforeunload', beforeUnload);
    return () => { window.removeEventListener('beforeunload', beforeUnload); if (unloadRef.current === beforeUnload) unloadRef.current = null; };
  }, [dirty]);

  // Escape closes (or asks first); a second Escape on the question returns to editing.
  // Ctrl/Cmd+Enter saves from any field, including multi-line notes.
  useEffect(() => {
    const handler = (e) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        if (confirmDiscard) setConfirmDiscard(false);
        else requestClose();
      } else if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && modalRef.current?.contains(document.activeElement)) {
        e.preventDefault();
        if (savingRef.current || confirmDiscard) return;
        // Ctrl+Shift+Enter: save and start the next entry
        if (e.shiftKey && repeatable) againRef.current?.click();
        else formRef.current?.requestSubmit();
      }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [requestClose, confirmDiscard, repeatable]);

  // Focus trap
  useEffect(() => {
    const modal = modalRef.current;
    if (!modal) return;
    const query = () => modal.querySelectorAll(
      'button:not(:disabled), [href], input:not([type="hidden"]):not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"]):not(:disabled)'
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
  }, [fields, confirmDiscard]);

  const handleSubmit = async (e, again = false, next = false) => {
    e.preventDefault();
    if (savingRef.current || confirmDiscard || draftWaiting || draft.status === 'changed' || draftBusy) return;
    // the browser's own checks (required fields) apply to "Speichern & weiteren" as well
    if ((again || next) && !formRef.current?.reportValidity()) return;
    savingRef.current = true;
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
      await (next ? onSaveNext(cleaned) : onSave(cleaned));
      if (!isCurrentSession()) return;
      // The domain save succeeded. Cleanup failure must never re-submit it.
      await draft.clear({ completed: true }).catch(() => {});
      if (!isCurrentSession()) return;
      if (unloadRef.current) {
        window.removeEventListener('beforeunload', unloadRef.current);
        unloadRef.current = null;
      }
      setDirty(false);
      if (next) return;
      if (again) {
        const keep = new Set(repeatKeep);
        setValues(current => Object.fromEntries(fields.map(f => [f.key,
          keep.has(f.key) ? current[f.key] : toFieldValue(f, f.default ?? '')])));
        setSavedCount(count => count + 1);
        return;
      }
      onClose();
    } catch (err) {
      if (isCurrentSession()) setError(err.message);
    } finally {
      if (isCurrentSession()) { savingRef.current = false; setSaving(false); }
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
            {initial?.id == null && ['contracts', 'bookings'].includes(draftContext || formContext(window.location.pathname)) && <DraftDefaults
              context={draftContext || formContext(window.location.pathname)} propertyId={values.property_id} disabled={fieldDisabled}
              onApply={defaults => { const next = { ...values }; for (const [key, value] of Object.entries(defaults)) if (fields.some(field => field.key === key) && !next[key]) next[key] = value; setValues(next); setDirty(true); draft.stage(next); }} />}
            <DuplicateHints values={values} initial={initial} context={draftContext} />
            {draft.enabled && <div className="draft-status" role="status">
              {draft.status === 'loading' ? 'Gespeicherte Entwürfe werden geprüft …'
                : draft.status === 'saving' || draft.status === 'pending' ? 'Entwurf wird gesichert …'
                  : draft.status === 'saved' ? 'Entwurf automatisch gesichert'
                    : draft.status === 'ready' ? 'Eingaben werden automatisch als Entwurf gesichert.' : ''}
            </div>}
            {draft.error && <div className="alert-error" role="alert">{draft.error}<button type="button" className="btn btn-sm btn-secondary" onClick={draft.retry}>Sicherung erneut versuchen</button></div>}
            {(draft.recovery || draft.status === 'changed') && <section className="draft-recovery" aria-label="Entwurf wiederaufnehmen">
              <strong>{draft.recovery ? 'Ungespeicherter Entwurf vorhanden' : 'Der Datensatz wurde zwischenzeitlich geändert.'}</strong>
              <p>{draft.recovery?.source_state?.status === 'deleted' ? 'Die ursprüngliche Akte wurde gelöscht. Der Entwurf bleibt zur Einsicht erhalten.' : 'Prüfen Sie die Eingaben vor der Übernahme. Die Übernahme speichert ausschließlich den Entwurf.'}</p>
              {draft.recovery?.source_state?.status === 'deleted' && <details open><summary>Entwurfsinhalt prüfen und kopieren</summary><dl>{fields.filter(f => f.type !== 'hidden').map(f => <div key={f.key}><dt>{f.label}</dt><dd>{String(draft.recovery.values?.[f.key] ?? '—')}</dd></div>)}</dl></details>}
              {draft.recovery?.server_values && <details><summary>Abweichenden Serverentwurf anzeigen</summary><dl>{fields.filter(f => f.type !== 'hidden').map(f => <div key={f.key}><dt>{f.label}</dt><dd>{String(draft.recovery.server_values[f.key] ?? '—')}</dd></div>)}</dl></details>}
              {recoverySource?.contextOnly && <p>Die zugehörige Akte „{recoverySource.title}“ wurde aktualisiert. Prüfen Sie die Notiz und ihre Zuordnung, bevor Sie den Entwurf auf diesen Stand übernehmen.</p>}
              {recoverySource && !recoverySource.contextOnly && <div className="table-scroll"><table className="data-table"><thead><tr><th>Feld</th><th>Aktueller Datensatz</th><th>Entwurf</th></tr></thead><tbody>{fields.filter(f => f.type !== 'hidden' && String(recoverySource.values[f.key] ?? '') !== String((draft.recovery?.values || values)[f.key] ?? '')).map(f => <tr key={f.key}><th>{f.label}</th><td>{String(recoverySource.values[f.key] ?? '—')}</td><td>{String((draft.recovery?.values || values)[f.key] ?? '—')}</td></tr>)}</tbody></table></div>}
              <div className="workspace-actions">
                {draft.recovery?.source_state?.status !== 'deleted' && <button type="button" className="btn btn-secondary" disabled={draftBusy} onClick={async () => {
                  setDraftBusy(true); setError(null);
                  try {
                    const source = draft.recovery?.source;
                    const changed = draft.status === 'changed' || draft.recovery?.source_state?.status === 'changed';
                    if (changed && !recoverySource) {
                      const reference = source || draft.recovery?.anchor || draftAnchor;
                      if (!reference?.kind || !reference?.id) throw new Error('Die geänderte Quellakte ist nicht mehr eindeutig. Bitte das Formular erneut öffnen; der Entwurf bleibt erhalten.');
                      const fresh = await api.get(`/workspace/source/${encodeURIComponent(reference.kind)}/${encodeURIComponent(reference.id)}`);
                      if (!isCurrentSession()) return;
                      setRecoverySource({ ...fresh, values: fresh.values || {}, contextOnly: !source });
                      return;
                    }
                    const restored = Object.fromEntries(fields.map(f => [f.key, toFieldValue(f, (draft.recovery?.values || values)[f.key] ?? f.default ?? '')]));
                    await draft.resume(restored, recoverySource?.revision, recoverySource?.dependency_etags);
                    if (!isCurrentSession()) return;
                    if (recoverySource) {
                      if (!recoverySource.contextOnly) sessionRef.current.updatedAt = recoverySource.revision;
                      onDraftRebase?.(recoverySource);
                    }
                    setValues(restored); setDirty(true); setRecoverySource(null); draft.stage(restored);
                  } catch (failure) { if (isCurrentSession()) { setError(failure.message); if (failure.statusCode === 409) setRecoverySource(null); } }
                  finally { if (isCurrentSession()) setDraftBusy(false); }
                }}>{recoverySource ? 'Verglichenen Entwurf übernehmen' : draft.status === 'changed' || draft.recovery?.source_state?.status === 'changed' ? 'Aktuellen Stand vergleichen' : 'Entwurf wiederaufnehmen'}</button>}
                <button type="button" className="btn btn-ghost" disabled={draftBusy} onClick={async () => {
                  setDraftBusy(true);
                  try { await draft.clear(); if (isCurrentSession()) setRecoverySource(null); }
                  catch (failure) { if (isCurrentSession()) setError(failure.message); }
                  finally { if (isCurrentSession()) setDraftBusy(false); }
                }}>Entwurf verwerfen</button>
              </div>
            </section>}
            {savedCount > 0 && !error && (
              <div className="form-saved-next" role="status">
                {tr('ui.form.savedNext', '{{count}} gespeichert – nächster Eintrag').replace('{{count}}', savedCount)}
              </div>
            )}
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
                        disabled={fieldDisabled}
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
                        disabled={fieldDisabled}
                        rows={3}
                      />
                    ) : f.type === 'date' ? (
                      // dates: one click for today, the most common entry (booking, reading, appointment)
                      <span className="date-input-row">
                        <input
                          id={inputId}
                          type="date"
                          value={values[f.key] ?? ''}
                          onChange={e => update(f.key, e.target.value)}
                          required={f.required}
                          disabled={fieldDisabled}
                        />
                        {!f.noToday && <button type="button" className="btn btn-sm btn-ghost date-today"
                          aria-label={tr('ui.form.todayFill', 'Heute eintragen')} aria-controls={inputId} disabled={fieldDisabled}
                          onClick={() => update(f.key, localToday())}>{tr('ui.form.today', 'Heute')}</button>}
                      </span>
                    ) : (
                      <input
                        id={inputId}
                        type={f.type || 'text'}
                        value={values[f.key] ?? ''}
                        onChange={e => update(f.key, e.target.value)}
                        required={f.required}
                        disabled={fieldDisabled}
                        step={f.type === 'number' ? '0.01' : undefined}
                        placeholder={f.placeholder}
                      />
                    )}
                    {f.hint && <small className="form-hint">{f.hint}</small>}
                    <MissingChoice hint={prerequisiteFor(f, options)} requestLeave={requestLeave} />
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
              <button type="button" disabled={draftBusy} onClick={async () => {
                // A plain prerequisite link may leave the browser page immediately.
                // The explicit discard has already answered its unload question.
                if (unloadRef.current) window.removeEventListener('beforeunload', unloadRef.current);
                if (!draft.enabled) { setDirty(false); setConfirmDiscard(false); (leaveRef.current || onClose)(); return; }
                setDraftBusy(true);
                try { await draft.clear(); if (isCurrentSession()) { setDirty(false); setConfirmDiscard(false); (leaveRef.current || onClose)(); } }
                catch (failure) { if (isCurrentSession()) { setError(failure.message); setConfirmDiscard(false); } }
                finally { if (isCurrentSession()) setDraftBusy(false); }
              }} className="btn btn-danger">{tr('ui.form.discard', 'Verwerfen')}</button>
            </div>
          ) : (
            <div className="modal-footer">
              <span className="modal-shortcut-hint" aria-hidden="true">{dirty ? tr('ui.form.saveShortcut', 'Strg+Enter speichert') : ''}</span>
              <button type="button" onClick={requestClose} className="btn btn-secondary">{t('ui.buttons.cancel')}</button>
              {repeatable && (
                <button ref={againRef} type="button" className="btn btn-secondary" disabled={fieldDisabled || draft.status === 'changed'}
                  title={tr('ui.form.saveAndNewShortcut', 'Strg+Umschalt+Enter')}
                  onClick={event => handleSubmit(event, true)}>{tr('ui.form.saveAndNew', 'Speichern & weiteren')}</button>
              )}
              {onSaveNext && <button type="button" className="btn btn-secondary" disabled={fieldDisabled || draft.status === 'changed'}
                onClick={event => handleSubmit(event, false, true)}>{saveNextLabel}</button>}
              <button type="submit" className="btn btn-primary" disabled={fieldDisabled || draft.status === 'changed'}>
                {saving ? `${t('ui.buttons.save')}...` : t('ui.buttons.save')}
              </button>
            </div>
          )}
        </form>
      </div>
    </div>
  );
}

// Nothing to choose from yet: say what is missing and link to where it is created.
function MissingChoice({ hint, requestLeave }) {
  const inRouter = useInRouterContext();
  if (!hint) return null;
  return (
    <small className="form-hint form-hint-missing" role="note">
      {hint.text}{' '}
      {inRouter ? <PrerequisiteLink hint={hint} requestLeave={requestLeave} /> : <a href={hint.to}
        onClick={event => { if (isCurrentNavigation(event)) { event.preventDefault(); requestLeave(() => window.location.assign(hint.to)); } }}>{hint.label}</a>}
    </small>
  );
}

const isCurrentNavigation = event => event.button === 0 && !event.ctrlKey && !event.metaKey && !event.altKey && !event.shiftKey;

function PrerequisiteLink({ hint, requestLeave }) {
  const navigate = useNavigate();
  return <Link to={hint.to} onClick={event => {
    if (!isCurrentNavigation(event)) return;
    event.preventDefault();
    requestLeave(() => navigate(hint.to));
  }}>{hint.label}</Link>;
}
