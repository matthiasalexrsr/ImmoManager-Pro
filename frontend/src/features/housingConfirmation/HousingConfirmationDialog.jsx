import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { AlertTriangle, ArrowLeft, CheckCircle2, Download, FileText, Plus, Trash2, X } from 'lucide-react';
import { useAuth } from '../../contexts/AuthContext';
import { useTranslation } from '../../i18n';
import { mayWrite } from '../../utils/permissions';
import PdfPreview from '../../components/PdfPreview';
import { resolveFileUrl } from '../partyWorkspace/files';
import { useModalDialog } from '../partyWorkspace/useModalDialog';
import { housingConfirmationService } from './housingConfirmationApi';
import {
  addSuggestedOccupant,
  blankHousingForm,
  cloneHousingForm,
  formFromCertificateData,
  formSignature,
  housingBindingKey,
  isConflictOutcome,
  isPrivateForgetOutcome,
  personRow,
  validateHousingForm,
} from './housingConfirmationModel';
import { housingText } from './housingConfirmationText';
import useHousingConfirmationCommand from './useHousingConfirmationCommand';
import './HousingConfirmation.css';

const PAGE_SIZE = 25;

function neutralPrivate(binding, { loading = false, accessDenied = false } = {}) {
  return {
    binding, source: null, form: null, baseline: null, preview: null, previewInvalidated: false,
    correctionOf: null, history: [], nextCursor: null, loading, error: null, sourceConflict: false,
    accessDenied, saved: false,
  };
}

function formatDate(value, locale) {
  if (!value) return '—';
  const date = /^\d{4}-\d{2}-\d{2}$/.test(value) ? new Date(`${value}T00:00:00Z`) : new Date(value);
  if (!Number.isFinite(date.getTime())) return String(value);
  return new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeZone: 'UTC' }).format(date);
}

/**
 * Wohnungsgeberbestätigung for one exact contract: enter the facts, review the PDF,
 * confirm and release it as an immutable original; earlier ones can be opened and corrected.
 *
 * Private state (form, preview, history) belongs to one contract, user, role and set of
 * write areas: when any of them changes it is discarded, and so is a pending retry.
 */
export default function HousingConfirmationDialog({ contractId, onClose, onPublished, service = housingConfirmationService }) {
  const auth = useAuth();
  const user = auth?.user;
  const write = auth?.write ?? null;
  const { locale } = useTranslation();
  const titleId = useId();
  const dialogRef = useRef(null);
  const binding = housingBindingKey(contractId, user, write);
  const canPublish = mayWrite(write, `/contracts/${contractId}/housing-confirmations`) && mayWrite(write, '/documents');
  const controllers = useRef(new Set());
  const [stored, setStored] = useState(() => neutralPrivate(''));
  const [shownPdf, setShownPdf] = useState(null);
  const [askDiscard, setAskDiscard] = useState(false);
  const objectUrl = useRef(null);
  const view = stored.binding === binding ? stored : neutralPrivate(binding, { loading: Boolean(binding) });
  // a PDF belongs to the binding it was opened under, like the rest of the private state
  const pdfView = shownPdf?.binding === binding ? shownPdf : null;
  const say = useCallback((key, params) => housingText(locale, key, params), [locale]);

  const abortRequests = useCallback(() => {
    for (const controller of controllers.current) controller.abort();
    controllers.current.clear();
  }, []);

  const showPdf = useCallback(next => {
    if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
    objectUrl.current = next?.revoke ? next.url : null;
    setShownPdf(next);
  }, []);
  const closePdf = useCallback(() => showPdf(null), [showPdf]);
  useEffect(() => () => {
    if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
  }, []);

  const forgetPrivate = useCallback(error => {
    if (!isPrivateForgetOutcome(error)) return false;
    abortRequests();
    closePdf();
    setStored(neutralPrivate(binding, { accessDenied: true }));
    return true;
  }, [abortRequests, binding, closePdf]);

  const command = useHousingConfirmationCommand(binding, forgetPrivate);
  const locked = command.busy || command.state.phase === 'unknown';
  const dirty = Boolean(view.form && view.baseline !== formSignature(view.form))
    || Boolean(view.correctionOf) || command.state.phase === 'unknown';

  const startRequest = useCallback(() => {
    const controller = new AbortController();
    controllers.current.add(controller);
    return controller;
  }, []);
  const finishRequest = useCallback(controller => controllers.current.delete(controller), []);

  const report = useCallback((error, { conflict = false } = {}) => {
    if (forgetPrivate(error)) return;
    setStored(current => current.binding !== binding ? current : conflict && isConflictOutcome(error)
      ? { ...current, error: null, sourceConflict: true, preview: null }
      : { ...current, error: error?.message || say('errorTitle') });
  }, [binding, forgetPrivate, say]);

  const loadBinding = useCallback(async ({ preserveForm = false } = {}) => {
    if (!binding) return;
    abortRequests();
    const controller = startRequest();
    setStored(current => ({
      ...(current.binding === binding ? current : neutralPrivate(binding)),
      loading: true, error: null, sourceConflict: false, accessDenied: false, preview: null,
      previewInvalidated: false, saved: false,
      ...(preserveForm ? {} : { source: null, form: null, baseline: null, correctionOf: null, history: [], nextCursor: null }),
    }));
    try {
      const [source, history] = await Promise.all([
        service.loadSource(contractId, { signal: controller.signal }),
        service.listHistory(contractId, { limit: PAGE_SIZE, signal: controller.signal }),
      ]);
      if (controller.signal.aborted) return;
      setStored(current => {
        if (current.binding !== binding) return current;
        const form = preserveForm && current.form ? current.form : blankHousingForm();
        return {
          ...current, source, form,
          baseline: preserveForm && current.form ? current.baseline : formSignature(form),
          history: history.items, nextCursor: history.next_cursor, loading: false, error: null,
        };
      });
    } catch (error) {
      if (controller.signal.aborted || error?.name === 'AbortError') return;
      if (!forgetPrivate(error)) {
        setStored(current => current.binding === binding
          ? { ...current, loading: false, error: error?.message?.startsWith('invalid_') ? say('loadFailed') : error?.message || say('loadFailed') }
          : current);
      }
    } finally {
      finishRequest(controller);
    }
  }, [abortRequests, binding, contractId, finishRequest, forgetPrivate, service, startRequest, say]);

  useEffect(() => {
    if (!binding) return undefined;
    void loadBinding();
    return abortRequests;
  }, [abortRequests, binding, loadBinding]);

  const updateForm = useCallback(updater => {
    if (locked) return;
    setStored(current => {
      if (current.binding !== binding || !current.form) return current;
      const form = updater(cloneHousingForm(current.form));
      return { ...current, form, preview: null, previewInvalidated: Boolean(current.preview), saved: false, error: null };
    });
    if (!['unknown', 'sending'].includes(command.state.phase)) command.reset();
  }, [binding, command, locked]);

  const patchForm = patch => updateForm(form => ({ ...form, ...patch }));
  const patchConfirmation = patch => {
    if (locked) return;
    setStored(current => current.binding === binding && current.form
      ? { ...current, form: { ...current.form, ...patch }, saved: false, error: null } : current);
    if (!['unknown', 'sending'].includes(command.state.phase)) command.reset();
  };

  const checkedInput = (forPublish = false) => {
    const checked = validateHousingForm(view.form, { forPublish });
    if (!checked.valid) setStored(current => current.binding === binding ? { ...current, error: say('requiredFields') } : current);
    return checked.valid ? checked.data : null;
  };

  const runPreview = async () => {
    if (!view.form || !view.source) return;
    const data = checkedInput();
    if (!data) return;
    const controller = startRequest();
    setStored(current => current.binding === binding ? { ...current, error: null, sourceConflict: false } : current);
    try {
      const preview = await service.preview({ contractId, data, sourceEtags: view.source.source_etags,
        correctionOf: view.correctionOf }, { signal: controller.signal });
      if (controller.signal.aborted) return;
      setStored(current => current.binding === binding
        ? { ...current, preview, previewInvalidated: false, sourceConflict: false, error: null, saved: false } : current);
    } catch (error) {
      if (!controller.signal.aborted && error?.name !== 'AbortError') report(error, { conflict: true });
    } finally {
      finishRequest(controller);
    }
  };

  const openPreviewPdf = async () => {
    if (!view.preview || !view.source) return;
    const data = checkedInput();
    if (!data) return;
    const controller = startRequest();
    try {
      const url = await service.previewPdfUrl({ contractId, data, sourceEtags: view.source.source_etags,
        correctionOf: view.correctionOf, preview: view.preview }, { signal: controller.signal });
      if (controller.signal.aborted) { URL.revokeObjectURL(url); return; }
      showPdf({ binding, url, revoke: true, title: say('previewPdfTitle') });
    } catch (error) {
      if (!controller.signal.aborted && error?.name !== 'AbortError') report(error, { conflict: true });
    } finally {
      finishRequest(controller);
    }
  };

  const publish = () => {
    if (!view.form || !view.preview || !canPublish || !view.source) return;
    const data = checkedInput(true);
    if (!data) return;
    const prepared = service.preparePublish({
      contractId, data, sourceEtags: view.source.source_etags, preview: view.preview, correctionOf: view.correctionOf,
      confirmations: {
        confirmed_actual_move_in: view.form.confirmed_actual_move_in,
        confirmed_authority: view.form.confirmed_authority,
        confirmed_residents: view.form.confirmed_residents,
      },
    });
    command.execute({
      label: 'publish-housing-confirmation',
      payload: prepared.payload,
      send: prepared.send,
      onSuccess: record => {
        setStored(current => current.binding === binding && current.form ? {
          ...current, preview: null, previewInvalidated: false, baseline: formSignature(current.form),
          correctionOf: null, saved: true, error: null,
          history: [record, ...current.history.filter(item => item.id !== record.id)],
        } : current);
        onPublished?.(record);   // a new document: lists and counts elsewhere are stale
      },
    });
  };

  const loadMore = async () => {
    if (!view.nextCursor || view.loading) return;
    const controller = startRequest();
    try {
      const page = await service.listHistory(contractId, { cursor: view.nextCursor, limit: PAGE_SIZE, signal: controller.signal });
      if (controller.signal.aborted) return;
      setStored(current => current.binding === binding ? {
        ...current,
        history: [...current.history, ...page.items.filter(item => !current.history.some(known => known.id === item.id))],
        nextCursor: page.next_cursor,
      } : current);
    } catch (error) {
      if (!controller.signal.aborted && error?.name !== 'AbortError') report(error);
    } finally {
      finishRequest(controller);
    }
  };

  const downloadOriginal = async item => {
    const controller = startRequest();
    try {
      await service.downloadOriginal(item, view.source?.contract_number, { signal: controller.signal });
    } catch (error) {
      if (!controller.signal.aborted && error?.name !== 'AbortError') report(error);
    } finally {
      finishRequest(controller);
    }
  };

  const startCorrection = item => {
    if (locked || !canPublish) return;
    const form = formFromCertificateData(item.data);
    setStored(current => current.binding === binding ? {
      ...current, form, baseline: formSignature(form),
      correctionOf: { document_id: item.document_id, version_id: item.version_id },
      preview: null, previewInvalidated: false, saved: false, error: null,
    } : current);
    command.reset();
  };

  const closeNow = useCallback(() => {
    abortRequests();
    command.abort();
    onClose?.();
  }, [abortRequests, command, onClose]);

  const requestClose = useCallback(() => {
    if (command.busy) return;
    if (pdfView) { closePdf(); return; }
    if (askDiscard) { setAskDiscard(false); return; }
    if (dirty || view.preview) { setAskDiscard(true); return; }
    closeNow();
  }, [askDiscard, closeNow, closePdf, command.busy, dirty, pdfView, view.preview]);

  useModalDialog(dialogRef, requestClose, Boolean(contractId && binding));

  if (!contractId || !binding) return null;

  const notice = (kind, content, key) => (
    <div key={key} className={`housing-confirmation__notice housing-confirmation__notice--${kind}`} role="alert">
      <AlertTriangle size={18} aria-hidden="true" />{content}
    </div>
  );

  return createPortal(
    <div className="housing-confirmation__overlay" role="presentation"
      onMouseDown={event => { if (event.target === event.currentTarget) requestClose(); }}>
      <section className="housing-confirmation" ref={dialogRef} role="dialog" aria-modal="true"
        aria-labelledby={titleId} tabIndex={-1} aria-busy={command.busy}>
        <header className="housing-confirmation__header">
          <div>
            <p className="housing-confirmation__eyebrow">{say('eyebrow')}</p>
            <h2 id={titleId}>{pdfView ? pdfView.title : say('title')}</h2>
            {view.source && <p>{view.source.contract_number} · {view.source.property_label} · {view.source.unit_label}</p>}
          </div>
          <button type="button" className="housing-confirmation__icon-button" aria-label={say('close')}
            disabled={command.busy} onClick={requestClose}><X size={20} aria-hidden="true" /></button>
        </header>

        {pdfView ? <div className="housing-confirmation__pdf">
          <div className="housing-confirmation__pdf-bar">
            <button type="button" className="btn btn-secondary btn-sm" onClick={closePdf}>
              <ArrowLeft size={16} aria-hidden="true" />{say('back')}</button>
          </div>
          <PdfPreview key={pdfView.url} url={pdfView.url} title={pdfView.title} />
        </div> : <div className="housing-confirmation__body">
          {askDiscard && <div className="housing-confirmation__notice housing-confirmation__notice--warning" role="alertdialog"
            aria-label={say('discardTitle')}>
            <AlertTriangle size={18} aria-hidden="true" /><div><strong>{say('discardTitle')}</strong><p>{say('discardPrompt')}</p></div>
            <div className="housing-confirmation__history-actions">
              <button type="button" className="btn btn-secondary btn-sm" onClick={() => setAskDiscard(false)}>{say('keepEditing')}</button>
              <button type="button" className="btn btn-danger btn-sm" onClick={closeNow}>{say('discardConfirm')}</button>
            </div>
          </div>}
          {view.loading && <p role="status">{say('loading')}</p>}
          {view.accessDenied && notice('error', <span>{say('accessLost')}</span>, 'access')}
          {view.error && notice('error', <span>{view.error}</span>, 'error')}
          {view.sourceConflict && notice('warning', <>
            <div><strong>{say('conflictTitle')}</strong><p>{say('conflictBody')}</p></div>
            <button type="button" className="btn btn-secondary btn-sm" onClick={() => void loadBinding({ preserveForm: true })}>
              {say('reloadSource')}</button>
          </>, 'source')}
          {command.state.phase === 'unknown' && notice('warning', <>
            <div><strong>{say('unknownTitle')}</strong><p>{say('unknownBody')}</p></div>
            <button type="button" className="btn btn-primary btn-sm" onClick={command.retryExact}>{say('retryExact')}</button>
          </>, 'unknown')}
          {command.state.phase === 'conflict' && notice('warning', <>
            <div><strong>{say('conflictTitle')}</strong><p>{command.state.error?.message || say('conflictBody')}</p></div>
            <button type="button" className="btn btn-secondary btn-sm" onClick={() => { command.reset(); void loadBinding({ preserveForm: true }); }}>
              {say('reloadSource')}</button>
          </>, 'conflict')}
          {command.state.phase === 'error' && notice('error', <span>{command.state.error?.message || say('errorTitle')}</span>, 'command')}
          {!canPublish && !view.loading && !view.accessDenied && <p className="housing-confirmation__policy" role="note">{say('readOnly')}</p>}

          {!view.loading && !view.accessDenied && view.source && view.form && <>
            <section className="housing-confirmation__source" aria-label={say('contract')}>
              <div><span>{say('property')}</span><strong>{view.source.property_label}</strong></div>
              <div><span>{say('unit')}</span><strong>{view.source.unit_label}</strong></div>
              <div><span>{say('contract')}</span><strong>{view.source.contract_number}</strong></div>
              <div><span>{say('contractStart')}</span><strong>{formatDate(view.source.reference_dates.contract_start_date, locale)}</strong></div>
            </section>

            {canPublish && <>
              <fieldset className="housing-confirmation__section" disabled={locked}>
                <legend>{say('dwelling')}</legend>
                {view.source.suggestions.dwelling_address && <div className="housing-confirmation__suggestion">
                  <div><span>{say('suggestedAddress')}</span><strong>{view.source.suggestions.dwelling_address}</strong></div>
                  <button type="button" className="btn btn-secondary btn-sm" onClick={() => patchForm({
                    dwelling_address: view.source.suggestions.dwelling_address,
                    dwelling_label: view.source.suggestions.dwelling_label || view.form.dwelling_label,
                  })}>{say('sourceSuggestion')}</button>
                </div>}
                <label>{say('dwellingAddress')}<textarea rows="3" value={view.form.dwelling_address}
                  onChange={event => patchForm({ dwelling_address: event.target.value })} /></label>
                <label>{say('dwellingLabel')}<input value={view.form.dwelling_label}
                  onChange={event => patchForm({ dwelling_label: event.target.value })} /></label>
                <label>{say('actualMoveIn')}<input type="date" value={view.form.actual_move_in_date}
                  aria-describedby={`${titleId}-move-in-hint`}
                  onChange={event => patchForm({ actual_move_in_date: event.target.value })} /></label>
                <small id={`${titleId}-move-in-hint`}>{say('actualMoveInHint')}</small>
              </fieldset>

              <fieldset className="housing-confirmation__section" disabled={locked}>
                <legend>{say('provider')}</legend>
                {(view.source.suggestions.housing_provider_name || view.source.suggestions.housing_provider_address) && <div className="housing-confirmation__suggestion">
                  <div><span>{say('suggestedProvider')}</span>
                    <strong>{view.source.suggestions.housing_provider_name || '—'}</strong>
                    {view.source.suggestions.housing_provider_address && <small>{view.source.suggestions.housing_provider_address}</small>}</div>
                  <button type="button" className="btn btn-secondary btn-sm" onClick={() => patchForm({
                    housing_provider_name: view.source.suggestions.housing_provider_name || view.form.housing_provider_name,
                    housing_provider_address: view.source.suggestions.housing_provider_address || view.form.housing_provider_address,
                  })}>{say('sourceSuggestion')}</button>
                </div>}
                <label>{say('providerName')}<input value={view.form.housing_provider_name}
                  onChange={event => patchForm({ housing_provider_name: event.target.value })} /></label>
                <label>{say('providerAddress')}<textarea rows="3" value={view.form.housing_provider_address}
                  onChange={event => patchForm({ housing_provider_address: event.target.value })} /></label>
              </fieldset>

              <fieldset className="housing-confirmation__section" disabled={locked}>
                <legend>{say('owner')}</legend>
                <label>{say('ownerRelation')}<select value={view.form.owner_relation}
                  onChange={event => patchForm({ owner_relation: event.target.value, owner_name: event.target.value === 'same' ? '' : view.form.owner_name })}>
                  <option value="">{say('ownerUnknown')}</option>
                  <option value="same">{say('ownerSame')}</option>
                  <option value="different">{say('ownerDifferent')}</option>
                </select></label>
                {view.form.owner_relation === 'different' && <>
                  {view.source.suggestions.owner_name && <div className="housing-confirmation__suggestion">
                    <div><span>{say('suggestedOwner')}</span><strong>{view.source.suggestions.owner_name}</strong></div>
                    <button type="button" className="btn btn-secondary btn-sm"
                      onClick={() => patchForm({ owner_name: view.source.suggestions.owner_name })}>{say('sourceSuggestion')}</button>
                  </div>}
                  <label>{say('ownerName')}<input value={view.form.owner_name}
                    onChange={event => patchForm({ owner_name: event.target.value })} /></label>
                </>}
              </fieldset>

              <fieldset className="housing-confirmation__section" disabled={locked}>
                <legend>{say('persons')}</legend>
                {view.source.suggestions.main_tenant_name && <div className="housing-confirmation__suggestion">
                  <div><span>{say('mainTenantSuggestion')}</span><strong>{view.source.suggestions.main_tenant_name}</strong></div>
                  <button type="button" className="btn btn-secondary btn-sm"
                    onClick={() => updateForm(form => addSuggestedOccupant(form, view.source.suggestions.main_tenant_name))}>
                    {say('addSuggestion')}</button>
                </div>}
                <div className="housing-confirmation__persons">
                  {view.form.occupants.map((person, index) => <div className="housing-confirmation__person" key={person.key}>
                    <label>{say('occupant')} {index + 1}<input value={person.name}
                      onChange={event => updateForm(form => {
                        form.occupants[index].name = event.target.value;
                        return form;
                      })} /></label>
                    <button type="button" className="btn btn-secondary btn-sm" aria-label={`${say('removePerson')} ${index + 1}`}
                      disabled={view.form.occupants.length === 1}
                      onClick={() => updateForm(form => ({ ...form, occupants: form.occupants.filter((_, at) => at !== index) }))}>
                      <Trash2 size={16} aria-hidden="true" /></button>
                  </div>)}
                </div>
                <button type="button" className="btn btn-secondary"
                  onClick={() => updateForm(form => ({ ...form, occupants: [...form.occupants, personRow()] }))}>
                  <Plus size={16} aria-hidden="true" />{say('addPerson')}</button>
              </fieldset>

              <fieldset className="housing-confirmation__section" disabled={locked}>
                <legend>{say('issue')}</legend>
                <label>{say('issueDate')}<input type="date" value={view.form.issue_date}
                  onChange={event => patchForm({ issue_date: event.target.value })} /></label>
                <label>{say('issuerName')}<input value={view.form.issuer_name}
                  onChange={event => patchForm({ issuer_name: event.target.value })} /></label>
                <label>{say('issuerRole')}<select value={view.form.issuer_role}
                  onChange={event => patchForm({ issuer_role: event.target.value })}>
                  <option value="">{say('ownerUnknown')}</option>
                  <option value="housing_provider">{say('role_housing_provider')}</option>
                  <option value="authorized_person">{say('role_authorized_person')}</option>
                </select></label>
              </fieldset>

              <section className="housing-confirmation__review-actions">
                <button type="button" className="btn btn-secondary" disabled={locked} onClick={() => void runPreview()}>{say('preview')}</button>
                {view.previewInvalidated && <p role="status">{say('previewInvalidated')}</p>}
              </section>

              {view.preview && <section className="housing-confirmation__preview">
                <div className="housing-confirmation__preview-title">
                  <CheckCircle2 size={19} aria-hidden="true" /><strong>{say('previewReady')}</strong>
                </div>
                <p>{say('personsCount', { count: view.preview.person_count })}</p>
                <button type="button" className="btn btn-secondary" disabled={locked}
                  onClick={() => void openPreviewPdf()}><FileText size={16} aria-hidden="true" />{say('openPreviewPdf')}</button>
                <label className="housing-confirmation__check"><input type="checkbox" checked={view.form.confirmed_residents}
                  disabled={locked} onChange={event => patchConfirmation({ confirmed_residents: event.target.checked })} />
                  <span>{say('confirmOccupancy')}</span></label>
                <label className="housing-confirmation__check"><input type="checkbox" checked={view.form.confirmed_authority}
                  disabled={locked} onChange={event => patchConfirmation({ confirmed_authority: event.target.checked })} />
                  <span>{say('confirmAuthority')}</span></label>
                <label className="housing-confirmation__check"><input type="checkbox" checked={view.form.confirmed_actual_move_in}
                  disabled={locked} onChange={event => patchConfirmation({ confirmed_actual_move_in: event.target.checked })} />
                  <span>{say('confirmActualMoveIn')}</span></label>
                <p className="housing-confirmation__policy">{say('noAuthorityClaim')}</p>
                <button type="button" className="btn btn-primary" disabled={locked} onClick={publish}>{say('publish')}</button>
              </section>}

              {view.saved && <div className="housing-confirmation__notice housing-confirmation__notice--success" role="status">
                <CheckCircle2 size={18} aria-hidden="true" /><span>{say('published')}</span>
              </div>}
              {dirty && <p className="housing-confirmation__dirty" role="status">
                {view.correctionOf ? say('correctionStatus') : say('dirtyStatus')}</p>}
            </>}

            <section className="housing-confirmation__history">
              <h3>{say('history')}</h3>
              {view.history.length === 0 ? <p>{say('noHistory')}</p> : <div className="housing-confirmation__history-list">
                {view.history.map(item => <article key={item.id}>
                  <div><FileText size={18} aria-hidden="true" /><div><strong>{formatDate(item.issue_date, locale)}</strong>
                    <small>{say('actualMoveIn')}: {formatDate(item.data.move_in_date, locale)} · {item.data.residents.length} {say('persons')}</small>
                    {item.correction_of && <small>{say('correctionOf')}</small>}</div></div>
                  <div className="housing-confirmation__history-actions">
                    <button type="button" className="btn btn-secondary btn-sm"
                      onClick={() => showPdf({ binding, url: resolveFileUrl(item.file_url), revoke: false, title: say('originalPdfTitle') })}>
                      {say('openPdf')}</button>
                    <button type="button" className="btn btn-secondary btn-sm" aria-label={`${say('download')} ${formatDate(item.issue_date, locale)}`}
                      onClick={() => void downloadOriginal(item)}><Download size={15} aria-hidden="true" /></button>
                    {canPublish && <button type="button" className="btn btn-secondary btn-sm"
                      disabled={locked} onClick={() => startCorrection(item)}>{say('correction')}</button>}
                  </div>
                </article>)}
              </div>}
              {view.nextCursor && <button type="button" className="btn btn-secondary" onClick={() => void loadMore()}>{say('loadMore')}</button>}
            </section>
          </>}
        </div>}

        <footer className="housing-confirmation__footer">
          <span>{say('noAuthorityClaim')}</span>
          <button type="button" className="btn btn-secondary" disabled={command.busy} onClick={requestClose}>{say('close')}</button>
        </footer>
      </section>
    </div>,
    document.body,
  );
}
