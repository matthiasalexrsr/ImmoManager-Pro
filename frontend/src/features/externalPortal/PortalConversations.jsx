import { useRef, useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../../api';
import { saveBlob } from '../documentShare/documentShare';
import { usePortalAdminAction, usePortalAdminPage } from './adminHooks';
import useLookupChoices from '../../hooks/useLookupChoices';

const BASE = '/portal-admin';
const labels = { open: 'Gemeldet', in_progress: 'In Bearbeitung', completed: 'Abgeschlossen', cancelled: 'Abgebrochen' };

export default function PortalConversations({ caseId = null, caseRecord = null }) {
  const [skip, setSkip] = useState(0), [refresh, setRefresh] = useState(0), [selected, setSelected] = useState(null);
  const reload = () => setRefresh(value => value + 1);
  const [page, error] = usePortalAdminPage(`${BASE}/cases?skip=${skip}&limit=25${caseId ? `&case_id=${encodeURIComponent(caseId)}` : ''}`, refresh);
  return <section><h3>Externe Kommunikation</h3><p>Hier verfasste Antworten sind für die zugeordnete Partei sichtbar. Interne Aktennotizen werden nicht veröffentlicht.</p>
    {error && <p role="alert">{error} <button onClick={reload}>Neu laden</button></p>}
    {!page ? <p role="status">Portalvorgänge werden geladen …</p> : <><ul className="transfer-list">{page.items.map(row => <li key={row.id}><strong>{row.title}</strong> · {labels[row.status] || row.status} · {row.active ? 'Veröffentlicht' : 'Zugriff widerrufen'}
      <div className="transfer-actions"><Link to={`/maintenance/${row.case_id}`}>Interne Schadenakte</Link><button className="btn btn-secondary" onClick={() => setSelected(row.id)}>Nachrichten öffnen</button></div></li>)}</ul>
      {!page.items.length && <p>Keine Portalzuordnungen vorhanden.</p>}<nav aria-label="Portalvorgänge"><button disabled={!skip} onClick={() => setSkip(Math.max(0, skip - 25))}>Zurück</button><span> {page.total} Zuordnungen </span><button disabled={skip + 25 >= page.total} onClick={() => setSkip(skip + 25)}>Weiter</button></nav></>}
    {selected && <InternalConversation key={selected} identifier={selected} onChanged={reload} />}
    {caseRecord && <ShareCase key={caseRecord.id} caseRecord={caseRecord} onChanged={reload} />}
  </section>;
}

function InternalConversation({ identifier, onChanged }) {
  const [skip, setSkip] = useState(0), [refresh, setRefresh] = useState(0), [body, setBody] = useState(''), [reason, setReason] = useState(''), [downloadError, setDownloadError] = useState('');
  const [page, error] = usePortalAdminPage(`${BASE}/cases/${identifier}?skip=${skip}&limit=50`, refresh);
  const action = usePortalAdminAction(), heading = useRef(null);
  useEffect(() => { if (page) heading.current?.focus(); }, [page?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const reload = () => { setRefresh(value => value + 1); onChanged(); };
  return <section>{(error || action.error || downloadError) && <p role="alert">{error || action.error || downloadError} <button onClick={reload}>Aktuellen Verlauf laden</button></p>}
    {page && <><h4 tabIndex={-1} ref={heading}>{page.title}</h4><ol className="transfer-list">{page.messages.map(message => <li key={message.id}><strong>{message.sender_kind === 'external' ? 'Externe Partei' : 'Verwaltung'}</strong> · {new Date(message.created_at).toLocaleString('de-DE')}
      <p style={{ whiteSpace: 'pre-wrap' }}>{message.body}</p>{message.attachments.map(image => <button className="btn btn-secondary" key={image.id} onClick={async () => {
        try { const current = api.captureSession(); const blob = await api.getBlob(`${BASE}/attachments/${image.id}`); current(); saveBlob(blob, image.filename); } catch (failure) { setDownloadError(failure.message); }
      }}>{image.filename} herunterladen</button>)}</li>)}</ol>
      <nav aria-label="Externe Nachrichten"><button disabled={!skip} onClick={() => setSkip(Math.max(0, skip - 50))}>Zurück</button><span> {page.total} Nachrichten </span><button disabled={skip + 50 >= page.total} onClick={() => setSkip(skip + 50)}>Weiter</button></nav>
      <form onSubmit={async event => { event.preventDefault(); if (await action.perform(`${BASE}/cases/${identifier}/messages`, { expected_revision: page.revision, body })) { setBody(''); reload(); } }}>
        <label>Antwort an die externe Partei<textarea required maxLength={10000} disabled={action.busy} value={body} onChange={event => setBody(event.target.value)} /></label>
        <button className="btn btn-primary" disabled={action.busy || !body.trim()}>Antwort im Portal veröffentlichen</button></form>
      <form onSubmit={async event => { event.preventDefault(); if (await action.perform(`${BASE}/cases/${identifier}`, { expected_revision: page.revision, active: !page.active, reason }, 'put')) { setReason(''); reload(); } }}>
        <label>Begründung der Zugriffsänderung<textarea required minLength={10} maxLength={2000} value={reason} disabled={action.busy} onChange={event => setReason(event.target.value)} /></label>
        <button className="btn btn-secondary" disabled={action.busy}>{page.active ? 'Vorgang im Portal sperren' : 'Vorgang im Portal wieder freigeben'}</button></form>
    </>}
  </section>;
}

function ShareCase({ caseRecord, onChanged }) {
  const choices = useLookupChoices({ grants: `${BASE}/grants` });
  const candidates = (choices.data.grants || []).filter(row => row.active && row.identity_active && row.binding.property_id === caseRecord.property_id && row.binding.unit_id === caseRecord.unit_id);
  const [grantId, setGrantId] = useState(''), [title, setTitle] = useState(''), [reason, setReason] = useState(''), [notice, setNotice] = useState('');
  const action = usePortalAdminAction();
  return <details><summary>Diese Schadenakte ausdrücklich einer Portalpartei zuordnen</summary><form className="transfer-grid" onSubmit={async event => {
    event.preventDefault(); const grant = candidates.find(row => row.id === grantId); if (!grant) return;
    if (await action.perform(`${BASE}/grants/${grantId}/cases`, { grant_revision: grant.revision, case_id: caseRecord.id, case_updated_at: caseRecord.updated_at, title, reason })) { setNotice('Vorgang veröffentlicht. Interne Notizen bleiben in der internen Akte.'); onChanged(); }
  }}>
    {choices.error && <p role="alert">{choices.error} <button type="button" onClick={choices.reload}>Zuordnungen neu laden</button></p>}
    <label>Aktive Partei für diese Einheit<select required disabled={!choices.ready || action.busy} value={grantId} onChange={event => setGrantId(event.target.value)}><option value="">Bitte auswählen</option>{candidates.map(row => <option key={row.id} value={row.id}>{row.email}</option>)}</select></label>
    <label>Für die Partei sichtbarer Titel<input required minLength={3} maxLength={200} value={title} disabled={action.busy} onChange={event => setTitle(event.target.value)} /></label>
    <label>Begründung und geprüfte Zugehörigkeit<textarea required minLength={10} maxLength={2000} value={reason} disabled={action.busy} onChange={event => setReason(event.target.value)} /></label>
    {action.error && <p role="alert">{action.error}</p>}{notice && <p role="status">{notice}</p>}
    <button className="btn btn-primary" disabled={action.busy || !grantId}>Vorgangsstand ausdrücklich veröffentlichen</button>
  </form></details>;
}
