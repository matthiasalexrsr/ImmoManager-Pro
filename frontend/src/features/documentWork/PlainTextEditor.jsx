import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../../api';
import { base64Blob } from './documentWorkApi';

export default function PlainTextEditor({ documentId, session, onSession, onPublished, disabled }) {
  const [text, setText] = useState('');
  const [ready, setReady] = useState(false);
  const [error, setError] = useState(null);
  const [status, setStatus] = useState('');
  const [busy, setBusy] = useState(false);
  const pending = useRef(null);
  const latest = useRef({ session, text });
  const busyRef = useRef(false);
  latest.current = { session, text };
  useEffect(() => {
    let active = true;
    const current = api.captureSession();
    (async () => {
      try {
        const restored = await api.get(`/documents/${documentId}/work/sessions/${session.session_id}`);
        const blob = restored.draft_base64 !== null ? base64Blob(restored.draft_base64, 'text/plain')
          : await api.getBlob(`/documents/${documentId}/work/versions/${restored.version_id}/download`);
        const value = await blob.text(); current();
        if (active) { onSession(restored); setText(value); setReady(true); }
      } catch (failure) { if (active) setError(failure.message); }
    })();
    return () => { active = false; };
  }, [documentId, session.session_id, onSession]);
  const send = useCallback(async payload => {
    if (busyRef.current) return;
    const current = api.captureSession();
    busyRef.current = true; setBusy(true);
    try {
      const result = await api.post(`/documents/${documentId}/work/sessions/${latest.current.session.session_id}/text`, payload);
      current(); pending.current = null; onSession(result); setError(null);
      setStatus(payload.autosave ? 'Zwischenstand auf dem Server gesichert.' : 'Neue Textfassung gespeichert.');
      if (!payload.autosave) onPublished();
      return result;
    } catch (failure) { setError(failure.message); }
    finally { busyRef.current = false; setBusy(false); }
  }, [documentId, onSession, onPublished]);
  const save = useCallback(async autosave => {
    if (!ready || disabled || busyRef.current || pending.current) return;
    const state = latest.current;
    const payload = { command_key: crypto.randomUUID(), expected_version: state.session.version_id,
      expected_sha256: state.session.sha256, expected_document_revision: state.session.document_revision,
      session_revision: state.session.revision, text: state.text, autosave };
    pending.current = payload;
    if (!autosave) {
      const recovery = { ...payload, autosave: true, command_key: crypto.randomUUID() };
      pending.current = recovery;
      const buffered = await send(recovery);
      if (!buffered) return;
      payload.session_revision = buffered.revision;
      pending.current = payload;
    }
    await send(payload);
  }, [ready, disabled, send]);
  useEffect(() => {
    if (!ready || disabled) return;
    const timer = setInterval(() => save(true), 20000);
    return () => clearInterval(timer);
  }, [save, ready, disabled]);
  return <section aria-label="Text bearbeiten"><label>Dokumenttext<textarea rows="20" value={text} disabled={!ready || disabled}
    onChange={event => setText(event.target.value)} /></label>
    {error && <div role="alert"><p>{error}</p>{pending.current && <>
      <button className="btn btn-secondary" disabled={busy} onClick={() => send(pending.current)}>Denselben Speicherauftrag wiederholen</button>
      <button className="btn btn-secondary" onClick={() => { pending.current = null; setError(null); }}>Auftrag verwerfen, Text behalten</button></>}</div>}
    <div className="document-work-toolbar"><button className="btn btn-primary" disabled={!ready || disabled || busy} onClick={() => save(false)}>Neue Textfassung speichern</button>
      <button className="btn btn-secondary" disabled={!ready || disabled || busy} onClick={() => save(true)}>Zwischenstand sichern</button></div><p role="status">{status}</p>
  </section>;
}
