import { useEffect, useId, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { MessageSquare, Send, Sparkles } from 'lucide-react';
import { CONFIDENCE_LABELS, READER_HINTS, aiReadingApi, preferredReader, shownValue } from './aiReadingApi';
import './aiReading.css';

/**
 * Reading a document for a form (no <form> of its own, so it can sit inside one): who reads it, what should happen with it, the conversation with the AI,
 * the question about a record that already exists, and the values with their evidence. `onApply` gets the
 * reading once the person takes the values into the form; `children(reading)` shows surface-specific results.
 */
export default function AiReadingPanel({ surface, source, params, title, onApply, onOpenExisting, onUpdateExisting, onSkip,
  onCancel, applyLabel = 'In die Maske übernehmen', children, service = aiReadingApi, autoStart = false }) {
  const id = useId();
  const [options, setOptions] = useState(null);
  const [reader, setReader] = useState('');
  const [instruction, setInstruction] = useState('');
  const [reading, setReading] = useState(null);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const started = useRef(false);
  const chatEnd = useRef(null);
  const info = options?.surfaces?.find(item => item.id === surface);

  useEffect(() => {
    const controller = new AbortController();
    service.options(surface, { signal: controller.signal }).then(found => {
      if (controller.signal.aborted || !found) return;
      setOptions(found);
      setReader(current => current || preferredReader(found, found.surfaces?.[0]?.needs_ai));
    }).catch(failure => { if (!controller.signal.aborted) setError(failure?.message || 'Die Einstellungen zum Einlesen sind nicht erreichbar.'); });
    return () => controller.abort();
  }, [service, surface]);

  useEffect(() => { chatEnd.current?.scrollIntoView?.({ block: 'nearest' }); }, [reading?.messages?.length]);

  const run = async (key, task) => {
    if (busy) return;
    setBusy(key); setError('');
    try { await task(); }
    catch (failure) { setError(failure?.message || 'Das hat nicht geklappt.'); }
    finally { setBusy(''); }
  };
  const start = () => run('start', async () => {
    const found = await service.start({ surface, document_id: source?.documentId || null, file_url: source?.fileUrl || null,
      params: params || {}, reader: reader || 'auto', instruction: instruction.trim() || null });
    setReading(found);
  });
  const send = event => {
    event?.preventDefault();
    const text = message.trim();
    if (!text || !reading) return;
    run('say', async () => {
      const found = await service.say(reading, text);
      setReading(found); setMessage('');
    });
  };
  const decide = (action, record) => run('decide', async () => {
    const found = await service.decide(reading, action, record);
    setReading(found);
    if (action === 'use_existing') onOpenExisting?.(record, found);
    if (action === 'update_existing') onUpdateExisting?.(record, found);
    if (action === 'cancel') onCancel?.(found);
  });
  const discard = () => run('discard', async () => {
    const found = await service.finish(reading, 'cancelled');
    setReading(null); onCancel?.(found);
  });
  const skipValues = () => run('skip', async () => {
    if (reading.status === 'open') await service.finish(reading, 'cancelled');
    onSkip();
  });

  useEffect(() => {
    if (!autoStart || started.current || !options || !reader || reader !== 'local') return;
    started.current = true;
    start();                                  // the local rules read at once: nothing leaves this computer
  });

  const readers = options?.readers || [];
  const duplicates = reading?.duplicates || [];
  const decided = reading?.decision?.action;
  const waiting = duplicates.length > 0 && !decided;
  const fields = info?.fields || [];
  const values = reading?.values || {};
  const changed = new Set(reading?.changed || []);
  const label = name => fields.find(field => field.name === name)?.label || name;

  return (
    <section className="ai-reading" aria-labelledby={`${id}-title`} aria-busy={busy ? true : undefined}>
      <header className="ai-reading-head">
        <Sparkles size={18} aria-hidden="true" />
        <h3 id={`${id}-title`}>{title || `Dokument einlesen: ${info?.label || ''}`}</h3>
        {source?.name && <span className="text-muted">{source.name}</span>}
      </header>
      {info && !info.may_use && <p role="alert" className="alert alert-error">Hier einlesen darf, wer die Werte auch speichern darf.</p>}
      {!reading && options && (
        <div className="ai-reading-start">
          <fieldset className="ai-reading-readers">
            <legend>Wer liest das Dokument?</legend>
            {readers.map(item => {
              const blocked = item.ai ? (!item.available || !info?.ai_allowed) : info?.needs_ai;
              return <label key={item.id} className={blocked ? 'is-unavailable' : undefined}>
                <input type="radio" name={`${id}-reader`} value={item.id} checked={reader === item.id} disabled={blocked}
                  onChange={() => setReader(item.id)} />
                {item.label}{item.ai && !item.available && <small> – nicht verbunden</small>}
                {item.ai && item.available && !info?.ai_allowed && <small> – in den Einstellungen aus</small>}
              </label>;
            })}
          </fieldset>
          {reader && <p className="form-hint">{READER_HINTS[reader]}</p>}
          {info?.ai_reason && <p className="form-hint">{info.ai_reason}</p>}
          {readers.every(item => !item.ai || !item.available) && <p className="form-hint">
            Für Scans, Fotos und das Gespräch über das Dokument im <Link to="/assistant">Assistenten</Link> ein Claude- oder ChatGPT-Konto verbinden.</p>}
          {reader && reader !== 'local' && <label className="ai-reading-instruction">Was soll mit dem Dokument geschehen? (freiwillig)
            <textarea rows={2} maxLength={4000} value={instruction} onChange={event => setInstruction(event.target.value)}
              placeholder="z. B. „Nur die Heizkosten übernehmen“ oder „Das ist eine Gutschrift zur Rechnung vom März“" /></label>}
          <div className="ai-reading-actions">
            <button type="button" className="btn btn-primary" disabled={!reader || Boolean(busy) || (info && !info.may_use)} onClick={start}>
              <Sparkles size={16} aria-hidden="true" /> {busy === 'start' ? 'Liest …' : 'Einlesen'}</button>
            {onSkip && <button type="button" className="btn btn-secondary" disabled={Boolean(busy)} onClick={onSkip}>Ohne Einlesen weiter</button>}
          </div>
        </div>
      )}
      {!options && !error && <p role="status" className="text-muted">Wird vorbereitet …</p>}
      {error && <p role="alert" className="alert alert-error">{error}</p>}

      {reading && <>
        {waiting && <div className="ai-reading-duplicates" role="alertdialog" aria-labelledby={`${id}-dup`}>
          <p id={`${id}-dup`}><strong>Zu diesem Dokument gibt es vermutlich schon {duplicates.length === 1 ? 'einen Eintrag' : `${duplicates.length} Einträge`}.</strong> Was soll geschehen?</p>
          <ul>{duplicates.map(item => <li key={`${item.kind}:${item.id}`}>
            <span><Link to={item.href}>{item.title}</Link> <small className="text-muted">– {item.reason_label}{item.details ? ` · ${item.details}` : ''}</small></span>
            <span className="ai-reading-dup-actions">
              <button type="button" className="btn btn-sm btn-secondary" disabled={Boolean(busy)} onClick={() => decide('use_existing', item)}>Öffnen</button>
              {item.can_update && onUpdateExisting && <button type="button" className="btn btn-sm btn-secondary" disabled={Boolean(busy)}
                onClick={() => decide('update_existing', item)}>Mit den gelesenen Werten ergänzen</button>}
            </span>
          </li>)}</ul>
          <div className="ai-reading-actions">
            <button type="button" className="btn btn-primary" disabled={Boolean(busy)} onClick={() => decide('create_new')}>Trotzdem neu anlegen</button>
            <button type="button" className="btn btn-ghost" disabled={Boolean(busy)} onClick={() => decide('cancel')}>Abbrechen</button>
          </div>
        </div>}

        <ol className="ai-chat" aria-label="Gespräch zum Dokument">
          {(reading.messages || []).map(item => <li key={item.id} className={`ai-chat-${item.role}`}>
            <span className="ai-chat-who">{item.role === 'user' ? 'Sie' : reading.reader_label}</span>
            <span className="ai-chat-text">{item.text}</span>
            {item.role === 'assistant' && item.changed?.length > 0 && <span className="ai-chat-changed">
              {item.changed.length === 1 && item.changed[0] === 'extraction' ? 'Werte neu gelesen'
                : `Geändert: ${item.changed.map(label).join(', ')}`}</span>}
          </li>)}
          <li ref={chatEnd} aria-hidden="true" className="ai-chat-end" />
        </ol>
        {busy === 'say' && <p role="status" className="text-muted">{reading.reader_label} antwortet …</p>}
        {reading.questions?.length > 0 && <div className="ai-reading-questions"><strong>Rückfragen</strong>
          <ul>{reading.questions.map(text => <li key={text}>{text}</li>)}</ul></div>}
        {reading.notes?.length > 0 && <ul className="ai-reading-notes">{reading.notes.map(text => <li key={text}>{text}</li>)}</ul>}
        {reading.dropped?.length > 0 && <p className="form-hint">Nicht übernommen, weil ungültig: {reading.dropped.join(', ')}. Bitte von Hand prüfen.</p>}

        {fields.length > 0 && <div className="table-scroll"><table className="data-table ai-reading-values">
          <caption className="sr-only">Gelesene Werte</caption>
          <thead><tr><th>Feld</th><th>Wert</th><th>Beleg im Dokument</th><th>Sicherheit</th></tr></thead>
          <tbody>{fields.filter(field => values[field.name]).map(field => {
            const item = values[field.name];
            return <tr key={field.name} className={changed.has(field.name) ? 'is-changed' : undefined}>
              <th scope="row">{field.label}{changed.has(field.name) && <span className="badge badge-blue ai-badge">neu</span>}</th>
              <td>{shownValue(field, item.value)}</td>
              <td className="ai-evidence">{item.evidence ? `„${item.evidence}“` : '—'}</td>
              <td>{item.confidence ? <span className={`ai-confidence is-${item.confidence}`}>{CONFIDENCE_LABELS[item.confidence]}</span> : '—'}</td>
            </tr>;
          })}</tbody>
        </table></div>}
        {fields.length > 0 && Object.keys(values).length === 0 && <p className="text-muted">Keine Werte erkannt.</p>}
        {typeof children === 'function' ? children(reading, setReading) : children}

        {reading.chat ? <div className="ai-chat-input" role="group" aria-label="Nachricht schreiben">
          <label htmlFor={`${id}-message`} className="sr-only">Nachricht an {reading.reader_label}</label>
          <MessageSquare size={18} aria-hidden="true" />
          <textarea id={`${id}-message`} rows={2} maxLength={4000} value={message} disabled={busy === 'say' || reading.status !== 'open'}
            onChange={event => setMessage(event.target.value)}
            onKeyDown={event => { if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) send(event); }}
            placeholder="Was soll mit dem Dokument geschehen, was ist falsch erkannt? (Strg+Enter sendet)" />
          <button type="button" className="btn btn-secondary" disabled={!message.trim() || Boolean(busy) || reading.status !== 'open'}
            aria-label="Senden" onClick={send}><Send size={16} aria-hidden="true" /> Senden</button>
        </div> : reading.reader === 'local' && <p className="form-hint">Ein Gespräch über das Dokument ist mit Claude oder ChatGPT möglich.</p>}

        <div className="ai-reading-actions">
          {onApply && <button type="button" className="btn btn-primary" disabled={waiting || decided === 'cancel' || reading.status !== 'open' || Boolean(busy)}
            onClick={() => onApply(reading)}>{applyLabel}</button>}
          {onSkip && <button type="button" className="btn btn-secondary" disabled={Boolean(busy) || decided === 'cancel'} onClick={skipValues}>
            Ohne die Werte weiter</button>}
          <button type="button" className="btn btn-secondary" disabled={Boolean(busy)} onClick={() => setReading(null)}>Neu einlesen</button>
          <button type="button" className="btn btn-ghost" disabled={Boolean(busy) || reading.status !== 'open'} onClick={discard}>Verwerfen</button>
        </div>
        {waiting && <p className="form-hint">Bitte zuerst entscheiden, was mit dem vorhandenen Eintrag geschehen soll.</p>}
      </>}
    </section>
  );
}
