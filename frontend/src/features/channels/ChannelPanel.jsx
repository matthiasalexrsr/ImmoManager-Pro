import { useEffect, useRef, useState } from 'react';
import { api } from '../../api';
import { useCanWrite } from '../../contexts/AuthContext';
import './channels.css';
import AppLink from '../../components/AppLink';

const labels = { prepared: 'Vorbereitet', unknown: 'Ausgang unklar – Abgleich erforderlich', failed: 'Fehlgeschlagen',
  accepted: 'Von WhatsApp angenommen', sent: 'An WhatsApp übergeben', delivered: 'Zugestellt', read: 'Gelesen',
  received: 'Empfangene Nachricht – ausdrücklich zugeordnet', franked: 'Frankaturoriginal zugeordnet', posted: 'Manuell eingeworfen', published: 'Veröffentlicht',
  unpublished: 'Deaktiviert', transferred: 'Datei übertragen – Veröffentlichung unbestätigt' };
const key = () => crypto.randomUUID();

export default function ChannelPanel({ sourceId, mode }) {
  const [channel, setChannel] = useState(mode === 'listing' ? 'is24' : mode);
  const [preview, setPreview] = useState(null);
  const [cases, setCases] = useState([]);
  const [connections, setConnections] = useState([]);
  const [connectionId, setConnectionId] = useState('');
  const [fields, setFields] = useState({ language_code: 'de_DE', recipient_name: '', street: '', postcode: '', city: '' });
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [nextCursor, setNextCursor] = useState(null);
  const generation = useRef(0);
  const pending = useRef(new Map());
  const canWrite = useCanWrite(mode === 'listing' ? '/listings' : '/messages');
  const path = channel === 'whatsapp' ? `/messages/threads/${sourceId}/whatsapp/preview`
    : channel === 'post' ? `/documents/${sourceId}/post/preview` : `/listings/${sourceId}/channels/${channel}/preview`;
  const update = (name, value) => setFields(current => ({ ...current, [name]: value }));
  useEffect(() => {
    const current = ++generation.current;
    const controller = new AbortController();
    setPreview(null); setCases([]); setError(''); setBusy(true); pending.current.clear();
    const session = api.captureSession();
    Promise.all([api.get(path, { signal: controller.signal }),
      api.get(`/messages/channels/${channel}/${sourceId}`, { signal: controller.signal }),
      channel === 'post' ? Promise.resolve([]) : api.get(`/messages/channel-options?channel=${channel}`, { signal: controller.signal })])
      .then(([data, records, options]) => { session(); if (current !== generation.current) return;
        if (!data || typeof data.source_sha256 !== 'string' || !data.snapshot?.context || !Array.isArray(data.snapshot.assets)
          || !Array.isArray(records?.items || records) || !(records.items || records).every(record => record && typeof record.id === 'string' && record.snapshot && record.progress)
          || !Array.isArray(options)) {
          throw new Error('Die Kanalvorschau ist unvollständig. Bitte erneut laden.');
        }
        setPreview(data); setCases(records.items || records); setNextCursor(records.next_cursor || null); setConnections(options); setConnectionId(options[0]?.id || ''); })
      .catch(reason => { if (current === generation.current && reason.name !== 'AbortError') setError(reason.message); })
      .finally(() => { if (current === generation.current) setBusy(false); });
    return () => { generation.current = current + 1; controller.abort(); };
  }, [sourceId, channel, path, attempt]);
  async function perform(operation, body, target) {
    const current = generation.current;
    const session = api.captureSession();
    setBusy(true); setError('');
    const fingerprint = JSON.stringify([operation, body, target]);
    // Preserve the exact command on a lost response, even after pressing Retry.
    const commandKey = pending.current.get(fingerprint) || key();
    pending.current.set(fingerprint, commandKey);
    try {
      const result = await api.post(target, { ...body, idempotency_key: commandKey });
      session(); if (current !== generation.current) return;
      setCases(previous => [result, ...previous.filter(item => item.id !== result.id)]);
      pending.current.delete(fingerprint);
    } catch (reason) { if (current === generation.current) setError(reason.message); }
    finally { if (current === generation.current) setBusy(false); }
  }
  function prepare() {
    const connection = connections.find(item => item.id === connectionId);
    let parameters = {};
    if (channel === 'post') parameters = Object.fromEntries(['recipient_name', 'street', 'postcode', 'city'].map(name => [name, fields[name]]));
    if (channel === 'whatsapp') parameters = { to: fields.to, template_name: fields.template_name, language_code: fields.language_code,
      opt_in: fields.opt_in === true, opt_in_evidence: fields.opt_in_evidence,
      components: [{ type: 'body', parameters: (fields.parameters || '').split('\n').filter(Boolean).map(text => ({ type: 'text', text })) }] };
    const existing = channel === 'whatsapp' ? null : cases[0];
    perform('prepare', { source_sha256: preview.source_sha256, parameters, base_revision: existing?.revision || 0,
      connection_id: connection?.id || null, connection_revision: connection?.revision || null }, `/messages/channels/${channel}/${sourceId}/prepare`);
  }
  const input = (name, label, type = 'text') => <label>{label}<input type={type} value={fields[name] || ''} onChange={event => update(name, event.target.value)} /></label>;
  const action = (record, name, parameters = {}) => perform(name, { base_revision: record.revision, action: name, parameters }, `/messages/channel-cases/${record.id}/actions`);
  return <section className="channel-panel" aria-label="Versand und Veröffentlichung">
    <h3>{mode === 'listing' ? 'Portalübertragung' : mode === 'post' ? 'Brief und Frankatur' : 'WhatsApp'}</h3>
    {mode === 'listing' && <label>Übertragungsweg<select value={channel} onChange={event => setChannel(event.target.value)}>
      <option value="is24">ImmoScout24</option><option value="openimmo">OpenImmo 1.2.7 / FTPS</option></select></label>}
    {error && <p role="alert">{error} <button disabled={busy} onClick={() => setAttempt(value => value + 1)}>Neu laden (Eingaben bleiben erhalten)</button></p>}
    {busy && <p role="status">Vorgang wird geprüft …</p>}
    {preview && <>
      <p>{preview.snapshot.listing?.title || preview.snapshot.context.title} · {preview.asset_count} Originaldatei(en)</p>
      {preview.snapshot.listing && <p>{preview.snapshot.listing.description}<br />{preview.snapshot.listing.address.street} {preview.snapshot.listing.address.house_number}, {preview.snapshot.listing.address.postcode} {preview.snapshot.listing.address.city}</p>}
      <details><summary>Quell- und Bildnachweis ansehen</summary><p className="channel-hash">Quellhash: {preview.source_sha256}</p>
        {preview.snapshot.assets.map(file => <p className="channel-hash" key={file.id}>{file.title} · {file.size} Bytes · {file.sha256}</p>)}</details>
      {channel !== 'post' && <label>Freigegebene Verbindung<select value={connectionId} onChange={event => setConnectionId(event.target.value)}>
        <option value="">Verbindung wählen</option>{connections.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>}
      {channel !== 'post' && !connections.length && <p>In den <AppLink to="/integration-connections">Schnittstellen</AppLink> eine passende Verbindung einrichten. Die lokale Vorbereitung des Inserats bleibt verfügbar.</p>}
      {channel === 'whatsapp' && <div className="channel-fields">
        {input('to', 'Mobilnummer mit Ländervorwahl', 'tel')}{input('template_name', 'Von Meta freigegebener Template-Name')}{input('language_code', 'Exakte Template-Sprache')}
        <label>Textparameter in Template-Reihenfolge (ein Wert je Zeile)<textarea value={fields.parameters || ''} onChange={event => update('parameters', event.target.value)} /></label>
        {input('opt_in_evidence', 'Nachweis der WhatsApp-Einwilligung')}
        <label><input type="checkbox" checked={fields.opt_in || false} onChange={event => update('opt_in', event.target.checked)} />Einwilligung liegt vor und gilt für diesen Empfänger.</label>
      </div>}
      {channel === 'post' && <div className="channel-fields">{input('recipient_name', 'Empfänger')}{input('street', 'Straße und Hausnummer')}{input('postcode', 'Postleitzahl')}{input('city', 'Ort')}
        <p><a href="https://shop.deutschepost.de/internetmarke" target="_blank" rel="noreferrer">INTERNETMARKE-Shop öffnen</a>. Den gekauften Originalbeleg anschließend in der Dokumentakte ablegen und unten zuordnen.</p></div>}
      {canWrite && <button className="btn btn-secondary" disabled={busy || (channel !== 'post' && !connectionId)} onClick={prepare}>Auswahl prüfen und Vorgang vorbereiten</button>}
    </>}
    {nextCursor && <button disabled={busy} onClick={async () => { const session = api.captureSession(); const current = generation.current;
      try { const page = await api.get(`/messages/channels/${channel}/${sourceId}?cursor=${encodeURIComponent(nextCursor)}`); session(); if (current === generation.current) { setCases(previous => [...previous, ...page.items]); setNextCursor(page.next_cursor); } }
      catch (reason) { if (current === generation.current) setError(reason.message); } }}>Weitere Vorgänge</button>}
    {mode === 'listing' && preview?.asset_count === 0 && <label><input type="checkbox" checked={fields.without_images || false} onChange={event => update('without_images', event.target.checked)} />Ich bestätige ausdrücklich die Veröffentlichung ohne Bilder.</label>}
    {cases.map(record => <article key={record.id}>
      <h4>{labels[record.state] || record.state}</h4>
      {[...(record.snapshot.originals || []), record.progress.purchased_original, record.progress.media_original, record.progress.received_media].filter(Boolean).map(original => <button key={original.evidence_name} disabled={busy} onClick={async () => {
        const session = api.captureSession(); const current = generation.current;
        try { const blob = await api.getBlob(`/messages/channel-cases/${record.id}/original?name=${encodeURIComponent(original.evidence_name)}`); session(); if (current !== generation.current) return;
          const url = URL.createObjectURL(blob); const link = document.createElement('a'); link.href = url; link.download = original.name || 'Original.bin'; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); }
        catch (reason) { if (current === generation.current) setError(reason.message); }
      }}>Original herunterladen: {original.name || 'Beleg'}</button>)}
      {record.state === 'received' && <p>{record.snapshot.inbound?.text?.body || 'Empfangene Mediennachricht'}</p>}
      {canWrite && record.state === 'received' && ['image', 'document'].includes(record.snapshot.inbound?.type) && <button disabled={busy} onClick={() => action(record, 'receive_media')}>Empfangene Originalmedien abrufen und prüfen</button>}
      {record.external_id && <p>Anbieterreferenz: {record.external_id}</p>}
      {record.progress.error && <p role="alert">{record.progress.error}</p>}
      {record.channel === 'post' && <p>Brief: {record.snapshot.originals[0]?.name} · Empfänger: {record.snapshot.parameters.recipient_name}, {record.snapshot.parameters.street}, {record.snapshot.parameters.postcode} {record.snapshot.parameters.city}</p>}
      {canWrite && channel === 'post' && record.state === 'prepared' && <div className="channel-fields">
        {input('document_id', 'Dokument-ID des tatsächlich gekauften Frankaturoriginals')}{input('purchase_reference', 'Kaufreferenz')}
        <label><input type="checkbox" checked={fields.purchased_original_confirmed || false} onChange={event => update('purchased_original_confirmed', event.target.checked)} />Dies ist das tatsächlich gekaufte Frankaturoriginal für diesen Brief.</label>
        <button disabled={busy || !fields.purchased_original_confirmed} onClick={() => action(record, 'frank', { document_id: fields.document_id, purchase_reference: fields.purchase_reference, purchased_original_confirmed: true })}>Kaufbeleg zuordnen</button>
      </div>}
      {canWrite && channel === 'post' && record.state === 'franked' && <button disabled={busy} onClick={() => action(record, 'posted', { manually_posted_confirmed: true })}>Tatsächlichen manuellen Einwurf bestätigen</button>}
      {canWrite && channel === 'whatsapp' && record.state === 'prepared' && <div>
        {input('media_document_id', 'Optional: Dokument-ID für den freigegebenen Template-Medienkopf (JPEG, PNG, PDF)')}
        <button disabled={busy || !fields.media_document_id} onClick={() => action(record, 'upload_media', { document_id: fields.media_document_id })}>Gewähltes Original als Medium hochladen</button>
        {record.progress.media && <p>Geprüftes Medium: {record.progress.media_original.name} · {record.progress.media.sha256}</p>}
        <button disabled={busy} onClick={() => action(record, 'send', record.progress.media ? { media_id: record.progress.media.id } : {})}>Diese Template-Nachricht jetzt übergeben</button>
      </div>}
      {canWrite && mode === 'listing' && ['prepared', 'failed', 'unpublished'].includes(record.state) && <button disabled={busy} onClick={() => action(record, record.external_id ? 'update' : 'publish', { publish_without_images_confirmed: fields.without_images === true })}>Ausgewählte Fassung jetzt übertragen</button>}
      {canWrite && mode === 'listing' && record.state === 'published' && <button disabled={busy} onClick={() => action(record, 'deactivate')}>Veröffentlichung deaktivieren</button>}
      {canWrite && channel !== 'post' && <button disabled={busy} onClick={() => action(record, 'reconcile')}>Ergebnis abgleichen</button>}
      <button disabled={busy} onClick={async () => { const session = api.captureSession(); const current = generation.current;
        try { const fresh = await api.get(`/messages/channel-cases/${record.id}`); session(); if (current === generation.current) setCases(previous => previous.map(item => item.id === fresh.id ? fresh : item)); }
        catch (reason) { if (current === generation.current) setError(reason.message); } }}>Stand neu laden</button>
    </article>)}
  </section>;
}
