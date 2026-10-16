import { useEffect, useRef, useState } from 'react';
import { api } from '../api';
import { useCanWrite } from '../contexts/AuthContext';
import { privateStorageKey, workspaceOwner } from '../utils/workspaceIdentity';
import './taxExports.css';

const key = () => crypto.randomUUID();
const money = cents => {
  const value = BigInt(cents || '0');
  const absolute = value < 0n ? -value : value;
  return `${value < 0n ? '-' : ''}${absolute / 100n},${(absolute % 100n).toString().padStart(2, '0')} €`;
};
const emptyRule = () => ({ account_id: '', category_id: '', flow: 'income', bank_gl: '', counter_gl: '',
  treatment: 'income', form_line: '', reason: '', exclusion_kind: '', counter_kind: 'general' });
const labels = { income: 'Einnahme', expense: 'Ausgabe', excluded: 'Nicht steuerlich übernehmen' };
const exclusions = [['deposit', 'Kaution'], ['loan_principal', 'Darlehenstilgung'], ['personal', 'Privat'], ['internal_transfer', 'Interner Übertrag'], ['other', 'Sonstiges']];
const issueNames = { classification_missing: 'Steuerliche Zuordnung fehlt', property_assignment_required: 'Objektzuordnung fehlt',
  allocation_sum_differs_from_cash: 'Teilbeträge stimmen nicht mit der Buchung überein', allocation_sign_differs_from_cash: 'Teilbeträge haben ein abweichendes Vorzeichen',
  pending_entries_need_explicit_review: 'Offene Buchungen benötigen eine Begründung', no_confirmed_cash_sources: 'Keine bestätigten Zahlungen: Leerbestand ausdrücklich prüfen',
  internal_transfer_counter_evidence_required: 'Gegenbuchung für internen Übertrag fehlt', internal_transfer_counter_must_also_be_excluded: 'Die Gegenbuchung muss ebenfalls als interner Übertrag ausgeschlossen werden',
  correction_evidence_requires_earlier_opposite_cash: 'Korrektur benötigt einen früheren Beleg mit umgekehrtem Vorzeichen',
  internal_transfer_requires_opposite_confirmed_other_account: 'Gegenbuchung muss bestätigt, betragsgleich und auf einem anderen Konto sein',
  category_missing_or_cross_portfolio: 'Kategorie fehlt oder gehört zu einem anderen Portfolio', property_missing_or_cross_portfolio: 'Objekt fehlt oder gehört zu einem anderen Portfolio' };

export default function TaxExports() {
  const canWrite = useCanWrite('/reports');
  const [mode, setMode] = useState('annual-tax');
  const [portfolios, setPortfolios] = useState([]);
  const [portfolio, setPortfolio] = useState('');
  const [options, setOptions] = useState({ accounts: [], categories: [], properties: [] });
  const [profiles, setProfiles] = useState({ items: [], total: 0 });
  const [history, setHistory] = useState({ items: [], total: 0 });
  const [profileOffset, setProfileOffset] = useState(0);
  const [historyOffset, setHistoryOffset] = useState(0);
  const [selected, setSelected] = useState('');
  const [draft, setDraft] = useState({ name: '', reviewed_by: '', tax_year: 2026, adviser: '', client: '', gl_length: 4, chart: '', freeze: 0, document_reference: 'empty' });
  const [previous, setPrevious] = useState(null);
  const [rules, setRules] = useState([emptyRule()]);
  const [confirmed, setConfirmed] = useState(false);
  const [start, setStart] = useState('2026-01-01');
  const [end, setEnd] = useState('2026-12-31');
  const [propertyIds, setPropertyIds] = useState([]);
  const [asOf, setAsOf] = useState(new Date().toISOString().slice(0, 10));
  const [pendingReason, setPendingReason] = useState('');
  const [emptyReason, setEmptyReason] = useState('');
  const [revision, setRevision] = useState(null);
  const [revisionReason, setRevisionReason] = useState('');
  const [overrides, setOverrides] = useState([]);
  const [preview, setPreview] = useState(null);
  const [sourcePage, setSourcePage] = useState(null);
  const [sourceOffset, setSourceOffset] = useState(0);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const retry = useRef(new Map());
  const epoch = useRef(0);
  const annual = mode === 'annual-tax';
  const base = `/reports/${mode}`;
  const bufferKey = privateStorageKey(`tax-input:${mode}:${portfolio}`);
  const [recovered, setRecovered] = useState(false);

  useEffect(() => {
    if (!portfolio || !workspaceOwner()) return;
    try {
      const stored = JSON.parse(localStorage.getItem(bufferKey) || 'null');
      if (stored) {
        setDraft(stored.draft); setRules(stored.rules); setPrevious(stored.previous);
        setOverrides(stored.overrides); setPendingReason(stored.pendingReason); setEmptyReason(stored.emptyReason);
        setAsOf(stored.asOf); setStart(stored.start); setEnd(stored.end); setConfirmed(false); setRecovered(true);
      }
    } catch { setError('Der lokale Entwurf konnte nicht gelesen werden. Gespeicherte Profile bleiben erhalten.'); }
  }, [bufferKey, portfolio]);

  useEffect(() => {
    if (!portfolio || !workspaceOwner()) return;
    const values = { draft, rules, previous, overrides, pendingReason, emptyReason, asOf, start, end };
    const current = api.captureSession();
    const save = () => {
      try { current(); localStorage.setItem(bufferKey, JSON.stringify(values)); }
      catch { /* Session changes must never write under another owner's identity. */ }
    };
    const timer = setTimeout(save, 150);
    window.addEventListener('beforeunload', save);
    return () => { clearTimeout(timer); window.removeEventListener('beforeunload', save); };
  }, [bufferKey, portfolio, draft, rules, previous, overrides, pendingReason, emptyReason, asOf, start, end]);

  useEffect(() => {
    let active = true;
    api.list('/portfolios').then(rows => { if (active) setPortfolios(rows); }).catch(e => { if (active) setError(e.message); });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    let active = true;
    const current = api.captureSession();
    if (!portfolio) return;
    setBusy(true); setError('');
    Promise.all([api.get(`${base}/options?portfolio_id=${encodeURIComponent(portfolio)}`),
      api.get(`${base}/profiles?portfolio_id=${encodeURIComponent(portfolio)}&offset=${profileOffset}&limit=20`),
      api.get(`${base}/${annual ? 'projections' : 'exports'}?portfolio_id=${encodeURIComponent(portfolio)}&offset=${historyOffset}&limit=20`),
    ]).then(([choices, versions, receipts]) => {
      current();
      if (active) { setOptions(choices); setProfiles(versions); setHistory(receipts); }
    }).catch(e => { if (active) setError(e.message); }).finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, [portfolio, base, annual, profileOffset, historyOffset]);

  function resetContext() {
    epoch.current += 1; setSelected(''); setPrevious(null); setPreview(null); setRevision(null); setPropertyIds([]);
    setRules([emptyRule()]); setOverrides([]); setConfirmed(false); setProfiles({ items: [], total: 0 });
    setHistory({ items: [], total: 0 }); setProfileOffset(0); setHistoryOffset(0); setError('');
  }
  async function action(work) {
    const generation = epoch.current;
    const current = api.captureSession();
    setBusy(true); setError('');
    try {
      const result = await work(); current();
      if (generation === epoch.current) return result;
    } catch (e) { if (generation === epoch.current) setError(e.message); }
    finally { if (generation === epoch.current) setBusy(false); }
  }
  async function post(path, body) {
    const identity = JSON.stringify([path, body]);
    const storageKey = workspaceOwner() ? privateStorageKey('tax-pending-command') : null;
    if (storageKey && !retry.current.has(identity)) {
      try {
        const stored = JSON.parse(localStorage.getItem(storageKey) || 'null');
        if (stored?.identity === identity) retry.current.set(identity, stored.key);
      } catch { /* The in-session command remains retryable if storage is unavailable. */ }
    }
    if (!retry.current.has(identity)) retry.current.set(identity, key());
    if (storageKey) {
      try { localStorage.setItem(storageKey, JSON.stringify({ identity, key: retry.current.get(identity) })); }
      catch { /* The server still enforces the in-session key. */ }
    }
    const result = await api.post(path, { ...body, idempotency_key: retry.current.get(identity) });
    retry.current.delete(identity);
    if (storageKey) {
      try { if (JSON.parse(localStorage.getItem(storageKey) || 'null')?.identity === identity) localStorage.removeItem(storageKey); }
      catch { /* An inaccessible buffer cannot authorize another write. */ }
    }
    return result;
  }
  async function refresh() {
    return Promise.all([api.get(`${base}/profiles?portfolio_id=${encodeURIComponent(portfolio)}&offset=${profileOffset}&limit=20`),
      api.get(`${base}/${annual ? 'projections' : 'exports'}?portfolio_id=${encodeURIComponent(portfolio)}&offset=${historyOffset}&limit=20`)]);
  }
  async function saveProfile(event) {
    event.preventDefault();
    const result = await action(async () => {
      const common = { portfolio_id: portfolio, name: draft.name, reviewed_by: draft.reviewed_by,
        review_confirmed: confirmed, currency: 'EUR', previous_version_id: previous };
      const body = annual ? { ...common, tax_year: Number(draft.tax_year), rules: rules.map(r => ({
        account_id: r.account_id, category_id: r.category_id || null, treatment: r.treatment,
        form_line: r.treatment === 'excluded' ? null : r.form_line, reason: r.reason,
        exclusion_kind: r.treatment === 'excluded' ? r.exclusion_kind : null,
      })) } : { ...common, adviser: Number(draft.adviser), client: Number(draft.client),
        gl_length: Number(draft.gl_length), chart: draft.chart, freeze: Number(draft.freeze), calendar_year: true,
        document_reference: draft.document_reference, rules: rules.map(r => ({ account_id: r.account_id,
          category_id: r.category_id, flow: r.flow, account_type: options.accounts.find(a => a.id === r.account_id)?.account_type,
          bank_gl: r.bank_gl, counter_gl: r.counter_gl, counter_kind: r.counter_kind || 'general', no_vat_nonautomatic: true })) };
      const saved = await post(`${base}/profiles`, body);
      return { saved, pages: await refresh() };
    });
    if (result) { setSelected(result.saved.id); setProfiles(result.pages[0]); setHistory(result.pages[1]); setPrevious(null); setPreview(null); }
  }
  const preflightBody = () => ({ profile_version_id: selected, as_of: asOf, overrides,
    pending_review_reason: pendingReason || null, empty_cash_review_reason: emptyReason || null });
  async function check() {
    const result = await action(() => annual ? api.post(`${base}/preflight`, preflightBody()) :
      post(`${base}/preview`, { profile_version_id: selected, start_date: start, end_date: end, property_ids: propertyIds }));
    if (result) { setPreview(result); setSourcePage(null); setSourceOffset(0); }
  }
  async function loadSourcePage(offset) {
    const result = await action(() => api.post(`${base}/source-page?offset=${offset}&limit=20`, preflightBody()));
    if (result) {
      if (result.preview_hash !== preview.preview_hash) { setError('Die Buchungsquellen wurden geändert. Bitte die Vorschau erneut prüfen.'); setPreview(null); return; }
      setSourcePage(result); setSourceOffset(offset);
    }
  }
  async function saveProjection() {
    const result = await action(async () => {
      await post(`${base}/projections`, { ...preflightBody(), preview_hash: preview.preview_hash,
        previous_projection_id: revision, revision_reason: revision ? revisionReason : null });
      return refresh();
    });
    if (result) { setProfiles(result[0]); setHistory(result[1]); setPreview(null); setRevision(null); }
  }
  async function download(item) {
    const blob = await action(() => api.getBlob(`${base}/${annual ? 'projections' : 'exports'}/${item.id}/download`));
    if (!blob) return;
    const url = URL.createObjectURL(blob); const link = document.createElement('a');
    link.href = url; link.download = `${annual ? 'Jahressteuer-neutral' : 'DATEV'}-${item.id}.zip`; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  function changeRule(index, name, value) { setRules(old => old.map((r, i) => i === index ? { ...r, [name]: value } : r)); setConfirmed(false); }
  function field(name, label, type = 'text') { return <label>{label}<input required type={type} value={draft[name]}
    onChange={e => { setDraft({ ...draft, [name]: e.target.value }); setConfirmed(false); }} /></label>; }
  function pager(offset, setOffset, total, label) { return <nav aria-label={label}><button disabled={busy || offset === 0} onClick={() => setOffset(Math.max(0, offset - 20))}>Zurück</button>
    <span>{total ? offset + 1 : 0}–{Math.min(offset + 20, total)} von {total}</span><button disabled={busy || offset + 20 >= total} onClick={() => setOffset(offset + 20)}>Weiter</button></nav>; }

  return <main className="tax-exports"><h1>Steueraufbereitung und DATEV</h1>
    <p>Geprüfte Zuordnungen, vollständige Buchungsquellen und unveränderliche Exporthistorie. Die Buchhaltung bleibt die Geldquelle.</p>
    <div className="tax-grid"><label>Verfahren<select value={mode} disabled={busy} onChange={e => { resetContext(); setMode(e.target.value); }}>
      <option value="annual-tax">Jahressteuerbasis (neutral)</option><option value="datev">DATEV EXTF ohne Umsatzsteuerautomatik</option></select></label>
    <label>Portfolio<select value={portfolio} disabled={busy} onChange={e => { resetContext(); setPortfolio(e.target.value); }}><option value="">Bitte wählen</option>
      {portfolios.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label></div>
    <aside>WISO Steuer Windows, Fachjahr 2026: Herstellerfelder und Zielimport sind noch nicht durch synthetische Producerbelege bestätigt. Die neutrale Jahressteuerbasis ist keine WISO-Datei. Keine automatische AfA oder Eigentümerquote.</aside>
    {error && <p role="alert">{error} Eingaben bleiben für Korrektur und Wiederholung erhalten.</p>}
    {recovered && <p role="status">Lokaler Entwurf wiederhergestellt. Bitte vor dem Speichern erneut fachlich prüfen.</p>}
    {busy && <p role="status">Daten werden vollständig geprüft …</p>}
    {portfolio && <>
      <section><h2>Profilfassungen</h2><label>Profil für die Vorschau<select value={selected} disabled={busy} onChange={e => { setSelected(e.target.value); setPreview(null); }}><option value="">Bitte wählen</option>
        {profiles.items.map(p => <option key={p.id} value={p.id}>{p.spec.name} · {p.tax_year || 'DATEV'} · {p.created_at}</option>)}</select></label>
        {pager(profileOffset, setProfileOffset, profiles.total, 'Profilseiten')}
        {canWrite && <><button disabled={!selected || busy} onClick={() => { const p = profiles.items.find(p => p.id === selected); if (p) { setDraft({ ...draft, ...p.spec }); setRules(p.spec.rules); setPrevious(p.id); setConfirmed(false); } }}>Gewähltes Profil als neue Fassung bearbeiten</button>
        <form onSubmit={saveProfile}><h3>{previous ? 'Neue Profilfassung' : 'Neues Profil'}</h3><fieldset disabled={busy}><div className="tax-grid">
          {field('name', 'Profilname')}{field('reviewed_by', 'Fachlich geprüft durch')}
          {annual ? field('tax_year', 'Steuerjahr', 'number') : <>{field('adviser', 'Beraternummer', 'number')}{field('client', 'Mandantennummer', 'number')}{field('gl_length', 'Sachkontenlänge', 'number')}
            <label>Kontenrahmen (optional)<input value={draft.chart} onChange={e => setDraft({ ...draft, chart: e.target.value })} /></label>
            <label>Festschreibung<select value={draft.freeze} onChange={e => setDraft({ ...draft, freeze: e.target.value })}><option value={0}>Nicht festschreiben</option><option value={1}>Festschreiben</option></select></label>
            <label>Belegfeld 1<select value={draft.document_reference} onChange={e => setDraft({ ...draft, document_reference: e.target.value })}><option value="empty">Leer lassen</option><option value="internal_booking_id">Interne Buchungs-ID</option></select></label></>}
        </div>
        {rules.map((r, index) => <div className="tax-rule" key={index}><h4>Zuordnung {index + 1}</h4><div className="tax-grid">
          <label>Quellkonto<select required value={r.account_id} onChange={e => changeRule(index, 'account_id', e.target.value)}><option value="">Bitte wählen</option>{options.accounts.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}</select></label>
          <label>Quellkategorie<select required={!annual} value={r.category_id || ''} onChange={e => changeRule(index, 'category_id', e.target.value)}><option value="">{annual ? 'Ohne Kategorie' : 'Bitte wählen'}</option>{options.categories.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label>
          {annual ? <><label>Steuerliche Behandlung<select value={r.treatment} onChange={e => changeRule(index, 'treatment', e.target.value)}>{Object.entries(labels).map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
            {r.treatment === 'excluded' ? <label>Ausschlussgrund<select required value={r.exclusion_kind || ''} onChange={e => changeRule(index, 'exclusion_kind', e.target.value)}><option value="">Bitte wählen</option>{[['deposit', 'Kaution'], ['loan_principal', 'Darlehenstilgung'], ['personal', 'Privat'], ['internal_transfer', 'Interner Übertrag (Gegenbeleg erforderlich)'], ['other', 'Sonstiges']].map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label> : <label>Geprüfte Formularzeile (freie Bezeichnung)<input required value={r.form_line || ''} onChange={e => changeRule(index, 'form_line', e.target.value)} /></label>}
            <label>Fachliche Begründung<input required value={r.reason} onChange={e => changeRule(index, 'reason', e.target.value)} /></label></> : <>
            <label>Geldrichtung<select value={r.flow} onChange={e => changeRule(index, 'flow', e.target.value)}><option value="income">Eingang / Soll</option><option value="expense">Ausgang / Haben</option></select></label>
            <label>DATEV-Konto<input required inputMode="numeric" value={r.bank_gl} onChange={e => changeRule(index, 'bank_gl', e.target.value)} /></label>
            <label>DATEV-Gegenkonto<input required inputMode="numeric" value={r.counter_gl} onChange={e => changeRule(index, 'counter_gl', e.target.value)} /></label></>}
          {!annual && <label>Gegenkontotyp<select value={r.counter_kind || 'general'} onChange={e => changeRule(index, 'counter_kind', e.target.value)}><option value="general">Sachkonto</option><option value="person">Personenkonto</option></select></label>}
        </div><button type="button" disabled={rules.length === 1} onClick={() => { setRules(rules.filter((_, i) => i !== index)); setConfirmed(false); }}>Zuordnung entfernen</button></div>)}
        <button type="button" onClick={() => setRules([...rules, emptyRule()])}>Zuordnung hinzufügen</button>
        <label className="tax-check"><input required type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />{annual ? 'Zuordnungen und Ausschlüsse fachlich geprüft' : 'EUR, Kalenderjahr, nicht automatische Konten ohne Umsatzsteuer und Kontierung fachlich geprüft'}</label>
        <button type="submit">Profilfassung speichern</button></fieldset></form></>}
      </section>
      <section><h2>Vorschau und fehlende Angaben</h2><fieldset disabled={busy || !canWrite}><div className="tax-grid">
        {annual ? <><label>Zahlungsstichtag<input type="date" value={asOf} onChange={e => { setAsOf(e.target.value); setPreview(null); }} /></label>
          <label>Begründung für offene Buchungen<textarea value={pendingReason} onChange={e => { setPendingReason(e.target.value); setPreview(null); }} /></label>
          <label>Begründung bei leerer Zahlungsbasis<textarea value={emptyReason} onChange={e => { setEmptyReason(e.target.value); setPreview(null); }} /></label></> : <>
          <label>Von<input type="date" value={start} onChange={e => { setStart(e.target.value); setPreview(null); }} /></label><label>Bis<input type="date" value={end} onChange={e => { setEnd(e.target.value); setPreview(null); }} /></label></>}
      </div><button disabled={!selected} onClick={check}>Vollständige Quellen prüfen</button></fieldset>
      {!annual && <fieldset disabled={busy}><legend>Objektfilter (leer: alle berechtigten Objekte)</legend>{options.properties?.map(p => <label className="tax-check" key={p.id}><input type="checkbox" checked={propertyIds.includes(p.id)} onChange={e => { setPropertyIds(old => e.target.checked ? [...old, p.id] : old.filter(id => id !== p.id)); setPreview(null); }} />{p.name}</label>)}</fieldset>}
      {preview && <><p role="status">{annual ? preview.ready ? 'Zur Bestätigung bereit' : 'Bitte fehlende Angaben bearbeiten' : 'Vollständig geprüfter Export gespeichert'} · {annual ? preview.source_rows : preview.rows} Buchungsquellen</p>
        {annual ? <><dl>{Object.entries(preview.totals).map(([name, cents]) => <div key={name}><dt>{{ cash_cents: 'Zahlungen gesamt', income_cents: 'Einnahmen', expense_cents: 'Ausgaben', excluded_cash_cents: 'Ausgeschlossen', unclassified_cash_cents: 'Noch zu prüfen' }[name]}</dt><dd>{money(cents)}</dd></div>)}</dl>
          {preview.blocking_issues.map((issue, i) => <p key={i}>{issue.booking_id || 'Gesamtprüfung'}: {issueNames[issue.code] || `Quelle muss geprüft werden (${issue.code})`}</p>)}
          <p>Objektaufteilungen und Korrekturen: Die Summe der Teilbeträge muss dem vorzeichenbehafteten Buchungsbetrag in Cent entsprechen.</p>
          {(sourcePage?.items || preview.source_samples).map(source => <details key={source.booking.id}><summary>{source.booking.booking_date} · {source.booking.payment_text || source.booking.id} · {money(source.booking.amount_cents)}</summary>
            <p>Buchungs-ID: {source.booking.id} · {{ included: 'Zugeordnet', needs_review: 'Prüfung erforderlich', pending: 'Noch nicht bestätigt', after_cutoff: 'Nach dem Stichtag' }[source.classification_state] || source.classification_state}</p>
            <button disabled={!canWrite || busy} onClick={() => { setOverrides(old => [...old.filter(o => o.booking_id !== source.booking.id), { booking_id: source.booking.id, reason: '', parts: [{ property_id: source.booking.property_id || '', amount_cents: source.booking.amount_cents, treatment: 'income', form_line: '', reason: '', exclusion_kind: null }] }]); setPreview(null); }}>Eigene Zuordnung / Objektaufteilung erfassen</button>
          </details>)}
          <nav aria-label="Buchungsquellenseiten"><button disabled={busy || sourceOffset === 0} onClick={() => loadSourcePage(Math.max(0, sourceOffset - 20))}>Vorherige Quellen</button><span>{preview.source_rows ? sourceOffset + 1 : 0} bis {Math.min(sourceOffset + 20, preview.source_rows)} von {preview.source_rows}</span><button disabled={busy || sourceOffset + 20 >= preview.source_rows} onClick={() => loadSourcePage(sourceOffset + 20)}>Weitere Quellen</button></nav>
          {revision && <label>Begründung der Jahresrevision<input value={revisionReason} onChange={e => setRevisionReason(e.target.value)} /></label>}
          <button disabled={!canWrite || busy || !preview.ready || (revision && !revisionReason.trim())} onClick={saveProjection}>Geprüfte Jahresfassung unveränderlich speichern</button></> : <><p>Eingänge: {preview.income} EUR · Ausgänge: {preview.expense} EUR</p><button onClick={() => download(preview)} disabled={busy}>DATEV-Dateien herunterladen</button></>}
      </>}
      {overrides.map((override, index) => <fieldset key={override.booking_id} disabled={busy || !canWrite}><legend>Aufteilung {override.booking_id}</legend>
        <label>Begründung<input required value={override.reason} onChange={e => { setOverrides(old => old.map((o, i) => i === index ? { ...o, reason: e.target.value } : o)); setPreview(null); }} /></label>
        <div className="tax-grid">{[['correction_of_booking_id', 'Korrektur zu Buchungs-ID (optional)'], ['transfer_counter_booking_id', 'Gegenbuchung bei internem ?bertrag']].map(([name, label]) => <label key={name}>{label}<input value={override[name] || ''} onChange={e => { setOverrides(old => old.map((o, i) => i === index ? { ...o, [name]: e.target.value || null } : o)); setPreview(null); }} /></label>)}</div>
        {override.parts.map((part, partIndex) => <div className="tax-grid" key={partIndex}>{[['property_id', 'Objekt'], ['treatment', 'Behandlung'], ['amount_cents', 'Teilbetrag in Cent mit Vorzeichen'], ['form_line', 'Formularzeile'], ['reason', 'Fachliche Begründung'], ['exclusion_kind', 'Ausschlussart']].map(([name, label]) => {
          const update = value => { setOverrides(old => old.map((o, i) => i === index ? { ...o, parts: o.parts.map((p, j) => j === partIndex ? { ...p, [name]: value || null,
            ...(name === 'treatment' ? value === 'excluded' ? { form_line: null } : { exclusion_kind: null } : {}) } : p) } : o)); setPreview(null); };
          return <label key={name}>{label}{name === 'property_id' ? <select value={part[name] || ''} onChange={e => update(e.target.value)}><option value="">Keine Zuordnung</option>{options.properties.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select> : name === 'treatment' ? <select value={part[name]} onChange={e => update(e.target.value)}>{Object.entries(labels).map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select> : name === 'exclusion_kind' ? <select disabled={part.treatment !== 'excluded'} value={part[name] || ''} onChange={e => update(e.target.value)}><option value="">Bitte wählen</option>{exclusions.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select> : <input disabled={name === 'form_line' && part.treatment === 'excluded'} value={part[name] || ''} onChange={e => update(e.target.value)} />}</label>;
        })}<button disabled={override.parts.length === 1} onClick={() => { setOverrides(old => old.map((o, i) => i === index ? { ...o, parts: o.parts.filter((_, j) => j !== partIndex) } : o)); setPreview(null); }}>Teilbetrag entfernen</button></div>)}
        <button onClick={() => setOverrides(old => old.map((o, i) => i === index ? { ...o, parts: [...o.parts, { ...o.parts[0], amount_cents: '', reason: '' }] } : o))}>Teilbetrag hinzufügen</button>
        <button onClick={() => { setOverrides(old => old.filter((_, i) => i !== index)); setPreview(null); }}>Eigene Aufteilung entfernen</button>
      </fieldset>)}
      </section>
      <section><h2>Gesicherte Historie</h2>{history.items.length === 0 && <p>Für dieses Portfolio ist noch keine Fassung gespeichert.</p>}
        {history.items.map(item => <article key={item.id}><p>{item.tax_year || `${item.start_date} bis ${item.end_date}`} · {item.created_at || item.generated_at} · {item.id}</p>
          <button disabled={busy} onClick={() => download(item)}>{annual ? 'Neutrale Quellen und Steuerzeilen' : 'Originale DATEV-Exportdateien'} herunterladen</button>
          {annual && canWrite && <button disabled={busy} onClick={() => { setRevision(item.id); setRevisionReason(''); setSelected(item.profile_version_id); setAsOf(item.review_request.as_of); setOverrides(item.review_request.overrides || []); setPendingReason(item.review_request.pending_review_reason || ''); setEmptyReason(item.review_request.empty_cash_review_reason || ''); setPreview(null); }}>Als neue Jahresrevision prüfen</button>}</article>)}
        {pager(historyOffset, setHistoryOffset, history.total, 'Historienseiten')}</section>
    </>}
  </main>;
}
