import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { AlertTriangle, CheckCircle2, FileText, Plus, Trash2, X } from 'lucide-react';
import { useAuth } from '../../contexts/AuthContext';
import { useConfirm } from '../../components/ConfirmDialog';
import { useTranslation } from '../../i18n';
import { authMayWrite } from '../../utils/writeAccess';
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

function neutralPrivate(binding, service, { loading = false, accessDenied = false } = {}) {
  return {
    binding,
    service,
    source: null,
    form: null,
    baseline: null,
    preview: null,
    previewInvalidated: false,
    correctionOf: null,
    history: [],
    nextCursor: null,
    loading,
    error: null,
    sourceConflict: false,
    accessDenied,
    saved: false,
  };
}

function safeText(value) {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

function validateSourceView(value, contractId) {
  if (!value || typeof value !== 'object' || value.contract_id !== contractId
      || !safeText(value.contract_number) || !safeText(value.property_label)
      || !safeText(value.unit_label) || !value.source_etags || typeof value.source_etags !== 'object') {
    throw new Error('invalid_housing_source');
  }
  return {
    ...value,
    suggestions: value.suggestions && typeof value.suggestions === 'object' ? value.suggestions : {},
    reference_dates: value.reference_dates && typeof value.reference_dates === 'object' ? value.reference_dates : {},
  };
}

function validatePreviewView(value) {
  if (!value || typeof value !== 'object' || !safeText(value.review_hash)
      || !Number.isInteger(value.person_count) || value.person_count < 1
      || !Array.isArray(value.warnings)) {
    throw new Error('invalid_housing_preview');
  }
  return value;
}

function validateHistoryItem(item) {
  if (!item || typeof item !== 'object' || !safeText(item.id) || !safeText(item.document_id)
      || !safeText(item.version_id) || !safeText(item.contract_id)
      || !safeText(item.issue_date) || !item.data || typeof item.data !== 'object') {
    throw new Error('invalid_housing_history');
  }
  if (!(item.correction_of == null || (
    safeText(item.correction_of.document_id) && safeText(item.correction_of.version_id)
  ))) throw new Error('invalid_housing_history');
  return item;
}

function validateHistoryPage(value) {
  if (!value || typeof value !== 'object' || !Array.isArray(value.items)
      || value.items.length > PAGE_SIZE
      || !(value.next_cursor == null || typeof value.next_cursor === 'string')) {
    throw new Error('invalid_housing_history_page');
  }
  value.items.forEach(validateHistoryItem);
  return value;
}

function formatDate(value, locale) {
  if (!value) return '—';
  const date = /^\d{4}-\d{2}-\d{2}$/.test(value)
    ? new Date(`${value}T00:00:00Z`)
    : new Date(value);
  if (!Number.isFinite(date.getTime())) return String(value);
  return new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeZone: 'UTC' }).format(date);
}

function reachableControls(modal) {
  if (!modal) return [];
  return [...modal.querySelectorAll('button, a[href], input, select, textarea, [tabindex]:not([tabindex="-1"])')]
    .filter(element => element.tabIndex >= 0 && !element.matches(':disabled')
      && !element.closest('[hidden], [inert], [aria-hidden="true"]'));
}

function HousingDialogFrame({ titleId, busy, opener, onRequestClose, children }) {
  const ref = useRef(null);

  useEffect(() => {
    const controls = reachableControls(ref.current);
    (controls.find(element => element.matches('input, select, textarea')) || controls[0] || ref.current)?.focus();
    return () => {
      if (opener?.isConnected && typeof opener.focus === 'function') opener.focus();
    };
  }, [opener]);

  useEffect(() => {
    const onKeyDown = event => {
      const modal = ref.current;
      if (!modal || !modal.contains(document.activeElement)) return;
      if (event.key === 'Escape' && !busy) {
        event.preventDefault();
        event.stopPropagation();
        void onRequestClose();
      } else if (event.key === 'Tab') {
        const controls = reachableControls(modal);
        const first = controls[0];
        const last = controls.at(-1);
        if (!first) {
          event.preventDefault();
          modal.focus();
        } else if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener('keydown', onKeyDown, true);
    return () => document.removeEventListener('keydown', onKeyDown, true);
  }, [busy, onRequestClose]);

  return (
    <div className="housing-confirmation__overlay" role="presentation"
      onMouseDown={event => {
        if (event.target === event.currentTarget && !busy) void onRequestClose();
      }}>
      <section className="housing-confirmation" ref={ref} role="dialog" aria-modal="true"
        aria-labelledby={titleId} tabIndex={-1} aria-busy={busy}>
        {children}
      </section>
    </div>
  );
}

function privateErrorText(error, tr) {
  if (error?.message === 'invalid_housing_source' || error?.message === 'invalid_housing_history_page') {
    return tr('loadFailed');
  }
  return error?.message || tr('loadFailed');
}

export default function HousingConfirmationDialog({
  contractId,
  opener,
  onClose,
  service,
  tenancyContext = null,
}) {
  const auth = useAuth();
  const user = auth?.user;
  const { locale } = useTranslation();
  const confirm = useConfirm();
  const titleId = useId();
  const binding = housingBindingKey(contractId, user);
  const canPublish = authMayWrite(auth, '/contracts') && authMayWrite(auth, '/documents');
  const controllers = useRef(new Set());
  const [stored, setStored] = useState(() => neutralPrivate('', null));
  const view = stored.binding === binding && stored.service === service
    ? stored
    : neutralPrivate(binding, service, { loading: Boolean(binding && service) });
  const tr = useCallback((key, params) => housingText(locale, key, params), [locale]);

  const abortRequests = useCallback(() => {
    for (const controller of controllers.current) controller.abort();
    controllers.current.clear();
  }, []);

  const forgetPrivate = useCallback(error => {
    if (!isPrivateForgetOutcome(error)) return false;
    abortRequests();
    setStored(neutralPrivate(binding, service, { accessDenied: true }));
    return true;
  }, [abortRequests, binding, service]);

  const command = useHousingConfirmationCommand(binding, forgetPrivate);
  const locked = command.busy || command.state.phase === 'unknown';
  const dirty = Boolean(view.form && view.baseline !== formSignature(view.form))
    || Boolean(view.correctionOf)
    || command.state.phase === 'unknown';

  const startRequest = useCallback(() => {
    const controller = new AbortController();
    controllers.current.add(controller);
    return controller;
  }, []);

  const finishRequest = useCallback(controller => controllers.current.delete(controller), []);

  const loadBinding = useCallback(async ({ preserveForm = false } = {}) => {
    if (!binding || !service?.loadSource) return;
    abortRequests();
    const controller = startRequest();
    setStored(current => {
      const base = current.binding === binding && current.service === service
        ? current
        : neutralPrivate(binding, service);
      return {
        ...base,
        binding,
        service,
        loading: true,
        error: null,
        sourceConflict: false,
        accessDenied: false,
        preview: null,
        previewInvalidated: false,
        saved: false,
        ...(preserveForm ? {} : {
          source: null,
          form: null,
          baseline: null,
          correctionOf: null,
          history: [],
          nextCursor: null,
        }),
      };
    });
    try {
      const [sourceRaw, historyRaw] = await Promise.all([
        service.loadSource(contractId, { signal: controller.signal }),
        typeof service.listHistory === 'function'
          ? service.listHistory(contractId, { cursor: null, limit: PAGE_SIZE, signal: controller.signal })
          : Promise.resolve({ items: [], next_cursor: null }),
      ]);
      if (controller.signal.aborted) return;
      const source = validateSourceView(sourceRaw, contractId);
      const history = validateHistoryPage(historyRaw);
      setStored(current => {
        if (current.binding !== binding || current.service !== service) return current;
        const form = preserveForm && current.form ? current.form : blankHousingForm();
        return {
          ...current,
          source,
          form,
          baseline: preserveForm && current.form ? current.baseline : formSignature(form),
          history: history.items,
          nextCursor: history.next_cursor,
          loading: false,
          error: null,
          accessDenied: false,
        };
      });
    } catch (error) {
      if (controller.signal.aborted || error?.name === 'AbortError') return;
      if (!forgetPrivate(error)) {
        setStored(current => current.binding === binding && current.service === service
          ? { ...current, loading: false, error: privateErrorText(error, tr) }
          : current);
      }
    } finally {
      finishRequest(controller);
    }
  }, [abortRequests, binding, contractId, finishRequest, forgetPrivate, service, startRequest, tr]);

  useEffect(() => {
    if (!binding || !service) return undefined;
    void loadBinding();
    return abortRequests;
  }, [abortRequests, binding, loadBinding, service]);

  const updateForm = useCallback(updater => {
    if (locked) return;
    setStored(current => {
      if (current.binding !== binding || current.service !== service || !current.form) return current;
      const form = typeof updater === 'function'
        ? updater(cloneHousingForm(current.form))
        : { ...current.form, ...updater };
      return {
        ...current,
        form,
        preview: null,
        previewInvalidated: Boolean(current.preview),
        saved: false,
        error: null,
      };
    });
    if (!['unknown', 'sending'].includes(command.state.phase)) command.reset();
  }, [binding, command, locked, service]);

  const patchForm = patch => updateForm(form => ({ ...form, ...patch }));
  const patchConfirmation = patch => {
    if (locked) return;
    setStored(current => {
      if (current.binding !== binding || current.service !== service || !current.form) return current;
      return {
        ...current,
        form: { ...current.form, ...patch },
        saved: false,
        error: null,
      };
    });
    if (!['unknown', 'sending'].includes(command.state.phase)) command.reset();
  };

  const runPreview = async () => {
    if (!view.form || typeof service?.preview !== 'function' || !view.source) return;
    const checked = validateHousingForm(view.form);
    if (!checked.valid) {
      setStored(current => current.binding === binding ? { ...current, error: tr('requiredFields') } : current);
      return;
    }
    const controller = startRequest();
    setStored(current => current.binding === binding ? { ...current, error: null, sourceConflict: false } : current);
    try {
      const raw = await service.preview({
        contractId,
        data: checked.data,
        sourceEtags: view.source.source_etags,
        correctionOf: view.correctionOf,
      }, { signal: controller.signal });
      if (controller.signal.aborted) return;
      const preview = validatePreviewView(raw);
      setStored(current => current.binding === binding && current.service === service
        ? { ...current, preview, previewInvalidated: false, sourceConflict: false, error: null, saved: false }
        : current);
    } catch (error) {
      if (controller.signal.aborted || error?.name === 'AbortError') return;
      if (!forgetPrivate(error)) {
        if (isConflictOutcome(error)) {
          setStored(current => current.binding === binding
            ? { ...current, error: null, sourceConflict: true, preview: null }
            : current);
        } else {
          setStored(current => current.binding === binding
            ? { ...current, error: error?.message || tr('errorTitle') }
            : current);
        }
      }
    } finally {
      finishRequest(controller);
    }
  };

  const publish = () => {
    if (!view.form || !view.preview || !canPublish || typeof service?.preparePublish !== 'function'
        || !view.source) return;
    const checked = validateHousingForm(view.form, { forPublish: true });
    if (!checked.valid) {
      setStored(current => current.binding === binding ? { ...current, error: tr('requiredFields') } : current);
      return;
    }
    const prepared = service.preparePublish({
      contractId,
      data: checked.data,
      sourceEtags: view.source.source_etags,
      preview: view.preview,
      correctionOf: view.correctionOf,
      confirmations: {
        confirmed_actual_move_in: view.form.confirmed_actual_move_in,
        confirmed_authority: view.form.confirmed_authority,
        confirmed_residents: view.form.confirmed_residents,
      },
    });
    if (!prepared?.payload || typeof prepared.send !== 'function') {
      setStored(current => current.binding === binding ? { ...current, error: tr('errorTitle') } : current);
      return;
    }
    command.execute({
      label: 'publish-housing-confirmation',
      payload: prepared.payload,
      send: prepared.send,
      onSuccess: result => {
        const outcome = typeof prepared.apply === 'function' ? prepared.apply(result) : result;
        const record = validateHistoryItem(outcome?.record || outcome);
        setStored(current => {
          if (current.binding !== binding || current.service !== service || !current.form) return current;
          return {
            ...current,
            preview: null,
            previewInvalidated: false,
            baseline: formSignature(current.form),
            correctionOf: null,
            history: [record, ...current.history.filter(item => item.id !== record.id)],
            saved: true,
            error: null,
          };
        });
        return record;
      },
    });
  };

  const loadMore = async () => {
    if (!view.nextCursor || typeof service?.listHistory !== 'function' || view.loading) return;
    const controller = startRequest();
    try {
      const raw = await service.listHistory(contractId, {
        cursor: view.nextCursor,
        limit: PAGE_SIZE,
        signal: controller.signal,
      });
      if (controller.signal.aborted) return;
      const page = validateHistoryPage(raw);
      setStored(current => current.binding === binding && current.service === service
        ? {
          ...current,
          history: [...current.history, ...page.items.filter(item => !current.history.some(existing => existing.id === item.id))],
          nextCursor: page.next_cursor,
        }
        : current);
    } catch (error) {
      if (controller.signal.aborted || error?.name === 'AbortError') return;
      if (!forgetPrivate(error)) {
        setStored(current => current.binding === binding
          ? { ...current, error: error?.message || tr('errorTitle') }
          : current);
      }
    } finally {
      finishRequest(controller);
    }
  };

  const openOriginal = async item => {
    if (typeof service?.openOriginal !== 'function') return;
    const controller = startRequest();
    try {
      await service.openOriginal(item, { signal: controller.signal });
    } catch (error) {
      if (controller.signal.aborted || error?.name === 'AbortError') return;
      if (!forgetPrivate(error)) {
        setStored(current => current.binding === binding
          ? { ...current, error: error?.message || tr('errorTitle') }
          : current);
      }
    } finally {
      finishRequest(controller);
    }
  };

  const openPreview = async () => {
    if (!view.preview || !view.form || !view.source || typeof service?.openPreview !== 'function') return;
    const checked = validateHousingForm(view.form);
    if (!checked.valid) return;
    const controller = startRequest();
    try {
      await service.openPreview({ contractId, data: checked.data, sourceEtags: view.source.source_etags,
        correctionOf: view.correctionOf }, { signal: controller.signal });
    } catch (error) {
      if (controller.signal.aborted || error?.name === 'AbortError') return;
      if (!forgetPrivate(error)) setStored(current => current.binding === binding
        ? { ...current, error: isConflictOutcome(error) ? null : error?.message || tr('errorTitle'),
          ...(isConflictOutcome(error) ? { sourceConflict: true, preview: null } : {}) } : current);
    } finally {
      finishRequest(controller);
    }
  };

  const startCorrection = item => {
    if (locked || !canPublish || !item.data) return;
    const form = formFromCertificateData(item.data);
    setStored(current => current.binding === binding && current.service === service
      ? {
        ...current,
        form,
        baseline: formSignature(form),
        correctionOf: { document_id: item.document_id, version_id: item.version_id },
        preview: null,
        previewInvalidated: false,
        saved: false,
        error: null,
      }
      : current);
    command.reset();
  };

  const requestClose = useCallback(async () => {
    if (command.busy) return;
    if ((dirty || view.preview) && typeof confirm === 'function') {
      const accepted = await confirm(tr('discardPrompt'));
      if (!accepted) return;
    }
    abortRequests();
    command.abort();
    onClose?.();
  }, [abortRequests, command, confirm, dirty, onClose, tr, view.preview]);

  if (!contractId || !binding) return null;

  return (
    <HousingDialogFrame titleId={titleId} busy={command.busy} opener={opener} onRequestClose={requestClose}>
      <header className="housing-confirmation__header">
        <div>
          <p className="housing-confirmation__eyebrow">{tr('eyebrow')}</p>
          <h2 id={titleId}>{tr('title')}</h2>
          {view.source && <p>{view.source.contract_number} · {view.source.property_label} · {view.source.unit_label}</p>}
        </div>
        <button type="button" className="housing-confirmation__icon-button"
          aria-label={tr('close')} disabled={command.busy} onClick={() => void requestClose()}>
          <X size={20} />
        </button>
      </header>

      <div className="housing-confirmation__body">
        {view.loading && <p role="status">{tr('loading')}</p>}
        {view.accessDenied && <div className="housing-confirmation__notice housing-confirmation__notice--error" role="alert">
          <AlertTriangle size={18} /><span>{tr('accessLost')}</span>
        </div>}
        {view.error && <div className="housing-confirmation__notice housing-confirmation__notice--error" role="alert">
          <AlertTriangle size={18} /><span>{view.error}</span>
        </div>}
        {view.sourceConflict && <div className="housing-confirmation__notice housing-confirmation__notice--warning" role="alert">
          <AlertTriangle size={18} /><div><strong>{tr('conflictTitle')}</strong><p>{tr('conflictBody')}</p></div>
          <button type="button" className="btn btn-secondary" onClick={() => {
            void loadBinding({ preserveForm: true });
          }}>{tr('reloadSource')}</button>
        </div>}
        {command.state.phase === 'unknown' && <div className="housing-confirmation__notice housing-confirmation__notice--warning" role="alert">
          <AlertTriangle size={18} /><div><strong>{tr('unknownTitle')}</strong><p>{tr('unknownBody')}</p></div>
          <button type="button" className="btn btn-primary" onClick={command.retryExact}>{tr('retryExact')}</button>
        </div>}
        {command.state.phase === 'conflict' && <div className="housing-confirmation__notice housing-confirmation__notice--warning" role="alert">
          <AlertTriangle size={18} /><div><strong>{tr('conflictTitle')}</strong><p>{tr('conflictBody')}</p></div>
          <button type="button" className="btn btn-secondary" onClick={() => {
            command.reset();
            void loadBinding({ preserveForm: true });
          }}>{tr('reloadSource')}</button>
        </div>}
        {command.state.phase === 'error' && <div className="housing-confirmation__notice housing-confirmation__notice--error" role="alert">
          <AlertTriangle size={18} /><span>{command.state.error?.message || tr('errorTitle')}</span>
        </div>}

        {!view.loading && !view.accessDenied && view.source && view.form && <>
          <section className="housing-confirmation__source" aria-label={tr('dwelling')}>
            <div><span>{tr('property')}</span><strong>{view.source.property_label}</strong></div>
            <div><span>{tr('unit')}</span><strong>{view.source.unit_label}</strong></div>
            <div><span>{tr('contract')}</span><strong>{view.source.contract_number}</strong></div>
            <div><span>{tr('contractStart')}</span><strong>{formatDate(view.source.reference_dates.contract_start_date, locale)}</strong></div>
            {(tenancyContext?.handover_date || view.source.reference_dates.handover_date) && <div>
              <span>{tr('handoverReference')}</span>
              <strong>{formatDate(tenancyContext?.handover_date || view.source.reference_dates.handover_date, locale)}</strong>
            </div>}
          </section>

          <fieldset className="housing-confirmation__section" disabled={locked}>
            <legend>{tr('dwelling')}</legend>
            {view.source.suggestions.dwelling_address && <div className="housing-confirmation__suggestion">
              <div><span>{tr('suggestedAddress')}</span><strong>{view.source.suggestions.dwelling_address}</strong></div>
              <button type="button" className="btn btn-secondary btn-sm" onClick={() => patchForm({
                dwelling_address: view.source.suggestions.dwelling_address,
                dwelling_label: view.source.suggestions.dwelling_label || view.form.dwelling_label,
              })}>{tr('sourceSuggestion')}</button>
            </div>}
            <label>{tr('dwellingAddress')}<textarea rows="3" value={view.form.dwelling_address}
              onChange={event => patchForm({ dwelling_address: event.target.value })} /></label>
            <label>{tr('dwellingLabel')}<input value={view.form.dwelling_label}
              onChange={event => patchForm({ dwelling_label: event.target.value })} /></label>
            <label>{tr('actualMoveIn')}<input type="date" value={view.form.actual_move_in_date}
              aria-describedby={`${titleId}-move-in-hint`}
              onChange={event => patchForm({ actual_move_in_date: event.target.value })} /></label>
            <small id={`${titleId}-move-in-hint`}>{tr('actualMoveInHint')}</small>
          </fieldset>

          <fieldset className="housing-confirmation__section" disabled={locked}>
            <legend>{tr('provider')}</legend>
            {(view.source.suggestions.housing_provider_name || view.source.suggestions.housing_provider_address) && <div className="housing-confirmation__suggestion">
              <div><span>{tr('suggestedProvider')}</span>
                <strong>{view.source.suggestions.housing_provider_name || '—'}</strong>
                <small>{view.source.suggestions.housing_provider_address || '—'}</small></div>
              <button type="button" className="btn btn-secondary btn-sm" onClick={() => patchForm({
                housing_provider_name: view.source.suggestions.housing_provider_name || view.form.housing_provider_name,
                housing_provider_address: view.source.suggestions.housing_provider_address || view.form.housing_provider_address,
              })}>{tr('sourceSuggestion')}</button>
            </div>}
            <label>{tr('providerName')}<input value={view.form.housing_provider_name}
              onChange={event => patchForm({ housing_provider_name: event.target.value })} /></label>
            <label>{tr('providerAddress')}<textarea rows="3" value={view.form.housing_provider_address}
              onChange={event => patchForm({ housing_provider_address: event.target.value })} /></label>
          </fieldset>

          <fieldset className="housing-confirmation__section" disabled={locked}>
            <legend>{tr('owner')}</legend>
            <label>{tr('ownerRelation')}<select value={view.form.owner_relation}
              onChange={event => patchForm({ owner_relation: event.target.value, owner_name: event.target.value === 'same' ? '' : view.form.owner_name })}>
              <option value="">{tr('ownerUnknown')}</option>
              <option value="same">{tr('ownerSame')}</option>
              <option value="different">{tr('ownerDifferent')}</option>
            </select></label>
            {view.form.owner_relation === 'different' && <>
              {view.source.suggestions.owner_name && <div className="housing-confirmation__suggestion">
                <div><span>{tr('suggestedOwner')}</span><strong>{view.source.suggestions.owner_name}</strong></div>
                <button type="button" className="btn btn-secondary btn-sm"
                  onClick={() => patchForm({ owner_name: view.source.suggestions.owner_name })}>{tr('sourceSuggestion')}</button>
              </div>}
              <label>{tr('ownerName')}<input value={view.form.owner_name}
                onChange={event => patchForm({ owner_name: event.target.value })} /></label>
            </>}
          </fieldset>

          <fieldset className="housing-confirmation__section" disabled={locked}>
            <legend>{tr('persons')}</legend>
            {view.source.suggestions.main_tenant_name && <div className="housing-confirmation__suggestion">
              <div><span>{tr('mainTenantSuggestion')}</span><strong>{view.source.suggestions.main_tenant_name}</strong></div>
              <button type="button" className="btn btn-secondary btn-sm"
                onClick={() => updateForm(form => addSuggestedOccupant(form, view.source.suggestions.main_tenant_name))}>
                {tr('addSuggestion')}</button>
            </div>}
            <div className="housing-confirmation__persons">
              {view.form.occupants.map((person, index) => <div className="housing-confirmation__person" key={person.key}>
                <label>{tr('occupant')} {index + 1}<input value={person.name}
                  onChange={event => updateForm(form => {
                    form.occupants[index].name = event.target.value;
                    return form;
                  })} /></label>
                <button type="button" className="btn btn-secondary btn-sm"
                  aria-label={`${tr('removePerson')} ${index + 1}`}
                  disabled={view.form.occupants.length === 1}
                  onClick={() => updateForm(form => ({
                    ...form,
                    occupants: form.occupants.filter((_, itemIndex) => itemIndex !== index),
                  }))}><Trash2 size={16} /></button>
              </div>)}
            </div>
            <button type="button" className="btn btn-secondary" onClick={() => updateForm(form => ({
              ...form,
              occupants: [...form.occupants, personRow()],
            }))}><Plus size={16} />{tr('addPerson')}</button>
          </fieldset>

          <fieldset className="housing-confirmation__section" disabled={locked}>
            <legend>{tr('issue')}</legend>
            <label>{tr('issueDate')}<input type="date" value={view.form.issue_date}
              onChange={event => patchForm({ issue_date: event.target.value })} /></label>
            <label>{tr('issuerName')}<input value={view.form.issuer_name}
              onChange={event => patchForm({ issuer_name: event.target.value })} /></label>
            <label>{tr('issuerRole')}<select value={view.form.issuer_role}
              onChange={event => patchForm({ issuer_role: event.target.value })}>
              <option value="">{tr('ownerUnknown')}</option>
              <option value="housing_provider">{tr('role_housing_provider')}</option>
              <option value="authorized_person">{tr('role_authorized_person')}</option>
            </select></label>
          </fieldset>

          <section className="housing-confirmation__review-actions">
            <button type="button" className="btn btn-secondary"
              disabled={locked} onClick={() => void runPreview()}>
              {tr('preview')}</button>
            {view.previewInvalidated && <p role="status">{tr('previewInvalidated')}</p>}
          </section>

          {view.preview && <section className="housing-confirmation__preview">
            <div className="housing-confirmation__preview-title">
              <CheckCircle2 size={19} /><strong>{tr('previewReady')}</strong>
            </div>
            <p>{tr('personsCount', { count: view.preview.person_count })}</p>
            {typeof service?.openPreview === 'function' && <button type="button" className="btn btn-secondary"
              disabled={locked} onClick={() => void openPreview()}>{tr('openPreviewPdf')}</button>}
            {view.preview.warnings.length > 0 && <div><h4>{tr('warnings')}</h4>
              <ul>{view.preview.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul></div>}
            <label className="housing-confirmation__check"><input type="checkbox"
              checked={view.form.confirmed_residents} disabled={locked}
              onChange={event => patchConfirmation({ confirmed_residents: event.target.checked })} />
              <span>{tr('confirmOccupancy')}</span></label>
            <label className="housing-confirmation__check"><input type="checkbox"
              checked={view.form.confirmed_authority} disabled={locked}
              onChange={event => patchConfirmation({ confirmed_authority: event.target.checked })} />
              <span>{tr('confirmAuthority')}</span></label>
            <label className="housing-confirmation__check"><input type="checkbox"
              checked={view.form.confirmed_actual_move_in} disabled={locked}
              onChange={event => patchConfirmation({ confirmed_actual_move_in: event.target.checked })} />
              <span>{tr('confirmActualMoveIn')}</span></label>
            <p className="housing-confirmation__policy">{tr('noAuthorityClaim')}</p>
            <button type="button" className="btn btn-primary"
              disabled={locked || !canPublish} onClick={publish}>{tr('publish')}</button>
          </section>}

          {view.saved && <div className="housing-confirmation__notice housing-confirmation__notice--success" role="status">
            <CheckCircle2 size={18} /><span>{tr('published')}</span>
          </div>}
          {dirty && <p className="housing-confirmation__dirty" role="status">
            {view.correctionOf ? tr('correctionStatus') : tr('dirtyStatus')}</p>}

          <section className="housing-confirmation__history">
            <h3>{tr('history')}</h3>
            {view.history.length === 0 ? <p>{tr('noHistory')}</p> : <div className="housing-confirmation__history-list">
              {view.history.map(item => <article key={item.id}>
                <div><FileText size={18} /><div><strong>{formatDate(item.issue_date, locale)}</strong>
                  {item.correction_of && <small>{tr('correctionOf')}</small>}</div></div>
                <div className="housing-confirmation__history-actions">
                  <button type="button" className="btn btn-secondary btn-sm"
                    onClick={() => void openOriginal(item)}>{tr('openPdf')}</button>
                  {canPublish && item.data && <button type="button" className="btn btn-secondary btn-sm"
                    disabled={locked} onClick={() => startCorrection(item)}>{tr('correction')}</button>}
                </div>
              </article>)}
            </div>}
            {view.nextCursor && <button type="button" className="btn btn-secondary"
              onClick={() => void loadMore()}>{tr('loadMore')}</button>}
          </section>
        </>}
      </div>

      <footer className="housing-confirmation__footer">
        <span>{tr('noAuthorityClaim')}</span>
        <button type="button" className="btn btn-secondary" disabled={command.busy}
          onClick={() => void requestClose()}>{tr('close')}</button>
      </footer>
    </HousingDialogFrame>
  );
}
