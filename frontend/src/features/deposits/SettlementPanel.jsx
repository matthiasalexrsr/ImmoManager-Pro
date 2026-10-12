import { useEffect, useId, useRef, useState } from 'react';
import { AlertTriangle, FileText } from 'lucide-react';
import PdfPreview from '../../components/PdfPreview';
import { formatDate, formatMoney } from '../../utils/format';

const KINDS = ['defect', 'other', 'receivable', 'rent_arrears', 'retention'];
const newId = () => crypto.randomUUID();

const rowOf = item => ({
  id: item.id, kind: item.kind, description: item.description, amount: item.amount != null ? String(item.amount) : '',
  reason: item.reason || '', handover_defect_id: item.handover_defect_id || null, receivable_id: item.receivable_id || null,
});

function Outcome({ say, outcome }) {
  if (!outcome) return null;
  const result = Number(outcome.result);
  return <dl className="deposit__outcome">
    <div><dt>{say('principal')}</dt><dd>{formatMoney(outcome.principal)}</dd></div>
    <div><dt>{say('interest')}</dt><dd>{formatMoney(outcome.interest)}</dd></div>
    <div><dt>{say('credit')}</dt><dd>{formatMoney(outcome.credit)}</dd></div>
    <div><dt>{say('claims')}</dt><dd>{formatMoney(outcome.claims)}</dd></div>
    {Number(outcome.retention) > 0 && <div><dt>{say('retention')}</dt><dd>{formatMoney(outcome.retention)}</dd></div>}
    <div className="deposit__outcome-result"><dt>{result > 0 ? say('payout') : result < 0 ? say('remainingClaim') : say('outcome')}</dt>
      <dd>{result === 0 ? say('balanced') : formatMoney(Math.abs(result))}</dd></div>
  </dl>;
}

/** One settlement: a draft with claims, offsets and retention, its check and finalization; or the finalized result. */
export default function SettlementPanel({ say, file, settlement, service, canEdit, onFile, onError, onNotice }) {
  const id = useId();
  const depositId = file.deposit.id;
  const finalized = settlement.finalized;
  const [rows, setRows] = useState(() => settlement.items.map(rowOf));
  const [day, setDay] = useState(settlement.settlement_date);
  const [interestOverride, setInterestOverride] = useState(settlement.interest_amount != null ? String(settlement.interest_amount) : '');
  const [interestReason, setInterestReason] = useState(settlement.interest_reason || '');
  const [notes, setNotes] = useState(settlement.notes || '');
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(null);
  const [preview, setPreview] = useState(null);
  const [pdf, setPdf] = useState(null);
  const [confirmed, setConfirmed] = useState(false);
  const [account, setAccount] = useState(file.deposit.account_id || '');
  const [pending, setPending] = useState(null);
  const [unknown, setUnknown] = useState(false);
  const mounted = useRef(true);
  const [seen, setSeen] = useState(settlement.revision);
  if (seen !== settlement.revision) {      // a saved (or newly loaded) state replaces the form
    setSeen(settlement.revision);
    setRows(settlement.items.map(rowOf));
    setDay(settlement.settlement_date);
    setDirty(false);
  }

  useEffect(() => () => { mounted.current = false; }, []);
  useEffect(() => () => { if (pdf) URL.revokeObjectURL(pdf); }, [pdf]);

  const change = updater => { setRows(updater); setDirty(true); setPreview(null); setConfirmed(false); };
  const update = (index, name, value) => change(current => current.map((row, i) => (i === index ? { ...row, [name]: value } : row)));
  const add = (row) => change(current => [...current, { id: newId(), kind: 'other', description: '', amount: '', reason: '',
    handover_defect_id: null, receivable_id: null, ...row }]);

  const run = async (name, work) => {
    setBusy(name);
    onError(null);
    try {
      return await work();
    } catch (failure) {
      onError(failure?.message || say('loadFailed'));
      return null;
    } finally {
      if (mounted.current) setBusy(null);
    }
  };

  const save = async () => {
    const payload = {
      base_revision: settlement.revision, settlement_date: day,
      interest_amount: interestOverride === '' ? null : Number(interestOverride),
      interest_reason: interestReason.trim() || null, notes: notes.trim() || null,
      items: rows.map(row => ({ id: row.id, kind: row.kind, description: row.description.trim(), amount: Number(row.amount),
        reason: row.reason.trim() || null, handover_defect_id: row.kind === 'defect' ? row.handover_defect_id : null,
        receivable_id: row.kind === 'receivable' ? row.receivable_id : null })),
    };
    const next = await run('save', () => service.saveSettlement(depositId, settlement.id, payload));
    if (next) { setDirty(false); onFile(next); onNotice(say('savedNotice')); }
    return next;
  };

  const check = async () => {
    if (dirty && !await save()) return;
    const value = await run('check', () => service.preview(depositId, settlement.id));
    if (value) { setPreview(value); setConfirmed(false); }
  };

  const showPdf = async () => {
    const url = await run('pdf', () => service.previewPdfUrl(depositId, settlement.id, preview));
    if (url && mounted.current) setPdf(url); else if (url) URL.revokeObjectURL(url);
  };

  const finalize = async () => {
    const command = pending || { idempotencyKey: `deposit:${newId()}`, reviewHash: preview.review_hash,
      payoutAccountId: account || null };
    setPending(command);
    setBusy('finalize');
    onError(null);
    try {
      const next = await service.finalize(depositId, settlement.id, command);
      if (!mounted.current) return;
      setPending(null);
      setUnknown(false);
      setPreview(null);
      onFile(next);
      onNotice(say('finalized'));
    } catch (failure) {
      if (!mounted.current) return;
      if (failure?.isNetwork || failure?.statusCode >= 500) {
        setUnknown(true);
      } else {
        setPending(null);
        onError(failure?.message || say('loadFailed'));
      }
    } finally {
      if (mounted.current) setBusy(null);
    }
  };

  const openOriginal = async () => {
    const url = await run('original', () => service.originalUrl(depositId, settlement.id, settlement.original?.pdf_sha256));
    if (url && mounted.current) setPdf(url); else if (url) URL.revokeObjectURL(url);
  };

  const remove = async () => {
    const next = await run('delete', () => service.deleteSettlement(depositId, settlement.id));
    if (next) onFile(next);
  };

  const title = say(`kind_${settlement.kind}`);
  if (finalized) {
    return <section className="deposit__section" aria-label={title}>
      <h3>{title} · {formatDate(settlement.settlement_date)}</h3>
      <Outcome say={say} outcome={settlement.outcome} />
      {settlement.original && <div className="deposit__original">
        <FileText size={18} aria-hidden="true" />
        <span>{say('original')} · SHA-256 <code>{settlement.original.pdf_sha256.slice(0, 16)}…</code></span>
        <button type="button" className="btn btn-secondary btn-sm" disabled={busy === 'original'}
          onClick={() => void openOriginal()}>{say('openOriginal')}</button>
      </div>}
      {pdf && <div className="deposit__pdf"><PdfPreview url={pdf} title={title} /></div>}
    </section>;
  }

  const suggestions = settlement.suggestions || {};
  const ready = preview?.ready && !dirty;
  const editable = canEdit && !busy;
  return <section className="deposit__section" aria-label={title}>
    <div className="deposit__section-head">
      <h3>{title}</h3>
      {dirty && <span className="deposit__badge">{say('dirty')}</span>}
    </div>
    <div className="deposit__grid">
      <label htmlFor={`${id}-day`}>{say('settlementDate')}
        <input id={`${id}-day`} type="date" value={day} disabled={!canEdit}
          onChange={event => { setDay(event.target.value); setDirty(true); setPreview(null); }} /></label>
      <label htmlFor={`${id}-interest`}>{say('interestOverride')}
        <input id={`${id}-interest`} type="number" step="0.01" min="0" value={interestOverride} disabled={!canEdit}
          placeholder={say('computedInterest', { amount: formatMoney(settlement.interest?.computed) })}
          onChange={event => { setInterestOverride(event.target.value); setDirty(true); setPreview(null); }} /></label>
      {interestOverride !== '' && <label htmlFor={`${id}-ireason`}>{say('interestReason')}
        <input id={`${id}-ireason`} value={interestReason} disabled={!canEdit}
          onChange={event => { setInterestReason(event.target.value); setDirty(true); }} /></label>}
    </div>

    {canEdit && <div className="deposit__suggestions" aria-label={say('suggestions')}>
      <h4>{say('suggestions')}</h4>
      {(suggestions.defects || []).length > 0 && <ul>
        {suggestions.defects.map(defect => {
          const taken = rows.some(row => row.handover_defect_id === defect.id);
          return <li key={defect.id}><span>{defect.room ? `${defect.room}: ` : ''}{defect.description}</span>
            <button type="button" className="btn btn-secondary btn-sm" disabled={taken}
              onClick={() => add({ kind: 'defect', description: defect.description, handover_defect_id: defect.id })}>
              {taken ? say('taken') : say('take')}</button></li>;
        })}
      </ul>}
      {(suggestions.receivables || []).length > 0 && <ul>
        {suggestions.receivables.map(receivable => {
          const taken = rows.some(row => row.receivable_id === receivable.id);
          return <li key={receivable.id}><span>{receivable.description || say('item_receivable')} · {formatDate(receivable.due_date)} · {formatMoney(receivable.open)}</span>
            <button type="button" className="btn btn-secondary btn-sm" disabled={taken}
              onClick={() => add({ kind: 'receivable', description: receivable.description || say('item_receivable'),
                amount: String(receivable.open), receivable_id: receivable.id })}>{taken ? say('taken') : say('take')}</button></li>;
        })}
      </ul>}
      {suggestions.rent_arrears > 0 && <p className="deposit__suggestion-line">
        <span>{say('arrearsSuggestion', { amount: formatMoney(suggestions.rent_arrears) })}</span>
        <button type="button" className="btn btn-secondary btn-sm" disabled={rows.some(row => row.kind === 'rent_arrears')}
          onClick={() => add({ kind: 'rent_arrears', description: say('item_rent_arrears'), amount: String(suggestions.rent_arrears) })}>
          {say('take')}</button></p>}
      {settlement.kind === 'final' && <p className="deposit__muted">{suggestions.retention_allowed
        ? say('retentionAllowed', { amount: formatMoney(suggestions.monthly_advances) }) : say('retentionNotAllowed')}</p>}
    </div>}

    <h4>{say('items')}</h4>
    <div className="deposit__items">
      {rows.map((row, index) => <fieldset key={row.id} className="deposit__item">
        <legend className="deposit__sr">{`${index + 1}. ${say(`item_${row.kind}`)}`}</legend>
        <label htmlFor={`${id}-${row.id}-kind`}>{say('itemKind')}
          <select id={`${id}-${row.id}-kind`} value={row.kind} disabled={!canEdit || Boolean(row.handover_defect_id || row.receivable_id)}
            onChange={event => update(index, 'kind', event.target.value)}>
            {KINDS.filter(kind => kind !== 'receivable' || row.receivable_id)
              .filter(kind => kind !== 'retention' || settlement.kind === 'final')
              .map(kind => <option key={kind} value={kind}>{say(`item_${kind}`)}</option>)}
          </select></label>
        <label htmlFor={`${id}-${row.id}-desc`}>{say('description')}
          <input id={`${id}-${row.id}-desc`} value={row.description} disabled={!canEdit} maxLength={1000}
            onChange={event => update(index, 'description', event.target.value)} /></label>
        <label htmlFor={`${id}-${row.id}-amount`}>{say('amount')}
          <input id={`${id}-${row.id}-amount`} type="number" inputMode="decimal" min="0.01" step="0.01" value={row.amount}
            disabled={!canEdit} onChange={event => update(index, 'amount', event.target.value)} /></label>
        <label htmlFor={`${id}-${row.id}-reason`}>{say('reason')}
          <input id={`${id}-${row.id}-reason`} value={row.reason} disabled={!canEdit} maxLength={2000}
            onChange={event => update(index, 'reason', event.target.value)} /></label>
        {canEdit && <button type="button" className="btn btn-secondary btn-sm deposit__remove"
          onClick={() => change(current => current.filter((_, i) => i !== index))}>{say('remove')}</button>}
      </fieldset>)}
    </div>
    {canEdit && <button type="button" className="btn btn-secondary btn-sm" onClick={() => add({})}>{say('addItem')}</button>}
    <label className="deposit__wide" htmlFor={`${id}-notes`}>{say('notes')}
      <textarea id={`${id}-notes`} rows={2} value={notes} disabled={!canEdit}
        onChange={event => { setNotes(event.target.value); setDirty(true); }} /></label>

    <Outcome say={say} outcome={preview?.outcome || settlement.outcome} />
    {(preview?.problems || settlement.problems || []).length > 0 && <ul className="deposit__problems" aria-label={say('problems')}>
      {(preview?.problems || settlement.problems).map(problem => <li key={problem.code + problem.message}
        className={problem.blocking ? 'deposit__problem--blocking' : undefined}>
        <AlertTriangle size={15} aria-hidden="true" /><span>{problem.message}{problem.blocking ? ` (${say('blocking')})` : ''}</span></li>)}
    </ul>}
    {unknown && <div className="deposit__notice deposit__notice--warning" role="alert">{say('unknownResult')}
      <button type="button" className="btn btn-primary btn-sm" disabled={busy === 'finalize'} onClick={() => void finalize()}>
        {say('retryExact')}</button></div>}
    {canEdit && <div className="deposit__actions">
      <button type="button" className="btn btn-secondary" disabled={!editable} onClick={() => void remove()}>{say('deleteDraft')}</button>
      <button type="button" className="btn btn-secondary" disabled={!editable || !dirty} onClick={() => void save()}>{say('saveSettlement')}</button>
      <button type="button" className="btn btn-primary" disabled={!editable} onClick={() => void check()}>
        {preview ? say('checkAgain') : say('check')}</button>
    </div>}
    {ready && <div className="deposit__finish">
      <button type="button" className="btn btn-secondary btn-sm" disabled={Boolean(busy)} onClick={() => void showPdf()}>{say('previewPdf')}</button>
      {pdf && <div className="deposit__pdf"><PdfPreview url={pdf} title={title} /></div>}
      {canEdit && <>
        <label htmlFor={`${id}-account`}>{say('payoutAccount')}
          <select id={`${id}-account`} value={account} onChange={event => setAccount(event.target.value)}>
            <option value="">{say('noAccount')}</option>
            {file.accounts.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select></label>
        <label className="deposit__check" htmlFor={`${id}-confirm`}>
          <input id={`${id}-confirm`} type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />
          <span>{say('confirm')}</span></label>
        <button type="button" className="btn btn-primary" disabled={!confirmed || Boolean(busy)} onClick={() => void finalize()}>
          {busy === 'finalize' ? say('finalizing') : say('finalize')}</button>
      </>}
    </div>}
  </section>;
}
