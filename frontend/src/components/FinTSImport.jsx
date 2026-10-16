import { useEffect, useRef, useState } from 'react';
import { api } from '../api';

const newKey = () => crypto.randomUUID();

export default function FinTSImport({ accounts }) {
  const [config, setConfig] = useState({ account_id: '', bank_code: '', user_id: '', pin: '', server: '', product_id: '', customer_id: '', tan_mechanism: '', tan_medium: '', date_from: '', date_to: '' });
  const [session, setSession] = useState(null);
  const [identifier, setIdentifier] = useState('');
  const [tan, setTan] = useState('');
  const [selected, setSelected] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [imports, setImports] = useState([]);
  const command = useRef(null);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  function run(action) {
    const current = api.captureSession(); setBusy(true); setError('');
    const check = () => { current(); if (!mounted.current) throw new Error('Ansicht geschlossen'); };
    Promise.resolve().then(() => action(check)).catch(e => { if (mounted.current && e.code !== 'SESSION_CHANGED') setError(e.message); })
      .finally(() => { if (mounted.current) setBusy(false); });
  }
  function post(path, data, current) {
    const signature = JSON.stringify([path, data]);
    if (command.current?.signature !== signature) command.current = { signature, key: newKey() };
    return api.post(path, { ...data, idempotency_key: command.current.key }).then(result => { current(); return result; });
  }
  const start = () => run(async current => {
    const result = await post('/bank-imports/fints/sessions', config, current);
    setConfig(value => ({ ...value, pin: '' })); setSession(result); setIdentifier(result.id); setImports([]);
  });
  const reload = () => run(async current => {
    const result = await api.get(`/bank-imports/fints/sessions/${encodeURIComponent(identifier)}`); current(); setSession(result);
  });
  const step = () => run(async current => {
    const result = await post(`/bank-imports/fints/sessions/${session.id}/step`, { base_revision: session.revision,
      ...(session.state === 'tan_required' ? { tan } : {}),
      ...(session.state === 'select_account' ? { selected_account: Number(selected) } : {}) }, current);
    setSession(result); setTan(''); setSelected('');
  });
  const cancel = () => run(async current => {
    const result = await post(`/bank-imports/fints/sessions/${session.id}/cancel`, { base_revision: session.revision }, current);
    setSession(result); setTan('');
  });
  const stage = () => run(async current => {
    const result = await post(`/bank-imports/fints/sessions/${session.id}/stage`, { base_revision: session.revision }, current);
    setImports(result.imports);
  });
  const labels = { ready: 'Bereit zum lesenden Abruf', running: 'Abruf läuft oder Antwort steht aus', select_account: 'Bankkonto auswählen', tan_required: 'Bankfreigabe erforderlich', received: 'Bankdateien empfangen', expired: 'Freigabe abgelaufen', cancelled: 'Abgebrochen', failed: 'Neue Anmeldung erforderlich' };
  return <details className="card" style={{ marginBottom: 16 }}><summary>Bank online lesen (FinTS)</summary>
    <p>Dieser Zugang ruft Konten und gebuchte Umsätze ab. Empfangene Originaldateien werden anschließend separat geprüft und als Buchungen bestätigt.</p>
    <fieldset disabled={busy} style={{ minWidth: 0 }}><legend>Bankzugang</legend>
      <label>Zielkonto <select value={config.account_id} onChange={e => setConfig({ ...config, account_id: e.target.value })}><option value="">Bitte auswählen</option>{accounts.map(a => <option value={a.id} key={a.id}>{a.name}</option>)}</select></label>
      {Object.entries({ bank_code: 'Bankleitzahl', user_id: 'Bank-Benutzerkennung', pin: 'PIN', server: 'HTTPS-Bankadresse', product_id: 'Registrierte FinTS-Produktkennung', customer_id: 'Kundenkennung (optional)', tan_mechanism: 'TAN-Verfahren (Bankkennung, optional)', tan_medium: 'TAN-Medium (optional)', date_from: 'Umsätze ab', date_to: 'Umsätze bis' }).map(([field, label]) => <label key={field} style={{ display: 'block' }}>{label} <input type={field === 'pin' ? 'password' : field.startsWith('date_') ? 'date' : 'text'} autoComplete="off" value={config[field]} onChange={e => setConfig({ ...config, [field]: e.target.value })} /></label>)}
      <button type="button" onClick={start}>Geschützte Sitzung vorbereiten</button>
      <label>Gespeicherte Abrufkennung <input value={identifier} onChange={e => setIdentifier(e.target.value)} /></label><button type="button" onClick={reload}>Abrufstand laden</button>
    </fieldset>
    {busy && <p role="status">Bankvorgang wird verarbeitet …</p>}{error && <p role="alert">{error}</p>}
    {session && <section aria-label="Bankabruf"><p>Abrufkennung: <code style={{ overflowWrap: 'anywhere' }}>{session.id}</code></p><p role="status">{labels[session.state]} · Ablauf: {session.expires_at}</p>
      {session.error && <p role="alert">{session.error}</p>}
      {session.state === 'select_account' && <label>Abgerufenes Konto <select value={selected} onChange={e => setSelected(e.target.value)}><option value="">Bitte auswählen</option>{session.accounts.map((a, i) => <option value={i} key={i}>{a[0]} · {a[1]}</option>)}</select></label>}
      {session.state === 'tan_required' && <div><p>{session.challenge}</p>{session.challenge_image && <img alt="Freigabecode der Bank" src={session.challenge_image} style={{ maxWidth: '100%' }} />}{session.challenge_hhduc && <p style={{ overflowWrap: 'anywhere' }}>Bankcode für TAN-Gerät: {session.challenge_hhduc}</p>}
        {session.decoupled ? <p>Bitte in Ihrer Bank-App freigeben und anschließend den Status abfragen.</p> : <label>TAN <input type="password" autoComplete="off" value={tan} onChange={e => setTan(e.target.value)} /></label>}</div>}
      {['ready', 'select_account', 'tan_required'].includes(session.state) && <button type="button" disabled={busy || (session.state === 'select_account' && selected === '')} onClick={step}>{session.state === 'ready' ? 'Bank jetzt lesend kontaktieren' : session.decoupled ? 'Freigabestatus abfragen' : 'Fortsetzen'}</button>}
      {session.state === 'running' && <p>Bei verlorener Antwort den Abrufstand laden. Es erfolgt keine automatische Wiederholung. Nach Ablauf können Sie abbrechen und sich erneut anmelden.</p>}
      {session.state === 'received' && <button type="button" disabled={busy} onClick={stage}>Empfangene Originale zur Importprüfung bereitstellen</button>}
      {session.state !== 'cancelled' && <button type="button" disabled={busy} onClick={cancel}>Sitzung abbrechen und Zugangsdaten entfernen</button>}
      {imports.map(item => <p key={item.id}>Bankimport: <code style={{ overflowWrap: 'anywhere' }}>{item.id}</code> · {item.row_count} Bewegungen. Diese Kennung oben im Bankdatei-Import öffnen und prüfen.</p>)}
    </section>}
  </details>;
}
