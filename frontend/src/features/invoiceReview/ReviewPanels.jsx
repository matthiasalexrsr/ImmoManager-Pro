import { useCallback, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../../api';
import { formatDate, formatDateTime, formatMoney } from '../../utils/format';
import { Empty, Fact, PickerDialog, Pill, Section } from '../maintenanceProject/ProjectUi';
import { entityHref } from '../../utils/entityLinks';
import { localDay } from '../../utils/occupancy';
import { PAYMENT_TONE, compact, findingText, reviewApi } from './reviewApi';
import { fill, useReviewText } from './text';
import useEditableDraft from '../workCenter/useEditableDraft';
import EditableDraft from '../workCenter/EditableDraft';

const SEVERITY_TONE = { error: 'red', warning: 'orange', info: 'gray' };
const RECEIPT_DRAFT = ['received_on', 'kind', 'credit_for_invoice_id', 'skonto_percent', 'skonto_days', 'payment_days', 'property_id', 'cost_category', 'recoverable', 'document_id', 'duplicate_reason'];

function useAction(onChanged) {
  const lock = useRef(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const run = async action => {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    setError(null);
    try { await action(); onChanged(); } catch (failure) { setError(failure.message); } finally { lock.current = false; setBusy(false); }
  };
  return { busy, error, run };
}

export function Summary({ view }) {
  const { tx } = useReviewText();
  const { invoice, review, assignment } = view;
  const s = view.settlement;
  return (
    <Section id="ir-summary" title={tx.summary}>
      <dl className="mp-facts mp-facts-compact">
        <Fact label={tx.supplier}>{invoice.supplier}</Fact>
        <Fact label={tx.number}>{invoice.invoice_number}</Fact>
        <Fact label={tx.invoiceDate}>{formatDate(invoice.invoice_date)}</Fact>
        <Fact label={tx.net}>{formatMoney(invoice.net_amount)}</Fact>
        <Fact label={tx.vat}>{formatMoney(invoice.vat_amount)}</Fact>
        <Fact label={tx.gross}>{formatMoney(invoice.gross_amount)}</Fact>
        {review && <Fact label={tx.receivedOn}>{formatDate(review.received_on)}</Fact>}
        <Fact label={tx.dueOn}>{s.due_on ? formatDate(s.due_on) : null}</Fact>
        {s.skonto_until && <Fact label={tx.skontoUntil}>{formatDate(s.skonto_until)} ({s.skonto_amount > 0
          ? formatMoney(s.skonto_amount) : `${String(review?.skonto_percent).replace('.', ',')}\u00a0%`})</Fact>}
        <Fact label={tx.assignment}>
          {tx[`assign_${assignment.kind || 'none'}`]}
          {assignment.kind === 'maintenance_order' && <> · <Link to={`/maintenance/${encodeURIComponent(assignment.case_id)}`}>
            {assignment.order?.order_number || assignment.order?.supplier_name}</Link></>}
          {assignment.kind === 'service_contract' && <> · <Link to={`/service-contracts/${encodeURIComponent(
            assignment.service_contract_id)}`}>{assignment.contract_title}</Link></>}
          {assignment.kind === 'free' && assignment.cost_category && ` · ${assignment.cost_category}`}
          {assignment.recoverable && ` · ${tx.recoverable}`}
        </Fact>
        {assignment.change_order && <Fact label={tx.changeOrder}>{assignment.change_order.title}</Fact>}
        {view.credit_for && <Fact label={tx.creditForInvoice}>
          <Link to={`/invoice-review/${encodeURIComponent(view.credit_for.id)}`}>{view.credit_for.invoice_number
            || view.credit_for.supplier}</Link></Fact>}
      </dl>
    </Section>
  );
}

export function Findings({ view }) {
  const { tx } = useReviewText();
  const findings = view.findings || [];
  return (
    <Section id="ir-findings" title={tx.findings}>
      {findings.length === 0 ? <Empty>{tx.noFindings}</Empty> : (
        <ul className="ir-findings">
          {findings.map((finding, index) => (
            <li key={`${finding.code}-${index}`} className={`ir-finding ir-${finding.severity}`}>
              <Pill tone={SEVERITY_TONE[finding.severity]}>{tx[`sev_${finding.severity}`]}</Pill>
              <span>{findingText(tx, finding)}</span>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

export function ReceiptForm({ view, properties, onChanged }) {
  const { tx } = useReviewText();
  const { busy, error, run } = useAction(onChanged);
  const today = localDay();
  const [values, setValues] = useState({ received_on: today, kind: 'invoice', credit_for_invoice_id: '',
    skonto_percent: '', skonto_days: '', payment_days: '', property_id: view.invoice.property_id || '',
    cost_category: '', recoverable: false, document_id: view.invoice.source_document_id || '',
    accept_duplicate: false, duplicate_reason: '' });
  const draft = useEditableDraft({ context: 'invoice-review-action#receipt', kind: 'invoice', id: view.invoice.id, fields: RECEIPT_DRAFT, values });
  const set = (key, value) => setValues(current => ({ ...current, [key]: value }));
  const number = key => (values[key] === '' ? undefined : Number(values[key]));
  const submit = event => {
    event.preventDefault();
    if (draft.blocked || busy) return;
    run(() => draft.finish(() => reviewApi.receive(view.invoice.id, compact({
      ...values, skonto_percent: number('skonto_percent'), skonto_days: number('skonto_days'),
      payment_days: number('payment_days'),
      credit_for_invoice_id: values.kind === 'credit_note' ? values.credit_for_invoice_id : undefined,
      property_id: view.invoice.property_id ? undefined : values.property_id,
      accept_duplicate: values.accept_duplicate || undefined,
      duplicate_reason: values.accept_duplicate ? values.duplicate_reason : undefined,
      recoverable: values.recoverable }))));
  };
  return (
    <Section id="ir-receipt" title={tx.receipt}>
      <p className="text-muted">{tx.receiptHint}</p>
      <EditableDraft draft={draft} values={values} busy={busy} beforeRestore={() => reviewApi.load(view.invoice.id)}
        onRestore={restored => setValues(current => ({ ...current, ...Object.fromEntries(RECEIPT_DRAFT.filter(key => Object.hasOwn(restored, key)).map(key => [key, restored[key]])), accept_duplicate: false }))}>
      <form onSubmit={submit}>
        {error && <div className="alert-error" role="alert">{error}</div>}
        <div className="mp-form-grid">
          <label className="form-group">{tx.receivedOn}
            <input type="date" value={values.received_on} required onChange={e => set('received_on', e.target.value)} /></label>
          <label className="form-group">{tx.kind}
            <select value={values.kind} onChange={e => set('kind', e.target.value)}>
              <option value="invoice">{tx.kind_invoice}</option><option value="credit_note">{tx.kind_credit_note}</option>
            </select></label>
          {values.kind === 'credit_note' && <label className="form-group">{tx.creditFor}
            <input value={values.credit_for_invoice_id} required onChange={e => set('credit_for_invoice_id', e.target.value)} /></label>}
          <label className="form-group">{tx.skontoPercent}
            <input type="number" step="0.01" min="0" max="99" value={values.skonto_percent}
              onChange={e => set('skonto_percent', e.target.value)} /></label>
          <label className="form-group">{tx.skontoDays}
            <input type="number" min="0" value={values.skonto_days} onChange={e => set('skonto_days', e.target.value)} /></label>
          <label className="form-group">{tx.paymentDays}
            <input type="number" min="0" value={values.payment_days} onChange={e => set('payment_days', e.target.value)} /></label>
          {!view.invoice.property_id && <label className="form-group">{tx.property}
            <select value={values.property_id} onChange={e => set('property_id', e.target.value)}>
              <option value="">{tx.none}</option>
              {properties.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select></label>}
          <label className="form-group">{tx.costCategory}
            <input value={values.cost_category} onChange={e => set('cost_category', e.target.value)} /></label>
          <label className="ir-check"><input type="checkbox" checked={values.recoverable}
            onChange={e => set('recoverable', e.target.checked)} />{tx.recoverable}</label>
          {view.duplicates.length > 0 && <label className="ir-check"><input type="checkbox" checked={values.accept_duplicate}
            onChange={e => set('accept_duplicate', e.target.checked)} />{tx.acceptDuplicate}</label>}
          {values.accept_duplicate && <label className="form-group">{tx.duplicateReason}
            <input value={values.duplicate_reason} required onChange={e => set('duplicate_reason', e.target.value)} /></label>}
        </div>
        <div className="mp-actions"><button type="submit" className="btn btn-primary btn-sm" disabled={busy}>{tx.receipt}</button></div>
      </form>
      </EditableDraft>
    </Section>
  );
}

function CheckResult({ result, by }) {
  const { tx } = useReviewText();
  if (!result) return <p className="text-muted">{tx.notChecked}</p>;
  return <p><Pill tone={result === 'confirmed' ? 'green' : 'orange'}>{tx[`result_${result}`]}</Pill>{' '}
    {fill(tx.checkedBy, { name: by || '—', result: tx[`result_${result}`] })}</p>;
}

export function Checks({ view, onChanged }) {
  const { tx } = useReviewText();
  const { review, abilities } = view;
  const { busy, error, run } = useAction(onChanged);
  const [notes, setNotes] = useState({ factual: '', arithmetic: '' });
  const [manual, setManual] = useState(() => ({ ...(review?.checklist || {}) }));
  const draft = useEditableDraft({ context: 'invoice-review-action#checks', kind: 'invoice', id: view.invoice.id,
    fields: ['factual', 'arithmetic'], values: notes, enabled: abilities.factual_check || abilities.arithmetic_check });
  const send = (kind, result) => { if (!draft.blocked && !busy) run(() => draft.finish(() => reviewApi.check(view.invoice.id, kind, compact({
    result, note: notes[kind], checklist: kind === 'arithmetic' ? manual : undefined })))); };
  const lines = view.arithmetic.lines;
  return (
    <EditableDraft draft={draft} values={notes} busy={busy} beforeRestore={() => reviewApi.load(view.invoice.id)}
      onRestore={restored => { setNotes({ factual: restored.factual || '', arithmetic: restored.arithmetic || '' }); setManual({}); }}>
      <Section id="ir-factual" title={tx.factual}>
        {error && <div className="alert-error" role="alert">{error}</div>}
        <CheckResult result={review?.factual_result} by={review?.factual_by_name} />
        {review?.factual_note && <p className="text-muted">{review.factual_note}</p>}
        {abilities.factual_check && (
          <div className="ir-check-actions">
            <label className="form-group">{tx.note}
              <input value={notes.factual} onChange={e => setNotes(n => ({ ...n, factual: e.target.value }))} /></label>
            <div className="mp-actions">
              <button type="button" className="btn btn-primary btn-sm" disabled={busy} onClick={() => send('factual', 'confirmed')}>
                {tx.confirm}</button>
              <button type="button" className="btn btn-secondary btn-sm" disabled={busy || !notes.factual}
                onClick={() => send('factual', 'objected')}>{tx.object}</button>
            </div>
          </div>
        )}
      </Section>
      <Section id="ir-arithmetic" title={tx.arithmetic}>
        <table className="ir-vat">
          <caption className="sr-only">{tx.vatLines}</caption>
          <thead><tr><th scope="col">{tx.vatRate}</th><th scope="col">{tx.net}</th><th scope="col">{tx.vat}</th></tr></thead>
          <tbody>{lines.map(line => <tr key={line.rate}><td>{line.rate} %</td><td>{formatMoney(line.net)}</td>
            <td>{formatMoney(line.vat)}</td></tr>)}</tbody>
        </table>
        <CheckResult result={review?.arithmetic_result} by={review?.arithmetic_by_name} />
        <fieldset className="ir-checklist">
          <legend>{tx.checklist}{view.checklist.small_invoice ? ` · ${tx.smallInvoice}` : ''}</legend>
          <ul>
            {view.checklist.items.map(item => {
              const editable = abilities.arithmetic_check && item.source !== 'auto';
              const checked = editable ? manual[item.key] === true : item.present === true;
              return (
                <li key={item.key} className={item.required && item.present !== true ? 'ir-missing' : ''}>
                  <label className="ir-check">
                    <input type="checkbox" checked={checked} disabled={!editable}
                      onChange={e => setManual(m => ({ ...m, [item.key]: e.target.checked }))} />
                    <span>{tx[`cl_${item.key}`] || item.label}
                      <span className="text-muted"> · {item.required ? tx.required : tx.optional}
                        {item.source === 'auto' ? ` · ${tx.auto}` : ''}</span></span>
                  </label>
                </li>
              );
            })}
          </ul>
        </fieldset>
        {abilities.arithmetic_check && (
          <div className="ir-check-actions">
            <label className="form-group">{tx.note}
              <input value={notes.arithmetic} onChange={e => setNotes(n => ({ ...n, arithmetic: e.target.value }))} /></label>
            <div className="mp-actions">
              <button type="button" className="btn btn-primary btn-sm" disabled={busy}
                onClick={() => send('arithmetic', 'confirmed')}>{tx.confirm}</button>
              <button type="button" className="btn btn-secondary btn-sm" disabled={busy || !notes.arithmetic}
                onClick={() => send('arithmetic', 'objected')}>{tx.object}</button>
            </div>
          </div>
        )}
      </Section>
    </EditableDraft>
  );
}

export function Decision({ view, onChanged }) {
  const { tx } = useReviewText();
  const { review, abilities, four_eyes: fourEyes } = view;
  const { busy, error, run } = useAction(onChanged);
  const [reason, setReason] = useState('');
  const [amount, setAmount] = useState('');
  const draft = useEditableDraft({ context: 'invoice-review-action#decision', kind: 'invoice', id: view.invoice.id,
    fields: ['reason', 'amount'], values: { reason, amount }, enabled: abilities.decide });
  if (!review) return null;
  const decide = decision => {
    if (draft.blocked || busy || (decision !== 'approve' && !reason.trim())) return;
    run(() => draft.finish(() => reviewApi.decide(view.invoice.id, compact({ decision, reason: reason.trim(),
      amount: decision === 'partial' ? Number(amount) : undefined }))));
  };
  return (
    <Section id="ir-decision" title={tx.decision}>
      {error && <div className="alert-error" role="alert">{error}</div>}
      {fourEyes.required && <p className="ir-note">{fill(tx.fourEyes, { limit: formatMoney(fourEyes.limit) })}</p>}
      {review.decided_by_name && <p>{fill(tx.decidedBy, { name: review.decided_by_name })}
        {review.decision_reason ? ` – ${review.decision_reason}` : ''}</p>}
      {abilities.decide && (
        <EditableDraft draft={draft} values={{ reason, amount }} busy={busy} beforeRestore={() => reviewApi.load(view.invoice.id)}
          onRestore={restored => { setReason(restored.reason || ''); setAmount(restored.amount || ''); }}>
        <div className="ir-check-actions">
          <label className="form-group">{tx.reason}
            <input value={reason} onChange={e => setReason(e.target.value)} aria-describedby="ir-reason-hint" /></label>
          <span id="ir-reason-hint" className="text-muted">{tx.reasonRequired}</span>
          {review.kind === 'invoice' && <label className="form-group">{tx.amount} ({tx.partial})
            <input type="number" step="0.01" min="0.01" value={amount} onChange={e => setAmount(e.target.value)} /></label>}
          <div className="mp-actions ir-wrap">
            <button type="button" className="btn btn-primary btn-sm" disabled={busy} onClick={() => decide('approve')}>{tx.approve}</button>
            {review.kind === 'invoice' && <button type="button" className="btn btn-secondary btn-sm"
              disabled={busy || !amount || !reason.trim()} onClick={() => decide('partial')}>{tx.partial}</button>}
            <button type="button" className="btn btn-secondary btn-sm" disabled={busy || !reason.trim()}
              onClick={() => decide('query')}>{tx.query}</button>
            <button type="button" className="btn btn-danger btn-sm" disabled={busy || !reason.trim()}
              onClick={() => decide('reject')}>{tx.reject}</button>
          </div>
        </div>
        </EditableDraft>
      )}
    </Section>
  );
}

export function Payment({ view, onChanged }) {
  const { tx } = useReviewText();
  const s = view.settlement;
  const { busy, error, run } = useAction(onChanged);
  const [picker, setPicker] = useState(false);
  const [selectedBooking, setSelectedBooking] = useState(null);
  const [choice, setChoice] = useState({ booking_id: '', amount: '' });
  const draft = useEditableDraft({ context: 'invoice-review-action#payment', kind: 'invoice', id: view.invoice.id,
    fields: ['booking_id', 'amount'], values: choice, enabled: view.abilities.pay && s.payment_status !== 'rejected' && view.kind === 'invoice' });
  const invoiceId = view.invoice.id;
  const loadCandidates = useCallback(({ q, skip, limit, option }, options) =>
    reviewApi.paymentCandidates(invoiceId, { q, skip, limit, all_properties: option }, options), [invoiceId]);
  return (
    <Section id="ir-payment" title={tx.settlement}>
      {error && <div className="alert-error" role="alert">{error}</div>}
      <p><Pill tone={PAYMENT_TONE[s.payment_status]}>{tx[`pay_${s.payment_status}`]}</Pill>
        {s.overdue && <> <Pill tone="red">{tx.overdue}</Pill></>}</p>
      <dl className="mp-facts mp-facts-compact">
        <Fact label={tx.payable}>{s.payable === null ? null : formatMoney(s.payable)}</Fact>
        <Fact label={tx.paid}>{formatMoney(s.paid)}</Fact>
        <Fact label={tx.open}>{formatMoney(s.open)}</Fact>
        {s.disputed > 0 && <Fact label={tx.disputed}>{formatMoney(s.disputed)}</Fact>}
        {s.credits > 0 && <Fact label={tx.credits}>{formatMoney(s.credits)}</Fact>}
        {s.written_off > 0 && <Fact label={tx.writtenOff}>{formatMoney(s.written_off)}</Fact>}
        {s.skonto_taken > 0 && <Fact label={tx.skontoTaken}>{formatMoney(s.skonto_taken)}</Fact>}
      </dl>
      <h3 className="mp-subhead">{tx.payments}</h3>
      {view.payments.length === 0 ? <Empty>{tx.noPayments}</Empty> : (
        <ul className="mp-list">{view.payments.map(p => <li key={p.id} className="mp-row">
          <Link className="mp-row-main" to={entityHref('booking', p.booking_id)}>{formatDate(p.booking?.booking_date)} · {p.booking?.payment_text || tx.booking}</Link>
          <span>{formatMoney(p.amount)}</span></li>)}</ul>
      )}
      {view.abilities.pay && s.payment_status !== 'rejected' && view.kind === 'invoice' && (
        <EditableDraft draft={draft} values={choice} busy={busy} beforeRestore={() => reviewApi.load(view.invoice.id)}
          onRestore={restored => { setChoice({ booking_id: restored.booking_id || '', amount: restored.amount || '' }); setSelectedBooking(null); }}>
          <form className="ir-check-actions" onSubmit={event => { event.preventDefault();
            if (!draft.blocked && !busy) run(() => draft.finish(() => reviewApi.addPayment(view.invoice.id, { booking_id: choice.booking_id, amount: Number(choice.amount) }))); }}>
            <div className="form-group"><span>{tx.booking}</span>
              {choice.booking_id && <Link to={entityHref('booking', choice.booking_id)}>
                {selectedBooking ? `${formatDate(selectedBooking.booking_date)} · ${selectedBooking.payment_text || tx.booking}` : tx.openBooking}
              </Link>}
              <button type="button" className="btn btn-secondary btn-sm" disabled={busy} onClick={() => setPicker(true)}>{tx.addPayment}</button>
              {selectedBooking && <small>{tx.free} {formatMoney(selectedBooking.free)}</small>}
            </div>
            <label className="form-group">{tx.amount}
              <input type="number" step="0.01" min="0.01" max={selectedBooking?.free} required value={choice.amount}
                onChange={e => setChoice(c => ({ ...c, amount: e.target.value }))} /></label>
            <div className="mp-actions"><button type="submit" className="btn btn-primary btn-sm" disabled={busy || !choice.booking_id || draft.blocked}>{tx.save}</button></div>
          </form>
          {picker && <PickerDialog title={tx.addPayment} load={loadCandidates} onClose={() => setPicker(false)} extra={tx.otherProperties}
            renderItem={booking => <><strong>{booking.payment_text || tx.booking}</strong>
              <span>{formatDate(booking.booking_date)} · {formatMoney(booking.amount)} · {tx.free} {formatMoney(booking.free)}</span></>}
            onPick={booking => { setSelectedBooking(booking); setChoice({ booking_id: booking.id,
              amount: String(Math.min(booking.free, s.open > 0 ? s.open : booking.free)) }); setPicker(false); }} />}
        </EditableDraft>
      )}
    </Section>
  );
}

export function Dispute({ view, onChanged }) {
  const { tx } = useReviewText();
  const { review } = view;
  const { busy, error, run } = useAction(onChanged);
  const [values, setValues] = useState({ outcome: 'written_off', amount: '', reason: '' });
  const draft = useEditableDraft({ context: 'invoice-review-action#dispute', kind: 'invoice', id: view.invoice.id,
    fields: ['amount', 'reason'], values, enabled: view.abilities.resolve_dispute });
  if (!review?.dispute_status && view.credit_notes.length === 0) return null;
  return (
    <Section id="ir-dispute" title={tx.dispute}>
      {error && <div className="alert-error" role="alert">{error}</div>}
      {review?.dispute_status === 'open' && <p><Pill tone="orange">{tx.disputeOpen}</Pill> {formatMoney(view.settlement.dispute_open)}</p>}
      {review?.dispute_status === 'resolved' && <p><Pill tone="green">{tx[`outcome_${review.dispute_outcome}`]}</Pill>
        {' '}{review.dispute_reason}</p>}
      {view.credit_notes.length > 0 && <>
        <h3 className="mp-subhead">{tx.creditNotes}</h3>
        <ul className="mp-list">{view.credit_notes.map(note => <li key={note.invoice.id} className="mp-row">
          <Link to={`/invoice-review/${encodeURIComponent(note.invoice.id)}`}>{note.invoice.invoice_number || note.invoice.supplier}</Link>
          <span>{formatMoney(note.invoice.gross_amount)} · {tx[`status_${note.status}`]}</span></li>)}</ul>
      </>}
      {view.abilities.resolve_dispute && (
        <EditableDraft draft={draft} values={values} busy={busy} beforeRestore={() => reviewApi.load(view.invoice.id)}
          onRestore={restored => setValues({ amount: restored.amount || '', reason: restored.reason || '', outcome: '' })}>
        <form className="ir-check-actions" onSubmit={event => { event.preventDefault();
          if (!draft.blocked && !busy) run(() => draft.finish(() => reviewApi.resolve(view.invoice.id, compact({ outcome: values.outcome, reason: values.reason,
            amount: values.outcome === 'partial_payment' ? Number(values.amount) : undefined })))); }}>
          <label className="form-group">{tx.outcome}
            <select required value={values.outcome} onChange={e => setValues(v => ({ ...v, outcome: e.target.value }))}>
              <option value="">{tx.none}</option>
              {['credit', 'partial_payment', 'written_off'].map(key => <option key={key} value={key}>{tx[`outcome_${key}`]}</option>)}
            </select></label>
          {values.outcome === 'partial_payment' && <label className="form-group">{tx.amount}
            <input type="number" step="0.01" min="0.01" required value={values.amount}
              onChange={e => setValues(v => ({ ...v, amount: e.target.value }))} /></label>}
          <label className="form-group">{tx.reason}
            <input required value={values.reason} onChange={e => setValues(v => ({ ...v, reason: e.target.value }))} /></label>
          <div className="mp-actions"><button type="submit" className="btn btn-primary btn-sm" disabled={busy}>{tx.resolve}</button></div>
        </form>
        </EditableDraft>
      )}
    </Section>
  );
}

export function Transfer({ view, onChanged }) {
  const { tx } = useReviewText();
  const { busy, error, run } = useAction(onChanged);
  const [options, setOptions] = useState(null);
  const [values, setValues] = useState({ billing_period_id: '', allocation_key_id: '' });
  const place = view.invoice.property_id || view.review?.property_id;
  const eligible = view.review?.recoverable && view.abilities.transfer_cost && view.assignment.kind !== 'service_contract';
  const draft = useEditableDraft({ context: 'invoice-review-action#transfer', kind: 'invoice', id: view.invoice.id,
    fields: ['billing_period_id', 'allocation_key_id'], values, enabled: !view.transfer && eligible });
  if (!view.transfer && !eligible) return null;
  const load = () => Promise.all([api.list('/billing/periods').catch(() => []), api.list('/billing/allocation-keys').catch(() => [])])
    .then(([periods, keys]) => setOptions({
      periods: periods.filter(p => p.property_id === place && ['draft', 'review'].includes(p.status)),
      keys: keys.filter(k => k.property_id === place) }));
  return (
    <Section id="ir-transfer" title={tx.transfer}>
      {error && <div className="alert-error" role="alert">{error}</div>}
      {view.transfer ? <p><Pill tone="green">{fill(tx.transferDone, { period: view.transfer.billing_period_id })}</Pill>
        {' '}{formatMoney(view.transfer.amount)}</p> : <EditableDraft draft={draft} values={values} busy={busy}
          beforeRestore={() => reviewApi.load(view.invoice.id)} onRestore={restored => { setValues({ billing_period_id: restored.billing_period_id || '', allocation_key_id: restored.allocation_key_id || '' }); load(); }}>{options === null
        ? <button type="button" className="btn btn-secondary btn-sm" onClick={load}>{tx.transferAction}</button>
        : <form className="ir-check-actions" onSubmit={event => { event.preventDefault(); if (!draft.blocked && !busy) run(() => draft.finish(() => reviewApi.transfer(view.invoice.id, values))); }}>
          <label className="form-group">{tx.period}
            <select required value={values.billing_period_id} onChange={e => setValues(v => ({ ...v, billing_period_id: e.target.value }))}>
              <option value="">{tx.none}</option>
              {options.periods.map(p => <option key={p.id} value={p.id}>{p.label}</option>)}
            </select></label>
          <label className="form-group">{tx.allocationKey}
            <select required value={values.allocation_key_id} onChange={e => setValues(v => ({ ...v, allocation_key_id: e.target.value }))}>
              <option value="">{tx.none}</option>
              {options.keys.map(k => <option key={k.id} value={k.id}>{k.name}</option>)}
            </select></label>
          <div className="mp-actions"><button type="submit" className="btn btn-primary btn-sm" disabled={busy}>{tx.transferAction}</button></div>
        </form>}</EditableDraft>}
    </Section>
  );
}

export function History({ view }) {
  const { tx } = useReviewText();
  return (
    <Section id="ir-history" title={tx.history}>
      {view.history.length === 0 ? <Empty>{tx.noHistory}</Empty> : (
        <ol className="ir-history" aria-describedby="ir-history-note">
          {view.history.map(event => (
            <li key={event.id}>
              <span className="ir-history-head"><strong>{tx[`act_${event.action}`] || event.action}</strong>
                {event.amount !== null && event.amount !== undefined && ` · ${formatMoney(event.amount)}`}</span>
              <span className="text-muted">{formatDateTime(event.created_at)} · {tx.by} {event.actor_name || '—'}</span>
              {event.reason && <span>{event.reason}</span>}
            </li>
          ))}
        </ol>
      )}
      <p id="ir-history-note" className="text-muted">{tx.immutable}</p>
    </Section>
  );
}
