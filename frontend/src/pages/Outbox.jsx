import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { useTranslation } from '../i18n';
import { useConfirm } from '../components/ConfirmDialog';
import useWriteAccess from '../hooks/useWriteAccess';
import './Outbox.css';

const endpoint = '/messages/outbox';
const emptyJournal = { total: 0, items: [] };
const newDraft = () => ({ recipient: '', subject: '', body_text: '', reviewed_by: '', review_confirmed: false });
const referenceFor = (reference, body) => {
  const encoded = JSON.stringify(body);
  if (reference.current?.encoded !== encoded) reference.current = { encoded, key: crypto.randomUUID() };
  return reference.current.key;
};
const verified = value => value?.id && value?.snapshot && Number.isSafeInteger(value.revision) && value.revision >= 0
  && ['ready', 'claimed', 'sent', 'failed', 'unknown'].includes(value.state) && typeof value.message_id === 'string'
  && Number.isSafeInteger(value.wire_size) && value.wire_size > 0 && /^[a-f0-9]{64}$/.test(value.wire_sha256 || '');

export default function Outbox() {
  const { t, locale } = useTranslation();
  const label = key => t(`pages.outbox.${key}`);
  const confirm = useConfirm();
  const { canWrite, requireWrite, isAllowed } = useWriteAccess('/messages');
  const [portfolios, setPortfolios] = useState([]);
  const [portfolioId, setPortfolioId] = useState('');
  const [config, setConfig] = useState(null);
  const [journal, setJournal] = useState(emptyJournal);
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState(null);
  const [events, setEvents] = useState(emptyJournal);
  const [draft, setDraft] = useState(null);
  const [decisionAction, setDecisionAction] = useState('retry');
  const [note, setNote] = useState('');
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const running = useRef(false);
  const activePortfolio = useRef('');
  const selectedId = useRef('');
  const createReference = useRef(null);
  const actionReference = useRef(null);
  const previewRef = useRef(null);
  const firstField = useRef(null);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([api.getAll('/portfolios', { signal: controller.signal }),
      api.get(`${endpoint}/configuration`, { signal: controller.signal })])
      .then(([choices, settings]) => { if (!controller.signal.aborted) { setPortfolios(choices); setConfig(settings); } })
      .catch(err => { if (err.name !== 'AbortError') setError(err.message); });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    activePortfolio.current = portfolioId;
    if (!portfolioId) return undefined;
    const controller = new AbortController(); setLoading(true);
    api.get(`${endpoint}?portfolio_id=${encodeURIComponent(portfolioId)}&offset=${page * 20}&limit=20`, { signal: controller.signal })
      .then(result => { if (!controller.signal.aborted) setJournal(result); })
      .catch(err => { if (err.name !== 'AbortError') setError(err.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [portfolioId, page]);

  useEffect(() => { if (draft) firstField.current?.focus(); }, [!!draft]); // eslint-disable-line react-hooks/exhaustive-deps
  const date = value => value ? new Date(value).toLocaleString(locale) : '—';
  const adopt = value => {
    if (!verified(value)) throw new Error(label('malformed'));
    if (value.portfolio_id !== activePortfolio.current) throw new Error(label('malformed'));
    selectedId.current = value.id;
    setSelected(current => current?.id === value.id && current.revision > value.revision ? current : value);
    setJournal(current => ({ ...current, items: current.items.map(item => item.id === value.id && item.revision <= value.revision ? value : item) }));
  };
  const reload = async identifier => {
    const [result, history] = await Promise.all([api.get(`${endpoint}/${identifier}`), api.get(`${endpoint}/${identifier}/events?limit=50`)]);
    if (selectedId.current !== identifier || result.portfolio_id !== activePortfolio.current) return;
    adopt(result); setEvents(history);
  };
  const show = async entry => {
    if (running.current) return;
    running.current = true; setBusy(true); setError('');
    try {
      selectedId.current = entry.id; setSelected(null); setEvents(emptyJournal); setNote(''); actionReference.current = null;
      await reload(entry.id);
      requestAnimationFrame(() => { previewRef.current?.focus(); previewRef.current?.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' }); });
    } catch (err) { setError(err.message); }
    finally { running.current = false; setBusy(false); }
  };
  const changePortfolio = async value => {
    if (running.current || (draft && !await confirm(label('discardDraft')))) return;
    setPortfolioId(value); setPage(0); setJournal(emptyJournal); setSelected(null); selectedId.current = '';
    setEvents(emptyJournal); setDraft(null); setNote(''); setError('');
  };
  const field = (key, value) => setDraft(current => ({ ...current, [key]: value,
    ...(key === 'review_confirmed' ? {} : { review_confirmed: false }) }));
  const save = async event => {
    event.preventDefault(); if (running.current) return;
    running.current = true; setBusy(true); setError('');
    try {
      requireWrite();
      const body = { ...draft, portfolio_id: portfolioId, sender_address: config.sender_address, sender_name: config.sender_name };
      const result = await api.post(endpoint, { ...body, idempotency_key: referenceFor(createReference, body) });
      if (!isAllowed() || activePortfolio.current !== portfolioId) return;
      adopt(result); setDraft(null);
      const [history, list] = await Promise.all([api.get(`${endpoint}/${result.id}/events?limit=50`),
        api.get(`${endpoint}?portfolio_id=${encodeURIComponent(portfolioId)}&offset=${page * 20}&limit=20`)]);
      if (activePortfolio.current === portfolioId) { setEvents(history); setJournal(list); }
      requestAnimationFrame(() => { previewRef.current?.focus(); previewRef.current?.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' }); });
    } catch (err) { setError(err.message); }
    finally { running.current = false; setBusy(false); }
  };
  const action = async kind => {
    if (running.current || !selected) return;
    running.current = true; setBusy(true); setError('');
    const current = selected;
    try {
      requireWrite();
      if (!await confirm(label(kind === 'send' ? 'confirmSend' : kind === 'recover' ? 'confirmRecover' : 'confirmDecision'))) return;
      if (!isAllowed() || selectedId.current !== current.id) return;
      const body = { expected_revision: current.revision, confirmed: true,
        ...(kind === 'decision' ? { action: current.state === 'ready' ? 'cancel' : current.state === 'failed' ? 'retry' : decisionAction, note } : {}) };
      const result = await api.post(`${endpoint}/${current.id}/${kind}`, { ...body, idempotency_key: referenceFor(actionReference, { id: current.id, kind, ...body }) });
      if (!isAllowed() || selectedId.current !== current.id) return;
      adopt(result); await reload(current.id); setNote('');
    } catch (err) { setError(err.message); } // Preserve note/reference after rejected or disconnected requests.
    finally { running.current = false; setBusy(false); }
  };
  const moreEvents = async () => {
    if (running.current || !selected) return;
    running.current = true; setBusy(true); setError('');
    const id = selected.id;
    try {
      const next = await api.get(`${endpoint}/${id}/events?offset=${events.items.length}&limit=50`);
      if (selectedId.current === id) setEvents(current => ({ total: next.total, items: [...new Map([...current.items, ...next.items].map(entry => [entry.id, entry])).values()] }));
    } catch (err) { setError(err.message); }
    finally { running.current = false; setBusy(false); }
  };
  const refreshSmtp = async () => {
    if (running.current) return;
    running.current = true; setBusy(true); setError('');
    try {
      const latest = await api.get(`${endpoint}/configuration`);
      setConfig(latest);
      setDraft(current => current ? { ...current, review_confirmed: false } : null);
    } catch (err) { setError(err.message); }
    finally { running.current = false; setBusy(false); }
  };

  return <div className="outbox-workspace" aria-busy={loading || busy}>
    <header className="outbox-heading"><div><p className="outbox-eyebrow">{label('eyebrow')}</p><h1>{label('title')}</h1><p>{label('intro')}</p></div>
      <Link className="btn btn-secondary" to="/messages">{label('messages')}</Link></header>
    <div className="outbox-guidance"><p>{label('scope')}</p><p>{label('budget')}</p></div>
    {error && <div role="alert" className="alert alert-danger">{error}</div>}
    {(busy || loading) && <p role="status">{label('working')}</p>}
    <div className="outbox-actions"><button type="button" className="btn btn-secondary" disabled={busy} onClick={refreshSmtp}>{label('refreshSmtp')}</button></div>
    {config && (!config.configured || !config.enabled) && <div className="outbox-guidance"><p>{label('smtpUnavailable')}</p>
      <Link to="/integrations">{label('smtpSettings')}</Link></div>}
    <label className="outbox-portfolio">{label('portfolio')}<select value={portfolioId} disabled={busy || loading} onChange={event => changePortfolio(event.target.value)}>
      <option value="">{label('choosePortfolio')}</option>{portfolios.map(value => <option key={value.id} value={value.id}>{value.name}</option>)}</select></label>
    {portfolioId && <>
      <section className="outbox-panel"><div className="outbox-section-head"><h2>{label('journal')}</h2>
        {canWrite && <button type="button" className="btn btn-primary" disabled={busy || loading || !!draft || !config?.configured}
          onClick={() => { requireWrite(); setDraft(newDraft()); createReference.current = null; setError(''); }}>{label('compose')}</button>}</div>
        {!journal.items.length && !loading && <p>{label('empty')}</p>}
        {!!journal.items.length && <div className="outbox-table"><table><caption>{label('journal')}</caption><thead><tr><th>{label('subject')}</th><th>{label('recipient')}</th><th>{label('status')}</th><th>{label('created')}</th><th>{label('details')}</th></tr></thead>
          <tbody>{journal.items.map(entry => <tr key={entry.id}><td>{entry.snapshot.subject}</td><td>{entry.snapshot.recipient}</td><td><span className={`outbox-state outbox-state-${entry.state}`}>{label(`states.${entry.state}`)}</span></td>
            <td>{date(entry.created_at)}</td><td><button type="button" className="btn btn-secondary" disabled={busy} onClick={() => show(entry)}>{label('view')} · {entry.id.slice(0, 8)}</button></td></tr>)}</tbody></table></div>}
        <nav className="outbox-pagination" aria-label={label('pagination')}><button type="button" disabled={busy || loading || page === 0} onClick={() => setPage(value => value - 1)}>{label('previous')}</button>
          <span>{page * 20 + Math.min(1, journal.items.length)}–{page * 20 + journal.items.length} / {journal.total}</span>
          <button type="button" disabled={busy || loading || (page + 1) * 20 >= journal.total} onClick={() => setPage(value => value + 1)}>{label('next')}</button></nav>
      </section>
      {draft && <section className="outbox-panel"><h2>{label('compose')}</h2><p>{label('reviewHint')}</p><p>{label('envelopeHint')}</p>
        <form onSubmit={save} aria-busy={busy}><fieldset disabled={busy || !canWrite}>
          <div className="outbox-field-grid"><label>{label('sender')}<input readOnly value={`${config.sender_name} <${config.sender_address}>`} /></label>
            <label>{label('recipient')}<input ref={firstField} required type="email" value={draft.recipient} onChange={event => field('recipient', event.target.value)} /></label>
            <label>{label('subject')}<input required value={draft.subject} onChange={event => field('subject', event.target.value)} /></label>
            <label>{label('reviewedBy')}<input required value={draft.reviewed_by} onChange={event => field('reviewed_by', event.target.value)} /></label></div>
          <label>{label('body')}<textarea required rows={10} value={draft.body_text} onChange={event => field('body_text', event.target.value)} /></label>
          <label className="outbox-review"><input required type="checkbox" checked={draft.review_confirmed} onChange={event => field('review_confirmed', event.target.checked)} />{label('reviewConfirmation')}</label>
          <div className="outbox-actions"><button className="btn btn-primary" type="submit">{label('saveReviewed')}</button>
            <button className="btn btn-secondary" type="button" onClick={async () => { if (await confirm(label('discardDraft'))) setDraft(null); }}>{label('cancel')}</button></div>
        </fieldset></form></section>}
      {selected && <section className="outbox-panel outbox-preview" ref={previewRef} tabIndex={-1} aria-label={label('preview')}>
        <div className="outbox-section-head"><h2>{label('preview')}</h2><button type="button" disabled={busy} className="btn btn-secondary" onClick={() => show(selected)}>{label('reload')}</button></div>
        <p role="status"><span className={`outbox-state outbox-state-${selected.state}`}>{label(`states.${selected.state}`)}</span> · {label('revision')}: {selected.revision} · {label('attempts')}: {selected.attempt_no}</p>
        <dl className="outbox-metadata"><dt>{label('sender')}</dt><dd>{selected.snapshot.sender_name} &lt;{selected.snapshot.sender_address}&gt;</dd>
          <dt>{label('recipient')}</dt><dd>{selected.snapshot.recipient}</dd><dt>{label('subject')}</dt><dd>{selected.snapshot.subject}</dd>
          <dt>{label('reviewedBy')}</dt><dd>{selected.snapshot.reviewed_by}</dd><dt>{label('messageId')}</dt><dd><code>{selected.message_id}</code></dd></dl>
        <pre className="outbox-body">{selected.snapshot.body_text}</pre>
        <p>{label('wire')}: {selected.wire_size.toLocaleString(locale)} B · <code>{selected.wire_sha256}</code></p>
        {selected.state === 'sent' && <p className="outbox-guidance">{label('acceptedHint')}</p>}
        {selected.state === 'unknown' && <p role="alert" className="outbox-unknown-hint">{label('unknownHint')}</p>}
        {selected.state === 'claimed' && <p>{label('claimedHint')} · {label('leaseUntil')}: {date(selected.lease_until)}</p>}
        {canWrite && <div className="outbox-actions">
          {selected.state === 'ready' && <button type="button" disabled={busy || !config?.enabled} className="btn btn-primary" onClick={() => action('send')}>{label('send')}</button>}
          {selected.state === 'claimed' && <button type="button" disabled={busy} className="btn btn-secondary" onClick={() => action('recover')}>{label('recover')}</button>}
        </div>}
        {canWrite && ['unknown', 'failed', 'ready'].includes(selected.state) && <form className="outbox-decision" onSubmit={event => { event.preventDefault(); action('decision'); }}><fieldset disabled={busy || !canWrite}>
          <legend>{label('decision')}</legend><label>{label('decisionAction')}<select value={selected.state === 'ready' ? 'cancel' : selected.state === 'failed' ? 'retry' : decisionAction}
            onChange={event => setDecisionAction(event.target.value)}>
            {selected.state === 'ready' ? <option value="cancel">{label('actions.cancel')}</option> : selected.state === 'failed' ? <option value="retry">{label('actions.retry')}</option> : <>
              <option value="retry">{label('actions.retry')}</option><option value="mark_sent">{label('actions.mark_sent')}</option><option value="mark_failed">{label('actions.mark_failed')}</option></>}</select></label>
          <label>{label('note')}<textarea required rows={3} value={note} onChange={event => setNote(event.target.value)} /></label>
          <button type="submit" disabled={!note.trim()} className="btn btn-secondary">{label('saveDecision')}</button>
        </fieldset></form>}
        <h3>{label('attemptJournal')}</h3><ol className="outbox-events">{events.items.map(entry => <li key={entry.id}>
          <div><strong>{label(`events.${entry.kind}`)}</strong> · {label(`states.${entry.state}`)} · {label('revision')} {entry.revision}</div>
          <div>{date(entry.created_at)} · {label('actor')}: {entry.actor_id} · {label('attempts')}: {entry.attempt_no}{entry.code && <> · <code>{entry.code}</code></>}</div>
          {entry.note && <p>{entry.note}</p>}</li>)}</ol>
        {events.items.length < events.total && <button type="button" disabled={busy} className="btn btn-secondary" onClick={moreEvents}>{label('moreEvents')}</button>}
      </section>}
    </>}
  </div>;
}
