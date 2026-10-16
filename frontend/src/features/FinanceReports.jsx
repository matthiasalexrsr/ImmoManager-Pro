import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { formatMoney } from '../utils/format';
import './financeReports.css';
import { useAuth, useCanWrite } from '../contexts/AuthContext';
import { financeCommandKey, forgetFinanceCommand, readFinanceCommand, rememberFinanceCommand } from './financeCommandBuffer';

const today = () => new Date().toLocaleDateString('sv-SE');

export default function FinanceReports() {
  const [open, setOpen] = useState(false);
  return <section className="card"><h2>Finanzplanung und Leistungsperioden</h2>
    <p>Leistungsperiodenergebnis v2 und gespeicherte Liquiditätsszenarien mit nachvollziehbaren Quellen.</p>
    <button type="button" onClick={() => setOpen(!open)} aria-expanded={open}>{open ? 'Schließen' : 'Bericht erstellen oder öffnen'}</button>
    {open && <ReportEditor />}
  </section>;
}

function ReportEditor() {
  const canSave = useCanWrite('/reports');
  const owner = useAuth()?.user?.id;
  const commandKey = financeCommandKey(owner, 'report-definition');
  const [pendingState, setPending] = useState(() => ({ key: commandKey, command: readFinanceCommand(commandKey) }));
  const pending = pendingState.key === commandKey ? pendingState.command : readFinanceCommand(commandKey);
  const [definition, setDefinition] = useState({ version: 2, kind: 'liquidity-v2', as_of: today(), months: 3,
    rent_payment_day: 3, rent_collection_percent: '100', arrears_collection_percent: '0',
    vacant_unit_ids: [], planned_flows: [] });
  const [name, setName] = useState('Mein Finanzbericht');
  const [saved, setSaved] = useState([]);
  const [properties, setProperties] = useState([]);
  const [units, setUnits] = useState([]);
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [saveKey, setSaveKey] = useState(() => crypto.randomUUID());
  useEffect(() => {
    const changed = event => { if (event.key === commandKey) setPending({ key: commandKey, command: readFinanceCommand(commandKey) }); };
    window.addEventListener('storage', changed);
    return () => window.removeEventListener('storage', changed);
  }, [commandKey]);
  useEffect(() => {
    const controller = new AbortController();
    const current = api.captureSession();
    Promise.all([api.list('/reports/v2/saved', { signal: controller.signal }),
      api.list('/properties', { signal: controller.signal }), api.list('/units', { signal: controller.signal })])
      .then(([reports, props, allUnits]) => { current(); setSaved(reports); setProperties(props); setUnits(allUnits); })
      .catch(e => { if (!controller.signal.aborted) setError(e.message); });
    return () => controller.abort();
  }, []);
  const change = (key, value) => { setDefinition(d => ({ ...d, [key]: value })); setResult(null); setNotice(''); setSaveKey(crypto.randomUUID()); };
  const run = async (action) => {
    const current = api.captureSession();
    setBusy(true); setError(''); setNotice('');
    try { await action(current); current(); } catch (e) { setError(e.message); } finally { setBusy(false); }
  };
  const cash = value => formatMoney(value, { currency: result?.currency || 'EUR' });
  const saveReport = () => run(async current => {
    if (!owner) throw new Error('Die Anmeldung wird noch geprüft. Bitte erneut versuchen.');
    const command = pending || { path: '/reports/v2/saved', request: { name, definition, idempotency_key: saveKey } };
    rememberFinanceCommand(commandKey, command); setPending({ key: commandKey, command });
    try {
      const r = await api.post(command.path, command.request); current();
      forgetFinanceCommand(commandKey, command); setPending({ key: commandKey, command: null });
      setSaved(list => [...list.filter(v => v.id !== r.id), r]);
      setNotice('Definition gespeichert. Beim Öffnen gelten die aktuellen Rechte und Quellen.');
    } catch (error) {
      current();
      if (error.statusCode === 409 || error.statusCode === 422) { forgetFinanceCommand(commandKey, command); setPending({ key: commandKey, command: null }); }
      throw error;
    }
  });
  const exportReport = format => run(async current => {
    const expected = result?.result_hash ? `&expected_result_hash=${encodeURIComponent(result.result_hash)}` : '';
    const blob = await api.getBlob(`/reports/v2/preview?format=${format}&definition=${encodeURIComponent(JSON.stringify(definition))}${expected}`); current();
    const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url;
    a.download = `Finanzbericht-v2.${format}`; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  return <div className="finance-report-workspace">
    {error && <p role="alert">{error} Ihre Eingaben bleiben erhalten. Bitte erneut versuchen.</p>}
    {notice && <p role="status">{notice}</p>}
    {pending && <p role="status">Die Bestätigung einer Berichtsspeicherung steht noch aus.
      {canSave && <button type="button" disabled={busy} onClick={saveReport}>Speicherung prüfen und fortsetzen</button>}</p>}
    <fieldset disabled={busy || Boolean(pending)} style={{ border: 0, padding: 0, display: 'grid', gap: 12 }}>
    <label>Gespeicherten Bericht öffnen <select aria-label="Gespeicherten Bericht öffnen" value="" disabled={busy}
      onChange={e => { const r = saved.find(r => r.id === e.target.value); if (r) { setDefinition(r.definition); setName(r.name); setResult(null); setSaveKey(crypto.randomUUID()); } }}>
      <option value="">Bitte auswählen</option>{saved.map(r => <option key={r.id} value={r.id}>{r.name}</option>)}
    </select></label>
    <label>Berichtsart <select value={definition.kind} onChange={e => change('kind', e.target.value)}>
      <option value="liquidity-v2">Liquiditätsprognose v2</option><option value="performance-period-v2">Leistungsperiodenergebnis v2</option>
    </select></label>
    <label>Stichtag <input type="date" value={definition.as_of} onChange={e => change('as_of', e.target.value)} /></label>
    <label>Immobilie <select value={definition.property_id || ''} onChange={e => change('property_id', e.target.value || null)}>
      <option value="">Alle berechtigten Immobilien</option>{properties.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
    </select></label>
    {definition.kind === 'performance-period-v2' ? <>
      <label>Zeitraum von <input type="date" value={definition.date_from || ''} onChange={e => change('date_from', e.target.value || null)} /></label>
      <label>Zeitraum bis <input type="date" value={definition.date_to || ''} onChange={e => change('date_to', e.target.value || null)} /></label>
      <p>Ganze Kalendermonate auswählen. Ohne Zeitraum wird das Kalenderjahr des Stichtags ausgewertet. Rechnungen ohne Leistungszeitraum erhalten einen Hinweis.</p>
    </> : <>
      <label>Planungshorizont <select value={definition.months} onChange={e => change('months', Number(e.target.value))}>
        {[3, 6, 12].map(m => <option key={m} value={m}>{m} Monate einschließlich Restmonat</option>)}</select></label>
      <label>Zahlungstag der Miete <input type="number" min="1" max="31" value={definition.rent_payment_day} onChange={e => change('rent_payment_day', Number(e.target.value))} /></label>
      <label>Erwarteter Mieteingang (%) <input type="number" min="0" max="100" step="0.01" value={definition.rent_collection_percent} onChange={e => change('rent_collection_percent', e.target.value)} /></label>
      <label>Erwarteter Eingang offener Rückstände im Folgemonat (%) <input type="number" min="0" max="100" step="0.01" value={definition.arrears_collection_percent} onChange={e => change('arrears_collection_percent', e.target.value)} /></label>
      <fieldset><legend>Im Szenario leerstehende Einheiten</legend>{units.filter(u => !definition.property_id || u.property_id === definition.property_id).map(u =>
        <label key={u.id} style={{ display: 'block' }}><input type="checkbox" checked={definition.vacant_unit_ids.includes(u.id)} onChange={e => change('vacant_unit_ids', e.target.checked ? [...definition.vacant_unit_ids, u.id] : definition.vacant_unit_ids.filter(id => id !== u.id))} /> {u.label}</label>)}</fieldset>
      <fieldset><legend>Zusätzliche geplante Zahlungen (Ausgaben negativ)</legend>
        {definition.planned_flows.map((f, index) => <div key={f.identity} style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          <input aria-label={`Bezeichnung ${index + 1}`} value={f.label} onChange={e => change('planned_flows', definition.planned_flows.map((v, i) => i === index ? { ...v, label: e.target.value } : v))} />
          <input aria-label={`Datum ${index + 1}`} type="date" value={f.day} onChange={e => change('planned_flows', definition.planned_flows.map((v, i) => i === index ? { ...v, day: e.target.value } : v))} />
          <input aria-label={`Betrag ${index + 1}`} type="number" step="0.01" value={f.amount} onChange={e => change('planned_flows', definition.planned_flows.map((v, i) => i === index ? { ...v, amount: e.target.value } : v))} />
          <button type="button" onClick={() => change('planned_flows', definition.planned_flows.filter((_, i) => i !== index))}>Entfernen</button>
        </div>)}<button type="button" onClick={() => change('planned_flows', [...definition.planned_flows, { identity: `plan:${crypto.randomUUID()}`, day: definition.as_of, amount: '0.00', label: 'Geplante Zahlung' }])}>Zahlung ergänzen</button>
      </fieldset>
    </>}
    <label>Berichtsname <input value={name} maxLength={160} onChange={e => { setName(e.target.value); setSaveKey(crypto.randomUUID()); }} /></label>
    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
      <button type="button" disabled={busy} onClick={() => run(async current => { const data = await api.get(`/reports/v2/preview?definition=${encodeURIComponent(JSON.stringify(definition))}`); current(); setResult(data); })}>Berechnen</button>
      {canSave && <button type="button" disabled={busy} onClick={saveReport}>Als neue Fassung speichern</button>}
      {['json', 'csv', 'pdf'].map(f => <button type="button" key={f} disabled={busy} onClick={() => exportReport(f)}>{f.toUpperCase()} herunterladen</button>)}
    </div>
    </fieldset>
    {busy && <p role="status">Bericht wird verarbeitet …</p>}
    {result && <>
      <p>Definition: {result.definition_hash.slice(0, 12)} · {result.currency || 'EUR'}</p>
      {result.opening_balance != null && <p>Anfangssaldo: {cash(result.opening_balance)} · Endsaldo: {cash(result.closing_balance)}</p>}
      <div style={{ overflowX: 'auto' }}><table><thead><tr><th>Monat</th><th>{result.basis === 'liquidity-v2' ? 'Eingänge' : 'Sollmiete'}</th><th>{result.basis === 'liquidity-v2' ? 'Ausgänge' : 'Kosten'}</th><th>{result.basis === 'liquidity-v2' ? 'Kontostand Szenario' : 'Ergebnis'}</th>{result.baseline_monthly && <th>Kontostand Basis</th>}</tr></thead><tbody>
        {result.monthly.map((r, index) => <tr key={r.month}><td>{r.month}</td><td>{cash(r.income ?? r.rent_due)}</td><td>{cash(r.expense ?? r.costs)}</td><td>{cash(r.balance ?? r.result)}</td>{result.baseline_monthly && <td>{cash(result.baseline_monthly[index].balance)}</td>}</tr>)}
      </tbody></table></div>
      {result.warnings.map((w, i) => <p role="status" key={i}>{w.message}</p>)}
      <details><summary>Quellen und Zahlungsannahmen ({result.sources.length})</summary><ul>{result.sources.map((s, i) => <li key={i}>{s.day || s.month}: {cash(s.amount)} · {s.url ? <Link to={s.url}>{s.label || s.basis || 'Beleg öffnen'}</Link> : s.label}</li>)}</ul></details>
    </>}
  </div>;
}
