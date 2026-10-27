import { useEffect, useRef, useState } from 'react';
import { api } from '../../api';
import './channels.css';

export default function WhatsAppInbox({ connectionId }) {
  const [page, setPage] = useState(null);
  const [threads, setThreads] = useState([]);
  const [threadId, setThreadId] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [cursor, setCursor] = useState(null);
  const [attempt, setAttempt] = useState(0);
  const generation = useRef(0);
  const pending = useRef(new Map());
  useEffect(() => {
    const current = ++generation.current; const controller = new AbortController(); const session = api.captureSession();
    setPage(null); setError('');
    Promise.all([api.get(`/integrations/connections/${connectionId}/whatsapp-inbox${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ''}`, { signal: controller.signal }),
      api.list('/messages/threads', { signal: controller.signal })]).then(([result, choices]) => { session(); if (current !== generation.current) return;
      if (!Array.isArray(result?.items) || !Array.isArray(choices)) throw new Error('Der WhatsApp-Eingang ist unvollständig. Bitte neu laden.');
      setPage(result); setThreads(choices); })
      .catch(reason => { if (current === generation.current && reason.name !== 'AbortError') setError(reason.message); });
    return () => { generation.current = current + 1; controller.abort(); };
  }, [connectionId, cursor, attempt]);
  async function assign(batchId, messageId) {
    const thread = threads.find(item => item.id === threadId); if (!thread) return;
    const current = generation.current; const session = api.captureSession(); setError('');
    const fingerprint = JSON.stringify([batchId, messageId, thread.id, thread.updated_at]);
    const idempotencyKey = pending.current.get(fingerprint) || crypto.randomUUID(); pending.current.set(fingerprint, idempotencyKey);
    try { await api.post(`/integrations/connections/${connectionId}/whatsapp-inbox/${batchId}/assign`, {
      idempotency_key: idempotencyKey, thread_id: thread.id, thread_revision: thread.updated_at, message_id: messageId, confirmed: true });
      session(); if (current === generation.current) { pending.current.delete(fingerprint); setNotice('Empfangsnachricht dem gewählten Thread zugeordnet. Sie steht dort mit Originalnachweis bereit.'); } }
    catch (reason) { if (current === generation.current) setError(reason.message); }
  }
  return <section className="channel-panel" aria-label="WhatsApp-Eingang"><h3>Signierter WhatsApp-Eingang</h3>
    <p>Webhook-Adresse für diese Verbindung: <code style={{ overflowWrap: 'anywhere' }}>/api/v1/channel-webhooks/whatsapp/{connectionId}</code></p>
    <p>Mehrdeutige Antworten bleiben hier zur Prüfung. Eine Zuordnung erfolgt nur auf Ihre ausdrückliche Auswahl.</p>
    {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    <button onClick={() => setAttempt(value => value + 1)}>Eingang neu laden</button>
    <label>Geprüfter Nachrichtenfaden<select value={threadId} onChange={event => setThreadId(event.target.value)}><option value="">Bitte wählen</option>
      {threads.map(thread => <option value={thread.id} key={thread.id}>{thread.subject}</option>)}</select></label>
    {page && <><p>{page.total} geprüfte Empfangsbelege</p>{page.items.map(batch => <article key={batch.id}>
      <time>{new Date(batch.created_at).toLocaleString('de-DE')}</time>
      {(batch.original.entry || []).flatMap(entry => entry.changes || []).flatMap(change => change.value?.messages || []).map(message => <div key={message.id}>
        <p>Von {message.from}: {message.text?.body || `Mediennachricht (${message.type})`}</p>
        <button disabled={!threadId} onClick={() => assign(batch.id, message.id)}>Diese Nachricht dem gewählten Faden zuordnen</button>
      </div>)}
      <details><summary>Signierten Empfangsnachweis ansehen</summary><pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{JSON.stringify(batch.original, null, 2)}</pre><p className="channel-hash">SHA-256: {batch.sha256}</p></details>
    </article>)}
    {page.next_cursor && <button onClick={() => setCursor(page.next_cursor)}>Weitere Empfangsbelege</button>}</>}
  </section>;
}
