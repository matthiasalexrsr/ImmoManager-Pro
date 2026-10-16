import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../../api';
import { useCanWrite } from '../../contexts/AuthContext';
import useEntityFormDraft from '../../hooks/useEntityFormDraft';
import './communication.css';

const base = '/messages/communication';
const command = () => crypto.randomUUID();
const labels = { published: 'Gespeicherte Vorlagenfassung', manual_queued: 'Mahn-Entwurf wartet auf Freigabe', manual_draft: 'Manueller Mahnentwurf', manual_ready: 'Mahnung zum manuellen Versand bereit', manual_sent: 'Manueller Versand vermerkt', draft: 'Entwurf', preview: 'Vorschau – noch nicht freigegeben', ready: 'Zum Versand freigegeben', claimed: 'Versand wird vorbereitet', data_pending: 'Versandbestätigung steht aus', accepted: 'Vom Mailserver angenommen', failed: 'Sicher fehlgeschlagen', blocked: 'Versand gesperrt – Rechte oder Quellen geändert', released: 'Zum Versand freigegebener Entwurf', deferred: 'Eingang zurückgestellt – Original noch auf dem Mailserver', idle: 'Posteingang abrufbereit', unknown: 'Versandausgang unklar – nicht erneut senden', rejected: 'Nach Abgleich abgelehnt', assigned: 'Zugeordneter Eingang', review: 'Zuordnung prüfen' };
const empty = { to: '', cc: '', bcc: '', subject: '', body: '', attachments: [], connection_id: '', template_id: null, snippet_ids: [] };
const addresses = text => text.split(/[;,\n]/).map(value => value.trim()).filter(Boolean);
const draftFields = ['to', 'cc', 'bcc', 'subject', 'body', 'connection_id', 'template_id', 'reply_to_item_id', 'attachments', 'snippet_ids'].map(key => ({ key }));

export default function CommunicationCenter({ threads = [], onOpenThread }) {
  const canWrite = useCanWrite('/messages');
  const [kind, setKind] = useState('outbound');
  const [threadId, setThreadId] = useState('');
  const [rows, setRows] = useState({ items: [], total: null, next_cursor: null });
  const [selected, setSelected] = useState(null);
  const [form, setForm] = useState(empty);
  const [connections, setConnections] = useState([]);
  const [templates, setTemplates] = useState([]);
  const [documents, setDocuments] = useState([]);
  const [versions, setVersions] = useState([]);
  const [documentId, setDocumentId] = useState('');
  const [versionBefore, setVersionBefore] = useState(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [cleaning, setCleaning] = useState(false);
  const [evidence, setEvidence] = useState('');
  const [target, setTarget] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const epoch = useRef(0);
  const selectionEpoch = useRef(0);
  const formVersion = useRef(0);
  const cleanupActive = useRef(false);
  const pending = useRef(null);
  const loadGeneration = useRef(0);
  const versionGeneration = useRef(0);
  const writing = useRef(false);
  const thread = threads.find(item => item.id === threadId);
  const autosave = useEntityFormDraft({ context: 'email-compose', kind: 'message_thread', id: threadId,
    fields: draftFields, enabled: canWrite && Boolean(threadId) });

  useEffect(() => {
    const invalidate = () => { epoch.current++; loadGeneration.current++; pending.current = null; setRows({ items: [] }); setSelected(null); setForm(empty); setConnections([]); setDocuments([]); setTemplates([]); setVersions([]); setBusy(false); setError('Die Sitzung wurde geändert. Bitte neu laden.'); };
    window.addEventListener('workspace-owner', invalidate);
    window.addEventListener('workspace-logout', invalidate);
    const cleanup = () => { epoch.current++; loadGeneration.current++; };
    return () => { cleanup(); window.removeEventListener('workspace-owner', invalidate); window.removeEventListener('workspace-logout', invalidate); };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const current = api.captureSession();
    const options = { signal: controller.signal };
    const allPages = async path => {
      const items = []; let cursor;
      do { const page = await api.get(path + (cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''), options); current(); items.push(...page.items); cursor = page.next_cursor; } while (cursor && !controller.signal.aborted);
      return items;
    };
    Promise.all([allPages(`${base}/connections/choices?limit=50`), allPages(`${base}?kind=template`), api.list('/documents', options)])
      .then(([choices, values, files]) => { if (!controller.signal.aborted) { current(); setConnections(choices); setTemplates(values); setDocuments(files); } })
      .catch(failure => { if (!controller.signal.aborted) setError(failure.message || 'Auswahl konnte nicht geladen werden.'); });
    return () => controller.abort();
  }, [refresh]);

  const load = async (cursor = null, append = false) => {
    const attempt = ++loadGeneration.current;
    const identity = epoch.current; const current = api.captureSession();
    if (!append) setRows({ items: [], total: null, next_cursor: null });
    try {
      const query = new URLSearchParams({ kind, ...(threadId ? { thread_id: threadId } : {}), ...(cursor ? { cursor } : {}) });
      const page = await api.get(`${base}?${query}`);
      if (identity !== epoch.current || attempt !== loadGeneration.current) return;
      current(); setRows(previous => ({ ...page, items: append ? [...previous.items, ...page.items] : page.items }));
      setSelected(previous => {
        const fresh = previous && previous.kind !== 'draft' ? page.items.find(item => item.id === previous.id) : null;
        return fresh && (fresh.revision || 0) >= (previous.revision || 0) ? fresh : previous;
      });
      setError('');
    } catch (failure) { if (identity === epoch.current && attempt === loadGeneration.current) {
      setRows({ items: [], total: null });
      if ([401, 403, 404].includes(failure.statusCode)) { setSelected(null); setForm(empty); }
      setError(failure.message || 'Kommunikation konnte nicht geladen werden.');
    } }
  };
  useEffect(() => { load(); /* Selection has its own generation guard. */
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind, threadId, refresh]);

  const run = async (path, payload, method = 'post', expectedSelection = selectionEpoch.current) => {
    if (writing.current) return;
    if (pending.current) {
      setError('Eine frühere Speicherung ist noch unbestätigt. Bitte zuerst „Speicherung abgleichen“ wählen.'); return;
    }
    const identity = epoch.current; const selection = expectedSelection; const current = api.captureSession();
    const request = pending.current || { path, payload: { ...payload, idempotency_key: payload.idempotency_key || command() }, method, selection };
    pending.current = request; writing.current = true; setBusy(true); setError('');
    try {
      const result = await api[request.method](request.path, request.payload);
      if (identity !== epoch.current) return;
      current(); pending.current = null;
      if (selection !== selectionEpoch.current) return;
      setSelected(result?.id ? result : null); setConfirmed(false); setNotice(result?.received != null ? `${result.received} Nachrichten archiviert. Weitere Nachrichten mit „Eingang abrufen“ laden.` : 'Gespeichert.'); await load(); return result;
    } catch (failure) {
      if (identity !== epoch.current) return;
      if ([400, 401, 403, 404, 409, 422].includes(failure.statusCode)) pending.current = null;
      setError(failure.message || 'Die Speicherung wurde nicht bestätigt. Eingaben bleiben erhalten.');
    } finally { writing.current = false; if (identity === epoch.current) setBusy(false); }
  };
  const retryPending = () => { const request = pending.current; if (!request) return; pending.current = null; run(request.path, request.payload, request.method, request.selection); };
  const refreshAll = async () => {
    setRefresh(value => value + 1);
    if (!selected || ['draft', 'manual_dunning'].includes(selected.kind)) return;
    const id = selected.id; const selection = selectionEpoch.current; const identity = epoch.current;
    const current = api.captureSession();
    try {
      const row = await api.get(`${base}/${encodeURIComponent(id)}`);
      if (identity !== epoch.current || selection !== selectionEpoch.current) return;
      current();
      if (row?.id !== id) throw new Error('Der aktuelle Nachrichtenstand wurde nicht bestätigt.');
      setSelected(previous => previous?.id === id && row.revision >= previous.revision ? row : previous);
    } catch (failure) {
      if (identity !== epoch.current || selection !== selectionEpoch.current) return;
      if ([401, 403, 404].includes(failure.statusCode)) { setSelected(null); setForm(empty); }
      setError(failure.message || 'Der aktuelle Nachrichtenstand konnte nicht geladen werden.');
    }
  };
  const updateForm = next => { if (cleanupActive.current) return; formVersion.current++; setForm(next); autosave.stage(next); setConfirmed(false); };
  const change = (key, value) => updateForm({ ...form, [key]: value });
  const recoverDraft = async () => {
    try { await autosave.compare(); await autosave.recover(autosave.recovery.values); setForm({ ...empty, ...autosave.recovery.values }); }
    catch (failure) { setError(failure.message || 'Der Entwurf konnte nicht wiederhergestellt werden.'); }
  };
  const newDraft = () => { selectionEpoch.current++; formVersion.current++; setSelected(null); setForm({ ...empty, subject: thread?.subject || '' }); setNotice(''); setConfirmed(false); };
  const open = row => {
    selectionEpoch.current++; formVersion.current++;
    setSelected(row); setConfirmed(false); setEvidence(''); setTarget('');
    if (row.kind === 'draft') {
      setThreadId(row.thread_id);
      setForm({ ...row, to: row.to.join('; '), cc: row.cc.join('; '), bcc: row.bcc.join('; ') });
    }
  };
  const save = async () => {
    if (!thread) { setError('Bitte eine Konversation auswählen.'); return; }
    const connection = connections.find(item => item.id === form.connection_id);
    if (!connection) { setError('Bitte eine freigegebene E-Mail-Verbindung auswählen.'); return; }
    const version = formVersion.current;
    const result = await run(selected?.kind === 'draft' ? `${base}/drafts/${selected.id}` : `${base}/drafts`, {
      thread_id: thread.id, source_revision: thread.updated_at, connection_id: connection.id, config_revision: connection.revision,
      to: addresses(form.to), cc: addresses(form.cc), bcc: addresses(form.bcc), subject: form.subject, body: form.body,
      attachments: form.attachments, template_id: form.template_id || null, reply_to_item_id: form.reply_to_item_id || null,
      snippet_ids: form.snippet_ids || [],
      ...(selected?.kind === 'draft' ? { base_revision: selected.revision } : {}),
    }, selected?.kind === 'draft' ? 'put' : 'post');
    if (formVersion.current !== version) return;
    if (result) {
      cleanupActive.current = true; setCleaning(true);
      try { await autosave.clear({ completed: true }); }
      catch (failure) { setError(failure.message || 'Der Entwurf ist gespeichert; die private Sicherung konnte nicht abgeschlossen werden.'); return; }
      finally { cleanupActive.current = false; setCleaning(false); }
    }
    return result;
  };
  const loadVersions = async (id, before = null) => {
    const versionAttempt = ++versionGeneration.current;
    const identity = epoch.current; const current = api.captureSession();
    setDocumentId(id); setVersions([]); setVersionBefore(null);
    if (!id) return;
    try { const page = await api.get(`${base}/attachments/${encodeURIComponent(id)}/versions${before ? `?before=${before}` : ''}`);
      if (identity !== epoch.current || versionAttempt !== versionGeneration.current) return; current(); setVersions(page.items); setVersionBefore(page.next_before);
    } catch (failure) { if (identity === epoch.current) setError(failure.message || 'Originalfassungen konnten nicht geladen werden.'); }
  };
  const download = async (row, part) => {
    const identity = epoch.current; const current = api.captureSession();
    try { const blob = await api.getBlob(row.kind === 'manual_dunning' ? `/dunning/outbox/${row.id}/eml` : `${base}/${row.id}/original${part != null ? `?part=${part}` : ''}`);
      if (identity !== epoch.current) return; current(); const url = URL.createObjectURL(blob); const link = document.createElement('a'); link.href = url; link.download = part == null ? 'nachricht.eml' : row.attachments[part].filename; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (failure) { if (identity === epoch.current) setError(failure.message || 'Das Original konnte nicht geladen werden.'); }
  };

  return <section className="communication-center" aria-label="E-Mail und Empfang">
    <h2>E-Mail und Empfang</h2>
    <p>Vorschauen versenden nichts. Die Freigabe startet den Versand über den Hintergrundauftrag. „Angenommen“ bestätigt die Annahme durch den Mailserver; eine Zustellung ist damit nicht nachgewiesen.</p>
    <Link to="/dunning">Manuellen Mahn-Postausgang öffnen</Link>
    {!canWrite && <p>Nur Lesen: Entwürfe und Versand können nicht geändert werden.</p>}
    <div className="communication-controls">
      <label>Konversation<select disabled={cleaning} value={threadId} onChange={event => { selectionEpoch.current++; formVersion.current++; setThreadId(event.target.value); setSelected(null); setForm(empty); }}><option value="">Gesamter Postausgang / ungeklärter Eingang</option>{threads.map(item => <option key={item.id} value={item.id}>{item.subject}</option>)}</select></label>
      <label>Ansicht<select disabled={cleaning} value={kind} onChange={event => { selectionEpoch.current++; setKind(event.target.value); setSelected(null); }}><option value="outbound">Postausgang</option><option value="manual_dunning">Manueller Mahn-Postausgang</option><option value="inbound">Posteingang</option><option value="draft">Meine Entwürfe</option><option value="template">Vorlagenfassungen</option><option value="mailbox">Abruffortschritt und Eingangsfehler</option></select></label>
      <button className="btn btn-secondary" onClick={refreshAll}>Aktualisieren</button>
      {canWrite && <button className="btn btn-primary" disabled={!threadId || busy || cleaning} onClick={newDraft}>E-Mail entwerfen</button>}
    </div>
    {error && <div role="alert">{error}{pending.current && <button disabled={busy} onClick={retryPending}>Speicherung abgleichen</button>}</div>}
    {notice && <p role="status">{notice}</p>}
    <div className="communication-layout">
      <div><p>{rows.total == null ? 'Bestand nicht geladen' : `${rows.total} Einträge`}</p>
        {rows.items.length === 0 && rows.total === 0 && <p>Keine Einträge in dieser Ansicht.</p>}
        <ul className="communication-list">{rows.items.map(row => <li key={row.id}><button disabled={cleaning} aria-pressed={selected?.id === row.id} onClick={() => open(row)}><strong>{row.subject || row.name || 'Ohne Betreff'}</strong><span>{labels[row.state] || row.state}</span><time>{row.created_at?.slice(0, 16).replace('T', ' ')}</time></button></li>)}</ul>
        {rows.next_cursor && <button onClick={() => load(rows.next_cursor, true)}>Weitere Einträge laden</button>}
      </div>
      <div>
        {canWrite && threadId && (!selected || (selected.kind === 'draft' && selected.state === 'draft')) && <form onSubmit={event => { event.preventDefault(); save(); }}>
          <fieldset disabled={cleaning || (autosave.enabled && !autosave.ready)}>
          <h3>{selected ? 'Entwurf bearbeiten' : 'Neue E-Mail'}</h3>
          {autosave.recovery && <div role="status"><p>Ein privater E-Mail-Arbeitsstand wurde wiedergefunden: {autosave.recovery.values.subject}</p><button type="button" onClick={recoverDraft}>Arbeitsstand übernehmen</button><button type="button" onClick={() => autosave.clear()}>Arbeitsstand verwerfen</button></div>}
          {autosave.error && <div role="alert">{autosave.error}<button type="button" onClick={autosave.retry}>Entwurfssicherung wiederholen</button></div>}
          <label>E-Mail-Verbindung<select required value={form.connection_id} onChange={event => change('connection_id', event.target.value)}><option value="">Bitte auswählen</option>{connections.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
          <label>Vorlagenfassung<select value={form.template_id || ''} onChange={event => { const template = templates.find(item => item.id === event.target.value); if (template) updateForm({ ...form, subject: template.subject, body: template.body, template_id: template.id }); }}><option value="">Keine Vorlage</option>{templates.filter(item => item.usage !== 'snippet').map(item => <option key={item.id} value={item.id}>{item.name} · {item.created_at?.slice(0, 16)}</option>)}</select></label>
          <label>Textbaustein einfügen<select value="" onChange={event => { const snippet = templates.find(item => item.id === event.target.value); if (snippet) updateForm({ ...form, body: `${form.body}${form.body ? '\n' : ''}${snippet.body}`, snippet_ids: [...new Set([...(form.snippet_ids || []), snippet.id])] }); }}><option value="">Textbaustein auswählen</option>{templates.filter(item => item.usage === 'snippet').map(item => <option key={item.id} value={item.id}>{item.name} · {item.created_at?.slice(0, 16)}</option>)}</select></label>
          {['to', 'cc', 'bcc'].map(key => <label key={key}>{({ to: 'An', cc: 'Kopie (Cc)', bcc: 'Blindkopie (Bcc)' })[key]}<input value={form[key]} onChange={event => change(key, event.target.value)} placeholder="adresse@example.de; weitere@example.de" /></label>)}
          <label>Betreff<input required value={form.subject} onChange={event => change('subject', event.target.value)} /></label>
          <label>Nachricht<textarea required rows={8} value={form.body} onChange={event => change('body', event.target.value)} /></label>
          <fieldset><legend>Freigegebene Originalanhänge</legend>
            <label>Dokument<select value={documentId} onChange={event => loadVersions(event.target.value)}><option value="">Dokument auswählen</option>{documents.map(item => <option key={item.id} value={item.id}>{item.title}</option>)}</select></label>
            {documentId && versions.length === 0 && <p>Keine archivierte Originalfassung verfügbar.</p>}
            {versions.map(version => <button type="button" key={version.id} onClick={() => { if (!form.attachments.some(item => item.version_id === version.id && item.document_id === documentId)) change('attachments', [...form.attachments, { document_id: documentId, version_id: version.id, sha256: version.sha256, document_revision: version.document_revision || null }]); }}>{version.filename} · Fassung {version.number} hinzufügen</button>)}
            {versionBefore && <button type="button" onClick={() => loadVersions(documentId, versionBefore)}>Ältere Originalfassungen</button>}
            <ul>{form.attachments.map(item => <li key={`${item.document_id}:${item.version_id}`}><Link to={`/documents?focus_id=${encodeURIComponent(item.document_id)}`}>Originaldokument</Link> · {item.sha256.slice(0, 12)} <button type="button" onClick={() => change('attachments', form.attachments.filter(value => value !== item))}>Entfernen</button></li>)}</ul>
          </fieldset>
          <button className="btn btn-primary" disabled={busy}>Entwurf speichern</button>
          {selected && <button type="button" disabled={busy} onClick={async () => { const saved = await save(); if (saved) run(`${base}/${saved.id}/preview`, { base_revision: saved.revision }); }}>Entwurf speichern und Vorschau einfrieren</button>}
          <button type="button" disabled={busy || !form.subject} onClick={() => run(`${base}/templates`, { name: form.subject, subject: form.subject, body: form.body, predecessor_id: form.template_id || null })}>Als neue Vorlagenfassung speichern</button>
          <button type="button" disabled={busy || !form.subject || !form.body} onClick={() => run(`${base}/templates`, { name: form.subject, subject: '', body: form.body, usage: 'snippet', predecessor_id: form.snippet_ids?.at(-1) || null })}>Als neuen Textbaustein speichern</button>
          </fieldset>
        </form>}
        {selected && (!canWrite || selected.kind !== 'draft' || selected.state !== 'draft') && <article>
          <h3>{selected.subject || selected.name}</h3><p><strong>{labels[selected.state] || selected.state}</strong></p>
          {selected.sender && <p>Von: {selected.sender}</p>}
          {['to', 'cc', 'bcc'].map(key => selected[key]?.length ? <p key={key}>{key.toUpperCase()}: {selected[key].join('; ')}</p> : null)}
          <p className="communication-body">{selected.body}</p>
          {selected.kind === 'manual_dunning' && <p>Der bestehende manuelle Versandvermerk bleibt im Mahnwesen. Diese Ansicht erstellt keine zweite Nachricht. <Link to={selected.source_href}>Vertragsakte</Link> <Link to="/dunning">Versand im Mahnwesen vermerken</Link></p>}
          {selected.thread_id && <Link to={`/messages?focus_id=${encodeURIComponent(selected.thread_id)}`} onClick={() => onOpenThread?.(selected.thread_id)}>Zugehörige Konversation</Link>}
          {!['template', 'mailbox', 'draft'].includes(selected.kind) && selected.raw_available !== false && (selected.kind !== 'manual_dunning' || selected.manual_eml_available) && <button onClick={() => download(selected)}>Unverändertes E-Mail-Original herunterladen</button>}
          <ul>{selected.attachments?.map((item, index) => <li key={item.version_id || index}>{item.document_id ? <Link to={`/documents?focus_id=${encodeURIComponent(item.document_id)}`}>Originalanhang · {item.sha256.slice(0, 12)}</Link> : item.downloadable === false ? <span>{item.filename}: im E-Mail-Original enthalten</span> : <button onClick={() => download(selected, index)}>{item.filename} herunterladen</button>}</li>)}</ul>
          {selected.kind === 'mailbox' && <p>Letzte UID: {selected.uid} · UIDVALIDITY: {selected.uidvalidity || 'noch nicht bekannt'}{selected.last_error ? ` · Abruf unterbrochen bei UID ${selected.last_error.uid || 'unbekannt'}` : ''}</p>}
          {canWrite && selected.kind === 'mailbox' && selected.last_error?.uid && <div><p>Das Original ist noch nicht archiviert. Nach ausdrücklicher Zurückstellung können spätere Nachrichten abgerufen werden; der fehlende Eingang bleibt einzeln nachholbar.</p><label>Begründung<textarea value={evidence} onChange={event => setEvidence(event.target.value)} /></label><button disabled={busy || evidence.trim().length < 10} onClick={() => run(`${base}/mailboxes/${selected.id}/skip`, { base_revision: selected.revision, reason: evidence })}>Diesen Eingang zurückstellen</button></div>}
          {canWrite && selected.state === 'deferred' && <button disabled={busy} onClick={() => run(`${base}/${selected.id}/receive-again`, { base_revision: selected.revision })}>Original vom Mailserver nachholen</button>}
          {canWrite && ['preview', 'failed', 'blocked'].includes(selected.state) && <div><label className="communication-confirm"><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />Ich habe Empfänger, Text und Originalanhänge geprüft und bestätige den Versand.</label><button className="btn btn-primary" disabled={busy || !confirmed} onClick={() => run(`${base}/${selected.id}/${selected.state !== 'preview' ? 'retry' : 'confirm'}`, { base_revision: selected.revision, mime_sha256: selected.mime_sha256, confirmed: true })}>{selected.state !== 'preview' ? 'Versand ausdrücklich wiederholen' : 'Versand verbindlich freigeben'}</button></div>}
          {canWrite && selected.state === 'unknown' && <div><p>Bitte anhand eines externen Belegs abgleichen. Eine erneute Sendung ist gesperrt.</p><label>Abgleichbeleg<textarea value={evidence} onChange={event => setEvidence(event.target.value)} /></label>{['accepted', 'rejected'].map(decision => <button key={decision} disabled={busy || evidence.trim().length < 10} onClick={() => run(`${base}/${selected.id}/reconcile`, { base_revision: selected.revision, decision, evidence })}>{decision === 'accepted' ? 'Annahme nachgewiesen' : 'Ablehnung nachgewiesen'}</button>)}</div>}
          {canWrite && selected.kind === 'inbound' && selected.state === 'review' && <div><p>Keine eindeutige Zuordnung. Bitte den Vorgang anhand des Originals prüfen.</p><label>Zielkonversation<select value={target} onChange={event => setTarget(event.target.value)}><option value="">Bitte auswählen</option>{threads.map(item => <option key={item.id} value={item.id}>{item.subject}</option>)}</select></label><label>Begründung<textarea value={evidence} onChange={event => setEvidence(event.target.value)} /></label><button disabled={busy || !target || evidence.trim().length < 5} onClick={() => run(`${base}/${selected.id}/assign`, { base_revision: selected.revision, thread_id: target, source_revision: threads.find(item => item.id === target).updated_at, reason: evidence })}>Eingang zuordnen</button></div>}
          {canWrite && selected.kind === 'inbound' && selected.thread_id && <button onClick={() => { setThreadId(selected.thread_id); setForm({ ...empty, subject: `Re: ${selected.subject}`, reply_to_item_id: selected.id }); setSelected(null); }}>Antwort entwerfen</button>}
          <ol>{selected.history?.map((entry, index) => <li key={index}>{entry.at?.slice(0, 19).replace('T', ' ')} · {labels[entry.state] || entry.state}{entry.detail ? ` · ${entry.detail}` : ''}</li>)}</ol>
        </article>}
      </div>
    </div>
    {canWrite && <details><summary>Posteingang abrufen</summary><p>Der Abruf liest den IMAP-Ordner, verändert dort keine Nachrichten und löscht nichts.</p>{connections.map(connection => <button key={connection.id} disabled={busy} onClick={() => run(`${base}/receive/${connection.id}`, { config_revision: connection.revision })}>{connection.name}: Eingang abrufen</button>)}</details>}
  </section>;
}
