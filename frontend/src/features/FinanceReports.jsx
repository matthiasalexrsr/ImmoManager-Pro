import { useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api } from '../api';
import { formatDate, formatMoney } from '../utils/format';
import './financeReports.css';
import { useAuth, useCanWrite } from '../contexts/AuthContext';
import { financeCommandKey, forgetFinanceCommand, readFinanceCommand, rememberFinanceCommand } from './financeCommandBuffer';

const today = () => new Date().toLocaleDateString('sv-SE');

const queryKeys = ['kind', 'as_of', 'date_from', 'date_to', 'portfolio_id', 'property_id', 'unit_id', 'owner_contact_id'];
const reportKinds = ['cash-v2', 'performance-period-v2', 'liquidity-v2'];
const queryDefinition = params => Object.fromEntries(queryKeys.flatMap(key => {
  const value = params.get(key);
  if (key === 'kind') return [[key, reportKinds.includes(value) ? value : 'cash-v2']];
  return value ? [[key, value]] : [];
}));
const followingDay = day => { const value = new Date(`${day}T12:00:00`); value.setDate(value.getDate() + 1); return value.toLocaleDateString('sv-SE'); };

export default function FinanceReports({ standalone = false }) {
  const [open, setOpen] = useState(false);
  const owner = useAuth()?.user?.id;
  if (standalone) return <ReportEditor key={owner || 'pending'} standalone />;
  return <section className="card finance-report-entry"><h2>Auswertungen und Finanzplanung</h2>
    <p>Zahlungen, Periodenergebnis und Liquidität mit nachvollziehbaren Quellen.</p>
    <div className="finance-actions"><Link className="btn btn-primary" to="/reports">Auswertungen öffnen</Link>
    <button type="button" className="btn btn-secondary" onClick={() => setOpen(!open)} aria-expanded={open}>{open ? 'Schließen' : 'Bericht erstellen oder öffnen'}</button></div>
    {open && <ReportEditor key={owner || 'pending'} />}
  </section>;
}

function ReportEditor({ standalone = false }) {
  const canSave = useCanWrite('/reports');
  const owner = useAuth()?.user?.id;
  const commandKey = financeCommandKey(owner, 'report-definition');
  const [pendingState, setPending] = useState(() => ({ key: commandKey, command: readFinanceCommand(commandKey) }));
  const pending = pendingState.key === commandKey ? pendingState.command : readFinanceCommand(commandKey);
  const [params, setParams] = useSearchParams();
  const [definition, setDefinition] = useState(() => ({ version: 2, kind: standalone ? 'cash-v2' : 'liquidity-v2', as_of: today(), months: 3,
    rent_payment_day: 3, rent_collection_percent: '100', arrears_collection_percent: '0',
    vacant_unit_ids: [], planned_flows: [], ...(standalone ? queryDefinition(params) : {}) }));
  const [name, setName] = useState('Mein Finanzbericht');
  const [saved, setSaved] = useState([]);
  const [properties, setProperties] = useState([]);
  const [units, setUnits] = useState([]);
  const [portfolios, setPortfolios] = useState([]);
  const [owners, setOwners] = useState([]);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [referenceError, setReferenceError] = useState('');
  const [referencesReady, setReferencesReady] = useState(false);
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [saveKey, setSaveKey] = useState(() => crypto.randomUUID());
  const active = useRef(false);
  const requestEpoch = useRef(0);
  const querySignature = params.toString();
  const latestQuery = useRef(querySignature);
  latestQuery.current = querySignature;
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  useEffect(() => {
    if (!standalone) return;
    requestEpoch.current += 1;
    setDefinition(previous => {
      const next = { ...previous };
      queryKeys.forEach(key => delete next[key]);
      return { ...next, as_of: today(), ...queryDefinition(new URLSearchParams(querySignature)) };
    });
    setResult(null); setError(''); setNotice(''); setBusy(false);
  }, [standalone, querySignature]);
  useEffect(() => {
    const changed = event => { if (event.key === commandKey) setPending({ key: commandKey, command: readFinanceCommand(commandKey) }); };
    window.addEventListener('storage', changed);
    return () => window.removeEventListener('storage', changed);
  }, [commandKey]);
  useEffect(() => {
    const controller = new AbortController();
    const current = api.captureSession();
    setReferencesReady(false); setReferenceError('');
    Promise.all([api.list('/reports/v2/saved', { signal: controller.signal }),
      api.list('/properties', { signal: controller.signal }), api.list('/units', { signal: controller.signal }),
      api.list('/portfolios', { signal: controller.signal }), api.list('/ownership-shares/owners', { signal: controller.signal })])
      .then(([reports, props, allUnits, allPortfolios, allOwners]) => {
        current(); if (controller.signal.aborted) return;
        setSaved(reports); setProperties(props); setUnits(allUnits); setPortfolios(allPortfolios); setOwners(allOwners); setReferencesReady(true);
      })
      .catch(e => { if (!controller.signal.aborted) setReferenceError(e.message); });
    return () => controller.abort();
  }, [loadAttempt]);
  const update = next => {
    setDefinition(next); setResult(null); setNotice(''); setError(''); setSaveKey(crypto.randomUUID());
    if (standalone) setParams(current => {
      const query = new URLSearchParams(current);
      queryKeys.forEach(key => { if (next[key]) query.set(key, next[key]); else query.delete(key); });
      return query;
    }, { replace: true });
  };
  const change = (key, value) => {
    const next = { ...definition, [key]: value };
    if (key === 'portfolio_id') { next.property_id = null; next.unit_id = null; next.vacant_unit_ids = []; }
    if (key === 'property_id') { next.unit_id = null; next.vacant_unit_ids = []; }
    if (key === 'unit_id') {
      if (value) next.property_id = units.find(unit => unit.id === value)?.property_id || next.property_id;
      next.vacant_unit_ids = next.vacant_unit_ids.filter(id => !value || id === value);
    }
    update(next);
  };
  const run = async (action) => {
    const session = api.captureSession();
    const epoch = ++requestEpoch.current;
    const actionQuery = querySignature;
    const isCurrent = () => active.current && requestEpoch.current === epoch && (!standalone || latestQuery.current === actionQuery);
    const current = () => { session(); if (!isCurrent()) throw new Error('Die Berichtsauswahl hat sich geändert.'); };
    setBusy(true); setError(''); setNotice('');
    try { await action(current); current(); } catch (e) { if (isCurrent()) setError(e.message); } finally { if (isCurrent()) setBusy(false); }
  };
  const saveReport = () => run(async current => {
    if (!owner) throw new Error('Die Anmeldung wird noch geprüft. Bitte erneut versuchen.');
    const command = pending || { path: '/reports/v2/saved', request: { name, definition, idempotency_key: saveKey } };
    rememberFinanceCommand(commandKey, command); setPending({ key: commandKey, command });
    try {
      const r = await api.post(command.path, command.request); current();
      forgetFinanceCommand(commandKey, command); setPending({ key: commandKey, command: null });
      setSaved(list => [...list.filter(v => v.id !== r.id), r]);
      setSaveKey(crypto.randomUUID());
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
  const selectedProperties = properties.filter(property => !definition.portfolio_id || property.portfolio_id === definition.portfolio_id);
  const selectedPropertyIds = new Set(selectedProperties.map(property => property.id));
  const selectedUnits = units.filter(unit => selectedPropertyIds.has(unit.property_id) && (!definition.property_id || unit.property_id === definition.property_id));
  const selectPeriod = preset => {
    const day = definition.as_of || today();
    const year = Number(day.slice(0, 4));
    let first = null, last = null;
    if (preset === 'year') { first = `${year}-01-01`; last = definition.kind === 'cash-v2' ? day : `${year}-12-31`; }
    if (preset === 'previous') { first = `${year - 1}-01-01`; last = `${year - 1}-12-31`; }
    if (preset === 'twelve') {
      const start = new Date(`${day.slice(0, 7)}-01T12:00:00`); start.setMonth(start.getMonth() - 11);
      first = start.toLocaleDateString('sv-SE');
      const end = new Date(`${day.slice(0, 7)}-01T12:00:00`); end.setMonth(end.getMonth() + 1); end.setDate(0);
      last = definition.kind === 'cash-v2' ? day : end.toLocaleDateString('sv-SE');
    }
    update({ ...definition, date_from: first, date_to: last });
  };
  return <div className="finance-report-workspace">
    {referenceError && <div role="alert" className="alert alert-error">{referenceError} <button type="button" className="btn btn-secondary" onClick={() => setLoadAttempt(value => value + 1)}>Auswahldaten erneut laden</button></div>}
    {!referencesReady && !referenceError && <p role="status">Berichte und Objektauswahl werden geladen…</p>}
    {error && <p role="alert">{error} Ihre Eingaben bleiben erhalten. Bitte erneut versuchen.</p>}
    {notice && <p role="status">{notice}</p>}
    {pending && <p role="status">Die Bestätigung einer Berichtsspeicherung steht noch aus.
      {canSave && <button type="button" disabled={busy} onClick={saveReport}>Speicherung prüfen und fortsetzen</button>}</p>}
    <fieldset disabled={busy || Boolean(pending)} className="finance-editor">
    <label>Gespeicherten Bericht öffnen <select aria-label="Gespeicherten Bericht öffnen" value="" disabled={busy}
      onChange={e => { const r = saved.find(r => r.id === e.target.value); if (r) { update(r.definition); setName(r.name); } }}>
      <option value="">Bitte auswählen</option>{saved.map(r => <option key={r.id} value={r.id}>{r.name}</option>)}
    </select></label>
    <label>Berichtsart <select aria-label="Berichtsart" value={definition.kind} onChange={e => change('kind', e.target.value)}>
      <option value="cash-v2">Zahlungsübersicht</option><option value="performance-period-v2">Periodenergebnis</option><option value="liquidity-v2">Liquiditätsplanung</option>
    </select></label>
    <p className="finance-basis">{definition.kind === 'cash-v2' ? 'Tatsächlich gebuchte Einnahmen und Ausgaben nach Zahlungsdatum.' : definition.kind === 'performance-period-v2' ? 'Sollmiete + sonstige Einnahmen − Kosten nach Leistungszeitraum. Zahlungseingänge werden nicht ein zweites Mal gezählt.' : 'Erwartete Zahlungen mit sichtbaren Annahmen. Planwerte sind keine zugesicherten Zahlungseingänge.'}</p>
    <div className="finance-filter-grid">
    <label>Stichtag <input type="date" value={definition.as_of} onChange={e => change('as_of', e.target.value)} /></label>
    <label>Portfolio <select aria-label="Portfolio" disabled={!referencesReady} value={definition.portfolio_id || ''} onChange={e => change('portfolio_id', e.target.value || null)}>
      <option value="">Alle berechtigten Portfolios</option>{portfolios.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
      {definition.portfolio_id && !portfolios.some(p => p.id === definition.portfolio_id) && <option value={definition.portfolio_id}>Nicht verfügbares Portfolio ({definition.portfolio_id})</option>}
    </select></label>
    <label>Immobilie <select aria-label="Immobilie" disabled={!referencesReady} value={definition.property_id || ''} onChange={e => change('property_id', e.target.value || null)}>
      <option value="">Alle berechtigten Immobilien</option>{selectedProperties.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
      {definition.property_id && !selectedProperties.some(p => p.id === definition.property_id) && <option value={definition.property_id}>Nicht verfügbare Immobilie ({definition.property_id})</option>}
    </select></label>
    <label>Einheit <select aria-label="Einheit" disabled={!referencesReady} value={definition.unit_id || ''} onChange={e => change('unit_id', e.target.value || null)}>
      <option value="">Alle Einheiten und Objektkosten</option>{selectedUnits.map(unit => <option key={unit.id} value={unit.id}>{unit.label || unit.unit_number || unit.id}{!definition.property_id ? ` · ${properties.find(property => property.id === unit.property_id)?.name || 'Immobilie'}` : ''}</option>)}
      {definition.unit_id && !selectedUnits.some(unit => unit.id === definition.unit_id) && <option value={definition.unit_id}>Nicht verfügbare Einheit ({definition.unit_id})</option>}
    </select></label>
    {(owners.length > 0 || definition.owner_contact_id) && <label>Eigentümer <select aria-label="Eigentümer" disabled={!referencesReady} value={definition.owner_contact_id || ''} onChange={e => change('owner_contact_id', e.target.value || null)}>
      <option value="">Alle Eigentümer (ganzer Bestand)</option>{owners.map(owner => <option key={owner.id} value={owner.id}>{owner.name}</option>)}
      <option value="none">Ohne erfassten Eigentümer</option>
      {definition.owner_contact_id && definition.owner_contact_id !== 'none' && !owners.some(owner => owner.id === definition.owner_contact_id) && <option value={definition.owner_contact_id}>Nicht verfügbarer Eigentümer ({definition.owner_contact_id})</option>}
    </select></label>}
    </div>
    {definition.owner_contact_id && <p className="finance-help">Jeder Betrag zählt mit dem Anteil des Eigentümers an Einheit oder Objekt am jeweiligen Tag; Kontoeröffnungssalden zählen nicht. Die Eigentümer ergeben zusammen den ganzen Bestand.</p>}
    {(definition.portfolio_id || definition.property_id || definition.unit_id || definition.owner_contact_id) && <button className="btn btn-secondary finance-reset-selection" type="button" onClick={() => update({ ...definition, portfolio_id: null, property_id: null, unit_id: null, owner_contact_id: null, vacant_unit_ids: [] })}>Objektauswahl zurücksetzen</button>}
    {definition.property_id && <div className="finance-actions"><Link to={`/properties/${encodeURIComponent(definition.property_id)}`}>Immobilienakte öffnen →</Link>{definition.unit_id && <Link to={`/units/${encodeURIComponent(definition.unit_id)}`}>Einheitenakte öffnen →</Link>}</div>}
    {definition.kind !== 'liquidity-v2' ? <>
      <div className="finance-actions" role="group" aria-label="Zeitraum schnell auswählen"><button className="btn btn-secondary" type="button" onClick={() => selectPeriod('year')}>Stichtagsjahr</button><button className="btn btn-secondary" type="button" onClick={() => selectPeriod('previous')}>Vorjahr</button><button className="btn btn-secondary" type="button" onClick={() => selectPeriod('twelve')}>Letzte 12 Monate</button><button className="btn btn-secondary" type="button" onClick={() => selectPeriod('reset')}>Zeitraum zurücksetzen</button></div>
      <div className="finance-filter-grid">
      <label>Zeitraum von <input type="date" value={definition.date_from || ''} onChange={e => change('date_from', e.target.value || null)} /></label>
      <label>Zeitraum bis <input type="date" value={definition.date_to || ''} onChange={e => change('date_to', e.target.value || null)} /></label>
      </div><p className="finance-help">{definition.kind === 'cash-v2' ? 'Ohne Zeitraum: alle passenden Buchungen bis einschließlich Stichtag. Objektkosten ohne Einheitenzuordnung bleiben in der Immobilienauswertung sichtbar.' : 'Ganze Kalendermonate auswählen. Ohne Zeitraum wird das Kalenderjahr des Stichtags ausgewertet. Rechnungen ohne Leistungszeitraum erhalten einen Hinweis.'}</p>
    </> : <>
      <h2 className="finance-subheading">Planungsannahmen</h2><div className="finance-filter-grid">
      <label>Planungshorizont <select value={definition.months} onChange={e => change('months', Number(e.target.value))}>
        {[3, 6, 12].map(m => <option key={m} value={m}>{m} Monate einschließlich Restmonat</option>)}</select></label>
      <label>Zahlungstag der Miete <input type="number" min="1" max="31" value={definition.rent_payment_day} onChange={e => change('rent_payment_day', Number(e.target.value))} /></label>
      <label>Erwarteter Mieteingang (%) <input type="number" min="0" max="100" step="0.01" value={definition.rent_collection_percent} onChange={e => change('rent_collection_percent', e.target.value)} /></label>
      <label>Erwarteter Eingang offener Rückstände im Folgemonat (%) <input type="number" min="0" max="100" step="0.01" value={definition.arrears_collection_percent} onChange={e => change('arrears_collection_percent', e.target.value)} /></label>
      </div><p className="finance-help">Der Anfangssaldo umfasst Buchungen bis einschließlich Stichtag; geplante Zahlungen werden ab dem Folgetag berücksichtigt. Bei Immobilien und Einheiten ist der Saldo ein Buchungssaldo, kein eigener Bankkontostand.</p>
      <details><summary>Im Szenario leerstehende Einheiten ({definition.vacant_unit_ids.length})</summary>{selectedUnits.filter(unit => !definition.unit_id || unit.id === definition.unit_id).map(u =>
        <label key={u.id} className="finance-check"><input type="checkbox" checked={definition.vacant_unit_ids.includes(u.id)} onChange={e => change('vacant_unit_ids', e.target.checked ? [...definition.vacant_unit_ids, u.id] : definition.vacant_unit_ids.filter(id => id !== u.id))} /> {u.label}</label>)}</details>
      <fieldset><legend>Zusätzliche geplante Zahlungen (Ausgaben negativ)</legend>
        {definition.planned_flows.map((f, index) => <div key={f.identity} className="finance-planned-row">
          <input aria-label={`Bezeichnung ${index + 1}`} value={f.label} onChange={e => change('planned_flows', definition.planned_flows.map((v, i) => i === index ? { ...v, label: e.target.value } : v))} />
          <input aria-label={`Datum ${index + 1}`} type="date" value={f.day} onChange={e => change('planned_flows', definition.planned_flows.map((v, i) => i === index ? { ...v, day: e.target.value } : v))} />
          <input aria-label={`Betrag ${index + 1}`} type="number" step="0.01" value={f.amount} onChange={e => change('planned_flows', definition.planned_flows.map((v, i) => i === index ? { ...v, amount: e.target.value } : v))} />
          <button type="button" onClick={() => change('planned_flows', definition.planned_flows.filter((_, i) => i !== index))}>Entfernen</button>
          {f.day <= definition.as_of && <p role="status" className="finance-help">Diese Zahlung liegt am oder vor dem Stichtag und wird nicht prognostiziert.</p>}
        </div>)}<button type="button" onClick={() => change('planned_flows', [...definition.planned_flows, { identity: `plan:${crypto.randomUUID()}`, day: followingDay(definition.as_of || today()), amount: '0.00', label: 'Geplante Zahlung' }])}>Zahlung ergänzen</button>
      </fieldset>
    </>}
    <label>Berichtsname <input value={name} maxLength={160} onChange={e => { setName(e.target.value); setSaveKey(crypto.randomUUID()); }} /></label>
    <div className="finance-actions">
      <button className="btn btn-primary" type="button" disabled={busy || !referencesReady || !definition.as_of} onClick={() => run(async current => {
        setResult(null);
        const data = await api.get(`/reports/v2/preview?definition=${encodeURIComponent(JSON.stringify(definition))}`); current();
        const numeric = value => (typeof value === 'number' || (typeof value === 'string' && value.trim() !== '')) && Number.isFinite(Number(value));
        const columns = data?.basis === 'liquidity-v2' ? ['income', 'expense', 'balance'] : data?.basis === 'cash-v2' ? ['income', 'expense', 'net'] : ['rent_due', 'other_income', 'costs', 'result'];
        if (!data || data.basis !== definition.kind || typeof data.definition_hash !== 'string' || !data.result_hash || !Array.isArray(data.sources) || !Array.isArray(data.warnings) || !Array.isArray(data.monthly)
          || (data.basis === 'liquidity-v2' ? !numeric(data.opening_balance) || !numeric(data.closing_balance)
            : !data.totals || !columns.every(key => numeric(data.totals[key])))
          || !data.monthly.every(row => row && typeof row.month === 'string' && columns.every(key => numeric(row[key])))
          || !data.sources.every(source => source && numeric(source.amount) && (source.url == null || typeof source.url === 'string'))
          || ['opening_sources', 'baseline_sources'].some(key => data[key] != null && (!Array.isArray(data[key]) || !data[key].every(source => source && numeric(source.amount))))
          || !data.warnings.every(warning => warning && typeof warning.message === 'string')
          || (data.baseline_monthly != null && (!Array.isArray(data.baseline_monthly) || !data.baseline_monthly.every(row => row && typeof row.month === 'string' && numeric(row.balance))))) throw new Error('Die Berichtsantwort ist unvollständig. Bitte erneut berechnen.');
        setResult(data);
      })}>Berechnen</button>
      {canSave && <button className="btn btn-secondary" type="button" disabled={busy || !referencesReady || !name.trim()} onClick={saveReport}>Als neue Fassung speichern</button>}
      {['json', 'csv', 'pdf'].map(f => <button className="btn btn-secondary" type="button" key={f} disabled={busy || !result} onClick={() => exportReport(f)}>{f.toUpperCase()} herunterladen</button>)}
    </div>
    </fieldset>
    {busy && <p role="status">Bericht wird verarbeitet …</p>}
    {result && <ReportResult key={result.result_hash || result.definition_hash} result={result} />}
    {definition.kind === 'performance-period-v2' && owners.length > 0 && <OwnerResults definition={definition} onPick={id => change('owner_contact_id', id)} />}
  </div>;
}

function ReportResult({ result }) {
  const [search, setSearch] = useState('');
  const [month, setMonth] = useState('');
  const [contribution, setContribution] = useState('');
  const [page, setPage] = useState(0);
  const [sourceSet, setSourceSet] = useState('scenario');
  const [allWarnings, setAllWarnings] = useState(false);
  const sourceRef = useRef(null);
  const cash = value => formatMoney(value, { currency: result.currency || 'EUR' });
  const plan = result.basis === 'liquidity-v2', payment = result.basis === 'cash-v2';
  const totals = result.totals || {};
  const metrics = plan ? [['Anfangssaldo', result.opening_balance, 'opening'], ['Endsaldo Szenario', result.closing_balance, 'scenario'], ['Endsaldo Basis', result.baseline_monthly?.at(-1)?.balance, 'baseline']]
    : payment ? [['Einnahmen', totals.income], ['Ausgaben', totals.expense], ['Saldo', totals.net],
      // the owners' own money moves the accounts, not the balance of income and expenses
      ...(Number(totals.withdrawal) || Number(totals.contribution) ? [['Entnahmen', totals.withdrawal], ['Einlagen', totals.contribution]] : [])]
      : [['Sollmiete inkl. Vorauszahlungen', totals.rent_due, 'rent_due'], ['Sonstige Einnahmen', totals.other_income, 'other_income'], ['Kosten', totals.costs, 'costs'], ['Periodenergebnis', totals.result, '']];
  const reveal = (value, role = contribution) => { setMonth(value); if (!value) setSearch(''); if (plan) setSourceSet(role || 'scenario'); else setContribution(role); setPage(0); sourceRef.current?.focus(); sourceRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'start' }); };
  const sourceRows = plan && sourceSet === 'opening' ? result.opening_sources || [] : plan && sourceSet === 'baseline' ? result.baseline_sources || [] : result.sources;
  const sourceTitle = plan && sourceSet === 'opening' ? 'Quellen des Anfangssaldos' : plan && sourceSet === 'baseline' ? 'Quellen der Basisprognose' : 'Quellen und Zahlungsannahmen';
  const needle = search.toLocaleLowerCase();
  const sources = sourceRows.filter(source => (!month || (source.month || source.day?.slice(0, 7)) === month)
    && (!contribution || source.contribution === contribution)
    && (!needle || [source.label, source.basis, source.identity, source.month, source.day, source.amount].some(value => String(value ?? '').toLocaleLowerCase().includes(needle))));
  const pageSize = 50, currentPage = Math.min(page, Math.max(0, Math.ceil(sources.length / pageSize) - 1));
  const query = new URLSearchParams(Object.entries(result.filters || {}).filter(([, value]) => value));
  return <section className="finance-result" aria-label="Berechneter Bericht">
    <h2>Ergebnis und Quellen</h2><p className="finance-help">{payment ? 'Tatsächliche Zahlungen' : plan ? 'Szenario und Basisprognose' : 'Sollmiete + sonstige Einnahmen − Kosten'} · {result.currency || 'EUR'}{result.filters?.date_from && ` · ${formatDate(result.filters.date_from)}`}{result.filters?.date_to && ` bis ${formatDate(result.filters.date_to)}`}</p>
    <div className="finance-result-metrics">{metrics.map(([label, value, role]) => <div className="finance-result-metric" key={label}><span>{label}</span><strong className={Number(value) < 0 ? 'is-negative' : ''}>{value == null ? 'Nicht übermittelt' : cash(value)}</strong>
      {payment && !result.filters?.owner_contact_id ? <Link to={`/bookings?${query}${{ Einnahmen: '&flow=income', Ausgaben: '&flow=expense', Entnahmen: '&flow=withdrawal', Einlagen: '&flow=contribution' }[label] || ''}`}>Buchungen prüfen →</Link> : <button type="button" disabled={value == null} onClick={() => reveal('', role || '')}>Quellen prüfen →</button>}</div>)}</div>
    <div className="finance-table-scroll"><table><caption>Monatsverlauf</caption><thead><tr><th scope="col">Monat</th><th scope="col">{plan || payment ? 'Eingänge' : 'Sollmiete'}</th>{!plan && !payment && <th scope="col">Sonstige Einnahmen</th>}<th scope="col">{plan || payment ? 'Ausgänge' : 'Kosten'}</th><th scope="col">{plan ? 'Saldo Szenario' : payment ? 'Saldo' : 'Ergebnis'}</th>{result.baseline_monthly && <th scope="col">Saldo Basis</th>}</tr></thead><tbody>
      {result.monthly.map(row => <tr key={row.month}><th scope="row"><button type="button" onClick={() => reveal(row.month)} aria-label={`Quellen für ${row.month} anzeigen`}>{row.month}</button></th><td>{cash(row.income ?? row.rent_due)}</td>{!plan && !payment && <td>{cash(row.other_income)}</td>}<td>{cash(row.expense ?? row.costs)}</td><td>{cash(row.balance ?? row.net ?? row.result)}</td>{result.baseline_monthly && <td>{cash(result.baseline_monthly.find(baseline => baseline.month === row.month)?.balance)}</td>}</tr>)}
    </tbody></table></div>
    {result.warnings.length > 0 && <div className="finance-warnings"><h3>Angaben prüfen ({result.warnings.length})</h3>{(allWarnings ? result.warnings : result.warnings.slice(0, 5)).map((warning, index) => {
      const [type, ...id] = (warning.source || '').split(':');
      const path = { invoice: '/invoice-review/', receivable: '/receivables?focus_id=', booking: '/bookings?booking_id=' }[type];
      return <p role="status" key={index}>{warning.message}{path && id.length > 0 && <> <Link to={path + encodeURIComponent(id.join(':'))}>Vorgang prüfen →</Link></>}</p>;
    })}{result.warnings.length > 5 && <button type="button" className="btn btn-secondary" aria-expanded={allWarnings} onClick={() => setAllWarnings(!allWarnings)}>{allWarnings ? 'Weniger Hinweise anzeigen' : `Alle ${result.warnings.length} Hinweise anzeigen`}</button>}</div>}
    <section className="finance-sources" tabIndex={-1} ref={sourceRef} aria-label="Quellen und Zahlungsannahmen"><h3>{sourceTitle} ({sourceRows.length})</h3>
      {plan && <><label>Berechnungsgrundlage <select aria-label="Berechnungsgrundlage" value={sourceSet} onChange={event => { setSourceSet(event.target.value); setMonth(''); setSearch(''); setPage(0); }}><option value="scenario">Szenario: künftige Zahlungen</option><option value="baseline">Basis: künftige Zahlungen</option><option value="opening">Anfangssaldo: Kontovortrag und bisherige Buchungen</option></select></label><p className="finance-help">{sourceSet === 'opening' ? 'Diese Belege ergeben zusammen den Anfangssaldo zum Stichtag.' : 'Der Endsaldo ergibt sich aus dem Anfangssaldo plus den hier aufgeführten künftigen Zahlungen. Basis: voller Mieteingang, keine zusätzliche Einziehung von Rückständen, keine Leerstands- oder Zusatzannahmen.'}</p>{sourceSet !== 'opening' && <p className="finance-help">Bereits datierte Zahlungen und Rückbuchungen bis zum Ende der Planung werden berücksichtigt. Vertragsabschläge ohne zugeordnete Rechnungsperiode gelten für den Buchungsmonat; abweichende Zeiträume bitte über eine verknüpfte Rechnung zuordnen.</p>}</>}
      <div className="finance-filter-grid"><label>Quellen durchsuchen <input type="search" value={search} onChange={event => { setSearch(event.target.value); setPage(0); }} placeholder="Vorgang, Grundlage, Betrag…" /></label>{sourceSet !== 'opening' && <label>Quellenmonat <select value={month} onChange={event => { setMonth(event.target.value); setPage(0); }}><option value="">Alle Monate</option>{result.monthly.map(row => <option key={row.month} value={row.month}>{row.month}</option>)}</select></label>}</div>
      {!plan && !payment && <label className="finance-source-type">Quellenart <select aria-label="Quellenart" value={contribution} onChange={event => { setContribution(event.target.value); setPage(0); }}><option value="">Alle Beitragsarten</option><option value="rent_due">Sollmiete</option><option value="other_income">Sonstige Einnahmen</option><option value="costs">Kosten</option></select></label>}
      {sources.length > 0 ? <div className="finance-table-scroll"><table><caption>Quellbelege und Berechnungsannahmen</caption><thead><tr><th scope="col">Datum / Monat</th><th scope="col">Vorgang / Grundlage</th><th scope="col">Betrag laut Quelle</th></tr></thead><tbody>{sources.slice(currentPage * pageSize, (currentPage + 1) * pageSize).map((source, index) => <tr key={`${source.identity}:${index}`}><td>{source.day ? formatDate(source.day) : source.month || 'Kontovortrag'}</td><td>{source.url ? <Link to={source.url}>{source.label || source.basis || 'Beleg öffnen'}</Link> : source.label || source.basis || source.identity}</td><td>{cash(source.amount)}</td></tr>)}</tbody></table></div> : <p>{sourceRows.length ? 'Keine Quellen entsprechen der Auswahl.' : 'Keine beitragenden Vorgänge in diesem Zeitraum.'}</p>}
      <div className="finance-source-pagination"><span role="status">{sources.length ? `${currentPage * pageSize + 1}–${Math.min((currentPage + 1) * pageSize, sources.length)} von ${sources.length} Quellen` : '0 Quellen'}</span><div className="finance-actions"><button className="btn btn-secondary" type="button" disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}>Vorherige Quellen</button><button className="btn btn-secondary" type="button" disabled={(currentPage + 1) * pageSize >= sources.length} onClick={() => setPage(currentPage + 1)}>Weitere Quellen</button></div></div>
    </section>
    <details className="finance-proof"><summary>Berechnungsnachweis</summary><p>Definition: {result.definition_hash} · Ergebnis: {result.result_hash || 'Nicht übermittelt'}</p><p>Exporte werden vor der Ausgabe erneut mit dem Ergebnisstand abgeglichen. Eine gespeicherte Definition wird beim Öffnen mit aktuellen Daten neu berechnet.</p></details>
  </section>;
}

// The period result and the owners' own money per owner; the rows add up to the whole (reports/owner-results).
function OwnerResults({ definition, onPick }) {
  const [state, setState] = useState({ status: 'idle', data: null, error: '', query: '' });
  const year = (definition.as_of || today()).slice(0, 4);
  const query = new URLSearchParams(Object.entries({ date_from: definition.date_from || `${year}-01-01`, date_to: definition.date_to || `${year}-12-31`,
    portfolio_id: definition.portfolio_id, property_id: definition.property_id, unit_id: definition.unit_id }).filter(([, value]) => value)).toString();
  const load = async () => {
    const asked = query;
    setState({ status: 'loading', data: null, error: '', query: asked });
    // a later calculation (or another selection) wins over an earlier answer
    const settle = next => setState(current => current.query === asked ? { ...next, query: asked } : current);
    try { settle({ status: 'ready', data: await api.get(`/reports/owner-results?${asked}`), error: '' }); }
    catch (e) { settle({ status: 'error', data: null, error: e.message }); }
  };
  const current = state.query === query;
  const shown = current ? state.data : null;
  const money = value => formatMoney(value);
  return <section className="finance-result" aria-label="Ergebnis je Eigentümer">
    <h2>Ergebnis je Eigentümer</h2>
    <p className="finance-help">Sollmiete, Erträge und Kosten nach den Eigentumsanteilen an Einheiten und Objekten; Entnahmen und Einlagen des jeweiligen Eigentümers daneben. Die Zeilen ergeben zusammen das Ergebnis des ganzen Bestands.</p>
    <button type="button" className="btn btn-secondary" disabled={state.status === 'loading'} onClick={load}>{shown ? 'Neu berechnen' : 'Ergebnis je Eigentümer berechnen'}</button>
    {current && state.status === 'loading' && <p role="status">Wird berechnet …</p>}
    {current && state.status === 'error' && <p role="alert">{state.error}</p>}
    {shown && <div className="finance-table-scroll"><table><caption>Ergebnis je Eigentümer</caption><thead><tr>
      <th scope="col">Eigentümer</th><th scope="col">Sollmiete</th><th scope="col">Sonstige Einnahmen</th><th scope="col">Kosten</th><th scope="col">Ergebnis</th><th scope="col">Entnahmen</th><th scope="col">Einlagen</th><th scope="col">Kontostand zum Periodenende</th><th scope="col"><span className="sr-only">Auswahl</span></th>
    </tr></thead><tbody>
      {shown.owners.map(row => <tr key={row.owner_contact_id}><th scope="row">{row.name}</th><td>{money(row.rent_due)}</td><td>{money(row.other_income)}</td><td>{money(row.costs)}</td><td>{money(row.result)}</td><td>{money(row.withdrawal)}</td><td>{money(row.contribution)}</td><td>{money(row.balance)}</td>
        <td><button type="button" className="btn btn-sm btn-ghost" onClick={() => onPick(row.owner_contact_id)}>Nur diesen Teil auswerten</button></td></tr>)}
    </tbody><tfoot><tr><th scope="row">Gesamt</th><td>{money(shown.totals.rent_due)}</td><td>{money(shown.totals.other_income)}</td><td>{money(shown.totals.costs)}</td><td>{money(shown.totals.result)}</td><td>{money(shown.totals.withdrawal)}</td><td>{money(shown.totals.contribution)}</td><td>{money(shown.totals.balance)}</td><td /></tr></tfoot></table></div>}
  </section>;
}
