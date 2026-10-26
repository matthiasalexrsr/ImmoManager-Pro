import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../../api';
import { useAuth } from '../../contexts/AuthContext';
import { privateStorageKey } from '../../utils/workspaceIdentity';
import { usePreferences } from '../../contexts/PreferencesContext';
import './catalogue.css';
import SessionInventory from './SessionInventory';
import ConfigurationContract from './ConfigurationContract';


// where a value comes from, in words (the server reports its configuration sources as keys)
const ORIGINS = { explicit: 'Beim Start übergeben', process_env: 'Umgebungsvariable', dotenv_file: '.env-Datei',
  secret_file: 'Geheimnisdatei', default: 'Standard', global: 'Installation', personal: 'Persönlich',
  launcher_env_file: '.env-Datei des Starters' };
const originLabel = origin => ORIGINS[origin] || (String(origin || '').startsWith('object:') ? 'Ausgewähltes Objekt' : origin);

export function SettingField({ item, onSaved }) {
  const storage = privateStorageKey(`setting-draft:${item.scope}:${item.key}`);
  const [recovery] = useState(() => { try { return JSON.parse(sessionStorage.getItem(storage) || 'null'); } catch { return null; } });
  const [value, setValue] = useState(recovery?.value ?? item.value);
  const expected = useRef(recovery?.base_revision ?? item.revision);
  const [comparisonRevision, setComparisonRevision] = useState(expected.current);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(Boolean(recovery));
  const dirtyNow = useRef(Boolean(recovery));
  const pending = useRef(recovery?.command || null);
  const mounted = useRef(true);
  const submitting = useRef(false);
  const prefs = usePreferences();
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  // edit()/save() persist at the event boundary. A delayed effect carrying an
  // older value must never overwrite a newer draft immediately before unmount.
  useEffect(() => {
    // Initial/late effects must not replace an edit made before React has
    // rendered the new dirty state. The input event fences them immediately.
    if (!dirtyNow.current) { setValue(item.value); expected.current = item.revision; setComparisonRevision(item.revision); }
  }, [item.value, item.revision, dirty]);
  const edit = next => {
    dirtyNow.current = true;
    setValue(next); setDirty(true);
    try { sessionStorage.setItem(storage, JSON.stringify({ value: next, base_revision: expected.current, command: pending.current })); } catch { /* optional recovery */ }
  };
  const save = async (reset = false) => {
    if (submitting.current) return;
    submitting.current = true;
    const chosen = reset ? item.value : value;
    const parsed = typeof item.value === 'boolean' ? chosen === true || chosen === 'true' : typeof item.value === 'number' ? Number(chosen) : chosen;
    if (pending.current?.values[item.key] !== parsed || Boolean(pending.current?.reset) !== reset) pending.current = { values: { [item.key]: parsed }, scope: item.scope,
      base_revision: expected.current, reset, idempotency_key: crypto.randomUUID() };
    try { sessionStorage.setItem(storage, JSON.stringify({ value, base_revision: expected.current, command: pending.current })); } catch { /* optional recovery */ }
    setBusy(true); setError(null); const same = api.captureSession();
    const sent = pending.current;
    let sentRecovery = null;
    try { sentRecovery = sessionStorage.getItem(storage); } catch { /* optional recovery */ }
    try {
      await api.put('/auth/users/me/settings', sent); same();
      // A late answer from an unmounted card must not erase a newer draft of
      // this same setting created after remount/filter/navigation.
      try {
        if (sentRecovery !== null && sessionStorage.getItem(storage) === sentRecovery) sessionStorage.removeItem(storage);
      } catch { /* optional recovery */ }
      if (!mounted.current) return;
      pending.current = null; dirtyNow.current = false; setDirty(false); onSaved(); prefs?.reload?.();
    } catch (failure) {
      if (!mounted.current) return;
      setError(failure.message || 'Nicht gespeichert. Eingabe bleibt erhalten.');
      if ((failure.statusCode || failure.status) === 409) {
        pending.current = null;
        try { sessionStorage.setItem(storage, JSON.stringify({ value, base_revision: expected.current, command: null })); } catch { /* optional recovery */ }
        onSaved();
      }
    }
    finally { submitting.current = false; if (mounted.current) setBusy(false); }
  };
  const compareCurrent = () => {
    expected.current = item.revision; pending.current = null; setComparisonRevision(item.revision); setError(null);
    try { sessionStorage.setItem(storage, JSON.stringify({ value, base_revision: item.revision, command: null })); } catch { /* optional recovery */ }
  };
  const choiceLabels = { symbol: 'Währungssymbol (Quellwährung)', code: 'ISO-Währungscode (Quellwährung)', '\t': 'Tabulator', housing_provider: 'Wohnungsgeber', authorized_person: 'Beauftragte Person', light: 'Hell', dark: 'Dunkel', system: 'Wie das Betriebssystem', 'de-DE': 'Deutsch', 'en-US': 'Englisch', 'es-ES': 'Spanisch', all: 'Alle Hinweise', important: 'Wichtige Hinweise', none: 'Keine E-Mail-Hinweise', comfortable: 'Normal', compact: 'Kompakt', '/': 'Übersicht', '/work-center': 'Arbeitszentrale', '/properties': 'Immobilien', '/tasks': 'Aufgaben', '/notifications': 'Persönlicher Eingang' };
  const id = `setting-${item.scope}-${item.key}`;
  return <article className="setting-card">
    <label htmlFor={id} className="setting-card-title">{item.label}</label>
    <p className="setting-card-meta">Geltung: {item.scope === 'personal' ? 'Nur für mich' : item.scope === 'global' ? 'Installation' : item.scope.startsWith('object:') ? 'Ausgewähltes Objekt' : 'Server'} · Herkunft: {originLabel(item.origin)}</p>
    {item.editable ? <div className="setting-controls">
      {item.choices ? <select id={id} value={String(value)} onChange={e => edit(e.target.value)} disabled={busy}>
        {item.choices.map(choice => <option key={String(choice.value ?? choice)} value={String(choice.value ?? choice)}>{choice.label || (choice === true ? 'Ja' : choice === false ? 'Nein' : choiceLabels[choice] || String(choice))}</option>)}
      </select> : item.input_type === 'textarea' || item.key === 'document_address' ? <textarea id={id} value={value} onChange={e => edit(e.target.value)} disabled={busy} /> : <input id={id} type={item.input_type || "number"} min={item.key === 'reminder_days' ? 0 : 1} max={item.key === 'reminder_days' ? 365 : item.key === 'default_due_day' ? 31 : undefined} value={value} onChange={e => edit(e.target.value)} disabled={busy} />}
      <button className="btn btn-primary" onClick={() => save()} disabled={busy || !dirty}>{busy ? 'Speichert …' : 'Speichern'}</button>
      {dirty && <small>Ungespeicherte Eingabe (in diesem Tab gesichert)</small>}
    </div> : <p id={id}>{typeof item.value === 'boolean' ? (item.value ? 'Ja' : 'Nein') : String(item.value)}{item.restart_required && ' · Serveränderung erfordert Neustart'}</p>}
    {item.editable && <button className="btn btn-ghost btn-sm setting-reset" disabled={busy} onClick={() => { expected.current = item.revision; pending.current = null; setDirty(true); save(true); }}>Vorgabe übernehmen</button>}
    {dirty && item.revision !== comparisonRevision && <p role="status">Aktuell gespeichert: {String(item.value)}. Ihre Eingabe: {String(value)}. <button onClick={compareCurrent}>Mit aktuellem Stand vergleichen und eigene Eingabe behalten</button></p>}
    {error && <p role="alert">{error} Eingabe bleibt erhalten. Bei Konflikt zuerst den aktuellen Stand laden und vergleichen.</p>}
  </article>;
}

export default function SettingsCatalogue() {
  const auth = useAuth();
  const [search, setSearch] = useState('');
  const [scope, setScope] = useState('');
  const [group, setGroup] = useState('');
  const [property, setProperty] = useState('');
  const [properties, setProperties] = useState([]);
  const [items, setItems] = useState([]);
  const [loadedProperty, setLoadedProperty] = useState(null);
  const [loading, setLoading] = useState(true);
  const [propertyError, setPropertyError] = useState(null);
  const [propertyAttempt, setPropertyAttempt] = useState(0);
  const [error, setError] = useState(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let live = true; const same = api.captureSession();
    setPropertyError(null);
    api.list('/properties').then(data => { same(); if (live) setProperties(data); }).catch(failure => { if (live) setPropertyError(failure.message); });
    return () => { live = false; };
  }, [propertyAttempt]);
  useEffect(() => {
    let live = true; const same = api.captureSession(); setError(null); setLoading(true);
    api.get(`/auth/users/me/settings${property ? `?property_id=${encodeURIComponent(property)}` : ''}`).then(data => {
      same();
      if (!Array.isArray(data?.items)) throw new Error('Die Einstellungsantwort ist unvollständig. Bitte erneut laden.');
      if (live) { setItems(data.items); setLoadedProperty(property); }
    }).catch(failure => { if (live) setError(failure.message); }).finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [property, attempt]);
  const normalize = value => String(value).normalize('NFKD').replace(/\p{Diacritic}/gu, '').toLocaleLowerCase('de').replaceAll('ß', 'ss');
  const words = normalize(search).trim().split(/\s+/).filter(Boolean);
  const matches = value => words.every(word => normalize(value).includes(word));
  // A newly selected object must never render writable cards from the prior
  // object's response while its own request is still pending.
  const currentItems = loadedProperty === property ? items : [];
  const found = currentItems.filter(item => (!scope || (scope === 'object' ? item.scope.startsWith('object:') : item.scope === scope))
    && (!group || item.group === group) && matches(`${item.label} ${item.group} ${item.origin} ${item.scope} ${item.key}`));
  const groups = [...new Set(currentItems.map(item => item.group).filter(Boolean))].sort((a, b) => a.localeCompare(b, 'de'));
  const links = [
    ['Favoriten und gespeicherte Ansichten', '/work-center'], ['Dokumente, Vorlagen und Originale', '/documents'],
    ['Benachrichtigungen und Archiv', '/notifications'], ['Sicherheit, Anmeldung, MFA und Authenticator', '/settings?section=security'], ['Import und Export', '/bookings'],
    ...(auth?.user?.role === 'eigentuemer' ? [['Datenübernahme, CSV-Vorlagen, Kundenexport und Wiederimport', '/settings?section=migration']] : []),
    ...(auth?.isAdmin ? [['Integrationen und Zugangsdaten', '/integrations'], ['Benutzer, Rollen und Objektzugriff', '/settings?section=users'], ['Sicherung, Wiederherstellung, Backupzeit, Aufbewahrung, Jobs und Betrieb', '/settings?section=system'], ['Updates und Erweiterungen', '/settings?section=system']] : []),
  ].filter(([label]) => matches(label));
  return <section className="settings-catalogue"><h2>Einstellungen finden</h2>
    <div className="settings-catalogue-filters">
      <div className="settings-catalogue-field"><label htmlFor="settings-search">Suche nach Einstellung oder Bereich</label><input id="settings-search" type="search" value={search} onChange={e => setSearch(e.target.value)} /></div>
      <div className="settings-catalogue-field"><label htmlFor="settings-object">Objektkontext</label><select id="settings-object" value={property} onChange={e => setProperty(e.target.value)}>
        <option value="">Ohne Objekt</option>{properties.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
      </select></div>
      <div className="settings-catalogue-field"><label htmlFor="settings-scope">Geltungsbereich</label><select id="settings-scope" value={scope} onChange={e => setScope(e.target.value)}>
        <option value="">Alle Geltungsbereiche</option><option value="personal">Nur für mich</option><option value="global">Installationsweite Vorgaben</option><option value="object">Objektvorgaben</option><option value="installation">Serverkonfiguration</option>
      </select></div>
      <div className="settings-catalogue-field"><label htmlFor="settings-group">Themenbereich</label><select id="settings-group" value={group} onChange={e => setGroup(e.target.value)}>
        <option value="">Alle Themenbereiche</option>{groups.map(value => <option key={value} value={value}>{value}</option>)}
      </select></div>
    </div>
    {propertyError && <p role="alert">Objekte konnten nicht geladen werden: {propertyError} <button onClick={() => setPropertyAttempt(n => n + 1)}>Objekte erneut laden</button></p>}
    <p className="settings-catalogue-intro">Persönliche Werte haben Vorrang vor Objektvorgaben und globalen Standardwerten. Ruhezeiten gelten für persönliche E-Mail-Hinweise in Europe/Berlin, sobald beide Zeiten gesetzt und verschieden sind. Serverparameter stammen aus der bestehenden Serverkonfiguration und werden hier nur angezeigt. Währungen werden nicht umgerechnet; Belege behalten ihre Quellwährung.</p>
    {error && <p role="alert">{error} <button onClick={() => setAttempt(n => n + 1)}>Erneut laden</button></p>}
    <button type="button" className="btn btn-secondary" disabled={loading} onClick={() => setAttempt(n => n + 1)}>Aktuelle Werte laden</button>
    <p role="status" className="settings-catalogue-count">{loading || loadedProperty !== property && !error ? 'Einstellungen werden geladen …' : error ? 'Aktuelle Einstellungen konnten nicht geladen werden.' : `${found.length} Einstellungen gefunden`}</p>
    <div className="setting-grid">{found.map(item => <SettingField key={`${property}:${item.scope}:${item.key}`} item={item} onSaved={() => setAttempt(n => n + 1)} />)}</div>
    {(!search || /sitz|sicher|anmeld|session/i.test(search)) && <SessionInventory />}
    {auth?.isAdmin && (!search || /api|plugin|erweiter/i.test(search)) && <ConfigurationContract />}
    <nav aria-label="Weitere Einstellungsbereiche">{links.map(([label, href]) => <p key={label}><Link to={href}>{label}</Link></p>)}</nav>
  </section>;
}
