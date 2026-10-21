import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Link, useInRouterContext } from 'react-router-dom';
import UnsavedNavigationGuard, { NavigationScopeNotice } from '../../components/UnsavedNavigationGuard';
import { navigationDiscardLabel, useNavigationProtection } from '../../components/navigationProtectionContext';
import RelatedPageLinks from '../../components/RelatedPageLinks';
import { entityHref } from '../../utils/entityLinks';
import { AlertTriangle, CheckCircle2, X } from 'lucide-react';
import { useAuth } from '../../contexts/AuthContext';
import { useTranslation } from '../../i18n';
import { formatDate, formatMoney } from '../../utils/format';
import { mayWrite } from '../../utils/permissions';
import { useModalDialog } from '../partyWorkspace/useModalDialog';
import AgreementForm from './AgreementForm';
import { depositService } from './depositApi';
import { depositText } from './depositText';
import SettlementPanel from './SettlementPanel';
import './deposits.css';

function Payments({ say, file, service, canEdit, onFile, onError, canNavigate, onDirtyChange, onBusyChange }) {
  const id = useId();
  const [candidates, setCandidates] = useState(null);
  const [candidatePage, setCandidatePage] = useState(null);
  const [query, setQuery] = useState('');
  const [loadedQuery, setLoadedQuery] = useState('');
  const [amounts, setAmounts] = useState({});
  const [busy, setBusy] = useState(false);
  const depositId = file.deposit.id;
  const hasTypedShare = Object.values(amounts).some(value => String(value).trim() !== '');
  useEffect(() => { onDirtyChange?.('payments', hasTypedShare); }, [hasTypedShare, onDirtyChange]);
  useEffect(() => () => onDirtyChange?.('payments', false), [onDirtyChange]);
  useEffect(() => { onBusyChange?.('payments', busy); }, [busy, onBusyChange]);
  useEffect(() => () => onBusyChange?.('payments', false), [onBusyChange]);

  const loadCandidates = async (append = false) => {
    setBusy(true);
    onError(null);
    try {
      const search = append ? loadedQuery : query;
      const result = await service.candidates(depositId, { skip: append ? candidates.length : 0, query: search });
      setCandidates(previous => append ? [...previous, ...(result.items || [])] : result.items || []);
      setCandidatePage(result);
      setLoadedQuery(search);
    } catch (failure) {
      onError(failure?.message || say('loadFailed'));
    } finally {
      setBusy(false);
    }
  };
  const act = async work => {
    setBusy(true);
    onError(null);
    try {
      onFile(await work());
      setCandidates(null);
      setCandidatePage(null);
      setAmounts({});
    } catch (failure) {
      onError(failure?.message || say('loadFailed'));
    } finally {
      setBusy(false);
    }
  };

  return <section className="deposit__section" aria-label={say('payments')}>
    <h3>{say('payments')}</h3>
    {(file.warnings || []).map(warning => <p key={warning.code + warning.booking_id} className="alert alert-warning" role="alert">
      {warning.message}{' '}{canNavigate && warning.booking_id && <Link to={entityHref('booking', warning.booking_id)}>{say('openBooking')}</Link>}
    </p>)}
    {file.payments.length === 0 ? <p className="deposit__muted">{say('noPayments')}</p>
      : <div className="deposit__table-wrap"><table className="deposit__table">
        <thead><tr><th scope="col">{say('date')}</th><th scope="col">{say('booking')}</th><th scope="col">{say('kind')}</th>
          <th scope="col" className="deposit__num">{say('share')}</th>{canEdit && !file.settled && <th scope="col"><span className="deposit__sr">{say('unlink')}</span></th>}</tr></thead>
        <tbody>{file.payments.map(payment => <tr key={payment.id}>
          <td>{payment.booking ? formatDate(payment.booking.booking_date) : '—'}</td>
          <td>{canNavigate && payment.booking?.id
            ? <Link className="deposit__context-link" to={entityHref('booking', payment.booking.id)}>
              {payment.booking.payment_text || say('openBooking')}</Link>
            : payment.booking?.payment_text || '—'}{payment.booking && Number(payment.booking.amount) !== Number(payment.amount)
            ? <small className="deposit__muted"> ({formatMoney(payment.booking.amount)})</small> : null}</td>
          <td>{say(`kind_${payment.kind}`)}</td>
          <td className="deposit__num">{formatMoney(payment.amount)}</td>
          {canEdit && !file.settled && <td>{payment.kind === 'receipt' && <button type="button" className="btn btn-secondary btn-sm"
            disabled={busy} onClick={() => void act(() => service.removePayment(depositId, payment.id))}>{say('unlink')}</button>}</td>}
        </tr>)}</tbody>
      </table></div>}
    {canEdit && !file.settled && <>
      <p className="deposit__muted">{say('onceHint')}</p>
      <form className="deposit__form" onSubmit={event => { event.preventDefault(); void loadCandidates(); }}>
        <label htmlFor={`${id}-candidate-search`}>{say('searchPayments')}
          <input id={`${id}-candidate-search`} type="search" value={query} maxLength={500}
            disabled={busy} onChange={event => setQuery(event.target.value)} /></label>
        <button type="submit" className="btn btn-secondary btn-sm" disabled={busy}>{say('searchPaymentAction')}</button>
      </form>
      {candidates === null ? <button type="button" className="btn btn-secondary btn-sm" disabled={busy}
        onClick={() => void loadCandidates()}>{say('addPayment')}</button>
        : candidates.length === 0 ? <p className="deposit__muted">{say('noCandidates')}</p>
          : <ul className="deposit__candidates" aria-label={say('candidates')}>
            {candidates.map(candidate => <li key={candidate.booking_id}>
              <span>{formatDate(candidate.booking_date)} · {candidate.payment_text || '—'} · {formatMoney(candidate.amount)}
                <small className="deposit__muted"> ({say('free')} {formatMoney(candidate.free)})</small></span>
              <label className="deposit__sr" htmlFor={`${id}-${candidate.booking_id}`}>{say('partAmount')}</label>
              <input id={`${id}-${candidate.booking_id}`} type="number" step="0.01" placeholder={String(candidate.free)}
                value={amounts[candidate.booking_id] ?? ''} aria-label={say('partAmount')}
                onChange={event => setAmounts(current => ({ ...current, [candidate.booking_id]: event.target.value }))} />
              <button type="button" className="btn btn-primary btn-sm" disabled={busy}
                onClick={() => void act(() => service.addPayment(depositId, candidate.booking_id, amounts[candidate.booking_id] ?? null))}>
                {say('assign')}</button>
            </li>)}
          </ul>}
      {candidatePage?.more && <button type="button" className="btn btn-secondary btn-sm" disabled={busy}
        onClick={() => void loadCandidates(true)}>{say('morePayments')}</button>}
      {candidatePage?.total != null && candidates !== null && <p className="deposit__muted" role="status">
        {say('paymentCount', { shown: candidates.length, total: candidatePage.total })}</p>}
    </>}
  </section>;
}

/** A deposit paid before the app's bookings: what was received and credited until the takeover day. */
function Takeover({ say, file, service, canEdit, onFile, onError, onDirtyChange, onBusyChange }) {
  const id = useId();
  const deposit = file.deposit;
  const taken = Boolean(deposit.carried_on);
  const editable = canEdit && !file.settled;
  const initial = () => (taken
    ? { carried_on: deposit.carried_on, carried_amount: String(deposit.carried_amount ?? ''),
      carried_interest: deposit.carried_interest ? String(deposit.carried_interest) : '', carried_note: deposit.carried_note || '' }
    : { carried_on: file.legacy_candidate ? deposit.held_date || '' : '',
      carried_amount: file.legacy_candidate ? String(deposit.amount ?? '') : '', carried_interest: '', carried_note: '' });
  const [values, setValues] = useState(initial);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const initialSnapshot = useRef(JSON.stringify(values));
  const dirty = editing && JSON.stringify(values) !== initialSnapshot.current;
  useEffect(() => { onDirtyChange?.('takeover', dirty); }, [dirty, onDirtyChange]);
  useEffect(() => () => onDirtyChange?.('takeover', false), [onDirtyChange]);
  useEffect(() => { onBusyChange?.('takeover', busy); }, [busy, onBusyChange]);
  useEffect(() => () => onBusyChange?.('takeover', false), [onBusyChange]);
  if (!taken && !editable) return null;
  const set = (name, value) => setValues(current => ({ ...current, [name]: value }));
  const save = async payload => {
    setBusy(true);
    onError(null);
    try {
      onFile(await service.setTakeover(deposit.id, { base_revision: deposit.revision, ...payload }));
      setEditing(false);
    } catch (failure) {
      onError(failure?.message || say('loadFailed'));
    } finally {
      setBusy(false);
    }
  };
  const submit = event => {
    event.preventDefault();
    void save({ carried_on: values.carried_on || null,
      carried_amount: values.carried_amount === '' ? null : Number(values.carried_amount),
      carried_interest: values.carried_interest === '' ? null : Number(values.carried_interest),
      carried_note: values.carried_note.trim() || null });
  };
  return <section className="deposit__section" aria-label={say('takeover')}>
    <div className="deposit__section-head"><h3>{say('takeover')}</h3>
      {editable && !editing && <button type="button" className="btn btn-secondary btn-sm"
        onClick={() => { setValues(initial()); setEditing(true); }}>{say(taken ? 'editTakeover' : 'recordTakeover')}</button>}</div>
    {!editing && (taken ? <dl className="deposit__facts">
      <div><dt>{say('carriedOn')}</dt><dd>{say('takeoverSummary', { date: formatDate(deposit.carried_on), amount: formatMoney(deposit.carried_amount) })}</dd></div>
      {Number(deposit.carried_interest) > 0 && <div><dt>{say('carriedInterest')}</dt><dd>{formatMoney(deposit.carried_interest)}</dd></div>}
      {deposit.carried_note && <div><dt>{say('carriedNote')}</dt><dd>{deposit.carried_note}</dd></div>}
    </dl> : <p className="deposit__muted">{say('takeoverHint')}</p>)}
    {editing && <form className="deposit__form" onSubmit={submit}>
      {!taken && file.legacy_candidate && <p className="deposit__muted">{say('takeoverLegacy', { date: formatDate(deposit.held_date) })}</p>}
      <div className="deposit__grid">
        <label htmlFor={`${id}-on`}>{say('carriedOn')}
          <input id={`${id}-on`} type="date" required value={values.carried_on} onChange={event => set('carried_on', event.target.value)} /></label>
        <label htmlFor={`${id}-amount`}>{say('carriedAmount')}
          <input id={`${id}-amount`} type="number" step="0.01" min="0.01" required inputMode="decimal" value={values.carried_amount}
            onChange={event => set('carried_amount', event.target.value)} /></label>
        <label htmlFor={`${id}-interest`}>{say('carriedInterest')}
          <input id={`${id}-interest`} type="number" step="0.01" min="0" inputMode="decimal" value={values.carried_interest}
            onChange={event => set('carried_interest', event.target.value)} /></label>
        <label className="deposit__wide" htmlFor={`${id}-note`}>{say('carriedNote')}
          <input id={`${id}-note`} type="text" maxLength={2000} value={values.carried_note} onChange={event => set('carried_note', event.target.value)} /></label>
      </div>
      <p className="deposit__muted">{say('takeoverHint')}</p>
      <div className="deposit__actions">
        {taken && <button type="button" className="btn btn-secondary btn-sm" disabled={busy}
          onClick={() => void save({ carried_on: null, carried_amount: null, carried_interest: null, carried_note: null })}>{say('removeTakeover')}</button>}
        <button type="button" className="btn btn-secondary btn-sm" disabled={busy} onClick={() => setEditing(false)}>{say('cancel')}</button>
        <button type="submit" className="btn btn-primary btn-sm" disabled={busy}>{say('saveTakeover')}</button>
      </div>
    </form>}
  </section>;
}

function Interest({ say, file, service, canEdit, onFile, onError, onDirtyChange, onBusyChange }) {
  const id = useId();
  const [rates, setRates] = useState(() => file.interest_rates.map(rate => ({ ...rate })));
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);
  const editable = canEdit && !file.settled;
  useEffect(() => { onDirtyChange?.('interest', dirty); }, [dirty, onDirtyChange]);
  useEffect(() => () => onDirtyChange?.('interest', false), [onDirtyChange]);
  useEffect(() => { onBusyChange?.('interest', busy); }, [busy, onBusyChange]);
  useEffect(() => () => onBusyChange?.('interest', false), [onBusyChange]);
  const change = next => { setRates(next); setDirty(true); };
  const save = async () => {
    setBusy(true);
    onError(null);
    try {
      onFile(await service.setRates(file.deposit.id, file.deposit.revision,
        rates.map(rate => ({ valid_from: rate.valid_from, rate_percent: String(rate.rate_percent), note: rate.note || null }))));
      setDirty(false);
    } catch (failure) {
      onError(failure?.message || say('loadFailed'));
    } finally {
      setBusy(false);
    }
  };
  return <section className="deposit__section" aria-label={say('interest')}>
    <h3>{say('interest')}</h3>
    <p>{say('interestUntil', { date: formatDate(file.interest.until), amount: formatMoney(file.interest.total) })}
      {file.interest.carried != null && <small className="deposit__muted"> ({say('carriedInterestPart', { amount: formatMoney(file.interest.carried) })})</small>}</p>
    {rates.length === 0 && <p className="deposit__muted">{say('noRates')}</p>}
    {rates.map((rate, index) => <div className="deposit__rate" key={rate.id || index}>
      <label htmlFor={`${id}-from-${index}`}>{say('validFrom')}
        <input id={`${id}-from-${index}`} type="date" value={rate.valid_from || ''} disabled={!editable}
          onChange={event => change(rates.map((r, i) => (i === index ? { ...r, valid_from: event.target.value } : r)))} /></label>
      <label htmlFor={`${id}-rate-${index}`}>{say('ratePercent')}
        <input id={`${id}-rate-${index}`} inputMode="decimal" value={rate.rate_percent ?? ''} disabled={!editable}
          onChange={event => change(rates.map((r, i) => (i === index ? { ...r, rate_percent: event.target.value } : r)))} /></label>
      {editable && <button type="button" className="btn btn-secondary btn-sm"
        onClick={() => change(rates.filter((_, i) => i !== index))}>{say('removeRate')}</button>}
    </div>)}
    {editable && <div className="deposit__actions">
      <button type="button" className="btn btn-secondary btn-sm" onClick={() => change([...rates, { valid_from: '', rate_percent: '' }])}>
        {say('addRate')}</button>
      <button type="button" className="btn btn-primary btn-sm" disabled={!dirty || busy} onClick={() => void save()}>{say('saveRates')}</button>
    </div>}
    {file.interest.years.length > 0 && <div className="deposit__table-wrap"><table className="deposit__table">
      <thead><tr><th scope="col">{say('year')}</th><th scope="col" className="deposit__num">{say('principalStart')}</th>
        <th scope="col" className="deposit__num">{say('interest')}</th></tr></thead>
      <tbody>{file.interest.years.map(year => <tr key={`${year.year}-${year.start}`}><td>{year.year}</td>
        <td className="deposit__num">{formatMoney(year.principal_start)}</td><td className="deposit__num">{formatMoney(year.interest)}</td></tr>)}</tbody>
    </table></div>}
    <p className="deposit__muted">{say('interestHint')}</p>
  </section>;
}

function Security({ say, file, service, canEdit, onFile, onError, onDirtyChange, onBusyChange }) {
  const id = useId();
  const deposit = file.deposit;
  const [values, setValues] = useState({
    provided_on: deposit.provided_on || '', proof_document_id: deposit.proof_document_id || '',
    released_on: deposit.released_on || '', release_document_id: deposit.release_document_id || '',
    release_note: deposit.release_note || '' });
  const [busy, setBusy] = useState(false);
  const initialSnapshot = useRef(JSON.stringify(values));
  const isDirty = JSON.stringify(values) !== initialSnapshot.current;
  useEffect(() => { onDirtyChange?.('security', isDirty); }, [isDirty, onDirtyChange]);
  useEffect(() => () => onDirtyChange?.('security', false), [onDirtyChange]);
  useEffect(() => { onBusyChange?.('security', busy); }, [busy, onBusyChange]);
  useEffect(() => () => onBusyChange?.('security', false), [onBusyChange]);
  const editable = canEdit && !deposit.released_on;
  const set = (name, value) => setValues(current => ({ ...current, [name]: value }));
  const save = async () => {
    setBusy(true);
    onError(null);
    try {
      onFile(await service.setSecurity(deposit.id, { base_revision: deposit.revision,
        ...Object.fromEntries(Object.entries(values).map(([key, value]) => [key, value || null])) }));
    } catch (failure) {
      onError(failure?.message || say('loadFailed'));
    } finally {
      setBusy(false);
    }
  };
  return <section className="deposit__section" aria-label={say('security')}>
    <h3>{say('security')}</h3>
    <p className="deposit__muted">{say('securityHint')}</p>
    <div className="deposit__grid">
      {[['provided_on', 'providedOn', 'date'], ['proof_document_id', 'proofDocument', 'text'],
        ['released_on', 'releasedOn', 'date'], ['release_document_id', 'releaseDocument', 'text'],
        ['release_note', 'releaseNote', 'text']].map(([name, label, type]) => <label key={name} htmlFor={`${id}-${name}`}>
        {say(label)}<input id={`${id}-${name}`} type={type} value={values[name]} disabled={!editable}
          onChange={event => set(name, event.target.value)} /></label>)}
    </div>
    {editable && <div className="deposit__actions"><button type="button" className="btn btn-primary btn-sm" disabled={busy}
      onClick={() => void save()}>{say('saveSecurity')}</button></div>}
  </section>;
}

/** The deposit file of one deposit: agreement, instalments, payments, interest, settlement and release. */
export default function DepositFile({ depositId, onClose, onChanged, service = depositService }) {
  const canNavigate = useInRouterContext();
  const protection = useNavigationProtection();
  const allowRouteLeaveRef = useRef(false);
  const auth = useAuth();
  const canEdit = mayWrite(auth?.write ?? null, '/deposits');
  const { locale } = useTranslation();
  const say = useCallback((key, params) => depositText(locale, key, params), [locale]);
  const titleId = useId();
  const dialogRef = useRef(null);
  const [file, setFile] = useState(null);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [dirtyParts, setDirtyParts] = useState({});
  const [busyParts, setBusyParts] = useState({});
  const [leaveRequest, setLeaveRequest] = useState(null);
  const [leaveBlocked, setLeaveBlocked] = useState(false);
  const keepEditingRef = useRef(null);
  const leaveSourceRef = useRef(null);
  const setPartDirty = useCallback((key, active) => setDirtyParts(previous => {
    if (Boolean(previous[key]) === Boolean(active)) return previous;
    const next = { ...previous };
    if (active) next[key] = true; else delete next[key];
    return next;
  }), []);
  const setPartBusy = useCallback((key, active) => setBusyParts(previous => {
    if (Boolean(previous[key]) === Boolean(active)) return previous;
    const next = { ...previous };
    if (active) next[key] = true; else delete next[key];
    return next;
  }), []);
  const hasUnsaved = Object.keys(dirtyParts).length > 0;
  const hasPendingAction = busy || Object.keys(busyParts).length > 0;
  const routeBlocked = useCallback(request => {
    if (request.cancelled) { setLeaveRequest(previous => previous?.kind === 'route' ? null : previous); return; }
    if (request.pending) {
      setLeaveBlocked(true);
      setLeaveRequest(previous => previous?.kind === 'route' ? null : previous);
      return;
    }
    leaveSourceRef.current = document.activeElement;
    setLeaveRequest({ kind: 'route', ...request });
  }, []);
  const returnToEditing = () => {
    leaveRequest?.reset?.();
    setLeaveRequest(null);
    if (leaveSourceRef.current?.isConnected) leaveSourceRef.current.focus();
  };
  const requestClose = () => {
    if (leaveRequest) { returnToEditing(); return; }
    if (hasPendingAction) { setLeaveBlocked(true); return; }
    if (hasUnsaved) {
      leaveSourceRef.current = document.activeElement;
      setLeaveRequest({ kind: 'close' });
      return;
    }
    onClose?.();
  };
  // Capture only ordinary same-tab internal link activation. Modified clicks
  // open a separate tab and leave the edited file safely in place.
  const guardLink = event => {
    if (protection) return;
    const anchor = event.target.closest?.('a[href]');
    if (!anchor || anchor.dataset.depositLeaveConfirmed === 'true' || event.button !== 0
      || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey
      || anchor.target === '_blank' || (!hasUnsaved && !hasPendingAction)) return;
    const href = anchor.getAttribute('href');
    if (!href?.startsWith('/') || href.startsWith('//')) return;
    event.preventDefault();
    event.stopPropagation();
    if (hasPendingAction) { setLeaveBlocked(true); return; }
    leaveSourceRef.current = anchor;
    setLeaveRequest({ kind: 'navigate', to: href });
  };
  const confirmClose = () => {
    if (hasPendingAction) { setLeaveBlocked(true); return; }
    // Closing the URL-owned file is itself navigation, already confirmed here.
    allowRouteLeaveRef.current = true;
    onClose?.();
  };
  useLayoutEffect(() => { if (leaveRequest) keepEditingRef.current?.focus(); }, [leaveRequest]);
  useEffect(() => { if (!hasPendingAction) setLeaveBlocked(false); }, [hasPendingAction]);
  // The inline link/close confirmation cannot intercept the browser's Reload,
  // close-tab or cross-origin navigation. Ask for its native confirmation only
  // while edits or a possibly unfinished business operation exist.
  useEffect(() => {
    if (!hasUnsaved && !hasPendingAction) return;
    const protectUnload = event => {
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', protectUnload);
    return () => window.removeEventListener('beforeunload', protectUnload);
  }, [hasUnsaved, hasPendingAction]);
  useModalDialog(dialogRef, requestClose, true);

  useEffect(() => {
    const controller = new AbortController();
    service.load(depositId, { signal: controller.signal })
      .then(value => { if (!controller.signal.aborted) { setFile(value); setError(null); } })
      .catch(failure => { if (!controller.signal.aborted && failure?.name !== 'AbortError') setError(failure?.message || say('loadFailed')); });
    return () => controller.abort();
  }, [attempt, depositId, say, service]);

  const apply = useCallback(next => { setFile(next); onChanged?.(); }, [onChanged]);

  const saveAgreement = async payload => {
    setBusy(true);
    setError(null);
    try {
      apply(await service.updateAgreement(depositId, { ...payload, base_revision: file.deposit.revision }));
      setEditing(false);
      setNotice(say('savedNotice'));
    } catch (failure) {
      setError(failure?.message || say('loadFailed'));
    } finally {
      setBusy(false);
    }
  };

  const start = async kind => {
    setBusy(true);
    setError(null);
    try {
      apply(await service.startSettlement(depositId, kind));
    } catch (failure) {
      setError(failure?.message || say('loadFailed'));
    } finally {
      setBusy(false);
    }
  };

  const deposit = file?.deposit;
  const source = file?.source;
  const hasFinal = file?.settlements.some(s => s.kind === 'final');
  const hasRelease = file?.settlements.some(s => s.kind === 'retention_release');

  return createPortal(<div className="deposit__overlay" role="presentation"
    onMouseDown={event => { if (event.target === event.currentTarget) requestClose(); }}>
    <UnsavedNavigationGuard when={hasUnsaved || hasPendingAction}
      pending={hasPendingAction} bypassRef={allowRouteLeaveRef} onBlocked={routeBlocked}
      label={`${say('fileTitle')}${source?.contract?.contract_number ? ` · ${source.contract.contract_number}` : ''}`} />
    <section className="deposit" ref={dialogRef} role="dialog" aria-modal="true"
      aria-labelledby={titleId} tabIndex={-1} onClickCapture={guardLink}>
      <header className="deposit__header">
        <div>
          <p className="deposit__eyebrow">{say('eyebrow')}</p>
          <h2 id={titleId}>{source ? `${say('fileTitle')} · ${source.contract.contract_number}` : say('fileTitle')}</h2>
          {source && <p>{source.tenant.full_name} · {source.property.name} · {source.unit.label}</p>}
        </div>
        <button type="button" className="deposit__icon-button" aria-label={say('close')} onClick={requestClose}><X size={20} aria-hidden="true" /></button>
      </header>
      <div className="deposit__body">
        {leaveBlocked && <p className="deposit__notice deposit__notice--warning" role="alert">
          {say('leaveBusy')}
        </p>}
        {leaveRequest && <div className="deposit__leave-confirmation" role="group" aria-label={say('leaveTitle')}>
          <p role="alert">{say('leaveWarning')}</p>
          <NavigationScopeNotice labels={leaveRequest.scopeLabels} locale={locale} />
          <div className="deposit__leave-actions">
            <button ref={keepEditingRef} type="button" className="btn btn-secondary"
              onClick={returnToEditing}>{say('keepEditing')}</button>
            {leaveRequest.kind === 'close'
              ? <button type="button" className="btn btn-danger" disabled={hasPendingAction} onClick={confirmClose}>
                {say('leaveWithoutSaving')}</button>
              : leaveRequest.kind === 'route'
                ? <button type="button" className="btn btn-danger" disabled={hasPendingAction} onClick={() => {
                  if (!hasPendingAction) leaveRequest.proceed();
                }}>{navigationDiscardLabel(leaveRequest.scopeLabels, locale, say('leaveWithoutSaving'))}</button>
              : <Link data-deposit-leave-confirmed="true" className="btn btn-danger"
                to={leaveRequest.to} onClick={event => {
                  if (hasPendingAction) { event.preventDefault(); setLeaveBlocked(true); }
                }}>{say('leaveWithoutSaving')}</Link>}
          </div>
        </div>}
        {error && <div className="deposit__notice deposit__notice--error" role="alert"><AlertTriangle size={18} aria-hidden="true" />
          <span>{error}</span>{!file && <button type="button" className="btn btn-secondary btn-sm"
            onClick={() => setAttempt(value => value + 1)}>{say('retry')}</button>}</div>}
        {notice && <div className="deposit__notice deposit__notice--success" role="status"><CheckCircle2 size={18} aria-hidden="true" />
          <span>{notice}</span></div>}
        {!file && !error && <p role="status">{say('loading')}</p>}
        {file && <>
          {canNavigate && <RelatedPageLinks label={say('relatedPages')} heading={say('nextPages')}
            items={[
              ...(deposit.contract_id ? [{ to: entityHref('contract', deposit.contract_id), label: say('openContract') }] : []),
              ...(source?.tenant?.id ? [{ to: entityHref('tenantAccount', source.tenant.id), label: say('openTenantAccount') }] : []),
              ...(deposit.account_id ? [{ to: `/bookings?konto=${encodeURIComponent(deposit.account_id)}`, label: say('openAccountBookings') }] : []),
            ]} />}
          {!canEdit && <p className="deposit__muted" role="note">{say('readOnly')}</p>}
          {file.settled && <p className="deposit__muted" role="note">{say('settledHint')}</p>}
          <dl className="deposit__figures">
            <div><dt>{say('stage')}</dt><dd><span className={`deposit__stage deposit__stage--${file.stage}`}>{say(`stage_${file.stage}`)}</span></dd></div>
            <div><dt>{say('amount')}</dt><dd>{formatMoney(deposit.amount)}</dd></div>
            {file.money_form && <div><dt>{say('received')}</dt><dd>{formatMoney(file.received)}</dd></div>}
            {file.money_form && <div><dt>{say('outstanding')}</dt><dd>{formatMoney(file.outstanding)}</dd></div>}
            {file.money_form && <div><dt>{say('interest')}</dt><dd>{formatMoney(file.interest.total)}</dd></div>}
            {file.retention > 0 && <div><dt>{say('retention')}</dt><dd>{formatMoney(file.retention)}</dd></div>}
          </dl>

          <section className="deposit__section" aria-label={say('agreement')}>
            <div className="deposit__section-head"><h3>{say('agreement')}</h3>
              {canEdit && !file.settled && !editing && !deposit.released_on && <button type="button" className="btn btn-secondary btn-sm"
                onClick={() => setEditing(true)}>{say('editAgreement')}</button>}</div>
            {editing ? <AgreementForm say={say} contractId={deposit.contract_id} cap={file.cap} accounts={file.accounts} busy={busy}
              initial={{ ...deposit, instalments: file.instalments }} onDirtyChange={setPartDirty}
              onSubmit={payload => void saveAgreement(payload)}
              onCancel={() => setEditing(false)} />
              : <dl className="deposit__facts">
                <div><dt>{say('form')}</dt><dd>{say(`form_${deposit.form}`)}</dd></div>
                {file.cap.known && <div><dt>{say('amount')}</dt><dd>{say('capInfo', { cap: formatMoney(file.cap.cap), cold: formatMoney(file.cap.cold_rent) })}
                  {file.cap.exceeds && <> · <strong>{deposit.cap_reason}</strong></>}</dd></div>}
                {file.account && <div><dt>{say('heldAccount')}</dt><dd>{file.account.name || '—'}{file.account.iban ? ` · ${file.account.iban}` : ''}</dd></div>}
                {(deposit.institution || deposit.account_reference) && <div><dt>{say('institution')}</dt>
                  <dd>{[deposit.institution, deposit.account_reference, deposit.account_holder].filter(Boolean).join(' · ')}</dd></div>}
                {deposit.notes && <div><dt>{say('notes')}</dt><dd>{deposit.notes}</dd></div>}
              </dl>}
          </section>

          {file.money_form && file.instalments.length > 0 && <section className="deposit__section" aria-label={say('instalments')}>
            <h3>{say('instalments')}</h3>
            <div className="deposit__table-wrap"><table className="deposit__table">
              <thead><tr><th scope="col">{say('number')}</th><th scope="col">{say('dueDate')}</th><th scope="col" className="deposit__num">{say('amount')}</th>
                <th scope="col" className="deposit__num">{say('paid')}</th><th scope="col">{say('status')}</th></tr></thead>
              <tbody>{file.instalments.map(item => <tr key={item.number}><td>{item.number}</td><td>{formatDate(item.due_date)}</td>
                <td className="deposit__num">{formatMoney(item.amount)}</td><td className="deposit__num">{formatMoney(item.paid)}</td>
                <td>{say(`instalment_${item.status}`)}</td></tr>)}</tbody>
            </table></div>
          </section>}

          {file.money_form ? <>
            <Takeover key={`takeover-${deposit.revision}`} say={say} file={file} service={service} canEdit={canEdit}
              onFile={apply} onError={setError} onDirtyChange={setPartDirty} onBusyChange={setPartBusy} />
            <Payments say={say} file={file} service={service} canEdit={canEdit} canNavigate={canNavigate}
              onDirtyChange={setPartDirty} onBusyChange={setPartBusy}
              onFile={apply} onError={setError} />
            <Interest key={deposit.revision} say={say} file={file} service={service} canEdit={canEdit}
              onDirtyChange={setPartDirty} onBusyChange={setPartBusy} onFile={apply} onError={setError} />
            <section className="deposit__section-group" aria-label={say('settlements')}>
              {file.settlements.map(settlement => <SettlementPanel key={settlement.id} say={say} file={file} settlement={settlement}
                service={service} canEdit={canEdit} onFile={apply} onError={setError} onNotice={setNotice}
                onDirtyChange={setPartDirty} onBusyChange={setPartBusy} />)}
              {canEdit && <div className="deposit__actions">
                {!hasFinal && <button type="button" className="btn btn-primary" disabled={busy || file.received <= 0}
                  onClick={() => void start('final')}>{say('startFinal')}</button>}
                {file.stage === 'retained' && !hasRelease && <button type="button" className="btn btn-primary" disabled={busy}
                  onClick={() => void start('retention_release')}>{say('startRelease')}</button>}
              </div>}
            </section>
          </> : <Security key={deposit.revision} say={say} file={file} service={service} canEdit={canEdit}
            onDirtyChange={setPartDirty} onBusyChange={setPartBusy} onFile={apply} onError={setError} />}
        </>}
      </div>
      <footer className="deposit__footer">
        <button type="button" className="btn btn-secondary" onClick={requestClose}>{say('close')}</button>
      </footer>
    </section>
  </div>, document.body);
}
