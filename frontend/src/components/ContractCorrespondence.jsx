import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { api } from '../api';
import { useAuth } from '../contexts/AuthContext';
import { useTranslation } from '../i18n';
import useWriteAccess from '../hooks/useWriteAccess';
import { useConfirm } from './ConfirmDialog';
import CorrespondenceSources from './CorrespondenceSources';
import { blankLetter, key, letterData, letterForm, PAGE_SIZE, sameData, sourceContract,
  unknownOutcome, validateCommand, validateDeadlines, validateEvents, validateLetter, validateLetterPage } from '../utils/contractCorrespondence';
import './ContractCorrespondence.css';

const blankEvent = () => ({ kind: 'dispatched', event_date: '', channel: 'post', reference: '', note: '', dispatch_event_id: '', confirmed: false });
const pdfHeader = blob => new Promise((resolve, reject) => {
  const reader = new FileReader(); reader.onload = () => resolve(reader.result);
  reader.onerror = () => reject(new Error('invalidDownload')); reader.readAsText(blob.slice(0, 5));
});
const consentKey = row => row?.review_hash ? `${row.id}:${row.revision}:${row.review_hash}` : null;

export default function ContractCorrespondence(props) {
  const user = useAuth()?.user;
  if (!user?.id || user.is_active === false) return null;
  const actor = JSON.stringify([user.id, user.role, user.portfolio_access,
    [...(user.portfolio_ids || [])].sort(), [...(user.write_permissions || [])].sort()]);
  return <CorrespondencePanel key={`${props.contract.id}:${actor}`} {...props} user={user} />;
}

function CorrespondencePanel({ contract, user, onBusyChange }) {
  const { t } = useTranslation(), confirm = useConfirm();
  const label = useRef(null); useLayoutEffect(() => { label.current = (name, args) => t(`contractCorrespondence.${name}`, args); });
  const tr = (name, args) => t(`contractCorrespondence.${name}`, args);
  const base = `/contracts/${encodeURIComponent(contract.id)}/correspondence`;
  const [source, setSource] = useState(null), [portfolio, setPortfolio] = useState(null);
  const [drafts, setDrafts] = useState(null), [history, setHistory] = useState(null), [deadlines, setDeadlines] = useState(null);
  const [tab, setTab] = useState('history'), [selected, setSelected] = useState(null), [events, setEvents] = useState(null);
  const [form, setForm] = useState(blankLetter), [observation, setObservation] = useState(blankEvent);
  const [loading, setLoading] = useState(true), [busy, setBusy] = useState(false), [sourceBusy, setSourceBusy] = useState(false);
  const [sourceRetry, setSourceRetry] = useState(false);
  const [error, setError] = useState(null), [notice, setNotice] = useState(null), [retry, setRetry] = useState(null);
  const [needsReload, setNeedsReload] = useState(false), [denied, setDenied] = useState(false), [consent, setConsent] = useState(null);
  const [smallPageOption, setSmallPageOption] = useState(false);
  const [eventBefore, setEventBefore] = useState(null), [pageBefore, setPageBefore] = useState(null);
  const active = useRef(true), pending = useRef(false), sequence = useRef(0), selection = useRef(0);
  const controllers = useRef(new Set()), urls = useRef(new Set()), callbacks = useRef(onBusyChange);
  const pageSize = useRef(PAGE_SIZE);
  const errorRef = useRef(null), editorRef = useRef(null), fieldId = useId();
  const { canWrite, isAllowed, requireWrite } = useWriteAccess('/contracts');
  const { canWrite: canPublish, isAllowed: mayPublish } = useWriteAccess('/documents');
  useEffect(() => { callbacks.current = onBusyChange; }, [onBusyChange]);
  useEffect(() => { callbacks.current?.(busy || sourceBusy); }, [busy, sourceBusy]);
  const controller = useCallback(() => { const value = new AbortController(); controllers.current.add(value); return value; }, []);
  const done = useCallback(value => controllers.current.delete(value), []);
  const message = useCallback(reason => ['invalidResponse', 'completeFields', 'invalidDownload'].includes(reason.message)
    ? label.current(reason.message) : reason.message || label.current('failed'), []);
  const forget = useCallback(reason => {
    if (![401, 403, 404].includes(reason.statusCode)) return false;
    for (const ctl of controllers.current) ctl.abort();
    setDenied(true); setSource(null); setPortfolio(null); setDrafts(null); setHistory(null); setDeadlines(null);
    setSelected(null); setEvents(null); setForm(blankLetter()); setObservation(blankEvent()); setRetry(null); setConsent(null);
    return true;
  }, []);
  const sourceDenied = useCallback(reason => {
    if (forget(reason)) setError(message(reason));
  }, [forget, message]);
  const freshSource = useCallback(async signal => {
    const next = sourceContract(await api.get(`/contracts/${encodeURIComponent(contract.id)}`, { signal }), contract.id);
    const property = await api.get(`/properties/${encodeURIComponent(next.value.property_id)}`, { signal });
    if (property?.id !== next.value.property_id || typeof property.portfolio_id !== 'string' || !property.portfolio_id) throw new Error('invalidResponse');
    return { ...next, value: { ...next.value, portfolio_id: property.portfolio_id }, portfolio: property.portfolio_id };
  }, [contract.id]);

  const restore = useCallback(async ({ id = null, preserve = false } = {}) => {
    const ticket = ++sequence.current, ctl = controller(); selection.current += 1;
    setLoading(true); setError(null); setConsent(null);
    try {
      const next = await freshSource(ctl.signal);
      const values = await Promise.all(['drafts', 'history', 'deadlines'].map(kind => api.get(`${base}/${kind}?limit=${pageSize.current}`, { signal: ctl.signal })));
      if (!active.current || ctl.signal.aborted || ticket !== sequence.current) return;
      const own = validateLetterPage(values[0], next.value, user.id), approved = validateLetterPage(values[1], next.value, user.id, true);
      const dates = validateDeadlines(values[2], contract.id);
      let current = null, eventPage = null;
      if (id) {
        current = validateLetter(await api.get(`${base}/drafts/${encodeURIComponent(id)}`, { signal: ctl.signal }), next.value, user.id, { live: true, history: true });
        if (current.state === 'approved') eventPage = validateEvents(await api.get(`${base}/drafts/${encodeURIComponent(id)}/events?limit=${pageSize.current}`, { signal: ctl.signal }), current.document_version_id);
      }
      if (!active.current || ctl.signal.aborted || ticket !== sequence.current) return;
      setSource(next); setPortfolio(next.portfolio); setDrafts(own); setHistory(approved); setDeadlines(dates);
      setSelected(current); setEvents(eventPage); setPageBefore(null); setEventBefore(null); setNeedsReload(false); setDenied(false);
      setSmallPageOption(false);
      if (!preserve) { setForm(current ? letterForm(current.data) : blankLetter()); setObservation(blankEvent()); }
      else setObservation(current => ({ ...current, confirmed: false }));
    } catch (reason) { if (active.current && !ctl.signal.aborted && ticket === sequence.current) {
      forget(reason); setError(message(reason)); setSmallPageOption(reason.statusCode === 422 && pageSize.current > 1);
    } }
    finally { done(ctl); if (active.current && ticket === sequence.current) setLoading(false); }
  }, [base, contract.id, controller, freshSource, user.id, forget, message, done]);
  useEffect(() => {
    active.current = true; void restore();
    const ownedControllers = controllers.current, ownedUrls = urls.current;
    return () => {
      active.current = false; sequence.current += 1; selection.current += 1;
      for (const ctl of ownedControllers) ctl.abort();
      for (const url of ownedUrls) URL.revokeObjectURL(url);
      callbacks.current?.(false);
    };
  }, [restore]);
  useEffect(() => { if (error) errorRef.current?.focus(); }, [error]);
  const locked = busy || sourceBusy || sourceRetry || Boolean(retry) || needsReload;
  const update = (name, value) => { setForm(current => ({ ...current, [name]: value })); setConsent(null); };
  let dirty = false;
  try { dirty = selected ? !sameData(letterData(form), selected.data) : false; } catch { dirty = Boolean(selected); }

  const choose = async id => {
    if (locked || loading) return;
    const ticket = ++selection.current, ctl = controller(); sequence.current += 1;
    setLoading(true); setError(null); setConsent(null);
    try {
      const next = await freshSource(ctl.signal);
      const current = validateLetter(await api.get(`${base}/drafts/${encodeURIComponent(id)}`, { signal: ctl.signal }), next.value, user.id, { live: true, history: true });
      const eventPage = current.state === 'approved' ? validateEvents(await api.get(`${base}/drafts/${encodeURIComponent(id)}/events?limit=${pageSize.current}`, { signal: ctl.signal }), current.document_version_id) : null;
      if (!active.current || ctl.signal.aborted || ticket !== selection.current) return;
      setSource(next); setPortfolio(next.portfolio); setSelected(current); setForm(letterForm(current.data)); setObservation(blankEvent());
      setEvents(eventPage); setEventBefore(null);
      queueMicrotask(() => { if (active.current && !editorRef.current?.closest('[hidden]')) editorRef.current?.focus(); });
    } catch (reason) { if (active.current && !ctl.signal.aborted && ticket === selection.current) { forget(reason); setError(message(reason)); } }
    finally { done(ctl); if (active.current && ticket === selection.current) setLoading(false); }
  };

  const send = async command => {
    if (pending.current || !isAllowed() || command.operation === 'approve' && !mayPublish()) return;
    pending.current = true; setBusy(true); setError(null); setNotice(null);
    const ctl = controller();
    let accepted = false;
    try {
      requireWrite();
      const value = await api.post(command.path, command.payload, { signal: ctl.signal });
      if (!active.current || ctl.signal.aborted || !isAllowed() || command.operation === 'approve' && !mayPublish()) return;
      const result = validateCommand(value, command.source, user.id, command);
      accepted = true; setRetry(null); setSelected(result); setConsent(null); setNotice(tr('saved'));
      await restore({ id: result.id });
      if (command.operation === 'approve') setTab('history');
    } catch (reason) {
      if (active.current && !ctl.signal.aborted) {
        if (!forget(reason) && !accepted) {
          if (unknownOutcome(reason)) setRetry(command);
          else if ([409, 412].includes(reason.statusCode)) { setNeedsReload(true); setConsent(null); }
        }
        setError(message(reason));
      }
    } finally { done(ctl); pending.current = false; if (active.current) setBusy(false); }
  };

  const execute = async operation => {
    if (pending.current || locked || loading || !isAllowed() || !source) return;
    if (operation === 'approve' && !mayPublish()) { setError(tr('documentPermission')); return; }
    let data;
    try { data = operation === 'approve' || operation === 'review' ? selected?.data : letterData(form); }
    catch (reason) { setError(message(reason)); return; }
    if (!data || ['review', 'approve'].includes(operation) && dirty) { setConsent(null); setError(tr('unsaved')); return; }
    if (operation === 'approve' && consent !== consentKey(selected)) { setError(tr('consentRequired')); return; }
    pending.current = true; setBusy(true); const ctl = controller();
    try {
      const next = await freshSource(ctl.signal);
      if (!active.current || ctl.signal.aborted || !isAllowed() || operation === 'approve' && !mayPublish()) return;
      if (operation === 'approve' && (next.etag !== selected.source_contract_etag || selected.source_review_status !== 'current')) {
        setNeedsReload(true); setConsent(null); setError(tr('requiresReview')); return;
      }
      const payload = { idempotency_key: key(), expected_contract_etag: next.etag,
        ...(selected ? { expected_revision: selected.revision } : {}),
        ...(['create', 'edit'].includes(operation) ? { data } : {}),
        ...(operation === 'approve' ? { reviewed_hash: selected.review_hash, confirmed: true } : {}) };
      if (operation === 'approve' && !await confirm(tr('approvePrompt'))) return;
      if (!active.current || ctl.signal.aborted || !isAllowed() || operation === 'approve' && !mayPublish()) return;
      pending.current = false;
      await send({ operation, source: next.value, data, id: selected?.id || null,
        reviewHash: operation === 'approve' ? selected.review_hash : null, payload,
        path: selected ? `${base}/drafts/${encodeURIComponent(selected.id)}/${operation}` : `${base}/drafts` });
    } catch (reason) { if (active.current && !ctl.signal.aborted) { forget(reason); setError(message(reason)); } }
    finally { done(ctl); pending.current = false; if (active.current) setBusy(false); }
  };

  const recordEvent = async () => {
    if (pending.current || locked || loading || !isAllowed() || selected?.state !== 'approved' || !events) return;
    if (!observation.confirmed || !observation.event_date || !observation.reference.trim() || !observation.note.trim()
        || observation.kind === 'received' && !observation.dispatch_event_id) { setError(tr('eventRequired')); return; }
    if (observation.kind === 'dispatched' && selected.source_review_status !== 'current') { setError(tr('requiresReview')); return; }
    pending.current = true; setBusy(true); const ctl = controller();
    try {
      const next = await freshSource(ctl.signal);
      const payload = { ...observation, reference: observation.reference.trim(), note: observation.note.trim(),
        dispatch_event_id: observation.kind === 'received' ? observation.dispatch_event_id : null,
        expected_revision: selected.revision, expected_event_revision: events.event_revision, idempotency_key: key(), confirmed: true };
      if (!await confirm(tr('eventPrompt')) || !active.current || ctl.signal.aborted || !isAllowed()) return;
      pending.current = false;
      await send({ operation: 'event', source: next.value, data: selected.data, id: selected.id,
        reviewHash: selected.review_hash, payload, path: `${base}/drafts/${encodeURIComponent(selected.id)}/events` });
    } catch (reason) { if (active.current && !ctl.signal.aborted) { forget(reason); setError(message(reason)); } }
    finally { done(ctl); pending.current = false; if (active.current) setBusy(false); }
  };

  const download = async preview => {
    if (pending.current || locked || loading || !selected || dirty) return;
    pending.current = true; setBusy(true); const ctl = controller();
    try {
      const id = selected.id;
      const blob = await api.getBlob(`${base}/drafts/${encodeURIComponent(id)}/${preview ? 'review-pdf' : 'download'}`, { signal: ctl.signal });
      if (!(blob instanceof Blob) || blob.size < 5 || blob.type.split(';')[0].toLowerCase() !== 'application/pdf'
          || await pdfHeader(blob) !== '%PDF-') throw new Error('invalidDownload');
      if (!active.current || ctl.signal.aborted || selected.id !== id) return;
      const url = URL.createObjectURL(blob); urls.current.add(url);
      const link = document.createElement('a'); link.href = url; link.download = preview ? 'correspondence-review.pdf' : 'correspondence-approved.pdf'; link.click();
      setTimeout(() => { if (urls.current.delete(url)) URL.revokeObjectURL(url); }, 1000);
    } catch (reason) { if (active.current && !ctl.signal.aborted) { forget(reason); setError(message(reason)); } }
    finally { done(ctl); pending.current = false; if (active.current) setBusy(false); }
  };
  const more = async kind => {
    if (locked || loading) return;
    const current = kind === 'events' ? events : kind === 'drafts' ? drafts : kind === 'history' ? history : deadlines;
    if (!current?.next_before) return;
    const ticket = ++sequence.current, ctl = controller(); setLoading(true);
    try {
      const path = kind === 'events' ? `${base}/drafts/${encodeURIComponent(selected.id)}/events` : `${base}/${kind}`;
      const page = await api.get(`${path}?limit=${pageSize.current}&before=${encodeURIComponent(current.next_before)}`, { signal: ctl.signal });
      if (!active.current || ctl.signal.aborted || ticket !== sequence.current) return;
      if (kind === 'events') { setEvents(validateEvents(page, selected.document_version_id)); setEventBefore(current.next_before); }
      else if (kind === 'deadlines') { setDeadlines(validateDeadlines(page, contract.id)); setPageBefore(current.next_before); }
      else {
        const checked = validateLetterPage(page, source.value, user.id, kind === 'history');
        (kind === 'drafts' ? setDrafts : setHistory)(checked); setPageBefore(current.next_before);
      }
    } catch (reason) { if (active.current && !ctl.signal.aborted && ticket === sequence.current) { forget(reason); setError(message(reason)); } }
    finally { done(ctl); if (active.current && ticket === sequence.current) setLoading(false); }
  };
  const selectedList = tab === 'drafts' ? drafts : history;
  const immutable = selected?.state === 'approved';
  const reviewCurrent = selected?.source_review_status === 'current';
  const eventChange = (name, value) => setObservation(current => ({ ...current, [name]: value, confirmed: name === 'confirmed' ? value : false,
    ...(name === 'kind' ? { dispatch_event_id: '' } : {}) }));
  return <section className="contract-correspondence" aria-labelledby={`${fieldId}-title`}>
    <h3 id={`${fieldId}-title`}>{tr('title')}</h3><p className="contract-correspondence-policy">{tr('policy')}</p>
    <nav aria-label={tr('sections')} className="contract-correspondence-actions">{['history', 'drafts', 'deadlines'].map(name =>
      <button type="button" key={name} aria-pressed={tab === name} disabled={busy || sourceBusy}
        onClick={() => setTab(name)}>{tr(name)}</button>)}</nav>
    {loading && <p role="status">{tr('loading')}</p>}
    {error && <div role="alert" tabIndex={-1} ref={errorRef} className="contract-correspondence-error">{error}
      {retry ? <><p>{tr('unknown')}</p><button type="button" disabled={busy || !canWrite} onClick={() => send(retry)}>{tr('retryExact')}</button></>
        : <button type="button" disabled={busy || sourceBusy} onClick={() => restore({ id: selected?.id || null, preserve: true })}>{tr(needsReload ? 'reloadConflict' : 'reload')}</button>}</div>}
    {smallPageOption && !retry && <button type="button" disabled={busy || sourceBusy} onClick={() => {
      pageSize.current = 1; restore({ id: selected?.id || null, preserve: true });
    }}>{tr('smallPages')}</button>}
    {notice && <p role="status">{notice}</p>}
    {!denied && <>
      {tab === 'deadlines' ? <div className="contract-correspondence-cards">
        {!deadlines?.items.length && !loading && <p>{tr('noDeadlines')}</p>}
        {deadlines?.items.map(item => <button type="button" key={item.id} disabled={locked || loading} onClick={() => { setTab('history'); choose(item.id); }}>
          <strong>{item.date}</strong><span>{item.basis}</span><small>{tr(item.source_review_status === 'current' ? 'confirmedDate' : 'requiresReview')}</small></button>)}
        {deadlines?.next_before && <button type="button" disabled={locked || loading} onClick={() => more('deadlines')}>{tr('nextPage')}</button>}
      </div> : <div className="contract-correspondence-cards">
        {tab === 'drafts' && canWrite && <button type="button" disabled={locked || loading} onClick={() => {
          selection.current += 1; setSelected(null); setForm(blankLetter()); setObservation(blankEvent()); setEvents(null); setConsent(null); setNotice(null);
        }}>{tr('newLetter')}</button>}
        {!selectedList?.items.length && !loading && <p>{tr(tab === 'drafts' ? 'noDrafts' : 'noHistory')}</p>}
        {selectedList?.items.map(row => <button type="button" key={row.id} disabled={locked || loading} aria-pressed={selected?.id === row.id} onClick={() => choose(row.id)}>
          <strong>{row.data.subject}</strong><span>{row.data.recipient_name} · {row.data.letter_date}</span>
          <small>{tr(`state_${row.state}`)} · {row.data.deadline_date}</small></button>)}
        {selectedList?.next_before && <button type="button" disabled={locked || loading} onClick={() => more(tab)}>{tr('nextPage')}</button>}
      </div>}
      {pageBefore && <button type="button" disabled={locked || loading} onClick={() => restore({ id: selected?.id || null, preserve: true })}>{tr('firstPage')}</button>}
      {canWrite && source && <div hidden={tab !== 'drafts' || immutable}><form onSubmit={event => { event.preventDefault(); execute(selected ? 'edit' : 'create'); }}>
        <fieldset disabled={locked || loading}><legend tabIndex={-1} ref={editorRef}>{tr(selected ? 'editLetter' : 'newLetter')}</legend>
          <div className="contract-correspondence-dates">{['letter_date', 'deadline_date'].map(name => <label key={name}>{tr(name)}<input type="date" required value={form[name]} onChange={event => update(name, event.target.value)} /></label>)}</div>
          <label>{tr('deadline_basis')}<textarea required rows={2} value={form.deadline_basis} onChange={event => update('deadline_basis', event.target.value)} /></label>
          <label className="contract-correspondence-check"><input type="checkbox" checked={form.deadline_confirmed} onChange={event => update('deadline_confirmed', event.target.checked)} />{tr('deadlineConfirmed')}</label>
          {['recipient_name', 'recipient_address', 'subject'].map(name => <label key={name}>{tr(name)}
            {name === 'recipient_address' ? <textarea required rows={3} value={form[name]} onChange={event => update(name, event.target.value)} />
              : <input required value={form[name]} onChange={event => update(name, event.target.value)} />}</label>)}
          <label>{tr('textSource')}<select value={form.mode} onChange={event => { update('mode', event.target.value); }}><option value="body">{tr('ownBody')}</option><option value="template">{tr('template')}</option></select></label>
          {form.mode === 'body' && <label>{tr('body')}<textarea required rows={8} value={form.body} onChange={event => update('body', event.target.value)} /></label>}
        </fieldset>
        {portfolio && <CorrespondenceSources portfolioId={portfolio} contract={source.value} templateId={form.template_id}
          lifecycleId={form.lifecycle_command_id} reviewedTemplate={selected?.review?.template} locked={busy || Boolean(retry) || needsReload || loading}
          onTemplateChange={value => { update('template_id', value); if (value) update('mode', 'template'); }}
          onLifecycleChange={value => update('lifecycle_command_id', value)} onBusyChange={setSourceBusy}
          onRetryChange={setSourceRetry} onDenied={sourceDenied} />}
        <div className="contract-correspondence-actions"><button type="submit" disabled={locked || loading}>{tr(selected ? 'saveChanges' : 'saveDraft')}</button>
          {selected && <button type="button" disabled={locked || loading || dirty} onClick={() => execute('review')}>{tr('review')}</button>}</div>
        {dirty && <p role="status">{tr('unsaved')}</p>}
      </form></div>}
      {selected?.review && <section className="contract-correspondence-review" aria-label={tr('reviewTitle')}>
        <h4>{tr('reviewTitle')}</h4><dl>
          <div><dt>{tr('recipient_name')}</dt><dd>{selected.review.data.recipient_name}</dd></div>
          <div><dt>{tr('recipient_address')}</dt><dd>{selected.review.data.recipient_address}</dd></div>
          <div><dt>{tr('deadline_date')}</dt><dd>{selected.review.data.deadline_date}</dd></div>
          <div><dt>{tr('deadline_basis')}</dt><dd>{selected.review.data.deadline_basis}</dd></div>
          <div><dt>{tr('template')}</dt><dd>{selected.review.template ? `${selected.review.template.title} · v${selected.review.template.version}` : tr('ownBody')}</dd></div>
        </dl><h5>{selected.data.subject}</h5><pre>{selected.review.rendered_body}</pre><small>{tr('pdfHash')}: {selected.review.pdf_sha256}</small>
        {!reviewCurrent && <p role="status">{tr('requiresReview')}</p>}
        <button type="button" disabled={locked || loading || dirty} onClick={() => download(!immutable)}>{tr(immutable ? 'download' : 'preview')}</button>
        {selected.state === 'reviewed' && canWrite && <div>
          <label className="contract-correspondence-check"><input type="checkbox" checked={consent === consentKey(selected)}
            disabled={locked || loading || dirty || !reviewCurrent || !canPublish} onChange={event => setConsent(event.target.checked ? consentKey(selected) : null)} />{tr('approveConsent')}</label>
          {!canPublish && <p role="status">{tr('documentPermission')}</p>}
          <button type="button" disabled={locked || loading || dirty || !reviewCurrent || !canPublish || consent !== consentKey(selected)} onClick={() => execute('approve')}>{tr('approve')}</button>
        </div>}
        {immutable && <p role="status">{tr('immutable')}</p>}
      </section>}
      {immutable && <section className="contract-correspondence-events" aria-label={tr('events')}>
        <h4>{tr('events')}</h4><p>{tr('eventsPolicy')}</p>
        {!events?.items.length && <p>{tr('noEvents')}</p>}
        {events?.items.map(event => <article key={event.id}><strong>{tr(event.data.kind)} · {event.data.event_date}</strong>
          <p>{tr(event.data.channel)} · {event.data.reference}</p><p>{event.data.note}</p></article>)}
        {events?.next_before && <button type="button" disabled={locked || loading} onClick={() => more('events')}>{tr('nextPage')}</button>}
        {eventBefore && <button type="button" disabled={locked || loading} onClick={() => restore({ id: selected.id, preserve: true })}>{tr('firstPage')}</button>}
        {canWrite && <form onSubmit={event => { event.preventDefault(); recordEvent(); }}>
          <fieldset disabled={locked || loading}><legend>{tr('recordEvent')}</legend>
            <label>{tr('eventKind')}<select value={observation.kind} onChange={event => eventChange('kind', event.target.value)}>
              <option value="dispatched" disabled={!reviewCurrent}>{tr('dispatched')}</option><option value="received">{tr('received')}</option></select></label>
            {observation.kind === 'received' && <label>{tr('dispatchReference')}<select value={observation.dispatch_event_id} required onChange={event => eventChange('dispatch_event_id', event.target.value)}>
              <option value="">{tr('selectDispatch')}</option>{events?.items.filter(event => event.data.kind === 'dispatched').map(event =>
                <option key={event.id} value={event.id}>{event.data.event_date} · {event.data.reference}</option>)}</select></label>}
            <label>{tr('eventDate')}<input type="date" required value={observation.event_date} onChange={event => eventChange('event_date', event.target.value)} /></label>
            <label>{tr('channel')}<select value={observation.channel} onChange={event => eventChange('channel', event.target.value)}>{['post', 'handover', 'other'].map(name => <option key={name} value={name}>{tr(name)}</option>)}</select></label>
            <label>{tr('reference')}<input required value={observation.reference} onChange={event => eventChange('reference', event.target.value)} /></label>
            <label>{tr('note')}<textarea required rows={3} value={observation.note} onChange={event => eventChange('note', event.target.value)} /></label>
            <label className="contract-correspondence-check"><input type="checkbox" checked={observation.confirmed} onChange={event => eventChange('confirmed', event.target.checked)} />{tr('eventConsent')}</label>
          </fieldset><button type="submit" disabled={locked || loading || !observation.confirmed || observation.kind === 'dispatched' && !reviewCurrent}>{tr('recordEvent')}</button>
        </form>}
      </section>}
    </>}
  </section>;
}
