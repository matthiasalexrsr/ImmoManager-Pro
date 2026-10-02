import { useEffect, useId, useRef, useState } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import { useDataStore } from '../contexts/DataStoreContext';
import useWriteAccess from '../hooks/useWriteAccess';
import { centsInput, euroCents, storedCents } from '../utils/accountMoney';
import { checkedSuggestions, exactAmount } from '../utils/bankMatching';
import { useConfirm } from './ConfirmDialog';
import PaymentHistoryPanel from './PaymentHistoryPanel';
import './BankMatchingPanel.css';

export default function BankMatchingPanel({ booking, initialInvoiceId = '', onMatched, onClose, onBusyChange }) {
  const { t, locale } = useTranslation();
  const text = (key, values) => t(`bankMatching.${key}`, values);
  const confirm = useConfirm();
  const store = useDataStore();
  const heading = useRef(null);
  const identifier = useId();
  const [source, setSource] = useState(booking);
  const [kind, setKind] = useState(Number(booking.amount) < 0 ? 'invoice' : 'rent_charge');
  const [draft, setDraft] = useState(initialInvoiceId);
  const [search, setSearch] = useState(initialInvoiceId);
  const [history, setHistory] = useState([null]);
  const [index, setIndex] = useState(0);
  const [revision, setRevision] = useState(0);
  const [receiptRevision, setReceiptRevision] = useState(0);
  const [page, setPage] = useState(null);
  const [selected, setSelected] = useState(null);
  const [amount, setAmount] = useState('');
  const [note, setNote] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [historyBusy, setHistoryBusy] = useState(false);
  const [error, setError] = useState(null);
  const [renewNeeded, setRenewNeeded] = useState(false);
  const [completed, setCompleted] = useState(null);
  const generation = useRef(0);
  const operation = useRef(null);
  const submitting = useRef(false);
  const command = useRef(null);
  const { canWrite, isAllowed, requireWrite } = useWriteAccess('/bookings', () => {
    generation.current += 1; operation.current?.abort(); setSelected(null); command.current = null;
  });
  useEffect(() => { heading.current?.focus(); }, []);
  useEffect(() => { onBusyChange?.(busy || historyBusy); }, [busy, historyBusy, onBusyChange]);
  useEffect(() => () => { generation.current += 1; operation.current?.abort(); }, []);
  const renew = () => {
    generation.current += 1; operation.current?.abort(); setSelected(null); command.current = null;
    setHistory([null]); setIndex(0); setRevision(value => value + 1);
  };
  useEffect(() => {
    generation.current += 1; operation.current?.abort();
    const controller = new AbortController();
    const params = new URLSearchParams({ kind, page_size: '25' });
    if (search) params.set('search', search);
    if (history[index]) params.set('cursor', history[index]);
    setLoading(true); setError(null); setPage(null); setSelected(null); setRenewNeeded(false);
    Promise.all([api.get(`/bookings/${encodeURIComponent(booking.id)}`, { signal: controller.signal }).then(fresh => {
      if (controller.signal.aborted) return fresh;
      if (fresh?.id !== booking.id || storedCents(fresh.amount) === null) throw new Error('bankMatching.invalidResponse');
      setSource(fresh);
      if (Number(fresh.amount) < 0 && kind !== 'invoice') { setKind('invoice'); setHistory([null]); setIndex(0); }
      else if (Number(fresh.amount) >= 0 && kind === 'invoice') { setKind('rent_charge'); setHistory([null]); setIndex(0); }
      return fresh;
    }),
      api.get(`/bookings/${encodeURIComponent(booking.id)}/suggestions?${params}`, { signal: controller.signal })])
      .then(([fresh, response]) => {
        if (controller.signal.aborted) return;
        if (fresh?.id !== booking.id || storedCents(fresh.amount) === null) throw new Error('bankMatching.invalidResponse');
        setSource(fresh); setPage(checkedSuggestions(response, booking.id, kind));
      }).catch(failure => { if (!controller.signal.aborted) { setError(failure.message); setRenewNeeded(true); } })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [booking.id, kind, search, history, index, revision]);
  const choose = candidate => {
    if (!isAllowed() || busy) return;
    setSelected(candidate); setAmount(centsInput(String(candidate.suggested_cents))); setNote(''); setError(null);
    command.current = null;
  };
  const publish = async event => {
    event.preventDefault();
    if (submitting.current || !selected || !page || !isAllowed()) return;
    const canonical = exactAmount(amount, Math.min(selected.open_cents, page.available_cents));
    if (!canonical) { setError(text('invalidAmount')); return; }
    const fingerprint = JSON.stringify([selected.review_token, canonical, note]);
    if (command.current?.fingerprint !== fingerprint) command.current = { fingerprint, key: crypto.randomUUID() };
    const payload = { review_token: selected.review_token, amount: canonical, note: note || null, idempotency_key: command.current.key };
    const captured = generation.current;
    submitting.current = true; setBusy(true); setError(null);
    try {
      requireWrite();
      if (!await confirm(text('confirmQuestion')) || captured !== generation.current || !isAllowed()) return;
      const controller = new AbortController(); operation.current = controller;
      requireWrite();
      const receipt = await api.post(`/bookings/${encodeURIComponent(booking.id)}/matching`, payload, { signal: controller.signal });
      if (captured !== generation.current || controller.signal.aborted) return;
      if (!receipt?.id || receipt.booking_id !== booking.id || receipt.entity_id !== selected.id || receipt.entity_type !== selected.kind
        || receipt.idempotency_key !== payload.idempotency_key || receipt.payment_date !== source.booking_date
        || storedCents(receipt.amount) !== storedCents(canonical)) throw new Error('bankMatching.invalidResponse');
      setCompleted(receipt.id); setReceiptRevision(value => value + 1); renew(); onMatched?.();
      store?.invalidateRelated('bookings', 'accounts', 'invoices', 'rent-charges', 'receivables', 'contracts');
    } catch (failure) {
      if (captured !== generation.current || failure.name === 'AbortError') return;
      setError(failure.message);
      if (failure.statusCode) { setRenewNeeded(true); setSelected(null); command.current = null; }
    } finally { submitting.current = false; operation.current = null; setBusy(false); }
  };
  const changed = () => { renew(); onMatched?.(); };
  const message = error === 'bankMatching.invalidResponse' ? text('invalidResponse') : error;
  return <section className="panel bank-matching-panel" aria-labelledby={identifier}>
    <div className="bank-matching-heading"><h2 id={identifier} ref={heading} tabIndex={-1}>{text('title')}</h2>
      <button type="button" className="btn btn-secondary" disabled={busy || historyBusy} onClick={onClose}>{t('ui.buttons.close')}</button></div>
    <p className="text-muted">{text('help')}</p>
    <div className="bank-matching-source"><strong>{source.booking_date} · {euroCents(storedCents(source.amount), locale)}</strong>
      <p>{source.payment_text || source.id}</p><p>{text('bookingIdentity')}: <code>{source.id}</code></p></div>
    {!canWrite && <p className="alert alert-info">{text('readonly')}</p>}
    {completed && <p role="status">{text('completed')} <code>{completed}</code></p>}
    <form className="bank-matching-filters" onSubmit={event => { event.preventDefault(); setSearch(draft.trim()); renew(); }}>
      <label>{text('targetKind')}<select value={kind} disabled={busy} onChange={event => { setKind(event.target.value); setDraft(''); setSearch(''); renew(); }}>
        {(Number(source.amount) < 0 ? ['invoice'] : ['rent_charge', 'receivable']).map(value => <option key={value} value={value}>{text(`kind.${value}`)}</option>)}</select></label>
      <label>{text('search')}<input type="search" maxLength={200} value={draft} disabled={busy} onChange={event => setDraft(event.target.value)} /></label>
      <button type="submit" className="btn btn-secondary" disabled={busy}>{text('searchAction')}</button>
    </form>
    {loading && <p role="status">{t('ui.table.loading')}</p>}
    {error && <div className="alert alert-error" role="alert">{message} {renewNeeded && <button type="button" className="btn btn-secondary" onClick={renew}>{text('renew')}</button>}</div>}
    {page && !loading && <>
      <p>{text('available')}: <strong>{euroCents(String(page.available_cents), locale)}</strong></p>
      {page.ambiguous && <p className="alert alert-warning">{text('ambiguous')}</p>}
      {!page.items.length && <p>{text(page.available_cents ? 'empty' : 'fullyAllocated')}</p>}
      <div className="bank-matching-candidates" role="group" aria-label={text('candidates')}>
        {page.items.map(candidate => <div className="bank-matching-candidate" key={candidate.id}>
          <label><input type="radio" name={`${identifier}-candidate`} disabled={!canWrite || busy} checked={selected?.id === candidate.id} onChange={() => choose(candidate)} />
            <span><strong>{candidate.label}</strong><span className="bank-matching-candidate-id"> · {candidate.id}</span></span></label>
          <p>{candidate.reference} {candidate.property_label && `· ${candidate.property_label}`}</p>
          <p>{text('dueDate')}: {candidate.due_date} · {text('open')}: {euroCents(String(candidate.open_cents), locale)}</p>
          <ul className="bank-matching-reasons">{candidate.reasons.map(reason => <li key={reason}>{text(`reasons.${reason}`)}</li>)}</ul>
        </div>)}
      </div>
      <nav className="bank-matching-paging" aria-label={text('candidatePages')}>
        <button type="button" className="btn btn-secondary" disabled={!index || busy} onClick={() => setIndex(value => value - 1)}>{t('bookingPages.previous')}</button>
        <span>{t('bookingPages.pageNumber', { page: index + 1 })}</span>
        <button type="button" className="btn btn-secondary" disabled={!page.has_more || busy} onClick={() => {
          setHistory(current => [...current.slice(0, index + 1), page.next_cursor]); setIndex(value => value + 1);
        }}>{t('bookingPages.next')}</button>
      </nav>
      {selected && canWrite && <form className="bank-matching-payment" onSubmit={publish} aria-busy={busy}>
        <p><strong>{text('selected')}: {selected.label}</strong></p>
        <label>{text('amount')}<input inputMode="decimal" required value={amount} disabled={busy} onChange={event => setAmount(event.target.value)} /></label>
        <label>{text('note')}<textarea maxLength={2000} value={note} disabled={busy} onChange={event => setNote(event.target.value)} /></label>
        <p className="text-muted">{text('confirmHelp')}</p>
        <button type="submit" className="btn btn-primary" disabled={busy}>{text(busy ? 'publishing' : 'confirm')}</button>
      </form>}
    </>}
    <PaymentHistoryPanel key={receiptRevision} path={`/bookings/${encodeURIComponent(booking.id)}/allocations`} onChanged={changed} onBusyChange={setHistoryBusy} />
  </section>;
}
