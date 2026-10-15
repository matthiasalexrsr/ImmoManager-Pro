import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useTranslation } from '../i18n';
import { useCanWrite } from '../contexts/AuthContext';
import PdfPreview from '../components/PdfPreview';
import { formatDate, formatDateTime, formatMoney } from '../utils/format';
import { dunningService } from '../features/dunning/dunningApi';
import { dunningText } from '../features/dunning/dunningText';
import { LetterFigures, Problem } from '../features/dunning/DunningTabs';
import useEditableDraft from '../features/workCenter/useEditableDraft';
import EditableDraft from '../features/workCenter/EditableDraft';
import '../features/dunning/dunning.css';

const today = () => new Date().toISOString().slice(0, 10);

// Mahnakte of one contract: claims, next step, letters with their originals, blocks, disputes, results, timeline.
export default function DunningCase() {
  const { contractId } = useParams();
  return <DunningCaseSession key={contractId} contractId={contractId} />;
}

function DunningCaseSession({ contractId }) {
  const { locale } = useTranslation();
  const say = useCallback((key, params) => dunningText(locale, key, params), [locale]);
  const canWrite = useCanWrite('/dunning');
  const [file, setFile] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  const reload = () => setRevision(v => v + 1);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    dunningService.contractFile(contractId, { signal: controller.signal })
      .then(data => { if (!controller.signal.aborted) { setFile(data); setError(null); } })
      .catch(e => { if (e.name !== 'AbortError') setError(e.message || say('loadFailed')); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [contractId, revision, say]);

  const act = async (operation) => {
    setError(null);
    try { await operation(); reload(); } catch (e) { setError(e.message); }
  };

  if (loading && !file) return <div className="page" role="status">{say('loading')}</div>;
  if (!file) return <div className="page"><Problem error={error} onRetry={reload} say={say} /></div>;
  const { contract, next } = file;
  const createLetter = () => act(async () => {
    const scope = { contract_id: contractId, as_of: file.as_of };
    const preview = await dunningService.preview(scope);
    await dunningService.createRun(scope, preview.preview_hash);
  });

  return (
    <div className="page dunning dunning-case">
      <p><Link to="/dunning">← {say('back')}</Link></p>
      <h1 className="page-title">{say('contractFile')} · {say('contract')} {contract.number}</h1>
      <p className="dn-muted">{contract.tenant_name} · {contract.property} · {contract.unit}</p>
      <Problem error={error} say={say} />
      <div className="dn-figures">
        <div className="dn-figure"><span className="dn-muted">{say('principal')}</span>
          <strong>{formatMoney(file.totals.overdue_principal)}</strong></div>
        <div className="dn-figure"><span className="dn-muted">{say('earlier')}</span>
          <strong>{formatMoney(file.totals.open_charges)}</strong></div>
        <div className="dn-figure"><span className="dn-muted">{say('unapplied')}</span>
          <strong>{formatMoney(file.totals.unapplied_payments)}</strong></div>
      </div>

      <section className="dn-section panel" aria-labelledby="dn-next">
        <h2 id="dn-next" className="panel-header">{say('nextStep')}</h2>
        <div className="panel-body">
          <p><strong>{say(`status_${next.status}`)}</strong>{next.next_stage_label && ` · ${next.next_stage_label}`}
            {next.reason && <span className="dn-muted"> – {next.reason}</span>}</p>
          {next.letter && <p><LetterFigures letter={next.letter} say={say} /></p>}
          {next.letter?.interest_note && <p className="dn-muted">{next.letter.interest_note}</p>}
          {next.status === 'due' && canWrite && (
            <button type="button" className="btn btn-primary" onClick={createLetter}>{say('runContract')}</button>)}
        </div>
      </section>

      <section className="dn-section" aria-labelledby="dn-claims">
        <h2 id="dn-claims">{say('claims')}</h2>
        <div className="dn-table-wrap">
          <table className="dn-table">
            <thead><tr><th>{say('claim')}</th><th>{say('dueDate')}</th><th className="num">{say('amount')}</th>
              <th className="num">{say('paid')}</th><th className="num">{say('outstanding')}</th></tr></thead>
            <tbody>
              {file.claims.map(c => (
                <tr key={c.key}><td>{c.description}</td><td>{formatDate(c.due_date)}</td>
                  <td className="num">{formatMoney(c.amount)}</td><td className="num">{formatMoney(c.paid)}</td>
                  <td className="num">{formatMoney(c.outstanding)}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
        {[...file.excluded, ...file.manual].length > 0 && (
          <>
            <h3>{say('excluded')}</h3>
            <ul className="dn-list">
              {[...file.excluded, ...file.manual].map(x => (
                <li key={x.key} className="dn-card">{x.description} · {formatMoney(x.amount)}
                  <div className="dn-muted">{say('reason')}: {x.reason_label}</div></li>
              ))}
            </ul>
          </>
        )}
      </section>

      {file.cases.map(c => (
        <CaseSection key={c.id} item={c} say={say} canWrite={canWrite} act={act} contractId={contractId} />
      ))}

      <Blocks file={file} say={say} canWrite={canWrite} act={act} contractId={contractId} />
      <Disputes file={file} say={say} canWrite={canWrite} act={act} contractId={contractId} />
    </div>
  );
}

function CaseSection({ item, say, canWrite, act, contractId }) {
  const [timeline, setTimeline] = useState(null);
  const [pdf, setPdf] = useState(null);
  const loadTimeline = async (more = false) => {
    const page = await dunningService.timeline(item.id, more ? timeline.next_after : undefined);
    setTimeline(current => (more ? { ...page, items: [...current.items, ...page.items] } : page));
  };
  useEffect(() => () => { if (pdf) URL.revokeObjectURL(pdf.url); }, [pdf]);
  const showPdf = async letter => {
    const blob = await dunningService.letterPdf(letter.id);
    setPdf({ id: letter.id, url: URL.createObjectURL(blob), title: `${letter.stage_label} ${letter.reference}` });
  };
  return (
    <section className="dn-section panel" aria-label={`${say('reference')} ${item.reference}`}>
      <h2 className="panel-header">{item.reference} · {item.status === 'open' ? item.stage_label
        : `${say('closed')}: ${item.result_label}`}</h2>
      <div className="panel-body">
        <p className="dn-muted">{say('outstanding')}: {formatMoney(item.outstanding)}
          {item.result_reference && ` · ${item.result_reference} (${formatDate(item.result_date)})`}</p>
        <ul className="dn-list" aria-label={say('letters')}>
          {item.letters.map(letter => (
            <LetterCard key={letter.id} letter={letter} say={say} canWrite={canWrite} act={act}
              onShow={() => act(() => showPdf(letter))} />
          ))}
        </ul>
        {pdf && (
          <div className="dn-pdf">
            <button type="button" className="btn btn-sm btn-secondary" onClick={() => setPdf(null)}>{say('closePdf')}</button>
            <PdfPreview url={pdf.url} title={pdf.title} />
          </div>
        )}
        {item.status === 'open' && canWrite && <ResultForm caseId={item.id} say={say} act={act} contractId={contractId} />}
        <div className="dn-actions">
          <button type="button" className="btn btn-sm btn-secondary" onClick={() => act(() => loadTimeline())}>
            {say('timeline')}</button>
        </div>
        {timeline && (
          <div className="dn-section">
            <h3>{say('timeline')} <span className="dn-muted">({say('of', { shown: timeline.items.length, total: timeline.total })})</span></h3>
            {timeline.items.length === 0 ? <p>{say('noEvents')}</p> : (
              <ol className="dn-timeline">
                {timeline.items.map(event => (
                  <li key={event.id}><span className="dn-muted">{formatDateTime(event.at)}</span> {event.summary}
                    {event.reply && <pre>{event.reply.body}</pre>}</li>
                ))}
              </ol>
            )}
            {timeline.has_more && <button type="button" className="btn btn-sm btn-secondary"
              onClick={() => loadTimeline(true)}>{say('more')}</button>}
            {canWrite && <NoteForm caseId={item.id} say={say} onSaved={() => loadTimeline()} contractId={contractId} />}
          </div>
        )}
      </div>
    </section>
  );
}

function LetterCard({ letter, say, canWrite, act, onShow }) {
  const [confirmed, setConfirmed] = useState(false);
  const [channel, setChannel] = useState('letter');
  const finalize = () => act(async () => {
    const current = await dunningService.letter(letter.id);
    await dunningService.finalize(letter.id, current.draft_hash, channel);
  });
  const cancel = () => {
    const reason = window.prompt(say('cancelReason'));
    if (reason) act(() => dunningService.cancel(letter.id, reason));
  };
  return (
    <li className="dn-card">
      <div className="dn-card-head"><strong>{letter.stage_label} · {formatDate(letter.letter_date)}</strong>
        <span>{say(letter.status)}{letter.outbox ? ` · ${say(`outbox_${letter.outbox.status}`)}` : ''}</span></div>
      <LetterFigures letter={{ ...letter, earlier_charges_total: letter.earlier_charges }} say={say} />
      <div className="dn-muted">{say('dueDate')}: {formatDate(letter.payment_deadline)}</div>
      <div className="dn-actions">
        {letter.status !== 'cancelled' && <button type="button" className="btn btn-sm btn-secondary" onClick={onShow}>
          {say('viewPdf')}</button>}
        {letter.status === 'draft' && canWrite && (
          <>
            <button type="button" className="btn btn-sm btn-secondary"
              onClick={() => act(() => dunningService.refresh(letter.id))}>{say('refresh')}</button>
            <button type="button" className="btn btn-sm btn-secondary" onClick={cancel}>{say('cancel')}</button>
          </>
        )}
      </div>
      {letter.status === 'draft' && canWrite && (
        <div className="dn-form">
          <label>{say('channel')}
            <select value={channel} onChange={e => setChannel(e.target.value)}>
              <option value="letter">{say('channel_letter')}</option>
              <option value="email">{say('channel_email')}</option>
            </select>
          </label>
          <label className="dn-check"><input type="checkbox" checked={confirmed}
            onChange={e => setConfirmed(e.target.checked)} />{say('confirmFinalize')}</label>
          <button type="button" className="btn btn-primary" disabled={!confirmed} onClick={finalize}>
            {say('finalize')}</button>
        </div>
      )}
    </li>
  );
}

function ResultForm({ caseId, say, act, contractId }) {
  const [values, setValues] = useState({ result: 'paid', result_date: today(), reference: '', note: '' });
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);
  const draft = useEditableDraft({ context: `dunning-action#result-${caseId}`, kind: 'contract', id: contractId,
    fields: ['result_date', 'reference', 'note'], values });
  const submit = event => {
    event.preventDefault();
    if (lock.current || draft.blocked) return;
    lock.current = true; setBusy(true);
    act(() => draft.finish(() => dunningService.result(caseId, { ...values, note: values.note || null })))
      .finally(() => { lock.current = false; setBusy(false); });
  };
  const set = (key, value) => setValues(current => ({ ...current, [key]: value }));
  return (
    <EditableDraft draft={draft} values={values} busy={busy} beforeRestore={() => dunningService.contractFile(contractId)}
      onRestore={restored => setValues({ result: '', result_date: restored.result_date || today(), reference: restored.reference || '', note: restored.note || '' })}>
    <form className="dn-form" onSubmit={submit} aria-label={say('result')}>
      <label>{say('result')}
        <select name="result" required value={values.result} onChange={event => set('result', event.target.value)}>
          <option value="">—</option>
          {['paid', 'partially_paid', 'written_off', 'handed_over'].map(r => (
            <option key={r} value={r}>{say(`result_${r}`)}</option>))}
        </select>
      </label>
      <label>{say('resultDate')}<input name="result_date" type="date" required value={values.result_date} onChange={event => set('result_date', event.target.value)} /></label>
      <label>{say('resultReference')}<input name="reference" required maxLength={200} value={values.reference} onChange={event => set('reference', event.target.value)} /></label>
      <label>{say('note')}<input name="note" maxLength={2000} value={values.note} onChange={event => set('note', event.target.value)} /></label>
      <button type="submit" className="btn btn-secondary">{say('save')}</button>
    </form>
    </EditableDraft>
  );
}

function NoteForm({ caseId, say, onSaved, contractId }) {
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const lock = useRef(false);
  const draft = useEditableDraft({ context: `dunning-action#note-${caseId}`, kind: 'contract', id: contractId, fields: ['text'], values: { text } });
  const save = async event => {
    event.preventDefault();
    if (lock.current || draft.blocked) return;
    lock.current = true; setBusy(true); setError(null);
    try { await draft.finish(() => dunningService.addNote(caseId, text)); draft.resetSnapshot({ text: '' }); setText(''); await onSaved(); }
    catch (failure) { setError(failure.message); }
    finally { lock.current = false; setBusy(false); }
  };
  return (
    <EditableDraft draft={draft} values={{ text }} busy={busy} beforeRestore={() => dunningService.contractFile(contractId)} onRestore={restored => setText(restored.text || '')}>
    <form className="dn-form" onSubmit={save}>
      {error && <p role="alert">{error}</p>}
      <label>{say('addNote')}<input value={text} onChange={e => setText(e.target.value)} required maxLength={5000} /></label>
      <button type="submit" className="btn btn-sm btn-secondary">{say('save')}</button>
    </form>
    </EditableDraft>
  );
}

function Blocks({ file, say, canWrite, act, contractId }) {
  const [values, setValues] = useState({ reason: '', blocked_until: '' });
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);
  const draft = useEditableDraft({ context: 'dunning-action#block', kind: 'contract', id: contractId,
    fields: ['reason', 'blocked_until'], values, enabled: canWrite });
  const submit = event => {
    event.preventDefault();
    if (lock.current || draft.blocked) return;
    lock.current = true; setBusy(true);
    act(async () => {
      await draft.finish(() => dunningService.addBlock(contractId, values));
      const empty = { reason: '', blocked_until: '' }; draft.resetSnapshot(empty); setValues(empty);
    }).finally(() => { lock.current = false; setBusy(false); });
  };
  return (
    <section className="dn-section" aria-labelledby="dn-blocks">
      <h2 id="dn-blocks">{say('blocks')}</h2>
      {file.blocks.length === 0 ? <p className="dn-muted">{say('noBlocks')}</p> : (
        <ul className="dn-list">
          {file.blocks.map(b => (
            <li key={b.id} className="dn-card dn-card-head">
              <span>{b.reason} · {say('blockedUntil')} {formatDate(b.blocked_until)} ·{' '}
                {b.lifted_at ? say('lifted') : b.active ? say('active') : '—'}</span>
              {canWrite && !b.lifted_at && <button type="button" className="btn btn-sm btn-secondary"
                onClick={() => act(() => dunningService.liftBlock(b.id))}>{say('lift')}</button>}
            </li>
          ))}
        </ul>
      )}
      {canWrite && (
        <EditableDraft draft={draft} values={values} busy={busy} beforeRestore={() => dunningService.contractFile(contractId)}
          onRestore={restored => setValues({ reason: restored.reason || '', blocked_until: restored.blocked_until || '' })}>
        <form className="dn-form" onSubmit={submit} aria-label={say('addBlock')}>
          <label>{say('blockReason')}<input name="reason" required maxLength={500} value={values.reason} onChange={event => setValues(current => ({ ...current, reason: event.target.value }))} /></label>
          <label>{say('blockedUntil')}<input name="blocked_until" type="date" required value={values.blocked_until} onChange={event => setValues(current => ({ ...current, blocked_until: event.target.value }))} /></label>
          <button type="submit" className="btn btn-secondary">{say('addBlock')}</button>
        </form>
        </EditableDraft>
      )}
    </section>
  );
}

function Disputes({ file, say, canWrite, act, contractId }) {
  const claims = [...file.claims, ...file.excluded];
  const [values, setValues] = useState({ claim_key: claims[0]?.key || '', reason: '' });
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);
  const draft = useEditableDraft({ context: 'dunning-action#dispute', kind: 'contract', id: contractId,
    fields: ['claim_key', 'reason'], values, enabled: canWrite && claims.length > 0 });
  const submit = event => {
    event.preventDefault();
    if (lock.current || draft.blocked) return;
    lock.current = true; setBusy(true);
    act(async () => {
      await draft.finish(() => dunningService.addDispute(contractId, values));
      const empty = { claim_key: claims[0]?.key || '', reason: '' }; draft.resetSnapshot(empty); setValues(empty);
    }).finally(() => { lock.current = false; setBusy(false); });
  };
  return (
    <section className="dn-section" aria-labelledby="dn-disputes">
      <h2 id="dn-disputes">{say('disputes')}</h2>
      {file.disputes.length === 0 ? <p className="dn-muted">{say('noDisputes')}</p> : (
        <ul className="dn-list">
          {file.disputes.map(d => (
            <li key={d.id} className="dn-card">
              <div className="dn-card-head"><span>{claims.find(c => c.key === d.claim_key)?.description || d.claim_key}</span>
                <span>{say(`dispute_${d.status}`)}</span></div>
              <div className="dn-muted">{d.reason}</div>
              {canWrite && d.status === 'open' && (
                <div className="dn-actions">
                  {['upheld', 'rejected'].map(decision => (
                    <button key={decision} type="button" className="btn btn-sm btn-secondary"
                      onClick={() => act(() => dunningService.decideDispute(d.id, decision))}>{say(`decide_${decision}`)}</button>
                  ))}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      {canWrite && claims.length > 0 && (
        <EditableDraft draft={draft} values={values} busy={busy} beforeRestore={() => dunningService.contractFile(contractId)}
          onRestore={restored => setValues({ claim_key: claims.some(claim => claim.key === restored.claim_key) ? restored.claim_key : '', reason: restored.reason || '' })}>
        <form className="dn-form" onSubmit={submit} aria-label={say('addDispute')}>
          <label>{say('claim')}
            <select name="claim_key" required value={values.claim_key} onChange={event => setValues(current => ({ ...current, claim_key: event.target.value }))}><option value="">—</option>{claims.map(c => <option key={c.key} value={c.key}>{c.description}</option>)}</select>
          </label>
          <label>{say('reason')}<input name="reason" required maxLength={1000} value={values.reason} onChange={event => setValues(current => ({ ...current, reason: event.target.value }))} /></label>
          <button type="submit" className="btn btn-secondary">{say('addDispute')}</button>
        </form>
        </EditableDraft>
      )}
    </section>
  );
}
