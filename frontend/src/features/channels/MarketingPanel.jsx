import { useEffect, useRef, useState } from 'react';
import { api } from '../../api';
import './channels.css';
import { useCanWrite } from '../../contexts/AuthContext';

export default function MarketingPanel({ listingId }) {
  const [data, setData] = useState(null);
  const [preview, setPreview] = useState(null);
  const [fields, setFields] = useState({});
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const generation = useRef(0);
  const retryKey = useRef(null);
  const canWrite = useCanWrite('/listings');
  useEffect(() => {
    const current = ++generation.current; const controller = new AbortController(); const session = api.captureSession();
    setData(null); setPreview(null); setError('');
    Promise.all([api.get(`/listings/${listingId}/marketing`, { signal: controller.signal }), api.get(`/listings/${listingId}/channels/is24/preview`, { signal: controller.signal })])
      .then(([overview, source]) => { session(); if (current !== generation.current) return;
        if (!overview || !['leads', 'viewings', 'contracts'].every(name => Array.isArray(overview[name]))
          || !source?.source_sha256 || !source.snapshot?.context) throw new Error('Die Vermarktungsvorschau ist unvollständig. Bitte neu laden.');
        setData(overview); setPreview(source); })
      .catch(reason => { if (current === generation.current && reason.name !== 'AbortError') setError(reason.message); });
    return () => { generation.current = current + 1; controller.abort(); };
  }, [listingId, attempt]);
  const set = (name, value) => setFields(previous => ({ ...previous, [name]: value }));
  const lead = data?.leads.find(item => item.id === fields.lead_id);
  const viewing = data?.viewings.find(item => item.id === fields.viewing_id && item.lead_id === lead?.id);
  const contract = data?.contracts.find(item => item.id === fields.contract_id);
  async function act(action, parameters) {
    const current = generation.current; const session = api.captureSession(); setBusy(true); setError('');
    const body = { action, parameters, source_sha256: preview.source_sha256 };
    const fingerprint = JSON.stringify(body);
    if (retryKey.current?.fingerprint !== fingerprint) retryKey.current = { fingerprint, key: crypto.randomUUID() };
    try { await api.post(`/listings/${listingId}/marketing`, { ...body, idempotency_key: retryKey.current.key }); session();
      if (current === generation.current) { retryKey.current = null; setAttempt(value => value + 1); } }
    catch (reason) { if (current === generation.current) setError(reason.message); }
    finally { if (current === generation.current) setBusy(false); }
  }
  const input = (name, label, type = 'text') => <label>{label}<input type={type} value={fields[name] || ''} onChange={event => set(name, event.target.value)} /></label>;
  return <section className="channel-panel" aria-label="Lokale Vermarktung"><h3>Exposé, Interessent und Vertragsabschluss</h3>
    {error && <p role="alert">{error}</p>}
    <button disabled={busy} onClick={() => setAttempt(value => value + 1)}>Stand neu laden</button>
    {preview && <button disabled={busy} onClick={async () => { const session = api.captureSession(); const current = generation.current;
      try { const blob = await api.getBlob(`/listings/${listingId}/expose?source_sha256=${preview.source_sha256}`); session(); if (current !== generation.current) return;
        const url = URL.createObjectURL(blob); const link = document.createElement('a'); link.href = url; link.download = 'expose.pdf'; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); }
      catch (reason) { if (current === generation.current) setError(reason.message); } }}>Exposé als PDF herunterladen</button>}
    {data && preview && <>
      {canWrite && <div className="channel-fields">{input('full_name', 'Neuer Interessent')}{input('email', 'E-Mail', 'email')}{input('phone', 'Telefon', 'tel')}
        <button disabled={busy || !fields.full_name} onClick={() => act('lead', { full_name: fields.full_name, email: fields.email, phone: fields.phone })}>Interessenten anlegen</button></div>}
      <label>Interessent<select value={fields.lead_id || ''} onChange={event => set('lead_id', event.target.value)}><option value="">Bitte wählen</option>
        {data.leads.map(item => <option key={item.id} value={item.id}>{item.full_name}</option>)}</select></label>
      {lead && canWrite && <><label>Besichtigung (lokale Uhrzeit)<input type="datetime-local" value={fields.scheduled_at || ''} onChange={event => set('scheduled_at', event.target.value)} /></label>
        <button disabled={busy || !fields.scheduled_at} onClick={() => act('viewing', { lead_id: lead.id, lead_revision: lead.updated_at, scheduled_at: new Date(fields.scheduled_at).toISOString() })}>Besichtigung planen</button></>}
      {lead && <label>Besichtigung<select value={fields.viewing_id || ''} onChange={event => set('viewing_id', event.target.value)}><option value="">Bitte wählen</option>
        {data.viewings.filter(item => item.lead_id === lead.id).map(item => <option key={item.id} value={item.id}>{new Date(item.scheduled_at).toLocaleString('de-DE')} · {item.status === 'completed' ? 'Durchgeführt' : item.status === 'scheduled' ? 'Geplant' : item.status}</option>)}</select></label>}
      {canWrite && viewing && viewing.status === 'scheduled' && <button disabled={busy} onClick={() => act('complete_viewing', { lead_id: lead.id, lead_revision: lead.updated_at, viewing_id: viewing.id, viewing_revision: viewing.updated_at, completed_confirmed: true })}>Tatsächlich durchgeführte Besichtigung bestätigen</button>}
      {canWrite && viewing?.status === 'completed' && <><p>Den geprüften Vertrag in der <a href="/contracts">Vertragsakte</a> erstellen und anschließend hier ausdrücklich zuordnen.</p>
        <label>Geprüfter Vertrag derselben Einheit<select value={fields.contract_id || ''} onChange={event => set('contract_id', event.target.value)}><option value="">Bitte wählen</option>
          {data.contracts.filter(item => item.status === 'active').map(item => <option key={item.id} value={item.id}>{item.contract_number}</option>)}</select></label>
        {contract && <p>Vertragspartei-ID: {contract.tenant_id}</p>}
        <label><input type="checkbox" checked={fields.confirmed || false} onChange={event => set('confirmed', event.target.checked)} />Der Vertrag wurde mit der angezeigten Vertragspartei tatsächlich abgeschlossen.</label>
        <button disabled={busy || !contract || !fields.confirmed} onClick={() => act('confirm_contract', { lead_id: lead.id, lead_revision: lead.updated_at,
          viewing_id: viewing.id, viewing_revision: viewing.updated_at, contract_id: contract.id, contract_revision: contract.updated_at, tenant_id: contract.tenant_id, contract_confirmed: true })}>Vertragsabschluss verknüpfen</button></>}
      {data.confirmations?.map(item => <p key={`${item.contract_id}-${item.confirmed_at}`}>Bestätigter Vertragsabschluss: {item.contract_id} · {new Date(item.confirmed_at).toLocaleString('de-DE')}</p>)}
    </>}
  </section>;
}
