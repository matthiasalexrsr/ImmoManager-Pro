import { useEffect, useRef, useState } from 'react';
import { api } from '../api';
import BankMatch from './BankMatch';

const key = () => crypto.randomUUID();
const amount = cents => (cents / 100).toLocaleString('de-DE', { style: 'currency', currency: 'EUR' });

export default function BankImport({ accounts, onImported }) {
  const [account, setAccount] = useState('');
  const [file, setFile] = useState(null);
  const [format, setFormat] = useState('csv');
  const [encoding, setEncoding] = useState('utf-8-sig');
  const [decimal, setDecimal] = useState('.');
  const [delimiter, setDelimiter] = useState(';');
  const [dateFormat, setDateFormat] = useState('%Y-%m-%d');
  const [columns, setColumns] = useState({ date: 'date', amount: 'amount', text: 'text', reference: '', currency: '' });
  const [preview, setPreview] = useState(null);
  const [identifier, setIdentifier] = useState('');
  const [checked, setChecked] = useState(false);
  const [decisions, setDecisions] = useState({});
  const [history, setHistory] = useState(null);
  const [formDirty, setFormDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [profile, setProfile] = useState(null);
  const [profileError, setProfileError] = useState('');
  const [expanded, setExpanded] = useState(false);
  const command = useRef(null);
  const mounted = useRef(true);
  const inputsTouched = useRef(false);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);

  const applyProfile = saved => {
    setFormat(saved.format);
    const options = saved.options;
    setEncoding(options.encoding); setDelimiter(options.delimiter); setDecimal(options.decimal);
    setDateFormat(options.date_format);
    setColumns({ date: 'date', amount: 'amount', text: 'text', reference: '', currency: '', ...options.columns });
  };
  useEffect(() => {
    if (!expanded) return;
    let active = true;
    const current = api.captureSession();
    api.get('/auth/users/me/settings/bank-import-profile').then(saved => {
      current();
      if (!active || !saved?.options?.columns || !['csv', 'mt940', 'camt'].includes(saved.format)) return;
      setProfile(saved);
      if (!inputsTouched.current) applyProfile(saved);
    }).catch(e => {
      if (active && e.code !== 'SESSION_CHANGED') setProfileError('Die gespeicherte Formatvorlage konnte nicht geladen werden. Sie können die Angaben hier selbst festlegen.');
    });
    return () => { active = false; };
  }, [expanded]);

  async function run(action) {
    const current = api.captureSession();
    setBusy(true); setError('');
    try { await action(() => { current(); if (!mounted.current) throw new Error('Ansicht geschlossen'); }); }
    catch (e) { if (mounted.current && e.code !== 'SESSION_CHANGED') setError(e.message); }
    finally { if (mounted.current) setBusy(false); }
  }
  const load = (id, offset = 0) => { inputsTouched.current = true; return run(async current => {
    const data = await api.get(`/bank-imports/${encodeURIComponent(id)}?offset=${offset}`);
    current(); if (id !== preview?.id) { setDecisions({}); command.current = null; } setPreview(data); setIdentifier(id); setChecked(false);
    setFormDirty(false);
    if (data.account_id !== account) setHistory(null);
    setAccount(data.account_id); setFormat(data.format);
    const options = data.options || {};
    setEncoding(options.encoding || 'utf-8-sig'); setDecimal(options.decimal || '.'); setDelimiter(options.delimiter || ';');
    setDateFormat(options.date_format || '%Y-%m-%d');
    setColumns(options.columns || { date: 'date', amount: 'amount', text: 'text', reference: '', currency: '' });
  }); };
  const list = cursor => run(async current => {
    if (!account) throw new Error('Bitte zuerst das Konto auswählen.');
    const result = await api.get(`/bank-imports?account_id=${encodeURIComponent(account)}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`);
    current(); setHistory(previous => ({ ...result, items: cursor ? [...(previous?.items || []), ...result.items] : result.items }));
  });
  const stage = () => run(async current => {
    if (!file || !account) throw new Error('Bitte Konto und Originaldatei auswählen.');
    if (file.size > 50 * 1024 * 1024) throw new Error('Die Originaldatei darf höchstens 50 MiB groß sein.');
    const bytes = new Uint8Array(await file.arrayBuffer()); current();
    let binary = '';
    for (let offset = 0; offset < bytes.length; offset += 32768) binary += String.fromCharCode(...bytes.subarray(offset, offset + 32768));
    const payload = { account_id: account, filename: file.name, source_base64: btoa(binary), format,
      options: { encoding, decimal, delimiter, date_format: dateFormat, columns } };
    const signature = JSON.stringify(payload);
    if (command.current?.signature !== signature) command.current = { signature, stage: key(), confirm: key() };
    const result = await api.post('/bank-imports', { ...payload, idempotency_key: command.current.stage }); current();
    setIdentifier(result.id);
    const data = await api.get(`/bank-imports/${result.id}`); current(); setPreview(data); setChecked(false); setDecisions({}); setFormDirty(false);
  });
  const confirm = () => run(async current => {
    if (!command.current) command.current = { confirm: key() };
    const payload = { base_revision: preview.revision, preview_sha256: preview.preview_sha256, confirm: true, duplicate_decisions: decisions };
    const signature = JSON.stringify(payload);
    if (command.current.confirmSignature !== signature) { command.current.confirmSignature = signature; command.current.confirm = key(); }
    await api.post(`/bank-imports/${preview.id}/confirm`, { idempotency_key: command.current.confirm, ...payload }); current();
    const data = await api.get(`/bank-imports/${preview.id}`); current(); setPreview(data); onImported();
  });
  const download = () => run(async current => {
    const blob = await api.getBlob(`/bank-imports/${preview.id}/original`); current();
    const url = URL.createObjectURL(blob); const a = document.createElement('a');
    a.href = url; a.download = preview.filename; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  return <details className="card" style={{ marginBottom: 16 }} onToggle={event => setExpanded(event.currentTarget.open)}><summary>Bankdatei importieren und Übernahmebeleg öffnen</summary>
    <fieldset disabled={busy} style={{ minWidth: 0 }} onChange={() => { inputsTouched.current = true; setFormDirty(true); setChecked(false); }}><legend>Original und Format</legend>
      {profile && <p>Ihre gespeicherte Formatvorlage steht bereit. <button type="button" onClick={() => { inputsTouched.current = true; applyProfile(profile); setFormDirty(true); setChecked(false); }}>Gespeicherte Formatvorlage anwenden</button></p>}
      {profileError && <p role="status">{profileError}</p>}
      <label>Konto <select value={account} onChange={e => { setAccount(e.target.value); setHistory(null); }}><option value="">Bitte auswählen</option>{accounts.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}</select></label>{' '}
      <label>Originaldatei <input type="file" onChange={e => setFile(e.target.files[0])} /></label>
      <label>Format <select value={format} onChange={e => setFormat(e.target.value)}>{['csv', 'mt940', 'camt'].map(v => <option key={v}>{v}</option>)}</select></label>{' '}
      <label>Kodierung <select value={encoding} onChange={e => setEncoding(e.target.value)}>{['utf-8-sig', 'cp1252', 'iso-8859-1', 'utf-16'].map(v => <option key={v}>{v}</option>)}</select></label>
      {format === 'csv' && <div><label>Trennzeichen <select value={delimiter} onChange={e => setDelimiter(e.target.value)}><option value=";">Semikolon</option><option value=",">Komma</option><option value={'\t'}>Tabulator</option></select></label>{' '}
        <label>Dezimalzeichen <select value={decimal} onChange={e => setDecimal(e.target.value)}><option value=".">Punkt</option><option value=",">Komma</option></select></label>{' '}
        <label>Datumsformat <select value={dateFormat} onChange={e => setDateFormat(e.target.value)}><option value="%Y-%m-%d">JJJJ-MM-TT</option><option value="%d.%m.%Y">TT.MM.JJJJ</option></select></label>
        {Object.entries({ date: 'Datumsspalte', amount: 'Betragsspalte', text: 'Verwendungszweckspalte', reference: 'Bankreferenzspalte (optional)', currency: 'Währungsspalte (optional)' }).map(([name, label]) => <label key={name} style={{ display: 'block' }}>{label} <input value={columns[name]} onChange={e => setColumns({ ...columns, [name]: e.target.value })} /></label>)}</div>}
      <button type="button" className="btn btn-secondary" onClick={stage}>Vollständige Vorschau vorbereiten</button>
      <p>Fehlerkorrektur: Kodierung oder Spalten ändern und erneut vorbereiten. Das Original bleibt erhalten. Es werden noch keine Buchungen angelegt.</p>
      <label>Gespeicherte Importkennung <input value={identifier} onChange={e => setIdentifier(e.target.value)} /></label>{' '}<button type="button" onClick={() => load(identifier)}>Vorgang wieder öffnen</button>
      <p>Nach einem Browserabbruch können Sie die gespeicherten Vorgänge dieses Kontos wieder öffnen oder dieselbe Originaldatei mit denselben Einstellungen erneut vorbereiten.</p>
      <button type="button" onClick={() => list(null)}>Gespeicherte Vorgänge dieses Kontos laden</button>
      {history && <div>{!history.items.length && <p>Für dieses Konto sind noch keine Bankimporte gespeichert.</p>}{history.items.map(item => <p key={item.id}><button type="button" onClick={() => load(item.id)}>Bankimport vom {item.created_at} · {item.state === 'confirmed' ? 'übernommen' : item.state === 'invalid' ? 'Korrektur erforderlich' : 'vorbereitet'} öffnen</button></p>)}{history.has_more && <button type="button" onClick={() => list(history.next_cursor)}>Weitere gespeicherte Vorgänge laden</button>}</div>}
    </fieldset>
    {busy && <p role="status">Bankvorgang wird verarbeitet …</p>}{error && <p role="alert">{error} Eingaben bleiben erhalten; denselben Schritt erneut versuchen.</p>}
    {preview && <section aria-label="Bankvorschau"><h2>{preview.filename}</h2>
      <p>Importkennung: <code style={{ overflowWrap: 'anywhere' }}>{preview.id}</code></p>
      {preview.source_provenance === 'submitted_text_utf8' && <p>Textübernahme aus der bisherigen Schnittstelle: Gesichert ist der übermittelte Text in UTF-8. Ursprüngliche Dateibytes wurden nicht mitgeliefert. Für einen Dateioriginalnachweis bitte die Originaldatei hochladen.</p>}
      <p>{preview.row_count} Bewegungen · {preview.error_count} Fehler · Summe {amount(preview.total_cents)} · {preview.state === 'confirmed' ? 'Übernommen' : preview.state === 'invalid' ? 'Korrektur erforderlich' : 'Zur Prüfung bereit'}</p>
      <p>{preview.balance_verified ? 'Bank-Anfangs- und Abschlusssalden sind mit den Bewegungen abgestimmt.' : 'Kein erfolgreich abgestimmtes Anfangs-/Abschlusssaldenpaar vorhanden. Bitte die Summe mit dem Kontoauszug prüfen.'}</p>
      <button type="button" disabled={busy} onClick={download}>{preview.source_provenance === 'submitted_text_utf8' ? 'Übermittelten Text herunterladen' : 'Original herunterladen'}</button>
      <div style={{ overflowX: 'auto' }}><table><thead><tr><th>Zeile</th><th>Datum</th><th>Betrag</th><th>Verwendungszweck</th><th>Referenz / Buchung</th></tr></thead><tbody>{preview.rows.map((r, i) => <tr key={`${r.line}-${i}`}><td>{r.line}</td><td>{r.date}</td><td>{amount(r.cents)}</td><td>{r.text}</td><td>{r.reference} {preview.links?.[i]?.booking_id && <a href={`/bookings?booking_id=${encodeURIComponent(preview.links[i].booking_id)}`}>Buchung öffnen</a>}
        {preview.links?.[i]?.booking_id && <BankMatch bookingId={preview.links[i].booking_id} onAssigned={onImported} />}
        <details><summary>Quelldaten und unbekannte Felder</summary><pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', maxWidth: 400 }}>{typeof r.raw === 'string' ? r.raw : JSON.stringify(r.raw, null, 2)}</pre></details>
        {preview.state === 'staged' && r.duplicate_candidates?.length > 0 && <label>Ähnliche Bewegung prüfen <select value={decisions[r.index] || ''} onChange={e => { setDecisions({ ...decisions, [r.index]: e.target.value }); setChecked(false); }}><option value="">Bitte vergleichen</option><option value="new">Eigenständige neue Bewegung</option>{r.duplicate_candidates.map(id => <option value={id} key={id}>Dieselbe Bewegung wie Buchung {id}</option>)}</select></label>}</td></tr>)}</tbody></table></div>
      {preview.errors.map((e, i) => <div key={i}><p role="alert">Zeile {e.line}: {e.error}</p><details><summary>Fehlerhafte Quelldaten anzeigen</summary><pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{typeof e.raw === 'string' ? e.raw : JSON.stringify(e.raw, null, 2)}</pre></details></div>)}
      <p>Abschnitt ab {preview.offset + 1}</p><button type="button" disabled={busy || !preview.offset} onClick={() => load(preview.id, Math.max(0, preview.offset - 100))}>Zurück</button>{' '}
      <button type="button" disabled={busy || preview.next_offset == null} onClick={() => load(preview.id, preview.next_offset)}>Weitere Zeilen und Fehler</button>
      {preview.receipt && <p role="status">Übernahmebeleg: {preview.receipt.created} neue Buchungen, {preview.receipt.duplicates} bereits bekannte Bewegungen. Zuordnungen stehen abschnittsweise in der Tabelle.</p>}
      {preview.state === 'staged' && <div>{formDirty && <p role="alert">Die Dateiauswahl oder Formateinstellungen wurden geändert. Bitte die Vorschau erneut vorbereiten oder den gespeicherten Vorgang neu öffnen.</p>}<label><input type="checkbox" checked={checked} onChange={e => setChecked(e.target.checked)} />Ich habe die vollständige Vorschau geprüft und bestätige die atomare Übernahme.</label><button type="button" className="btn btn-primary" disabled={busy || !checked || formDirty} onClick={confirm}>Buchungen verbindlich übernehmen</button></div>}
    </section>}
  </details>;
}
