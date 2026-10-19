import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { formatDate, formatMoney } from '../../utils/format';
import { dunningService, saveBlob } from './dunningApi';

const today = () => new Date().toISOString().slice(0, 10);

export function Problem({ error, onRetry, say }) {
  if (!error) return null;
  return (
    <div role="alert" className="alert alert-error">{error}
      {onRetry && <button type="button" className="btn btn-sm btn-secondary" onClick={onRetry}>{say('retry')}</button>}
    </div>
  );
}

function useLoad(load, deps) {
  const [state, setState] = useState({ data: null, error: null, loading: true });
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let active = true;
    setState(s => ({ ...s, loading: true, error: null }));
    load().then(data => { if (active) setState({ data, error: null, loading: false }); })
      .catch(error => { if (active) setState({ data: null, error: error.message || String(error), loading: false }); });
    return () => { active = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, revision]);
  return [state, () => setRevision(v => v + 1)];
}

export function CasesTab({ say }) {
  const [status, setStatus] = useState('open');
  const [items, setItems] = useState([]);
  const [page, reload] = useLoad(() => dunningService.overview({ status, limit: 50 }), [status]);
  useEffect(() => { if (page.data) setItems(page.data.items); }, [page.data]);
  const more = async () => {
    const next = await dunningService.overview({ status, limit: 50, offset: items.length });
    setItems(current => [...current, ...next.items]);
  };
  const counts = page.data?.counts;
  return (
    <div>
      {counts && (
        <div className="dn-figures">
          {[['openCases', counts.open_cases], ['drafts', counts.drafts], ['outboxReady', counts.outbox_ready],
            ['repliesReview', counts.replies_review], ['activeBlocks', counts.active_blocks]].map(([key, value]) => (
            <div className="dn-figure" key={key}><span className="dn-muted">{say(key)}</span><strong>{value}</strong></div>
          ))}
        </div>
      )}
      <div className="dn-form">
        <label>{say('status')}
          <select value={status} onChange={e => setStatus(e.target.value)}>
            {['open', 'closed', 'all'].map(s => <option key={s} value={s}>{say(s)}</option>)}
          </select>
        </label>
      </div>
      <Problem error={page.error} onRetry={reload} say={say} />
      {page.loading && !items.length ? <p role="status">{say('loading')}</p> : items.length === 0 ? (
        <p className="empty-text">{say('noCases')}</p>
      ) : (
        <ul className="dn-list" aria-label={say('tabCases')}>
          {items.map(row => (
            <li key={row.id} className="dn-card">
              <div className="dn-card-head">
                <strong>{row.reference}</strong>
                <span>{row.status === 'open' ? row.stage_label : `${say('closed')}: ${row.result_label}`}</span>
              </div>
              <div>{say('contract')} {row.contract_number} · {row.tenant_name || '—'} · {row.property_name || '—'}</div>
              <div className="dn-muted">
                {say('outstanding')}: {formatMoney(row.outstanding)}
                {row.next_status && ` · ${say('next')}: ${say(`status_${row.next_status}`)}`}
                {row.due_on && row.next_status === 'not_yet' && ` (${formatDate(row.due_on)})`}
                {row.drafts > 0 && ` · ${say('drafts')}: ${row.drafts}`}
              </div>
              <div className="dn-actions">
                <Link className="btn btn-sm btn-secondary" to={`/dunning/contracts/${encodeURIComponent(row.contract_id)}`}>
                  {say('openFile')}</Link>
              </div>
            </li>
          ))}
        </ul>
      )}
      {page.data && items.length < page.data.total && (
        <p><button type="button" className="btn btn-sm btn-secondary" onClick={more}>{say('more')}</button>{' '}
          <span className="dn-muted">{say('of', { shown: items.length, total: page.data.total })}</span></p>
      )}
    </div>
  );
}

export function LetterFigures({ letter, say }) {
  return (
    <span className="dn-muted">
      {say('principal')} {formatMoney(letter.principal)}
      {letter.earlier_charges_total ? ` · ${say('earlier')} ${formatMoney(letter.earlier_charges_total)}` : ''}
      {` · ${say('fee')} ${formatMoney(letter.fee)} · ${say('interest')} ${formatMoney(letter.interest)} · `}
      <strong>{say('total')} {formatMoney(letter.total)}</strong>
    </span>
  );
}

export function RunTab({ say, canWrite, portfolios }) {
  const [scope, setScope] = useState({ portfolio_id: '', as_of: today(), letter_date: '' });
  const [preview, setPreview] = useState(null);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!scope.portfolio_id && portfolios.length) setScope(s => ({ ...s, portfolio_id: portfolios[0].id }));
  }, [portfolios, scope.portfolio_id]);
  const body = () => ({ portfolio_id: scope.portfolio_id, as_of: scope.as_of || null,
    letter_date: scope.letter_date || null });
  const calculate = async () => {
    setBusy(true); setError(null); setNotice(null);
    try { setPreview(await dunningService.preview(body())); } catch (e) { setError(e.message); } finally { setBusy(false); }
  };
  const create = async () => {
    setBusy(true); setError(null);
    try {
      const run = await dunningService.createRun(body(), preview.preview_hash);
      setNotice(say('runCreated', { count: run.letters.length }));
      setPreview(null);
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  };
  return (
    <div>
      <p className="dn-muted">{say('previewHint')}</p>
      <div className="dn-form">
        <label>{say('portfolio')}
          <select value={scope.portfolio_id} onChange={e => setScope(s => ({ ...s, portfolio_id: e.target.value }))}>
            {portfolios.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </label>
        <label>{say('asOf')}<input type="date" value={scope.as_of}
          onChange={e => setScope(s => ({ ...s, as_of: e.target.value }))} /></label>
        <label>{say('letterDate')}<input type="date" value={scope.letter_date}
          onChange={e => setScope(s => ({ ...s, letter_date: e.target.value }))} /></label>
        <button type="button" className="btn btn-primary" disabled={!canWrite || busy || !scope.portfolio_id}
          onClick={calculate}>{say('preview')}</button>
      </div>
      <Problem error={error} say={say} />
      {notice && <div role="status" className="alert alert-success">{notice}</div>}
      {preview && (
        <div className="dn-section">
          <h2>{say('due', { count: preview.due_count })}</h2>
          {preview.due_count > 0 && <p><LetterFigures letter={preview.totals} say={say} /></p>}
          <ul className="dn-list">
            {preview.entries.map(entry => (
              <li key={entry.contract_id} className="dn-card">
                <div className="dn-card-head">
                  <Link to={`/dunning/contracts/${encodeURIComponent(entry.contract_id)}`}>
                    {say('contract')} {entry.contract_number}</Link>
                  <span>{say(`status_${entry.status}`)}{entry.next_stage_label && entry.status === 'due'
                    ? ` · ${entry.next_stage_label}` : ''}</span>
                </div>
                {entry.letter && <LetterFigures letter={entry.letter} say={say} />}
                {entry.reason && <div className="dn-muted">{entry.reason}</div>}
                {entry.excluded.length > 0 && (
                  <div className="dn-muted">{say('excluded')}: {entry.excluded.map(x => `${x.description} (${x.reason_label})`).join('; ')}</div>
                )}
              </li>
            ))}
          </ul>
          {preview.due_count > 0 && (
            <div className="dn-actions"><button type="button" className="btn btn-primary" disabled={!canWrite || busy}
              onClick={create}>{say('createRun')}</button></div>
          )}
        </div>
      )}
    </div>
  );
}

export function OutboxTab({ say, canWrite }) {
  const [status, setStatus] = useState('ready');
  const [page, reload] = useLoad(() => dunningService.outbox({ status, limit: 200 }), [status]);
  const [sending, setSending] = useState(null);
  const [error, setError] = useState(null);
  const pdf = async entry => {
    try { saveBlob(await dunningService.letterPdf(entry.letter_id), `${entry.letter?.reference || 'Mahnung'}.pdf`); }
    catch (e) { setError(e.message); }
  };
  const eml = async entry => {
    try { saveBlob(await dunningService.eml(entry.id), `${entry.letter?.reference || 'Mahnung'}.eml`); }
    catch (e) { setError(e.message); }
  };
  const markSent = async event => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      await dunningService.markSent(sending.id, { sent_on: form.get('sent_on'), via: form.get('via'),
        note: form.get('note') || null });
      setSending(null); reload();
    } catch (e) { setError(e.message); }
  };
  return (
    <div>
      <p className="dn-muted">{say('sendHint')}</p>
      <div className="dn-form">
        <label>{say('status')}
          <select value={status} onChange={e => setStatus(e.target.value)}>
            {['ready', 'queued', 'sent', 'cancelled'].map(s => <option key={s} value={s}>{say(`outbox_${s}`)}</option>)}
          </select>
        </label>
      </div>
      <Problem error={page.error || error} onRetry={reload} say={say} />
      {page.data && page.data.items.length === 0 && <p className="empty-text">{say('noOutbox')}</p>}
      <ul className="dn-list" aria-label={say('outbox')}>
        {(page.data?.items || []).map(entry => (
          <li key={entry.id} className="dn-card">
            <div className="dn-card-head">
              <strong>{entry.subject}</strong>
              <span>{say(`outbox_${entry.status}`)} · {say(`channel_${entry.channel}`)}</span>
            </div>
            <div className="dn-muted">{say('recipient')}: {entry.recipient_name}
              {entry.channel === 'email' && entry.recipient_email ? ` <${entry.recipient_email}>` : ''}
              {entry.sent_on && ` · ${say('sentOn')} ${formatDate(entry.sent_on)} (${entry.sent_via})`}</div>
            <div className="dn-actions">
              <button type="button" className="btn btn-sm btn-secondary" onClick={() => pdf(entry)}>{say('downloadPdf')}</button>
              {entry.channel === 'email' && entry.status !== 'queued' && (
                <button type="button" className="btn btn-sm btn-secondary" onClick={() => eml(entry)}>{say('eml')}</button>)}
              {entry.status === 'ready' && canWrite && (
                <button type="button" className="btn btn-sm btn-primary" onClick={() => setSending(entry)}>{say('markSent')}</button>)}
            </div>
            {sending?.id === entry.id && (
              <form className="dn-form" onSubmit={markSent}>
                <label>{say('sentOn')}<input name="sent_on" type="date" required defaultValue={today()} /></label>
                <label>{say('via')}<input name="via" required maxLength={200} /></label>
                <label>{say('note')}<input name="note" maxLength={1000} /></label>
                <button type="submit" className="btn btn-primary">{say('save')}</button>
              </form>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function RepliesTab({ say, canWrite }) {
  const [page, reload] = useLoad(() => dunningService.replies({ status: 'review', limit: 200 }), []);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const record = async event => {
    event.preventDefault();
    const target = event.currentTarget;
    const form = new FormData(target);
    try {
      const reply = await dunningService.recordReply({ reference: form.get('reference') || null,
        received_on: form.get('received_on') || null, channel: form.get('channel'), sender: form.get('sender') || null,
        body: form.get('body') });
      setNotice(reply.status === 'assigned' ? `${say('assign')}: ${reply.case_reference}`
        : say(`review_${reply.review_reason}`));
      target.reset(); reload();
    } catch (e) { setError(e.message); }
  };
  const assign = async (reply, reference) => {
    try { await dunningService.assignReply(reply.id, { reference: reference.trim() }); reload(); }
    catch (e) { setError(e.message); }
  };
  const dismiss = async reply => {
    try { await dunningService.dismissReply(reply.id); reload(); } catch (e) { setError(e.message); }
  };
  return (
    <div>
      <p className="dn-muted">{say('replyHint')}</p>
      {canWrite && (
        <form className="dn-form" onSubmit={record} aria-label={say('recordReply')}>
          <label>{say('received')}<input name="received_on" type="date" defaultValue={today()} /></label>
          <label>{say('channel')}
            <select name="channel" defaultValue="letter">
              {['letter', 'email', 'phone', 'note', 'other'].map(c => <option key={c} value={c}>{say(`via_${c}`)}</option>)}
            </select>
          </label>
          <label>{say('sender')}<input name="sender" maxLength={200} /></label>
          <label>{say('replyReference')}<input name="reference" maxLength={200} /></label>
          <label style={{ flexBasis: '100%' }}>{say('body')}<textarea name="body" required rows={3} maxLength={20000} /></label>
          <button type="submit" className="btn btn-primary">{say('recordReply')}</button>
        </form>
      )}
      <Problem error={page.error || error} onRetry={reload} say={say} />
      {notice && <div role="status" className="alert alert-info">{notice}</div>}
      {page.data && page.data.items.length === 0 && <p className="empty-text">{say('noReplies')}</p>}
      <ul className="dn-list" aria-label={say('replies')}>
        {(page.data?.items || []).map(reply => (
          <li key={reply.id} className="dn-card">
            <div className="dn-card-head"><strong>{formatDate(reply.received_on)} · {reply.sender || '—'}</strong>
              <span>{say(`review_${reply.review_reason}`)}</span></div>
            <div style={{ whiteSpace: 'pre-wrap' }}>{reply.body}</div>
            {canWrite && <AssignForm reply={reply} say={say} onAssign={assign} onDismiss={dismiss} />}
          </li>
        ))}
      </ul>
    </div>
  );
}

function AssignForm({ reply, say, onAssign, onDismiss }) {
  const [reference, setReference] = useState('');
  return (
    <div className="dn-form">
      <label>{say('assignTo')}<input value={reference} onChange={e => setReference(e.target.value)}
        placeholder="M-2026-…" /></label>
      <button type="button" className="btn btn-sm btn-primary" disabled={!reference.trim()}
        onClick={() => onAssign(reply, reference)}>{say('assign')}</button>
      <button type="button" className="btn btn-sm btn-secondary" onClick={() => onDismiss(reply)}>{say('dismiss')}</button>
    </div>
  );
}

export function SettingsTab({ say, canWrite }) {
  const [page, reload] = useLoad(() => dunningService.settings(), []);
  const [stages, setStages] = useState([]);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  useEffect(() => { if (page.data) setStages(page.data.stages); }, [page.data]);
  const update = useCallback((index, key, value) => {
    setStages(current => current.map((stage, i) => (i === index ? { ...stage, [key]: value } : stage)));
  }, []);
  const save = async () => {
    try {
      await dunningService.saveStages(stages.map(s => ({ ...s, days_after: Number(s.days_after), fee: Number(s.fee),
        payment_deadline_days: Number(s.payment_deadline_days) })));
      setNotice(say('saved')); reload();
    } catch (e) { setError(e.message); }
  };
  const addRate = async event => {
    event.preventDefault();
    const target = event.currentTarget;
    const form = new FormData(target);
    try {
      await dunningService.addRate({ valid_from: form.get('valid_from'), rate_percent: Number(form.get('rate_percent')),
        source_note: form.get('source_note') || null });
      target.reset(); reload();
    } catch (e) { setError(e.message); }
  };
  const removeRate = async id => {
    try { await dunningService.removeRate(id); reload(); } catch (e) { setError(e.message); }
  };
  return (
    <div>
      <Problem error={page.error || error} onRetry={reload} say={say} />
      {notice && <div role="status" className="alert alert-success">{notice}</div>}
      <section className="dn-section">
        <h2>{say('stages')}</h2>
        <p className="dn-muted">{say('stagesHint')}</p>
        <div className="dn-table-wrap">
          <table className="dn-table">
            <thead><tr><th>{say('stage')}</th><th>{say('label')}</th><th>{say('daysAfter')}</th><th>{say('fee')}</th>
              <th>{say('deadlineDays')}</th><th>{say('chargeInterest')}</th></tr></thead>
            <tbody>
              {stages.map((stage, index) => (
                <tr key={stage.stage}>
                  <td>{stage.stage}</td>
                  <td><input aria-label={`${say('label')} ${stage.stage}`} value={stage.label} disabled={!canWrite}
                    onChange={e => update(index, 'label', e.target.value)} /></td>
                  <td><input type="number" min="0" aria-label={`${say('daysAfter')} ${stage.stage}`} value={stage.days_after}
                    disabled={!canWrite} onChange={e => update(index, 'days_after', e.target.value)} style={{ width: '5rem' }} /></td>
                  <td><input type="number" min="0" step="0.01" aria-label={`${say('fee')} ${stage.stage}`} value={stage.fee}
                    disabled={!canWrite} onChange={e => update(index, 'fee', e.target.value)} style={{ width: '6rem' }} /></td>
                  <td><input type="number" min="1" aria-label={`${say('deadlineDays')} ${stage.stage}`}
                    value={stage.payment_deadline_days} disabled={!canWrite}
                    onChange={e => update(index, 'payment_deadline_days', e.target.value)} style={{ width: '5rem' }} /></td>
                  <td><input type="checkbox" aria-label={`${say('chargeInterest')} ${stage.stage}`} checked={stage.charge_interest}
                    disabled={!canWrite} onChange={e => update(index, 'charge_interest', e.target.checked)} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {canWrite && <div className="dn-actions"><button type="button" className="btn btn-primary" onClick={save}>
          {say('saveStages')}</button></div>}
      </section>
      <section className="dn-section">
        <h2>{say('baseRates')}</h2>
        <p className="dn-muted">{say('ratesHint')}</p>
        <ul className="dn-list">
          {(page.data?.base_rates || []).map(rate => (
            <li key={rate.id} className="dn-card dn-card-head">
              <span>{say('validFrom')} {formatDate(rate.valid_from)}: {rate.rate_percent} % → {rate.consumer_rate_percent} %
                {rate.source_note ? ` (${rate.source_note})` : ''}</span>
              {canWrite && <button type="button" className="btn btn-sm btn-secondary"
                onClick={() => removeRate(rate.id)}>{say('remove')}</button>}
            </li>
          ))}
        </ul>
        {canWrite && (
          <form className="dn-form" onSubmit={addRate} aria-label={say('addRate')}>
            <label>{say('validFrom')}<input name="valid_from" type="date" required /></label>
            <label>{say('rate')}<input name="rate_percent" type="number" step="0.001" required /></label>
            <label>{say('source')}<input name="source_note" maxLength={500} /></label>
            <button type="submit" className="btn btn-primary">{say('addRate')}</button>
          </form>
        )}
      </section>
    </div>
  );
}
