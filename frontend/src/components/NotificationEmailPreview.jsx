import { useRef, useState } from 'react';
import { api } from '../api';
import { useCanWrite } from '../contexts/AuthContext';
import { privateStorageKey } from '../utils/workspaceIdentity';

export default function NotificationEmailPreview({ notice }) {
  const canWrite = useCanWrite('/messages');
  const [choices, setChoices] = useState(null);
  const [connection, setConnection] = useState('');
  const [preview, setPreview] = useState(null);
  const [error, setError] = useState(null);
  const [conflict, setConflict] = useState(false);
  const [sourceRevision, setSourceRevision] = useState(notice.target?.revision);
  const [busy, setBusy] = useState(false);
  const pending = useRef(null);
  const storage = privateStorageKey(`notification-email:${notice.id}`);
  const run = async action => {
    if (busy) return;
    setBusy(true); setError(null); setConflict(false); const same = api.captureSession();
    try { await action(same); } catch (failure) {
      setConflict(failure.statusCode === 409);
      setError(failure.message || 'Befehl nicht bestätigt. Denselben Befehl erneut abgleichen.');
    }
    finally { setBusy(false); }
  };
  const load = () => run(async same => {
    try { pending.current = JSON.parse(sessionStorage.getItem(storage) || 'null'); } catch { /* optional recovery */ }
    if (pending.current?.item_id) {
      const result = await api.get(`/messages/communication/${encodeURIComponent(pending.current.item_id)}`);
      same(); setPreview(result); return;
    }
    const result = await api.get('/messages/communication/connections/choices'); same(); setChoices(result);
    setConnection(pending.current?.body?.connection_id || result.items[0]?.id || '');
  });
  const inspect = () => run(async same => {
    const selected = choices.items.find(item => item.id === connection);
    if (!selected) throw new Error('Bitte eine aktive E-Mail-Verbindung auswählen.');
    if (!pending.current || pending.current.body?.connection_id !== connection) {
      pending.current = { body: { connection_id: selected.id, config_revision: selected.revision,
        source_revision: sourceRevision, idempotency_key: crypto.randomUUID() } };
    }
    try { sessionStorage.setItem(storage, JSON.stringify(pending.current)); } catch { /* optional recovery */ }
    const result = await api.post(`/notifications/${encodeURIComponent(notice.id)}/email-preview`, pending.current.body);
    same(); setPreview(result); pending.current = { item_id: result.id };
    try { sessionStorage.setItem(storage, JSON.stringify(pending.current)); } catch { /* optional recovery */ }
  });
  const release = (retry = false) => run(async same => {
    const operation = retry ? 'retry' : 'confirm';
    if (!pending.current?.confirmation || pending.current.operation !== operation) pending.current = { item_id: preview.id, operation,
      confirmation: { base_revision: preview.revision, mime_sha256: preview.mime_sha256, confirmed: true, idempotency_key: crypto.randomUUID() } };
    try { sessionStorage.setItem(storage, JSON.stringify(pending.current)); } catch { /* optional recovery */ }
    const result = await api.post(`/messages/communication/${encodeURIComponent(preview.id)}/${operation}`, pending.current.confirmation);
    same(); setPreview(result); pending.current = { item_id: result.id };
    try { sessionStorage.setItem(storage, JSON.stringify(pending.current)); } catch { /* optional recovery */ }
  });
  if (!canWrite || !notice.email_eligible || !notice.target || notice.archived_at) return null;
  return <section aria-label={`Persönliche E-Mail: ${notice.title}`}>
    <button type="button" disabled={busy} onClick={load}>Persönliche E-Mail-Vorschau öffnen</button>
    {choices && !preview && <>
      <label>E-Mail-Verbindung <select value={connection} disabled={busy} onChange={event => setConnection(event.target.value)}>
        <option value="">Bitte auswählen</option>{choices.items.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
      </select></label>
      {!choices.items.length && <p>Keine aktive E-Mail-Verbindung verfügbar. Die Integrationsverwaltung enthält die Verbindungseinstellungen.</p>}
      {choices.next_cursor && <button type="button" disabled={busy} onClick={() => run(async same => {
        const result = await api.get(`/messages/communication/connections/choices?cursor=${encodeURIComponent(choices.next_cursor)}`);
        same(); setChoices(current => ({ ...result, items: [...current.items, ...result.items] }));
      })}>Weitere E-Mail-Verbindungen</button>}
      <button type="button" disabled={busy || !connection} onClick={inspect}>E-Mail-Vorschau erstellen</button>
    </>}
    {preview && <>
      <p>Empfänger: {preview.to.join(', ')} · Status: {preview.state}</p>
      <strong>{preview.subject}</strong><pre style={{ whiteSpace: 'pre-wrap' }}>{preview.body}</pre>
      {preview.state === 'preview' && <><p>Die Vorschau ist gespeichert. Erst Ihre ausdrückliche Freigabe beauftragt den bestehenden E-Mail-Ausgang. Kanalwahl, Ruhezeiten und Quellrechte werden vor Versand erneut geprüft.</p>
        <button type="button" disabled={busy} onClick={() => release()}>Persönlichen E-Mail-Versand ausdrücklich freigeben</button></>}
      {['failed', 'blocked'].includes(preview.state) && <button type="button" disabled={busy} onClick={() => release(true)}>Nach Prüfung ausdrücklich erneut freigeben</button>}
      {preview.state === 'unknown' && <p role="status">Das DATA-Ergebnis ist unklar. Kein automatischer Neuversand. Der Versandbeleg muss zuerst abgeglichen werden.</p>}
      {preview.state === 'ready' && <p role="status">Versand ausdrücklich beauftragt. Der vorhandene E-Mail-Ausgang verarbeitet diesen Auftrag.</p>}
      {preview.state === 'accepted' && <p role="status">SMTP-Annahme bestätigt; die Zustellung ist nicht nachgewiesen.</p>}
    </>}
    {error && <p role="alert">{error} Eingabe und unbestätigter Befehl bleiben in diesem Tab erhalten.</p>}
    {conflict && <button type="button" disabled={busy} onClick={() => run(async same => {
      const result = await api.get(`/notifications/${encodeURIComponent(notice.id)}/source`); same();
      pending.current = null; setSourceRevision(result.source.revision); setPreview(null);
      try { sessionStorage.removeItem(storage); } catch { /* optional recovery */ }
      const available = await api.get('/messages/communication/connections/choices'); same(); setChoices(available);
      setConnection(available.items[0]?.id || '');
    })}>Abgewiesene Vorschau verwerfen und aktuellen Stand prüfen</button>}
  </section>;
}
