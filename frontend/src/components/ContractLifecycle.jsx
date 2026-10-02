import { useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, CheckCircle2, FileClock, RefreshCw, X } from 'lucide-react';
import { api } from '../api';
import { snapshotRevision } from '../editRevision';
import { useAuth } from '../contexts/AuthContext';
import useWriteAccess from '../hooks/useWriteAccess';
import { useConfirm } from './ConfirmDialog';
import { useTranslation } from '../i18n';
import './ContractLifecycle.css';

const PAGE_SIZE = 25;
const FINAL_STATES = new Set(['confirmed', 'pending_effective', 'completed', 'superseded']);
const KNOWN_STATES = new Set(['draft', 'reviewed', ...FINAL_STATES]);
const isObject = value => Boolean(value) && typeof value === 'object' && !Array.isArray(value);
const isString = value => typeof value === 'string' && Boolean(value);
const optionalId = value => value == null || isString(value);
const isHash = value => typeof value === 'string' && /^[0-9a-f]{64}$/.test(value);
const isEtag = value => typeof value === 'string' && /^"[^"]+"$/.test(value);
const dataEqual = (first, second) => first?.operation === second?.operation
  && (first?.operation === 'renewal'
    ? ['reason', 'new_contract_number', 'new_start_date', 'new_end_date']
    : ['reason', 'termination_end_date']).every(key => first?.[key] === second?.[key]);

function actorKey(user) {
  if (!user?.id || user.is_active === false) return '';
  return JSON.stringify([
    user.id,
    user.role || '',
    [...(user.write_permissions || [])].sort(),
    user.portfolio_access || '',
    [...(user.portfolio_ids || [])].sort(),
  ]);
}

function commandKey() {
  if (typeof globalThis.crypto?.randomUUID !== 'function') throw new Error('crypto.randomUUID unavailable');
  return `g06:${globalThis.crypto.randomUUID()}`;
}

function strongEtag(record) {
  const etag = snapshotRevision(record)?.etag;
  return typeof etag === 'string' && /^"[^"]+"$/.test(etag) && !etag.startsWith('W/') ? etag : null;
}

function validateSource(value, contractId) {
  if (!isObject(value) || value.id !== contractId || !isString(value.property_id)
      || !isString(value.unit_id) || !isString(value.tenant_id)
      || !isString(value.contract_number) || typeof value.status !== 'string') {
    throw new Error('malformed_source');
  }
  const etag = strongEtag(value);
  if (!etag) throw new Error('missing_strong_etag');
  return { value, etag };
}

function validateData(data) {
  if (!isObject(data) || !['renewal', 'termination'].includes(data.operation)
      || typeof data.reason !== 'string' || !data.reason.trim()) throw new Error('malformed_draft');
  if (data.operation === 'renewal') {
    if (!isString(data.new_contract_number) || !isString(data.new_start_date)
        || !(data.new_end_date === null || isString(data.new_end_date))) throw new Error('malformed_draft');
  } else if (!isString(data.termination_end_date)) throw new Error('malformed_draft');
  return data;
}

function validateReview(review, source) {
  if (!isObject(review) || !isObject(review.source_contract)
      || ['id', 'property_id', 'unit_id', 'tenant_id'].some(key => review.source_contract[key] !== source[key])
      || !isEtag(review.source_contract_etag)
      || !isObject(review.related_etags)
      || !['property', 'unit', 'tenant'].every(key => isString(review.related_etags[key]))
      || !isObject(review.proposed_contract) || !isObject(review.obligations)
      || !isString(review.date_policy) || !isString(review.notice_policy)) throw new Error('malformed_review');
  validateData(review.data);
  if (review.supersedes !== null) {
    if (!isObject(review.supersedes) || !isString(review.supersedes.id)
        || !isString(review.supersedes.termination_end_date)
        || !/^[0-9a-f]{64}$/.test(review.supersedes.review_hash || '')) {
      throw new Error('malformed_review');
    }
  }
  const obligations = review.obligations;
  for (const key of ['rent_charge_count', 'receivable_count', 'receivables_due_after_end_count', 'rent_period_conflict_count']) {
    if (!Number.isInteger(obligations[key]) || obligations[key] < 0) throw new Error('malformed_review');
  }
  for (const key of ['receivables_due_after_end_sample', 'rent_period_conflict_sample']) {
    if (!Array.isArray(obligations[key]) || obligations[key].length > 20) throw new Error('malformed_review');
  }
  for (const item of obligations.receivables_due_after_end_sample) {
    if (!isObject(item) || !isString(item.id) || !isString(item.due_date)
        || typeof item.description !== 'string' || !isString(item.amount_due)
        || !isString(item.amount_paid)) throw new Error('malformed_review');
  }
  for (const item of obligations.rent_period_conflict_sample) {
    if (!isObject(item) || !isString(item.id) || !isString(item.month)) throw new Error('malformed_review');
  }
  if (!isHash(obligations.snapshot_sha256) || !isString(obligations.policy)) throw new Error('malformed_review');
  return review;
}

function validateDraft(value, source, actorId, { allowForeignActor = false } = {}) {
  if (!isObject(value) || !isString(value.id) || value.contract_id !== source.id
      || value.property_id !== source.property_id || value.unit_id !== source.unit_id
      || value.tenant_id !== source.tenant_id || !isString(value.actor_id)
      || ((!allowForeignActor || !FINAL_STATES.has(value.state)) && value.actor_id !== actorId)
      || !isString(value.revision) || !KNOWN_STATES.has(value.state)
      || (value.current_state != null && !KNOWN_STATES.has(value.current_state))
      || !isEtag(value.source_contract_etag) || !isString(value.portfolio_id)
      || typeof value.persistent !== 'boolean' || !isString(value.created_at) || !isString(value.updated_at)
      || !optionalId(value.successor_contract_id)
      || !optionalId(value.superseded_by_draft_id) || !optionalId(value.supersedes_draft_id)) {
    throw new Error('malformed_draft');
  }
  validateData(value.data);
  if (value.state === 'draft') {
    if (value.review !== null || value.review_hash !== null || value.supersedes_draft_id !== null) throw new Error('malformed_draft');
  } else {
    validateReview(value.review, source);
    if (!isHash(value.review_hash) || value.review.source_contract_etag !== value.source_contract_etag
        || !dataEqual(value.data, value.review.data)
        || (value.review.supersedes?.id ?? null) !== value.supersedes_draft_id) throw new Error('malformed_draft');
  }
  if (FINAL_STATES.has(value.state)) {
    if (!isEtag(value.applied_contract_etag)
        || (value.data.operation === 'renewal') !== (value.state === 'confirmed')
        || (value.data.operation === 'renewal' ? !isString(value.successor_contract_id) : value.successor_contract_id !== null)) throw new Error('malformed_draft');
  } else if (value.applied_contract_etag !== null || value.successor_contract_id !== null) throw new Error('malformed_draft');
  if ((value.superseded_by_draft_id !== null) !== (value.state === 'superseded')
      || !(value.finalized_contract_etag === null || (value.state === 'completed' && isEtag(value.finalized_contract_etag)))) throw new Error('malformed_draft');
  return value;
}

function validatePage(value, source, actorId, history = false) {
  if (!isObject(value) || !Array.isArray(value.items) || value.items.length > PAGE_SIZE
      || !(value.next_before === null || value.next_before === undefined || isString(value.next_before))
      || typeof value.persistent !== 'boolean') throw new Error('malformed_page');
  if (!history) {
    value.items.forEach(item => validateDraft(item, source, actorId));
  } else {
    value.items.forEach(item => {
      if (!isObject(item) || !isString(item.id) || !isString(item.draft_id)
          || !isString(item.actor_id) || !['confirm', 'finalize'].includes(item.operation)
          || !isString(item.created_at) || !isObject(item.result)
          || (item.current_state != null && !KNOWN_STATES.has(item.current_state))) throw new Error('malformed_history');
      validateDraft(item.result, source, actorId, { allowForeignActor: true });
      if (item.draft_id !== item.result.id || !FINAL_STATES.has(item.result.state)
          || !optionalId(item.superseded_by_draft_id) || !optionalId(item.supersedes_draft_id)) throw new Error('malformed_history');
    });
  }
  return value;
}

function validateCommand(value, source, actorId, { operation, id, data, reviewHash, etag }) {
  const checked = validateDraft(value, source, actorId, { allowForeignActor: operation === 'finalize' });
  const allowedStates = operation === 'confirm'
    ? (data.operation === 'renewal' ? ['confirmed'] : ['pending_effective', 'completed'])
    : operation === 'finalize' ? ['completed'] : operation === 'review' ? ['reviewed'] : ['draft'];
  if ((id && checked.id !== id) || !dataEqual(checked.data, data) || !allowedStates.includes(checked.state)
      || (reviewHash && checked.review_hash !== reviewHash)
      || (['create', 'edit', 'review'].includes(operation) && checked.source_contract_etag !== etag)) {
    throw new Error('malformed_draft');
  }
  return checked;
}

const blankForm = () => ({
  operation: 'renewal', reason: '', new_contract_number: '', new_start_date: '',
  new_end_date: '', unlimited: false, termination_end_date: '',
});

function formFromData(data) {
  if (data?.operation === 'termination') {
    return { ...blankForm(), operation: 'termination', reason: data.reason || '', termination_end_date: data.termination_end_date || '' };
  }
  return {
    ...blankForm(), operation: 'renewal', reason: data?.reason || '',
    new_contract_number: data?.new_contract_number || '', new_start_date: data?.new_start_date || '',
    new_end_date: data?.new_end_date || '', unlimited: data?.new_end_date === null,
  };
}

function dataFromForm(form) {
  const reason = form.reason.trim();
  if (!reason) throw new Error('reason_required');
  if (form.operation === 'termination') {
    if (!form.termination_end_date) throw new Error('date_required');
    return { operation: 'termination', reason, termination_end_date: form.termination_end_date };
  }
  if (!form.new_contract_number.trim() || !form.new_start_date) throw new Error('renewal_required');
  if (!form.unlimited && !form.new_end_date) throw new Error('end_choice_required');
  return {
    operation: 'renewal', reason, new_contract_number: form.new_contract_number.trim(),
    new_start_date: form.new_start_date, new_end_date: form.unlimited ? null : form.new_end_date,
  };
}

function reviewConsentKey(draft) {
  if (!draft?.id || !draft?.revision || !/^[0-9a-f]{64}$/.test(draft?.review_hash || '')) return null;
  return `${draft.id}:${draft.revision}:${draft.review_hash}`;
}

function sameLifecycleData(form, data) {
  try {
    return dataEqual(dataFromForm(form), data);
  } catch {
    return false;
  }
}

function formatAmount(value) {
  return typeof value === 'string' ? value : '—';
}

function FocusDialog({ children, titleId, busy, onClose, opener }) {
  const ref = useRef(null);
  const focusables = useCallback(() => {
    const node = ref.current;
    if (!node) return [];
    const selector = 'button,input,select,textarea,a[href]';
    return [...node.querySelectorAll(selector)].filter(element => {
      if (element.tabIndex < 0 || element.matches(':disabled') || element.closest('[hidden], [inert], [aria-hidden="true"]')) return false;
      for (let ancestor = element; ancestor && ancestor !== node.parentElement; ancestor = ancestor.parentElement) {
        const style = getComputedStyle(ancestor);
        if (style.display === 'none' || style.visibility === 'hidden') return false;
      }
      return true;
    });
  }, []);
  useEffect(() => {
    focusables()[0]?.focus();
    const contractId = opener?.getAttribute('data-lifecycle-contract');
    return () => {
      const currentOpener = opener?.isConnected ? opener : contractId
        ? [...document.querySelectorAll('button[data-lifecycle-contract]')]
          .find(button => button.getAttribute('data-lifecycle-contract') === contractId && !button.disabled)
        : null;
      currentOpener?.focus();
    };
  }, [focusables, opener]);
  useEffect(() => {
    const keyDown = event => {
      const node = ref.current;
      if (!node || !node.contains(document.activeElement)) return;
      if (event.key === 'Escape' && !event.defaultPrevented && !busy) {
        event.preventDefault(); event.stopPropagation(); onClose();
      }
    };
    document.addEventListener('keydown', keyDown, true);
    return () => document.removeEventListener('keydown', keyDown, true);
  }, [busy, onClose]);
  return <div className="contract-lifecycle__overlay" role="presentation" onMouseDown={event => {
    if (event.target === event.currentTarget && !busy) onClose();
  }}>
    <section className="contract-lifecycle" ref={ref} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1} aria-busy={busy}>
      <span className="contract-lifecycle__focus-sentinel" tabIndex={0}
        onFocus={() => focusables().at(-1)?.focus()} />
      {children}
      <span className="contract-lifecycle__focus-sentinel" tabIndex={0}
        onFocus={() => focusables()[0]?.focus()} />
    </section>
  </div>;
}

function LifecycleDialog({ contract, opener, onClose, onChanged, user }) {
  const { t } = useTranslation();
  const confirm = useConfirm();
  const label = useCallback(key => t(`contractLifecycle.${key}`), [t]);
  const controllers = useRef(new Set());
  const busyRef = useRef(false);
  const preparingRef = useRef(false);
  const alive = useRef(true);
  const relatedRequest = useRef(null);
  const pagingRequest = useRef(null);
  const labelRef = useRef(label);
  const titleId = useId();
  useLayoutEffect(() => { labelRef.current = label; });
  const { canWrite, isAllowed } = useWriteAccess('/contracts', () => {
    for (const controller of controllers.current) controller.abort();
    controllers.current.clear();
  });

  const [source, setSource] = useState(null);
  const [sourceEtag, setSourceEtag] = useState(null);
  const [drafts, setDrafts] = useState([]);
  const [draftBefore, setDraftBefore] = useState(null);
  const [history, setHistory] = useState([]);
  const [historyBefore, setHistoryBefore] = useState(null);
  const [tab, setTab] = useState(canWrite ? 'draft' : 'history');
  const [selected, setSelected] = useState(null);
  const [selectedHistory, setSelectedHistory] = useState(null);
  const [relatedDraft, setRelatedDraft] = useState(null);
  const [form, setForm] = useState(blankForm);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [retry, setRetry] = useState(null);
  const [needsReload, setNeedsReload] = useState(false);
  const [reviewConsent, setReviewConsent] = useState(null);
  const [accessDenied, setAccessDenied] = useState(false);

  const forgetProtectedData = useCallback(reason => {
    if (![401, 403, 404].includes(reason.statusCode)) return false;
    setAccessDenied(true); setSource(null); setSourceEtag(null);
    setDrafts([]); setHistory([]); setSelected(null); setSelectedHistory(null);
    setRelatedDraft(null); setForm(blankForm()); setRetry(null); setNeedsReload(false); setReviewConsent(null);
    return true;
  }, []);

  const endpoint = useCallback(suffix => `/contracts/${encodeURIComponent(contract.id)}/lifecycle${suffix}`, [contract.id]);

  const controller = useCallback(() => {
    const value = new AbortController();
    controllers.current.add(value);
    return value;
  }, []);

  const doneController = useCallback(value => controllers.current.delete(value), []);

  useEffect(() => {
    alive.current = true;
    const ownedControllers = controllers.current;
    return () => {
      alive.current = false;
      for (const value of ownedControllers) value.abort();
      ownedControllers.clear();
    };
  }, []);

  const loadSource = useCallback(async signal => {
    const fresh = await api.get(`/contracts/${encodeURIComponent(contract.id)}`, { signal });
    const checked = validateSource(fresh, contract.id);
    if (!alive.current || signal.aborted) throw new DOMException('Aborted', 'AbortError');
    setSource(checked.value); setSourceEtag(checked.etag);
    return checked;
  }, [contract.id]);

  const loadPage = useCallback(async (kind, checkedSource, before, append, signal) => {
    const cursor = before ? `&before=${encodeURIComponent(before)}` : '';
    const value = await api.get(endpoint(`/${kind}?limit=${PAGE_SIZE}${cursor}`), { signal });
    const page = validatePage(value, checkedSource.value, user.id, kind === 'history');
    if (!alive.current || signal.aborted) return;
    if (kind === 'drafts') {
      setDrafts(current => append ? [...current, ...page.items] : page.items);
      setDraftBefore(page.next_before || null);
    } else {
      setHistory(current => append ? [...current, ...page.items] : page.items);
      setHistoryBefore(page.next_before || null);
    }
    return page;
  }, [endpoint, user.id]);

  const reloadAll = useCallback(async ({ preserveForm = false, selectedDraft = null } = {}) => {
    const ctl = controller();
    setLoading(true); setError(null); setRetry(null); setNeedsReload(false); setReviewConsent(null);
    if (!preserveForm) {
      setSelected(null); setSelectedHistory(null); setRelatedDraft(null); setForm(blankForm());
    }
    try {
      const checked = await loadSource(ctl.signal);
      await Promise.all([
        loadPage('drafts', checked, null, false, ctl.signal),
        loadPage('history', checked, null, false, ctl.signal),
      ]);
      if (preserveForm && selectedDraft) {
        const current = validateDraft(await api.get(endpoint(`/drafts/${encodeURIComponent(selectedDraft.id)}`),
          { signal: ctl.signal }), checked.value, user.id, { allowForeignActor: true });
        if (alive.current && !ctl.signal.aborted) {
          setSelected(current);
          setSelectedHistory(null);
          if (FINAL_STATES.has(current.state)) { setForm(formFromData(current.data)); setTab('history'); }
        }
      }
    } catch (reason) {
      if (reason.name !== 'AbortError' && alive.current) {
        if (ctl.signal.aborted) return;
        forgetProtectedData(reason);
        const key = ['malformed_source', 'missing_strong_etag', 'malformed_page', 'malformed_draft', 'malformed_history', 'malformed_review'].includes(reason.message) ? 'malformed' : null;
        setError(key ? labelRef.current(key) : reason.message || labelRef.current('loadFailed'));
      }
    } finally {
      doneController(ctl);
      if (alive.current && !ctl.signal.aborted) setLoading(false);
    }
  }, [controller, doneController, endpoint, forgetProtectedData, loadPage, loadSource, user.id]);

  useEffect(() => { reloadAll(); }, [reloadAll]);

  const loadMore = async kind => {
    const before = kind === 'drafts' ? draftBefore : historyBefore;
    if (!before || loading || pagingRequest.current) return;
    const ctl = controller();
    pagingRequest.current = ctl;
    try {
      const checked = { value: source, etag: sourceEtag };
      await loadPage(kind, checked, before, true, ctl.signal);
    } catch (reason) {
      if (reason.name !== 'AbortError' && alive.current && !ctl.signal.aborted) {
        forgetProtectedData(reason); setError(reason.message || label('loadFailed'));
      }
    } finally { doneController(ctl); if (pagingRequest.current === ctl) pagingRequest.current = null; }
  };

  const loadRelated = useCallback(async draft => {
    relatedRequest.current?.abort();
    relatedRequest.current = null;
    setRelatedDraft(null);
    const id = draft?.supersedes_draft_id || draft?.superseded_by_draft_id;
    if (!id) { setRelatedDraft(null); return; }
    const ctl = controller();
    relatedRequest.current = ctl;
    try {
      const value = await api.get(endpoint(`/drafts/${encodeURIComponent(id)}`), { signal: ctl.signal });
      const checked = validateDraft(value, source, user.id, { allowForeignActor: true });
      if (!ctl.signal.aborted && alive.current && relatedRequest.current === ctl) setRelatedDraft(checked);
    } catch (reason) {
      if (reason.name !== 'AbortError' && alive.current && relatedRequest.current === ctl) setRelatedDraft({ id, unavailable: true });
    } finally { doneController(ctl); if (relatedRequest.current === ctl) relatedRequest.current = null; }
  }, [controller, doneController, endpoint, source, user.id]);

  const chooseDraft = draft => {
    if (busyRef.current || preparingRef.current || retry) return;
    setSelected(validateDraft(draft, source, user.id));
    setSelectedHistory(null); setForm(formFromData(draft.data)); setTab('draft');
    setError(null); setRetry(null); setNeedsReload(false); setReviewConsent(null); loadRelated(draft);
  };

  const chooseHistory = item => {
    if (busyRef.current || preparingRef.current || retry) return;
    const currentState = item.current_state || item.result.current_state || item.result.state;
    const result = { ...item.result, current_state: currentState,
      superseded_by_draft_id: item.superseded_by_draft_id ?? item.result.superseded_by_draft_id,
      supersedes_draft_id: item.supersedes_draft_id ?? item.result.supersedes_draft_id };
    setSelected(result); setSelectedHistory(item); setForm(formFromData(result.data)); setTab('history');
    setError(null); setRetry(null); setNeedsReload(false); setReviewConsent(null); loadRelated(result);
  };

  const freshSource = useCallback(async signal => loadSource(signal), [loadSource]);

  const applyResult = useCallback(checked => {
    if (!alive.current) return checked;
    setSelected(checked); setForm(formFromData(checked.data)); setRetry(null); setNeedsReload(false); setReviewConsent(null);
    setSelectedHistory(current => current?.draft_id === checked.id
      ? { ...current, current_state: checked.current_state || checked.state,
        supersedes_draft_id: checked.supersedes_draft_id,
        superseded_by_draft_id: checked.superseded_by_draft_id }
      : current);
    loadRelated(checked);
    return checked;
  }, [loadRelated]);

  const send = useCallback(async command => {
    if (busyRef.current) return;
    if (command.write && !isAllowed()) { setError(label('writeDenied')); return; }
    busyRef.current = true; setBusy(true); setError(null);
    const ctl = controller();
    try {
      const value = await api.post(command.path, command.payload, { signal: ctl.signal });
      if (ctl.signal.aborted || !alive.current) return;
      let checked;
      try { checked = command.validate(value); }
      catch { throw Object.assign(new Error(label('malformed')), { malformed: true }); }
      if (command.write && !isAllowed()) return;
      setRetry(null); setNeedsReload(false);
      await command.success?.(checked);
    } catch (reason) {
      if (reason.name === 'AbortError' || !alive.current) return;
      if (ctl.signal.aborted) return;
      forgetProtectedData(reason);
      if (reason.statusCode === 409 || reason.statusCode === 412) {
        setRetry(null); setNeedsReload(true);
        setError(reason.message || label('stale'));
      } else {
        setError(reason.message || label('commandFailed'));
        const ambiguousServerOutcome = Number.isInteger(reason.statusCode)
          && reason.statusCode >= 500 && reason.statusCode <= 599;
        if (reason.isNetwork || reason.malformed || ambiguousServerOutcome) setRetry(command);
      }
    } finally {
      doneController(ctl); busyRef.current = false;
      if (alive.current && !ctl.signal.aborted) setBusy(false);
    }
  }, [controller, doneController, forgetProtectedData, isAllowed, label]);

  const retryExact = () => {
    if (!retry || busyRef.current || preparingRef.current) return;
    // Deliberately reuse the original object. Do not refresh/substitute ETag,
    // revision, review hash or idempotency key after an unknown outcome.
    send(retry);
  };

  const refreshAfterMutation = useCallback(async checked => {
    // The command already validated its exact fresh source/actor binding.
    applyResult(checked);
    onChanged?.();
    const ctl = controller();
    try {
      const fresh = await freshSource(ctl.signal);
      const [, receipts] = await Promise.all([
        loadPage('drafts', fresh, null, false, ctl.signal),
        loadPage('history', fresh, null, false, ctl.signal),
      ]);
      if (!alive.current || ctl.signal.aborted) return;
      if (FINAL_STATES.has(checked.state)) {
        const receipt = receipts.items.find(item => item.draft_id === checked.id);
        setSelectedHistory(receipt || null);
        // The stored command result can legitimately describe an older state
        // on exact replay. Keep its evidence intact; load today's subject state.
        const current = validateDraft(await api.get(endpoint(`/drafts/${encodeURIComponent(checked.id)}`),
          { signal: ctl.signal }), fresh.value, user.id, { allowForeignActor: true });
        if (!alive.current || ctl.signal.aborted) return;
        setSelected(current); loadRelated(current);
        setTab('history');
      } else {
        setSelectedHistory(null); setTab('draft');
      }
    } catch (reason) {
      if (reason.name !== 'AbortError' && alive.current && !ctl.signal.aborted) {
        forgetProtectedData(reason); setError(reason.message || label('loadFailed'));
      }
    } finally { doneController(ctl); }
  }, [applyResult, controller, doneController, endpoint, forgetProtectedData, freshSource, label, loadPage, loadRelated, onChanged, user.id]);

  const saveDraft = async () => {
    if (!canWrite || retry || needsReload || busyRef.current || preparingRef.current || (selected && FINAL_STATES.has(selected.state))) return;
    preparingRef.current = true; setBusy(true);
    let data;
    try { data = dataFromForm(form); }
    catch (reason) {
      preparingRef.current = false; setBusy(false); setError(label(reason.message)); return;
    }
    const ctl = controller();
    try {
      if (!isAllowed()) { setError(label('writeDenied')); return; }
      const fresh = await freshSource(ctl.signal);
      if (!isAllowed() || ctl.signal.aborted || !alive.current) return;
      const payload = selected && !FINAL_STATES.has(selected.state)
        ? { idempotency_key: commandKey(), expected_contract_etag: fresh.etag, expected_revision: selected.revision, data }
        : { idempotency_key: commandKey(), expected_contract_etag: fresh.etag, data };
      const path = selected && !FINAL_STATES.has(selected.state)
        ? endpoint(`/drafts/${encodeURIComponent(selected.id)}/edit`) : endpoint('/drafts');
      const command = {
        path, payload, write: true,
        validate: value => validateCommand(value, fresh.value, user.id, {
          operation: selected ? 'edit' : 'create', id: selected?.id, data, etag: fresh.etag,
        }),
        success: value => refreshAfterMutation(value),
      };
      preparingRef.current = false;
      await send(command);
    } catch (reason) {
      if (reason.name !== 'AbortError' && alive.current && !ctl.signal.aborted) {
        forgetProtectedData(reason); setError(reason.message || label('loadFailed'));
      }
    } finally {
      preparingRef.current = false; doneController(ctl);
      if (!busyRef.current && alive.current) setBusy(false);
    }
  };

  const simpleCommand = async operation => {
    if (!selected || !canWrite || retry || needsReload || busyRef.current || preparingRef.current) return;
    if (operation !== 'finalize' && !sameLifecycleData(form, selected.data)) {
      setReviewConsent(null); setError(label('unsavedChanges')); return;
    }
    if (operation === 'confirm' && reviewConsent !== reviewConsentKey(selected)) {
      setError(label('confirmRequired')); return;
    }
    preparingRef.current = true; setBusy(true);
    const ctl = controller();
    try {
      if (!isAllowed()) return;
      const fresh = await freshSource(ctl.signal);
      if (!isAllowed() || ctl.signal.aborted) return;
      let current = selected;
      if (operation === 'confirm' && fresh.etag !== current.source_contract_etag) {
        setReviewConsent(null); setError(label('stale')); setNeedsReload(true); return;
      }
      if (operation === 'finalize') {
        current = validateDraft(await api.get(endpoint(`/drafts/${encodeURIComponent(selected.id)}`), { signal: ctl.signal }), fresh.value, user.id, { allowForeignActor: true });
        if (!alive.current || ctl.signal.aborted || !isAllowed()) return;
        if (current.superseded_by_draft_id || current.current_state === 'superseded' || current.state !== 'pending_effective') {
          setError(label('notFinalizable')); return;
        }
      }
      const payload = {
        idempotency_key: commandKey(), expected_contract_etag: fresh.etag,
        expected_revision: current.revision,
        ...(operation === 'confirm' || operation === 'finalize'
          ? { reviewed_hash: current.review_hash, confirmed: true } : {}),
      };
      if ((operation === 'confirm' || operation === 'finalize') && !/^[0-9a-f]{64}$/.test(current.review_hash || '')) {
        setError(label('malformed')); return;
      }
      const promptKey = operation === 'confirm' ? 'confirmPrompt' : operation === 'finalize' ? 'finalizePrompt' : null;
      if (promptKey) {
        const accepted = await confirm(label(promptKey));
        if (!accepted || !isAllowed() || ctl.signal.aborted) return;
      }
      const command = {
        path: endpoint(`/drafts/${encodeURIComponent(current.id)}/${operation}`),
        payload, write: true,
        validate: value => validateCommand(value, fresh.value, user.id, {
          operation, id: current.id, data: current.data, etag: fresh.etag,
          reviewHash: operation === 'confirm' || operation === 'finalize' ? current.review_hash : null,
        }),
        success: value => refreshAfterMutation(value),
      };
      preparingRef.current = false;
      await send(command);
    } catch (reason) {
      if (reason.name !== 'AbortError' && alive.current && !ctl.signal.aborted) {
        forgetProtectedData(reason); setError(reason.message || label('loadFailed'));
      }
    } finally {
      preparingRef.current = false; doneController(ctl);
      if (!busyRef.current && alive.current) setBusy(false);
    }
  };

  const selectedState = selected?.current_state || selected?.state || selectedHistory?.current_state;
  const superseded = selected?.superseded_by_draft_id || selectedState === 'superseded';
  const canFinalize = canWrite && selectedState === 'pending_effective' && !superseded;
  const locked = busy || Boolean(retry) || needsReload;
  const consentKey = reviewConsentKey(selected);
  const formDirty = Boolean(selected) && !sameLifecycleData(form, selected.data);
  const reviewApproved = Boolean(consentKey) && reviewConsent === consentKey;
  const staleReview = selected?.state === 'reviewed' && selected.source_contract_etag !== sourceEtag;
  const updateForm = updater => {
    setForm(current => typeof updater === 'function' ? updater(current) : updater);
    setReviewConsent(null);
  };

  const reviewBlock = selected?.review ? (() => {
    const review = selected.review;
    const obligations = review.obligations;
    const predecessorId = review.supersedes?.id || selected.supersedes_draft_id;
    const predecessorDate = review.supersedes?.termination_end_date
      || (predecessorId && relatedDraft?.id === predecessorId ? relatedDraft.data?.termination_end_date : null);
    return <div className="contract-lifecycle__review">
      <h3>{label('reviewTitle')}</h3>
      {predecessorId && <div className="contract-lifecycle__notice contract-lifecycle__notice--warning">
        <strong>{label('supersedesTitle')}</strong>
        <span>{t('contractLifecycle.supersedesDetail', { id: predecessorId, date: predecessorDate || '—' })}</span>
      </div>}
      <dl className="contract-lifecycle__facts">
        <div><dt>{label('sourceNumber')}</dt><dd>{review.source_contract.contract_number}</dd></div>
        <div><dt>{label('sourceStatus')}</dt><dd>{review.source_contract.status}</dd></div>
        <div><dt>{label('reason')}</dt><dd>{review.data.reason}</dd></div>
        {review.data.operation === 'renewal' ? <>
          <div><dt>{label('newNumber')}</dt><dd>{review.data.new_contract_number}</dd></div>
          <div><dt>{label('newStart')}</dt><dd>{review.data.new_start_date}</dd></div>
          <div><dt>{label('newEnd')}</dt><dd>{review.data.new_end_date ?? label('unlimited')}</dd></div>
        </> : <div><dt>{label('terminationEnd')}</dt><dd>{review.data.termination_end_date}</dd></div>}
      </dl>
      <div className="contract-lifecycle__obligations">
        <h4>{label('obligationsTitle')}</h4>
        <div className="contract-lifecycle__metrics">
          <span>{t('contractLifecycle.rentCharges', { count: obligations.rent_charge_count })}</span>
          <span>{t('contractLifecycle.receivables', { count: obligations.receivable_count })}</span>
          <span>{t('contractLifecycle.dueAfterEnd', { count: obligations.receivables_due_after_end_count })}</span>
          <span>{t('contractLifecycle.periodConflicts', { count: obligations.rent_period_conflict_count })}</span>
        </div>
        {(obligations.receivables_due_after_end_count > 0 || obligations.rent_period_conflict_count > 0) &&
          <div className="contract-lifecycle__notice contract-lifecycle__notice--warning">
            <AlertTriangle size={18} aria-hidden="true" />
            <span>{label('obligationsWarning')}</span>
          </div>}
        {obligations.receivables_due_after_end_sample.length > 0 && <div className="contract-lifecycle__sample">
          <h5>{label('receivableSample')}</h5>
          {obligations.receivables_due_after_end_sample.map(item =>
            <div key={item.id} className="contract-lifecycle__sample-row">
              <span>{item.due_date}</span><span>{item.description || item.id}</span>
              <span>{formatAmount(item.amount_paid)} / {formatAmount(item.amount_due)}</span>
            </div>)}
        </div>}
        {obligations.rent_period_conflict_sample.length > 0 && <div className="contract-lifecycle__sample">
          <h5>{label('rentConflictSample')}</h5>
          <p>{obligations.rent_period_conflict_sample.map(item => item.month).join(', ')}</p>
        </div>}
        <p className="contract-lifecycle__policy">{label('keepObligations')}</p>
      </div>
      <div className="contract-lifecycle__notice">
        <FileClock size={18} aria-hidden="true" />
        <span>{label('manualNotice')}</span>
      </div>
    </div>;
  })() : null;

  const relatedNotice = selected?.superseded_by_draft_id
    ? <div className="contract-lifecycle__notice contract-lifecycle__notice--warning">
      <strong>{label('supersededTitle')}</strong>
      <span>{t('contractLifecycle.supersededDetail', {
        id: selected.superseded_by_draft_id,
        date: relatedDraft?.id === selected.superseded_by_draft_id ? relatedDraft.data?.termination_end_date || '—' : '—',
      })}</span>
    </div> : null;

  return <FocusDialog titleId={titleId} busy={busy} onClose={onClose} opener={opener}>
    <header className="contract-lifecycle__header">
      <div>
        <p className="contract-lifecycle__eyebrow">{label('eyebrow')}</p>
        <h2 id={titleId}>{label('title')}</h2>
        <p>{contract.contract_number} · {source?.status || contract.status}</p>
      </div>
      <button type="button" className="contract-lifecycle__icon-button" onClick={onClose}
        disabled={busy} aria-label={label('close')}><X size={20} /></button>
    </header>

    <nav className="contract-lifecycle__tabs" aria-label={label('tabs')}>
      <button type="button" className={tab === 'draft' ? 'is-active' : ''} onClick={() => setTab('draft')}
        aria-pressed={tab === 'draft'}>{canWrite ? label('draftTab') : label('ownDraftsTab')}</button>
      <button type="button" className={tab === 'history' ? 'is-active' : ''} onClick={() => setTab('history')}
        aria-pressed={tab === 'history'}>{label('historyTab')}</button>
    </nav>

    <div className="contract-lifecycle__body">
      {loading && <p role="status">{label('loading')}</p>}
      {error && <div className="contract-lifecycle__error" role="alert">
        <AlertTriangle size={18} aria-hidden="true" /><span>{error}</span>
        {retry && <button type="button" className="btn btn-secondary" onClick={retryExact} disabled={busy}>{label('retryExact')}</button>}
        {needsReload && <button type="button" className="btn btn-secondary"
          onClick={() => reloadAll({ preserveForm: true, selectedDraft: selected })} disabled={busy}>
          <RefreshCw size={16} aria-hidden="true" />{label('reloadReview')}</button>}
      </div>}

      {!loading && !accessDenied && tab === 'draft' && <>
        <section className="contract-lifecycle__list" aria-label={label('ownDrafts')}>
          <div className="contract-lifecycle__section-title">
            <h3>{label('ownDrafts')}</h3>
            {canWrite && <button type="button" className="btn btn-secondary" disabled={locked}
              onClick={() => { setSelected(null); setSelectedHistory(null); setRelatedDraft(null); updateForm(blankForm()); setError(null); }}>
              {label('newDraft')}</button>}
          </div>
          {drafts.length === 0 ? <p className="text-muted">{label('noDrafts')}</p> :
            <div className="contract-lifecycle__cards">{drafts.map(draft =>
              <button type="button" key={draft.id} className={selected?.id === draft.id ? 'is-selected' : ''}
                disabled={locked} onClick={() => chooseDraft(draft)}>
                <strong>{draft.data.operation === 'renewal' ? label('renewal') : label('termination')}</strong>
                <span>{draft.data.reason}</span><small>{label(`state_${draft.state}`)}</small>
              </button>)}</div>}
          {draftBefore && <button type="button" className="btn btn-secondary" onClick={() => loadMore('drafts')} disabled={busy}>{label('loadMore')}</button>}
        </section>

        {canWrite && <form className="contract-lifecycle__form" onSubmit={event => { event.preventDefault(); saveDraft(); }}>
          <fieldset disabled={locked || Boolean(selected && FINAL_STATES.has(selected.state))}>
            <legend>{selected ? label('editDraft') : label('newDraft')}</legend>
            <label>{label('operation')}
              <select value={form.operation} onChange={event => updateForm(current => ({ ...blankForm(), reason: current.reason, operation: event.target.value }))}>
                <option value="renewal">{label('renewal')}</option><option value="termination">{label('termination')}</option>
              </select>
            </label>
            <label>{label('reason')}<textarea value={form.reason} rows="3" required
              onChange={event => updateForm(current => ({ ...current, reason: event.target.value }))} /></label>
            {form.operation === 'renewal' ? <>
              <label>{label('newNumber')}<input value={form.new_contract_number} required
                onChange={event => updateForm(current => ({ ...current, new_contract_number: event.target.value }))} /></label>
              <div className="contract-lifecycle__dates">
                <label>{label('newStart')}<input type="date" value={form.new_start_date} required
                  onChange={event => updateForm(current => ({ ...current, new_start_date: event.target.value }))} /></label>
                <label>{label('newEnd')}<input type="date" value={form.new_end_date} disabled={form.unlimited}
                  onChange={event => updateForm(current => ({ ...current, new_end_date: event.target.value }))} /></label>
              </div>
              <label className="contract-lifecycle__checkbox"><input type="checkbox" checked={form.unlimited}
                onChange={event => updateForm(current => ({ ...current, unlimited: event.target.checked, new_end_date: event.target.checked ? '' : current.new_end_date }))} />
                <span>{label('deliberateUnlimited')}</span></label>
            </> : <label>{label('terminationEnd')}<input type="date" value={form.termination_end_date} required
              onChange={event => updateForm(current => ({ ...current, termination_end_date: event.target.value }))} /></label>}
          </fieldset>
          <div className="contract-lifecycle__actions">
            <button type="submit" className="btn btn-primary" disabled={locked || Boolean(selected && FINAL_STATES.has(selected.state))}>{selected ? label('saveChanges') : label('saveDraft')}</button>
            {selected && !FINAL_STATES.has(selected.state) && <button type="button" className="btn btn-secondary"
              disabled={locked} onClick={() => {
                if (formDirty) { setError(label('unsavedChanges')); return; }
                simpleCommand('review');
              }}>{label('review')}</button>}
          </div>
        </form>}
        {selected && reviewBlock}
        {selected && relatedNotice}
        {formDirty && <p role="status" className="contract-lifecycle__policy">{label('unsavedChanges')}</p>}
        {selected?.state === 'reviewed' && canWrite && <div className="contract-lifecycle__confirm">
          <label className="contract-lifecycle__checkbox"><input type="checkbox" data-testid="confirm-reviewed"
            checked={reviewApproved} disabled={locked || formDirty || staleReview || !consentKey}
            onChange={event => setReviewConsent(event.currentTarget.checked ? consentKey : null)} />
            <span>{label('confirmChecked')}</span></label>
          <button type="button" className="btn btn-primary" disabled={locked || formDirty || staleReview}
            onClick={() => {
              if (formDirty) { setError(label('unsavedChanges')); return; }
              if (!reviewApproved) { setError(label('confirmRequired')); return; }
              simpleCommand('confirm');
            }}>{label('confirm')}</button>
        </div>}
      </>}

      {!loading && !accessDenied && tab === 'history' && <section className="contract-lifecycle__list" aria-label={label('history')}>
        <h3>{label('history')}</h3>
        {history.length === 0 ? <p className="text-muted">{label('noHistory')}</p> :
          <div className="contract-lifecycle__cards">{history.map(item => {
            const current = item.current_state || item.result.current_state || item.result.state;
            return <button type="button" key={item.id} className={selectedHistory?.id === item.id ? 'is-selected' : ''}
              disabled={locked} onClick={() => chooseHistory(item)}>
              <strong>{item.result.data.operation === 'renewal' ? label('renewal') : label('termination')}</strong>
              <span>{item.result.data.reason}</span><small>{label(`state_${current}`)}</small>
            </button>;
          })}</div>}
        {historyBefore && <button type="button" className="btn btn-secondary" onClick={() => loadMore('history')} disabled={busy}>{label('loadMore')}</button>}
        {selected && FINAL_STATES.has(selectedState) && <>
          <p className="contract-lifecycle__policy" role="status">{label(`state_${selectedState}`)}</p>
          {reviewBlock}{relatedNotice}
          {selected?.successor_contract_id && <div className="contract-lifecycle__success">
            <CheckCircle2 size={18} aria-hidden="true" />
            <span>{t('contractLifecycle.successorCreated', { id: selected.successor_contract_id })}</span>
          </div>}
          {selectedState === 'pending_effective' && !superseded && <p className="contract-lifecycle__policy">{label('pendingFinalize')}</p>}
          {canFinalize && <button type="button" className="btn btn-primary" disabled={locked}
            onClick={() => simpleCommand('finalize')}>{label('finalize')}</button>}
          {superseded && <p className="contract-lifecycle__policy">{label('supersededNoFinalize')}</p>}
        </>}
      </section>}
    </div>

    <footer className="contract-lifecycle__footer">
      <p>{label('disclaimer')}</p>
      <button type="button" className="btn btn-secondary" onClick={onClose} disabled={busy}>{label('close')}</button>
    </footer>
  </FocusDialog>;
}

export default function ContractLifecycle({ contract, opener, onClose, onChanged }) {
  const auth = useAuth();
  const user = auth?.user;
  const key = useMemo(() => actorKey(user), [user]);
  if (!contract?.id || !key) return null;
  return <LifecycleDialog key={`${contract.id}:${key}`} contract={contract} opener={opener}
    onClose={onClose} onChanged={onChanged} user={user} />;
}
