import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { api } from '../../api';
import { base64Blob, blobBase64 } from './documentWorkApi';
import UnsavedNavigationGuard, { NavigationScopeNotice } from '../../components/UnsavedNavigationGuard';
import { navigationDiscardLabel } from '../../components/navigationProtectionContext';
import { useTranslation } from '../../i18n';
import { loadDocumentEditor } from './documentEditorRuntime';

const DOCX = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';

export default function DocxEditor({ documentId, session, onSession, onPublished, disabled, onLeaveGuard }) {
  const { locale } = useTranslation();
  const host = useRef(null);
  const editor = useRef(null);
  const currentSession = useRef(session);
  const pending = useRef(null);
  const saving = useRef(false);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [status, setStatus] = useState('Editor wird geöffnet …');
  const [track, setTrack] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [leaveRequest, setLeaveRequest] = useState(null);
  const [leaveBlocked, setLeaveBlocked] = useState(false);
  const keepEditingRef = useRef(null);
  const allowRouteLeaveRef = useRef(false);
  const routeBlocked = useCallback(request => {
    if (request.cancelled || request.pending) {
      setLeaveRequest(null);
      if (request.pending) setLeaveBlocked(true);
      return;
    }
    setLeaveRequest(request);
  }, []);
  useEffect(() => { if (leaveRequest) keepEditingRef.current?.focus(); }, [leaveRequest]);
  useEffect(() => { if (!busy && !pending.current) setLeaveBlocked(false); }, [busy, error]);
  const check = useRef(null);
  currentSession.current = session;
  const requestLeave = useCallback(proceed => {
    if (busy || pending.current) { setLeaveBlocked(true); return; }
    if (ready && !disabled) {
      setLeaveRequest({ proceed: () => {
        allowRouteLeaveRef.current = true;
        const result = proceed();
        if (result === false) allowRouteLeaveRef.current = false;
        return result;
      }, reset: () => {} });
      return;
    }
    proceed();
  }, [busy, ready, disabled]);
  useLayoutEffect(() => {
    onLeaveGuard?.(requestLeave);
    return () => onLeaveGuard?.(null);
  }, [onLeaveGuard, requestLeave]);

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    const current = api.captureSession();
    check.current = current;
    setReady(false); setError(null);
    (async () => {
      try {
        const saved = await api.get(`/documents/${documentId}/work/sessions/${session.session_id}`, { signal: controller.signal });
        const blob = saved.draft_base64 ? base64Blob(saved.draft_base64, DOCX)
          : await api.getBlob(`/documents/${documentId}/work/versions/${saved.version_id}/download`, { signal: controller.signal });
        current();
        if (!active) return;
        // Only a locally built, same-origin optional component. No CDN/account.
        const component = await loadDocumentEditor();
        current();
        if (!active) return;
        if (!document.querySelector('link[data-document-editor]')) {
          const css = document.createElement('link');
          css.rel = 'stylesheet'; css.href = '/document-editor/editor.css'; css.dataset.documentEditor = 'true';
          document.head.appendChild(css);
        }
        onSession(saved);
        editor.current = component.mountEditor(host.current, new File([blob], saved.filename, { type: DOCX }), {
          onReady: () => { if (active) { current(); setReady(true); setStatus(saved.draft_base64 ? 'Zwischenstand wiederhergestellt.' : 'Bearbeitung bereit.'); } },
          onError: failure => { if (active) { setReady(false); setError(failure?.message || 'Das Dokument konnte nicht geöffnet werden.'); } },
        });
      } catch (failure) {
        if (active) setError(`${failure.message} Die lokale DOCX-Komponente muss installiert und freigegeben sein. Ihre gespeicherten Fassungen bleiben erhalten.`);
      }
    })();
    return () => { active = false; controller.abort(); editor.current?.destroy(); editor.current = null; };
    // Session updates after autosave must not remount the editor or discard edits.
  }, [documentId, session.session_id, attempt, onSession]);

  const send = useCallback(async request => {
    if (saving.current) return;
    saving.current = true; setBusy(true); setError(null);
    try {
      check.current();
      const result = await api.post(`/documents/${documentId}/work/sessions/${request.sessionId}/docx`, request.payload);
      check.current();
      pending.current = null;
      onSession(result);
      setStatus(request.payload.autosave ? 'Zwischenstand auf dem Server gesichert.' : 'Neue unveränderliche Fassung gespeichert.');
      if (!request.payload.autosave) onPublished();
      return result;
    } catch (failure) { setError(failure.message); }
    finally { saving.current = false; setBusy(false); }
  }, [documentId, onSession, onPublished]);

  const save = useCallback(async autosave => {
    if (!editor.current || saving.current || pending.current || disabled) return;
    saving.current = true; setBusy(true);
    try {
      check.current();
      const blob = await editor.current.exportDocx();
      if (!(blob instanceof Blob)) throw new Error('Der Editor hat keine native DOCX-Datei geliefert.');
      const content = await blobBase64(blob);
      check.current();
      const current = currentSession.current;
      const request = { sessionId: current.session_id, payload: { command_key: crypto.randomUUID(),
        expected_version: current.version_id, expected_sha256: current.sha256,
        expected_document_revision: current.document_revision, session_revision: current.revision,
        content_base64: content, autosave } };
      pending.current = request;
      saving.current = false;
      if (!autosave) {
        const recovery = { ...request, payload: { ...request.payload, autosave: true, command_key: crypto.randomUUID() } };
        pending.current = recovery;
        const buffered = await send(recovery);
        if (!buffered) return;
        request.payload.session_revision = buffered.revision;
        pending.current = request;
      }
      await send(request);
    } catch (failure) { setError(failure.message); saving.current = false; setBusy(false); }
  }, [send, disabled]);

  useEffect(() => {
    if (!ready || disabled) return;
    const timer = setInterval(() => { void save(true); }, 20000);
    return () => clearInterval(timer);
  }, [ready, save, disabled]);
  useEffect(() => {
    if ((!ready || disabled) && !busy && !pending.current) return;
    const warn = event => { event.preventDefault(); event.returnValue = ''; };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [ready, busy, disabled, error]);

  return <section aria-label="DOCX bearbeiten">
    <UnsavedNavigationGuard when={(ready && !disabled) || busy || Boolean(pending.current)}
      pending={busy || Boolean(pending.current)} bypassRef={allowRouteLeaveRef}
      onBlocked={routeBlocked} label={`DOCX · ${session.filename || documentId}`} />
    {leaveBlocked && <p role="alert">Ein Speicherauftrag läuft noch oder sein Ergebnis ist ungewiss. Bitte erst das Ergebnis prüfen, bevor Sie den Editor verlassen.</p>}
    {leaveRequest && <div role="group" aria-label="DOCX-Editor verlassen">
      <p role="alert">Die Änderungen seit dem letzten gesicherten Zwischenstand können beim Verlassen verloren gehen.</p>
      <NavigationScopeNotice labels={leaveRequest.scopeLabels} locale={locale} />
      <button ref={keepEditingRef} type="button" className="btn btn-secondary" onClick={() => {
        leaveRequest.reset(); setLeaveRequest(null);
      }}>Weiter bearbeiten</button>
      <button type="button" className="btn btn-danger" disabled={busy || Boolean(pending.current)}
        onClick={() => leaveRequest.proceed()}>{navigationDiscardLabel(leaveRequest.scopeLabels, locale, 'Ohne weiteres Sichern verlassen')}</button>
    </div>}
    <p>Absätze, Zeichen, Tabellen und Seiten bearbeiten Sie direkt im lokalen Word-Editor. Die Speicherung übernimmt native DOCX-Bytes. Prüfen Sie komplexe Layouts zusätzlich in Ihrer Textverarbeitung.</p>
    {error && <div role="alert"><p>{error}</p>{pending.current
      ? <><button className="btn btn-secondary" disabled={busy} onClick={() => send(pending.current)}>Denselben Speicherauftrag wiederholen</button>
        <button className="btn btn-secondary" disabled={busy} onClick={() => { pending.current = null; setError(null); }}>Auftrag verwerfen, Eingaben behalten</button></>
      : <button className="btn btn-secondary" onClick={() => setAttempt(value => value + 1)}>Editor erneut laden</button>}</div>}
    <div className="document-work-toolbar">
      <button className="btn btn-primary" disabled={!ready || busy || disabled || Boolean(pending.current)} onClick={() => save(false)}>Neue Fassung speichern</button>
      <button className="btn btn-secondary" disabled={!ready || busy || disabled || Boolean(pending.current)} onClick={() => save(true)}>Zwischenstand sichern</button>
      <label><input type="checkbox" checked={track} disabled={!ready} onChange={event => {
        setTrack(event.target.checked); editor.current?.suggesting(event.target.checked);
      }} />Änderungen nachverfolgen</label>
    </div>
    <p role="status">{busy ? 'Wird gespeichert …' : status}</p>
    <div className="document-docx-host" ref={host} />
  </section>;
}
