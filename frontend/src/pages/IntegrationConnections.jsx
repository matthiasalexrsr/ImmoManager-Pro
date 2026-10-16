import WhatsAppInbox from '../features/channels/WhatsAppInbox';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api } from '../api';
import { useCanWrite } from '../contexts/AuthContext';
import { useModalDialog } from '../features/partyWorkspace/useModalDialog';
import ConnectionEvidencePanel from './ConnectionEvidencePanel';
import ConnectionEmergencyStop from './ConnectionEmergencyStop';
import './integrationConnections.css';

const BASE = '/integration-connections';
const newKey = () => crypto.randomUUID();
const statusNames = { prepared: 'Vorbereitet', executing: 'Ausführung unbestätigt', completed: 'Abgeschlossen',
  accepted: 'Extern angenommen', unknown: 'Ausgang unklar', retryable: 'Erneut prüfbar',
  awaiting_page: 'Weitere Daten verfügbar', blocked: 'Prüfung erforderlich', cancelled: 'Abgebrochen', reconciled: 'Abgeglichen' };
const definite = failure => [400, 401, 403, 404, 409, 422].includes(failure.statusCode);

function Field({ field, value, onChange, disabled, prefix, hasSecret = false }) {
  const id = `${prefix}-${field.key}`;
  const description = [field.help, hasSecret ? 'Das vorhandene Geheimnis bleibt beim Leerlassen erhalten.' : null].filter(Boolean).join(' ');
  const help = description ? `${id}-help` : undefined;
  if (field.type === 'boolean') return <label className="connection-check"><input type="checkbox" id={id}
    checked={!!value} disabled={disabled} onChange={event => onChange(event.target.checked)} />{field.label || field.key}</label>;
  return <div className="connection-field"><label htmlFor={id}>{field.label || field.key}{field.required && !hasSecret ? ' *' : ''}</label>
    {field.type === 'textarea' || ['body', 'text'].includes(field.key) ? <textarea id={id} aria-describedby={help} rows={4} value={value ?? ''}
      disabled={disabled} required={field.required} onChange={event => onChange(event.target.value)} /> :
      field.options ? <select id={id} aria-describedby={help} value={value ?? field.default ?? ''} disabled={disabled}
        onChange={event => onChange(event.target.value)}><option value="">Bitte wählen</option>
        {field.options.map(option => <option key={option.value ?? option} value={option.value ?? option}>{option.label ?? option}</option>)}
      </select> : <input id={id} aria-describedby={help} type={field.secret ? 'password' : field.type === 'integer' || field.type === 'number' ? 'number' : field.type === 'email' ? 'email' : 'text'}
        value={value ?? field.default ?? ''} min={field.min} max={field.max} disabled={disabled}
        autoComplete={field.secret ? 'new-password' : 'off'} placeholder={hasSecret ? 'Gespeichert – leer lassen zum Beibehalten' : ''}
        required={field.required && !hasSecret} onChange={event => onChange(field.type === 'integer' || field.type === 'number'
          ? event.target.value === '' ? '' : Number(event.target.value) : event.target.value)} />}
    {description && <small id={help}>{description}</small>}
  </div>;
}

const defaultConfig = provider => Object.fromEntries((provider?.config_fields || []).filter(field => field.default !== undefined && !field.secret)
  .map(field => [field.key, field.default]));

function ConnectionEditor({ connection, catalog, onSaved, onClose }) {
  const dialogRef = useRef(null);
  const [providerId, setProviderId] = useState(connection?.provider_id || catalog[0]?.provider_id || '');
  const [name, setName] = useState(connection?.name || '');
  const [config, setConfig] = useState(() => ({ ...defaultConfig(catalog.find(item => item.provider_id === providerId)),
    ...Object.fromEntries(Object.entries(connection?.config || {}).filter(([, value]) => value !== '***')) }));
  const [enabled, setEnabled] = useState(connection?.enabled || false);
  const [clearSecrets, setClearSecrets] = useState([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const pending = useRef(null);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const provider = catalog.find(item => item.provider_id === providerId);
  const close = () => { if (!busy && !uncertain) onClose(); };
  useModalDialog(dialogRef, close);
  async function save(event) {
    event.preventDefault(); if (busy) return;
    const current = api.captureSession();
    const payload = pending.current || (connection ? { idempotency_key: newKey(), base_revision: connection.revision,
      name, config, enabled, clear_secrets: clearSecrets } : { idempotency_key: newKey(), provider_id: providerId, name, config, enabled });
    pending.current = payload; setBusy(true); setError('');
    try {
      const result = connection ? await api.patch(`${BASE}/${connection.id}`, payload) : await api.post(BASE, payload);
      current(); if (!mounted.current) return;
      if (!result?.id || !Number.isInteger(result.revision)) throw new Error('Die Speicherung wurde nicht eindeutig bestätigt.');
      pending.current = null; setUncertain(false); onSaved(result); onClose();
    } catch (failure) {
      if (!mounted.current || failure.code === 'SESSION_CHANGED') return;
      if (definite(failure)) { pending.current = null; setUncertain(false); }
      else setUncertain(true);
      setError(failure.message || 'Die Verbindung konnte nicht gespeichert werden.');
    } finally { if (mounted.current) setBusy(false); }
  }
  return <div className="modal-overlay"><section className="modal connection-dialog" role="dialog" aria-modal="true"
    aria-labelledby="connection-editor-title" ref={dialogRef}>
    <h2 id="connection-editor-title">{connection ? 'Verbindung bearbeiten' : 'Verbindung anlegen'}</h2>
    <p>Zugangsdaten werden auf dem Server verschlüsselt. Hier wird noch keine Anbieteraktion ausgeführt.</p>
    {error && <div role="alert" className="alert alert-danger">{error}</div>}
    {uncertain && <p role="status">Die Speicherung ist unbestätigt. „Speicherstatus prüfen“ wiederholt nur denselben Befehl mit derselben Kennung.</p>}
    <form onSubmit={save}>
      <fieldset disabled={busy || uncertain}>
        <label className="connection-field" htmlFor="connection-provider">Anbieter<select id="connection-provider" disabled={!!connection}
          value={providerId} onChange={event => { setProviderId(event.target.value); setConfig(defaultConfig(catalog.find(item => item.provider_id === event.target.value))); }}>
          {catalog.map(item => <option key={item.provider_id} value={item.provider_id}>{item.name}</option>)}
        </select></label>
        <label className="connection-field" htmlFor="connection-name">Bezeichnung *<input id="connection-name" value={name} required maxLength={200}
          onChange={event => setName(event.target.value)} /></label>
        {(provider?.config_fields || []).map(field => <div key={field.key}><Field field={field} value={config[field.key]}
          prefix="connection-config" hasSecret={connection?.secret_fields_present?.includes(field.key)}
          onChange={value => setConfig(current => ({ ...current, [field.key]: value }))} />
          {field.secret && connection?.secret_fields_present?.includes(field.key) && <label className="connection-check">
            <input type="checkbox" checked={clearSecrets.includes(field.key)} onChange={event => setClearSecrets(current =>
              event.target.checked ? [...current, field.key] : current.filter(key => key !== field.key))} />
            Dieses gespeicherte Geheimnis ausdrücklich entfernen</label>}</div>)}
        <label className="connection-check"><input type="checkbox" checked={enabled} onChange={event => setEnabled(event.target.checked)} />Verbindung aktivieren</label>
        {provider?.planned && <p>Dieser Anbieter ist noch in Vorbereitung. Speichern ist möglich, Geschäftsaktionen bleiben gesperrt.</p>}
      </fieldset>
      <div className="connection-actions"><button type="button" className="btn btn-secondary" disabled={busy || uncertain} onClick={close}>Abbrechen</button>
        <button className="btn btn-primary" type="submit" disabled={busy}>{busy ? 'Wird geprüft …' : uncertain ? 'Speicherstatus prüfen' : 'Speichern'}</button></div>
    </form>
  </section></div>;
}

function ActionEditor({ connection, contract, onPrepared }) {
  const actions = contract?.actions?.filter(item => item.enabled) || [];
  const [actionId, setActionId] = useState(actions[0]?.id || '');
  const [values, setValues] = useState({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [uncertain, setUncertain] = useState(false);
  const pending = useRef(null);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const selected = actions.find(action => action.id === actionId);
  async function prepare(event) {
    event.preventDefault(); if (busy || !selected) return;
    const current = api.captureSession();
    const command = pending.current || { idempotency_key: newKey(), config_revision: connection.revision, action: selected.id, payload: values };
    pending.current = command; setBusy(true); setError('');
    try {
      const run = await api.post(`${BASE}/${connection.id}/runs`, command);
      current(); if (!mounted.current) return;
      if (!run?.id) throw new Error('Die Vorschau wurde nicht eindeutig bestätigt.');
      pending.current = null; setUncertain(false); onPrepared(run, command.payload);
    } catch (failure) {
      if (!mounted.current || failure.code === 'SESSION_CHANGED') return;
      if (definite(failure)) { pending.current = null; setUncertain(false); } else setUncertain(true);
      setError(failure.message || 'Die Vorschau konnte nicht erstellt werden.');
    } finally { if (mounted.current) setBusy(false); }
  }
  if (!actions.length) return <p>Für diesen Anbieter ist noch keine Aktion zur Ausführung freigegeben.</p>;
  return <form className="connection-action-form" onSubmit={prepare}>
    <h3>Aktion vorbereiten</h3><p>Erst die Vorschau wird gespeichert. Ein Anbieteraufruf erfolgt nur nach der gesonderten Bestätigung.</p>
    {error && <div role="alert" className="alert alert-danger">{error}</div>}
    <fieldset disabled={busy || uncertain || !connection.enabled || connection.archived}>
      <label className="connection-field" htmlFor="connection-action">Aktion<select id="connection-action" value={actionId}
        onChange={event => { setActionId(event.target.value); setValues({}); }}>
        {actions.map(action => <option key={action.id} value={action.id}>{action.label || action.id}</option>)}
      </select></label>
      {(selected?.inputs || []).map(field => <Field key={field.key} field={field} value={values[field.key]} prefix="connection-action-input"
        onChange={value => setValues(current => ({ ...current, [field.key]: value }))} />)}
    </fieldset>
    <button className="btn btn-secondary" type="submit" disabled={busy || !connection.enabled || connection.archived}>
      {busy ? 'Wird vorbereitet …' : uncertain ? 'Vorschau abgleichen' : 'Vorschau erstellen'}</button>
  </form>;
}

function RunDetail({ connectionId, initial, preview: proposedPreview, onUpdated }) {
  const [run, setRun] = useState(initial);
  const [preview, setPreview] = useState(proposedPreview);
  const [previewReady, setPreviewReady] = useState(false);
  const [previewAttempt, setPreviewAttempt] = useState(0);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const pending = useRef(null);
  const mounted = useRef(true);
  const canWrite = useCanWrite('/integrations');
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => {
    const request = new AbortController(); const current = api.captureSession();
    setPreviewReady(false); setError('');
    api.get(`${BASE}/${connectionId}/runs/${initial.id}/preview`, { signal: request.signal }).then(result => {
      if (request.signal.aborted) return; current();
      if (result?.run?.id !== initial.id || !result.payload || typeof result.payload !== 'object') throw new Error('Die gespeicherte Vorschau ist unvollständig.');
      setRun(existing => existing.revision > result.run.revision ? existing : result.run);
      setPreview(result.payload); setPreviewReady(true);
    }).catch(failure => { if (!request.signal.aborted && failure.code !== 'SESSION_CHANGED') setError(failure.message || 'Die gespeicherte Vorschau konnte nicht geladen werden.'); });
    return () => request.abort();
  }, [connectionId, initial.id, previewAttempt]);
  async function updateRun({ execute = false, cancel = false } = {}) {
    if (busy) return;
    const current = api.captureSession(); setBusy(true); setError('');
    try {
      let result;
      if (execute || cancel) {
        const command = pending.current || { route: cancel ? 'cancel' : 'dispatch', payload: { idempotency_key: newKey(), base_revision: run.revision,
          ...(cancel ? { reason: 'In der Vorschau ausdrücklich abgebrochen.' } : { confirm: true }) } };
        pending.current = command;
        result = await api.post(`${BASE}/${connectionId}/runs/${run.id}/${command.route}`, command.payload);
      } else result = await api.get(`${BASE}/${connectionId}/runs/${run.id}`);
      current(); if (!mounted.current) return;
      if (result?.id !== run.id) throw new Error('Der Vorgangsstand wurde nicht eindeutig bestätigt.');
      pending.current = null; setRun(result); onUpdated(result); setConfirmed(false);
    } catch (failure) {
      if (!mounted.current || failure.code === 'SESSION_CHANGED') return;
      if (definite(failure)) pending.current = null;
      setError(failure.message || 'Der Vorgangsstand konnte nicht bestätigt werden.');
    } finally { if (mounted.current) setBusy(false); }
  }
  const cancelable = previewReady && !pending.current && ['prepared', 'retryable', 'awaiting_page'].includes(run.state);
  const executable = cancelable && run.can_dispatch !== false && !run.external_outcome_unknown
    && (run.effect !== 'external_write' || run.state === 'prepared');
  return <section className="connection-run-detail" aria-labelledby="connection-run-heading">
    <h3 id="connection-run-heading">Vorgang: {statusNames[run.state] || run.state}</h3>
    <p>{run.safe_summary}</p>
    {run.source_status === 'unavailable' && <p role="status">Die ursprüngliche Quelle ist nicht mehr verfügbar. Historie und Vorschau bleiben erhalten; ein neuer Anbieteraufruf ist gesperrt.</p>}
    {run.source_changed && <p role="status">Die Quelle wurde geändert. Für weitere Anbieteraktionen ist eine neue geprüfte Vorschau nötig.</p>}
    {!previewReady && <p role="status">Die gespeicherte Vorschau wird geprüft. Bis dahin ist keine Ausführung möglich.</p>}
    {error && <div role="alert" className="alert alert-danger">{error}</div>}
    {!previewReady && error && <button type="button" className="btn btn-secondary" disabled={busy}
      onClick={() => setPreviewAttempt(value => value + 1)}>Vorschau erneut laden</button>}
    {run.external_outcome_unknown && <div className="alert alert-warning"><strong>Nicht erneut senden.</strong>
      <p>Prüfen Sie den Vorgang bei der Gegenstelle anhand dieser Kennung und des ursprünglichen Auftrags. Ein Timeout ist kein Nachweis, dass nichts ausgeführt wurde.</p></div>}
    {run.state === 'accepted' && <p>Die Gegenstelle hat die Aktion angenommen. Das ist noch kein Nachweis einer Zustellung oder einer späteren Ausführung.</p>}
    <dl className="connection-facts"><dt>Vorgangskennung</dt><dd>{run.id}</dd><dt>Konfigurationsstand</dt><dd>{run.config_revision}</dd>
      <dt>Bestätigte Abschnitte</dt><dd>{run.completed_pages}</dd><dt>Gespeicherte Ergebnisbytes</dt><dd>{run.result_bytes || 0}</dd>
      {run.result_sha256 && <><dt>Ergebnisnachweis</dt><dd>{run.result_sha256}</dd></>}</dl>
    {preview && <details open><summary>Ausgewählte Angaben</summary><dl className="connection-facts">{Object.entries(preview).map(([key, value]) =>
      <div key={key}><dt>{key}</dt><dd>{String(value)}</dd></div>)}</dl></details>}
    {canWrite && executable && <label className="connection-check"><input type="checkbox" checked={confirmed} disabled={busy}
      onChange={event => setConfirmed(event.target.checked)} />{run.effect === 'external_write' ? 'Ich bestätige die ausgewählte externe Aktion.' : 'Diesen vorbereiteten Schritt jetzt ausführen.'}</label>}
    <div className="connection-actions">
      <button type="button" className="btn btn-secondary" disabled={busy} onClick={() => updateRun()}>Status aktualisieren</button>
      {canWrite && executable && <button type="button" className="btn btn-primary" disabled={busy || !confirmed}
        onClick={() => updateRun({ execute: true })}>{run.state === 'awaiting_page' ? 'Nächsten Abschnitt laden' : 'Jetzt ausführen'}</button>}
      {canWrite && cancelable && <button type="button" className="btn btn-secondary" disabled={busy} onClick={() => updateRun({ cancel: true })}>Weitere Schritte abbrechen</button>}
      {canWrite && pending.current && <button type="button" className="btn btn-secondary" disabled={busy}
        onClick={() => updateRun({ execute: true })}>Unbestätigten Befehl abgleichen</button>}
    </div>
    {run.recorded_attempts !== undefined && <ConnectionEvidencePanel key={run.id} connectionId={connectionId} run={run}
      onApplied={value => { setRun(value); onUpdated(value); setConfirmed(false); }} />}
  </section>;
}

function ConnectionDetail({ connection, contract, onEdit, onChanged }) {
  const [runs, setRuns] = useState({ items: [], next_cursor: null, total: null });
  const [selected, setSelected] = useState(null);
  const [preview, setPreview] = useState(null);
  const [cursor, setCursor] = useState(null);
  const [history, setHistory] = useState([]);
  const [attempt, setAttempt] = useState(0);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const canWrite = useCanWrite('/integrations');
  useEffect(() => {
    const request = new AbortController(); const current = api.captureSession(); setLoading(true); setError('');
    const query = new URLSearchParams({ limit: '25' }); if (cursor) query.set('cursor', cursor);
    api.get(`${BASE}/${connection.id}/runs?${query}`, { signal: request.signal }).then(result => {
      if (request.signal.aborted) return; current();
      if (!Array.isArray(result?.items)) throw new Error('Der Vorgangseingang ist unvollständig.');
      setRuns(result);
    }).catch(failure => { if (!request.signal.aborted && failure.code !== 'SESSION_CHANGED') setError(failure.message || 'Vorgänge konnten nicht geladen werden.'); })
      .finally(() => { if (!request.signal.aborted) setLoading(false); });
    return () => request.abort();
  }, [connection.id, cursor, attempt]);
  const updated = useCallback(run => setRuns(current => ({ ...current, items: current.items.map(item => item.id === run.id ? run : item) })), []);
  return <section className="connection-detail">
    {connection.provider_id === 'whatsapp' && !connection.read_error && <WhatsAppInbox key={connection.id} connectionId={connection.id} />}
    <div className="connection-heading"><div><h2>{connection.name}</h2><p>{connection.provider_name} · Stand {connection.revision} · {connection.enabled ? 'Aktiv' : 'Deaktiviert'}</p></div>
      {canWrite && !connection.read_error && <button type="button" className="btn btn-secondary" onClick={onEdit}>Verbindung bearbeiten</button>}</div>
    {connection.read_error && <div role="alert">{connection.read_error}</div>}
    {canWrite && connection.read_error && <ConnectionEmergencyStop connection={connection} onChanged={onChanged} />}
    {connection.unmapped_fields?.length > 0 && <p>Zusätzliche Quellfelder sind geschützt erhalten, aber nicht als Anbieterparameter freigegeben: {connection.unmapped_fields.join(', ')}.</p>}
    {!connection.read_error && !connection.configured && <div className="alert alert-warning">Die Verbindung benötigt noch vollständige gültige Zugangseinstellungen.</div>}
    {canWrite && !connection.read_error && <ActionEditor key={connection.id} connection={connection} contract={contract}
      onPrepared={(run, values) => { setSelected(run); setPreview(values); setCursor(null); setHistory([]); setAttempt(current => current + 1); }} />}
    {selected && <RunDetail key={selected.id} connectionId={connection.id} initial={selected} preview={preview} onUpdated={updated} />}
    <h3>Vorgänge und Ergebnisnachweise {runs.total !== null && `(${runs.total})`}</h3>
    {error && <div role="alert" className="alert alert-danger">{error}<button type="button" className="btn btn-secondary" onClick={() => setAttempt(value => value + 1)}>Erneut laden</button></div>}
    {loading ? <p role="status">Vorgänge werden geladen …</p> : !error && !runs.items.length ? <p>Noch keine Vorgänge für diese Verbindung.</p> :
      <div className="connection-run-list">{runs.items.map(run => <button type="button" key={run.id} className="connection-run-row" aria-label={`${statusNames[run.state] || run.state} ${run.safe_summary}`}
        onClick={() => { setSelected(run); setPreview(null); }}><strong>{statusNames[run.state] || run.state}</strong>
        <span>{run.safe_summary}</span><small>{run.created_at?.slice(0, 19).replace('T', ' ')}</small></button>)}</div>}
    <nav className="connection-actions" aria-label="Vorgangsseiten"><button type="button" className="btn btn-secondary" disabled={loading || !history.length}
      onClick={() => { setCursor(history.at(-1)); setHistory(current => current.slice(0, -1)); }}>Neuere Vorgänge</button>
      <button type="button" className="btn btn-secondary" disabled={loading || !runs.next_cursor}
        onClick={() => { setHistory(current => [...current, cursor]); setCursor(runs.next_cursor); }}>Ältere Vorgänge</button></nav>
  </section>;
}

export default function IntegrationConnections() {
  const [params, setParams] = useSearchParams();
  const [catalog, setCatalog] = useState([]);
  const [page, setPage] = useState({ items: [], total: null, next_cursor: null });
  const [selected, setSelected] = useState(null);
  const [editor, setEditor] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [attempt, setAttempt] = useState(0);
  const [cursor, setCursor] = useState(null);
  const [history, setHistory] = useState([]);
  const canWrite = useCanWrite('/integrations');
  const linked = params.get('connection');
  useEffect(() => {
    const request = new AbortController(); const current = api.captureSession(); setLoading(true); setError('');
    const invalidate = () => { request.abort(); setPage({ items: [], total: null, next_cursor: null }); setCatalog([]); setSelected(null); setEditor(null); setLoading(false); setError('Die Sitzung wurde geändert. Bitte erneut anmelden.'); };
    window.addEventListener('workspace-logout', invalidate); window.addEventListener('workspace-owner', invalidate);
    const query = new URLSearchParams({ limit: '50' }); if (cursor) query.set('cursor', cursor);
    Promise.all([api.get(`${BASE}/catalog`, { signal: request.signal }), api.get(`${BASE}?${query}`, { signal: request.signal }),
      (linked ? Promise.resolve(linked) : api.get('/auth/users/me/settings/selected-connection', { signal: request.signal }).then(result => result.selection?.connection_id))
        .then(identifier => identifier ? api.get(`${BASE}/${encodeURIComponent(identifier)}`, { signal: request.signal }).catch(failure => {
          if (failure.statusCode !== 503 || request.signal.aborted) throw failure;
          return api.get(`${BASE}/${encodeURIComponent(identifier)}/state`, { signal: request.signal });
        }) : null)])
      .then(([schema, result, connection]) => {
        if (request.signal.aborted) return; current();
        if (!Array.isArray(schema?.providers) || !Array.isArray(result?.items)) throw new Error('Die Verbindungsübersicht ist unvollständig.');
        setCatalog(schema.providers); setPage(result); setSelected(connection);
      }).catch(failure => { if (!request.signal.aborted && failure.code !== 'SESSION_CHANGED') setError(failure.message || 'Verbindungen konnten nicht geladen werden.'); })
      .finally(() => { if (!request.signal.aborted) setLoading(false); });
    return () => { request.abort(); window.removeEventListener('workspace-logout', invalidate); window.removeEventListener('workspace-owner', invalidate); };
  }, [attempt, cursor, linked]);
  function choose(connection) { setParams(current => { const next = new URLSearchParams(current); next.set('connection', connection.id); return next; }); }
  return <main className="page connection-workspace">
    <div className="connection-heading"><div><h1 className="page-title">Verbindungen und Vorgänge</h1>
      <p>Geschützte Zugänge, geprüfte Vorschauen und nachvollziehbare Ergebnisse.</p></div>
      {canWrite && <button type="button" className="btn btn-primary" disabled={loading || !catalog.length} onClick={() => setEditor({ create: true })}>Verbindung anlegen</button>}</div>
    <p><Link to="/integrations">Bisherige Anbieterübersicht</Link> · <Link to="/teha">TEHA Kundenportal</Link></p>
    {error && <div role="alert" className="alert alert-danger">{error}<button type="button" className="btn btn-secondary" onClick={() => setAttempt(value => value + 1)}>Übersicht erneut laden</button></div>}
    {loading && <p role="status">Verbindungen werden geladen …</p>}
    {!loading && !error && <div className="connection-layout"><aside aria-label="Verbindungen">
      <p>{page.total} Verbindungen</p>{!page.items.length && <p>Noch keine Verbindung angelegt.</p>}
      {page.items.map(connection => <button type="button" className="connection-card" key={connection.id} aria-label={`${connection.name} ${connection.provider_name} ${connection.enabled ? 'Aktiv' : 'Deaktiviert'}`} onClick={() => choose(connection)} aria-pressed={selected?.id === connection.id}>
        <strong>{connection.name}</strong><span>{connection.provider_name}</span><small>{connection.read_error ? 'Zugangsdaten nicht lesbar' : connection.enabled ? 'Aktiv' : 'Deaktiviert'} · Stand {connection.revision}</small></button>)}
      <nav className="connection-actions" aria-label="Verbindungsseiten"><button type="button" className="btn btn-secondary" disabled={!history.length}
        onClick={() => { setCursor(history.at(-1)); setHistory(current => current.slice(0, -1)); }}>Zurück</button>
        <button type="button" className="btn btn-secondary" disabled={!page.next_cursor}
          onClick={() => { setHistory(current => [...current, cursor]); setCursor(page.next_cursor); }}>Weitere Verbindungen</button></nav>
    </aside>{selected ? <ConnectionDetail key={selected.id} connection={selected} contract={catalog.find(item => item.provider_id === selected.provider_id)}
      onEdit={() => setEditor({ connection: selected })} onChanged={() => setAttempt(value => value + 1)} /> : <section className="connection-detail"><h2>Verbindung auswählen</h2><p>Wählen Sie einen Zugang oder legen Sie eine benannte Verbindung an.</p></section>}</div>}
    {editor && <ConnectionEditor connection={editor.connection} catalog={catalog} onClose={() => setEditor(null)}
      onSaved={connection => { choose(connection); setAttempt(value => value + 1); }} />}
  </main>;
}
