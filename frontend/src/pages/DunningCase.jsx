import { useCallback, useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useTranslation } from '../i18n';
import { useCanWrite } from '../contexts/AuthContext';
import PdfPreview from '../components/PdfPreview';
import { formatDate, formatDateTime, formatMoney } from '../utils/format';
import { dunningService } from '../features/dunning/dunningApi';
import { dunningText } from '../features/dunning/dunningText';
import { LetterFigures, Problem } from '../features/dunning/DunningTabs';
import '../features/dunning/dunning.css';

const today = () => new Date().toISOString().slice(0, 10);

// Mahnakte of one contract: claims, next step, letters with their originals, blocks, disputes, results, timeline.
export default function DunningCase() {
  const { contractId } = useParams();
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
      .then(data => { setFile(data); setError(null); })
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
        <CaseSection key={c.id} item={c} say={say} canWrite={canWrite} act={act} />
      ))}

      <Blocks file={file} say={say} canWrite={canWrite} act={act} contractId={contractId} />
      <Disputes file={file} say={say} canWrite={canWrite} act={act} contractId={contractId} />
    </div>
  );
}

function CaseSection({ item, say, canWrite, act }) {
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
        {item.status === 'open' && canWrite && <ResultForm caseId={item.id} say={say} act={act} />}
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
            {canWrite && <NoteForm caseId={item.id} say={say} onSaved={() => loadTimeline()} />}
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

function ResultForm({ caseId, say, act }) {
  const submit = event => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    act(() => dunningService.result(caseId, { result: form.get('result'), result_date: form.get('result_date'),
      reference: form.get('reference'), note: form.get('note') || null }));
  };
  return (
    <form className="dn-form" onSubmit={submit} aria-label={say('result')}>
      <label>{say('result')}
        <select name="result" defaultValue="paid">
          {['paid', 'partially_paid', 'written_off', 'handed_over'].map(r => (
            <option key={r} value={r}>{say(`result_${r}`)}</option>))}
        </select>
      </label>
      <label>{say('resultDate')}<input name="result_date" type="date" required defaultValue={today()} /></label>
      <label>{say('resultReference')}<input name="reference" required maxLength={200} /></label>
      <label>{say('note')}<input name="note" maxLength={2000} /></label>
      <button type="submit" className="btn btn-secondary">{say('save')}</button>
    </form>
  );
}

function NoteForm({ caseId, say, onSaved }) {
  const [text, setText] = useState('');
  const save = async event => {
    event.preventDefault();
    await dunningService.addNote(caseId, text);
    setText('');
    onSaved();
  };
  return (
    <form className="dn-form" onSubmit={save}>
      <label>{say('addNote')}<input value={text} onChange={e => setText(e.target.value)} required maxLength={5000} /></label>
      <button type="submit" className="btn btn-sm btn-secondary">{say('save')}</button>
    </form>
  );
}

function Blocks({ file, say, canWrite, act, contractId }) {
  const submit = event => {
    event.preventDefault();
    const target = event.currentTarget;
    const form = new FormData(target);
    act(async () => {
      await dunningService.addBlock(contractId, { reason: form.get('reason'), blocked_until: form.get('blocked_until') });
      target.reset();
    });
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
        <form className="dn-form" onSubmit={submit} aria-label={say('addBlock')}>
          <label>{say('blockReason')}<input name="reason" required maxLength={500} /></label>
          <label>{say('blockedUntil')}<input name="blocked_until" type="date" required /></label>
          <button type="submit" className="btn btn-secondary">{say('addBlock')}</button>
        </form>
      )}
    </section>
  );
}

function Disputes({ file, say, canWrite, act, contractId }) {
  const claims = [...file.claims, ...file.excluded];
  const submit = event => {
    event.preventDefault();
    const target = event.currentTarget;
    const form = new FormData(target);
    act(async () => {
      await dunningService.addDispute(contractId, { claim_key: form.get('claim_key'), reason: form.get('reason') });
      target.reset();
    });
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
        <form className="dn-form" onSubmit={submit} aria-label={say('addDispute')}>
          <label>{say('claim')}
            <select name="claim_key">{claims.map(c => <option key={c.key} value={c.key}>{c.description}</option>)}</select>
          </label>
          <label>{say('reason')}<input name="reason" required maxLength={1000} /></label>
          <button type="submit" className="btn btn-secondary">{say('addDispute')}</button>
        </form>
      )}
    </section>
  );
}
