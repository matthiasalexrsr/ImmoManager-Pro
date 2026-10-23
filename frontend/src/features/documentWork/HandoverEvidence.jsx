import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../../api';
import { useCanWrite } from '../../contexts/AuthContext';
import { downloadVersion } from './documentWorkApi';

export default function HandoverEvidence({ protocolId }) {
  const canWrite = useCanWrite('/documents');
  const canHandover = useCanWrite('/handover-protocols');
  const base = `/handover-protocols/${encodeURIComponent(protocolId)}/evidence`;
  const [page, setPage] = useState(null);
  const [source, setSource] = useState(null);
  const [file, setFile] = useState(null);
  const [purpose, setPurpose] = useState('original_photo');
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState(null);
  const pending = useRef(null);
  const alive = useRef(true);
  const load = useCallback(async () => {
    const current = api.captureSession();
    const [next, original] = await Promise.all([api.get(base), api.get(`${base}/source`)]);
    current();
    if (alive.current) { setPage(next); setSource(original); }
  }, [base]);
  useEffect(() => {
    alive.current = true;
    load().catch(failure => { if (alive.current) setError(failure.message); });
    return () => { alive.current = false; };
  }, [load]);
  const send = async data => {
    if (busy) return;
    setBusy(true); setError(null);
    try {
      const current = api.captureSession();
      const result = await api.upload(base, data); current();
      if (!alive.current) return;
      pending.current = null; setFile(null); setNotice(`Nachweis bytegleich archiviert. SHA-256: ${result.sha256}`);
      await load();
    } catch (failure) { if (alive.current) setError(failure.message); }
    finally { if (alive.current) setBusy(false); }
  };
  const upload = async () => {
    if (!file || !source || busy || pending.current) return;
    try {
      const current = api.captureSession();
      const hash = await crypto.subtle.digest('SHA-256', await file.arrayBuffer()); current();
      const data = new FormData();
      data.append('file', file); data.append('purpose', purpose);
      data.append('command_key', crypto.randomUUID());
      data.append('expected_protocol_revision', source.revision);
      data.append('expected_sha256', [...new Uint8Array(hash)].map(value => value.toString(16).padStart(2, '0')).join(''));
      pending.current = data;
      await send(data);
    } catch (failure) { if (alive.current) setError(failure.message); }
  };
  const more = async () => {
    try {
      const current = api.captureSession();
      const next = await api.get(`${base}?after=${encodeURIComponent(page.next_after)}`); current();
      if (alive.current) setPage(previous => ({ ...next, items: [...previous.items, ...next.items] }));
    } catch (failure) { if (alive.current) setError(failure.message); }
  };
  return <section className="handover__section" aria-label="Unveränderliche Originalnachweise"><h3>Originalfotos und unterschriebene Rückfassungen</h3>
    <p>Diese zusätzlichen Nachweise werden unveränderlich archiviert. Eine Bildunterschrift oder ein Scan belegt keine kryptografisch geprüfte digitale Signatur.</p>
    {error && <div role="alert"><p>{error}</p>{pending.current && <>
      <button type="button" className="btn btn-secondary" disabled={busy} onClick={() => send(pending.current)}>Denselben Upload wiederholen</button>
      <button type="button" className="btn btn-secondary" disabled={busy} onClick={() => { pending.current = null; setError(null); void load().catch(failure => setError(failure.message)); }}>Quelle neu prüfen, Datei behalten</button></>}
      {!pending.current && <button type="button" className="btn btn-secondary" onClick={() => { void load().catch(failure => setError(failure.message)); }}>Erneut laden</button>}</div>}
    {notice && <p role="status">{notice}</p>}
    <ul>{page?.items.map(item => <li key={item.version_id}>{item.purpose === 'original_photo' ? 'Originalfoto' : 'Unterschriebene Rückfassung'} · {item.filename}
      <button type="button" className="btn btn-secondary" onClick={() => downloadVersion(item.document_id, item.version_id, item.filename).catch(failure => setError(failure.message))}>Original herunterladen</button></li>)}</ul>
    {page?.next_after && <button type="button" className="btn btn-secondary" onClick={more}>Weitere Nachweise laden</button>}
    {canWrite && canHandover && <><label>Nachweisart<select value={purpose} disabled={busy || Boolean(pending.current)} onChange={event => setPurpose(event.target.value)}>
      <option value="original_photo">Originalfoto</option><option value="signed_return">Unterschriebene Rückfassung</option></select></label>
      <label>Datei auswählen<input type="file" accept="image/png,image/jpeg,image/webp,image/tiff,application/pdf" disabled={busy || Boolean(pending.current)} onChange={event => { setFile(event.target.files?.[0] || null); setNotice(null); }} /></label>
      <button type="button" className="btn btn-primary" disabled={!file || !source || busy || Boolean(pending.current)} onClick={upload}>{busy ? 'Wird archiviert …' : 'Nachweis unveränderlich archivieren'}</button></>}
  </section>;
}
