import { useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useTranslation } from '../i18n';
import { api } from '../api';
import { useCanWrite } from '../contexts/AuthContext';
import { MessageIcon, ContractIcon, DocumentIcon, BuildingIcon, IntegrationIcon } from '../components/Icons';
import { codeLabel } from '../utils/codeLabels';
import { initializeIntegrationValues, serializeIntegrationValues, isIntegrationFieldEmpty, isDefiniteIntegrationFailure } from '../utils/integrationFields';
import './integrations.css';

const ICONS = { communication: MessageIcon, workflow: ContractIcon, delivery: DocumentIcon, documents: DocumentIcon, listing: BuildingIcon };
const CATEGORIES = { communication: 'Kommunikation', workflow: 'Verträge und Abläufe', delivery: 'Post und Versand', documents: 'Dokumente', listing: 'Immobilienportale', ai: 'KI-Verarbeitung' };
const HEALTH = { ok: 'Bereit', local: 'Lokal verfügbar', configured: 'Verbindung noch nicht geprüft', available: 'Verfügbar', unavailable: 'Dienst derzeit nicht verfügbar', degraded: 'Eingeschränkt verfügbar', not_configured: 'Einrichtung erforderlich', disabled: 'Deaktiviert', unknown: 'Noch nicht geprüft' };
const FIELD_LABELS = { username: 'Benutzername', password: 'Passwort' };
const CAPABILITY_LABELS = { receive: 'Daten empfangen', originals: 'Originaldokumente', explicit_mapping: 'Zuordnung mit Bestätigung' };
const labelFor = field => field.label && field.label !== field.key ? field.label : FIELD_LABELS[field.key] || field.label || field.key;
const initialConfig = integration => initializeIntegrationValues(integration.config_fields, integration.config);
const statusFor = integration => integration.planned ? 'Geplant' : !integration.enabled ? 'Deaktiviert' : !integration.configured ? 'Einrichtung erforderlich' : ['unavailable', 'degraded', 'error'].includes(integration.health?.status) ? 'Eingeschränkt' : 'Aktiv';
const localWorkflowHref = value => {
  if (typeof value !== 'string' || !value.startsWith('/') || value.startsWith('//') || value.includes('\\') || Array.from(value).some(character => character.charCodeAt(0) < 32)) return null;
  try {
    const target = new URL(value, 'https://immomanager.invalid');
    return target.origin === 'https://immomanager.invalid' && /^\/(messages|documents|listings|teha)(\/|$)/.test(target.pathname) ? value : null;
  } catch { return null; }
};

function Field({ field, prefix, value, onChange, stored, disabled }) {
  const id = prefix + '-' + field.key;
  const structured = field.multiline || ['array', 'object'].includes(field.type);
  const props = { id, value: value ?? '', onChange: event => onChange(event.target.value), className: 'form-input',
    required: field.required && !stored, min: field.min, max: field.max, disabled };
  return <div className={'integration-field' + (structured ? ' integration-field-wide' : '')}>
    {field.type === 'boolean' ? <label className="integration-check" htmlFor={id}>
      <input id={id} type="checkbox" checked={Boolean(value)} onChange={event => onChange(event.target.checked)} /><span>{labelFor(field)}</span>
    </label> : <>
      <label htmlFor={id} className={field.required && !stored ? 'integration-field-required' : undefined}>{labelFor(field)}</label>
      {field.options ? <select {...props}><option value="">Bitte wählen</option>{field.options.map(option => {
        const optionValue = option?.value ?? option;
        return <option key={String(optionValue)} value={String(optionValue)}>{option?.label ?? String(optionValue)}</option>;
      })}</select> : structured ? <textarea {...props} rows={['array', 'object'].includes(field.type) ? 5 : 3} spellCheck={['array', 'object'].includes(field.type) ? false : undefined} />
        : <input {...props} type={field.secret ? 'password' : field.format === 'email' ? 'email' : ['integer', 'number'].includes(field.type) ? 'number' : 'text'}
          step={field.type === 'number' ? 'any' : field.type === 'integer' ? '1' : undefined}
          autoComplete={field.secret ? 'new-password' : undefined} placeholder={field.secret && stored ? 'Gespeichert – leer lassen zum Beibehalten' : undefined} />}
    </>}
    {(field.description || field.help) && <small>{field.description || field.help}</small>}
  </div>;
}

function IntegrationCard({ integration, canWrite, update }) {
  const [config, setConfig] = useState(() => initialConfig(integration));
  const [actionId, setActionId] = useState(integration.actions?.[0]?.id || '');
  const [inputs, setInputs] = useState(() => initializeIntegrationValues(integration.actions?.[0]?.inputs));
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [retry, setRetry] = useState(null);
  const [clearSecrets, setClearSecrets] = useState({});
  const [configDirty, setConfigDirty] = useState(false);
  const dirty = useRef(false);
  const [history, setHistory] = useState(null);
  const [historySkip, setHistorySkip] = useState(0);
  const [historyBusy, setHistoryBusy] = useState(false);
  const [historyError, setHistoryError] = useState(null);
  const running = useRef(false);
  const mounted = useRef(true);
  const historyRequest = useRef(0);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; historyRequest.current += 1; }; }, []);
  useEffect(() => {
    if (!dirty.current) setConfig(initialConfig(integration));
  }, [integration]);
  const fields = integration.config_fields || [];
  const actions = integration.actions || [];
  const action = actions.find(item => item.id === actionId);
  const Icon = ICONS[integration.category] || IntegrationIcon;
  const missing = action?.inputs?.some(field => field.required && isIntegrationFieldEmpty(inputs[field.key]));
  const href = result?.success ? localWorkflowHref(result.details?.href) : null;
  const health = integration.health?.message || HEALTH[integration.health?.status] || codeLabel(integration.health?.status) || 'Noch nicht geprüft';

  const loadHistory = async skip => {
    const request = ++historyRequest.current;
    setHistoryBusy(true); setHistoryError(null);
    try {
      const same = api.captureSession?.();
      const response = await api.get('/integrations/' + integration.id + '/history?limit=20&skip=' + skip);
      same?.();
      if (!Array.isArray(response?.items) || !Number.isInteger(response.total) || response.total < 0) throw new Error('Der Verlauf ist unvollständig. Bitte erneut laden.');
      if (!mounted.current || request !== historyRequest.current) return;
      setHistory(response); setHistorySkip(skip);
    } catch (error) { if (mounted.current && request === historyRequest.current) { if (error.code === 'SESSION_CHANGED') setHistory(null); setHistoryError({ message: error.message, skip }); } }
    finally { if (mounted.current && request === historyRequest.current) setHistoryBusy(false); }
  };
  const perform = async (operation, retryable = true) => {
    if (!canWrite || running.current) return;
    running.current = true; setBusy(true); setRetry(null); setResult(null);
    try {
      const same = api.captureSession?.();
      const publish = response => { same?.(); if (mounted.current) setResult(response); };
      await operation(publish, same);
    }
    catch (error) {
      if (!mounted.current) return;
      if (error.code === 'SESSION_CHANGED') {
        setRetry(null); setInputs({}); setConfig({}); setClearSecrets({}); dirty.current = false; setConfigDirty(false);
        historyRequest.current += 1; setHistory(null); setHistoryError(null); setHistoryBusy(false);
        setResult({ success: false, message: error.message }); return;
      }
      const uncertain = !retryable && !isDefiniteIntegrationFailure(error);
      setResult({ success: false, message: error.message + (uncertain ? ' Ergebnis unbestätigt; vor erneutem Versand beim Empfänger prüfen.' : '') });
      if (retryable) setRetry(() => operation);
    }
    finally { running.current = false; if (mounted.current) setBusy(false); }
  };
  const configuration = () => ({ ...serializeIntegrationValues(fields, config, {
    retainedSecrets: fields.filter(field => field.secret && integration.config?.[field.key] === '***').map(field => field.key), emptyValue: null,
  }), ...Object.fromEntries(Object.keys(clearSecrets).filter(key => clearSecrets[key]).map(key => [key, null])) });
  const save = () => perform(async (publish, same) => {
    const response = await api.put('/integrations/' + integration.id + '/config', { config: configuration() }); same?.();
    if (!response?.config || typeof response.config !== 'object' || Array.isArray(response.config)) throw new Error('Der gespeicherte Stand konnte nicht bestätigt werden. Bitte erneut prüfen.');
    if (!mounted.current) return;
    dirty.current = false; setConfigDirty(false);
    update(integration.id, response); setConfig(initialConfig({ ...integration, config: response.config })); setClearSecrets({});
    publish({ success: true, message: 'Konfiguration gespeichert' });
  });
  const validate = () => perform(async publish => {
    const response = await api.post('/integrations/' + integration.id + '/validate', { config: configuration() });
    if (typeof response?.valid !== 'boolean' || typeof response.message !== 'string') throw new Error('Die Konfigurationsprüfung wurde nicht vollständig bestätigt.');
    publish({ success: response.valid, message: response.message, details: response.errors });
  });
  const toggle = () => {
    const enabled = !integration.enabled;
    perform(async (publish, same) => {
      const response = await api.patch('/integrations/' + integration.id, { enabled }); same?.();
      if (response?.enabled !== enabled || response.id && response.id !== integration.id) throw new Error('Der Aktivierungszustand konnte nicht bestätigt werden. Bitte aktuelle Werte laden.');
      if (!mounted.current) return;
      update(integration.id, response);
      publish({ success: true, message: response.enabled ? 'Integration aktiviert' : 'Integration deaktiviert' });
    });
  };
  const run = () => {
    if (!action || !integration.enabled || integration.planned || configDirty) return;
    let payload;
    try { payload = { action: actionId, ...serializeIntegrationValues(action.inputs, inputs) }; }
    catch (error) { setResult({ success: false, message: error.message }); setRetry(null); return; }
    const retryable = action.effect === 'local' || ['check_connection', 'health'].includes(actionId) || integration.id === 'contract-wizard';
    const operation = async publish => {
      const response = await api.post('/integrations/' + integration.id + '/run', { payload });
      if (typeof response?.success !== 'boolean' || typeof response.message !== 'string') throw new Error('Das Aktionsergebnis konnte nicht bestätigt werden.');
      const notStarted = ['invalid_payload', 'history_unavailable'].includes(response.details?.code) || response.details?.valid === false;
      publish(!response.success && !retryable && !notStarted ? { ...response,
        message: response.message + ' Ergebnis unbestätigt. Prüfen Sie den Vorgang bei der Gegenstelle, bevor Sie ihn erneut ausführen.',
      } : response);
      if (mounted.current && !response.success && retryable) setRetry(() => operation);
    };
    perform(operation, retryable);
  };

  return <section className="panel integration-card" aria-label={integration.name} aria-busy={busy}>
    <div className="integration-detail-heading"><div className="integration-title"><span className="integration-icon"><Icon size={22} /></span><div><p className="integration-category">{CATEGORIES[integration.category] || integration.category || 'Schnittstelle'}</p><h2>{integration.name}</h2></div></div>
      <span className={'integration-status integration-status-' + (integration.planned ? 'planned' : !integration.enabled ? 'inactive' : !integration.configured || ['unavailable', 'degraded', 'error'].includes(integration.health?.status) ? 'attention' : 'active')}>{statusFor(integration)}</span></div>
    <div className="panel-body integration-detail-body">
      <p className="integration-description">{integration.description}</p>
      <dl className="integration-health"><div><dt>Konfiguration</dt><dd>{integration.configured ? 'Vorhanden' : 'Noch nicht eingerichtet'}</dd></div><div><dt>Verbindungsstatus</dt><dd>{health}</dd></div></dl>
      {integration.capabilities?.length > 0 && <ul className="integration-capabilities" aria-label="Funktionen">{integration.capabilities.map(capability => <li key={capability}>{CAPABILITY_LABELS[capability] || capability}</li>)}</ul>}
      {integration.planned && <p className="integration-notice">Diese Anbindung ist geplant und derzeit noch nicht verfügbar.</p>}
      {integration.persistence_error && <p className="integration-feedback integration-feedback-error" role="alert">{integration.persistence_error}</p>}
      {canWrite && !integration.planned && <>
        <div className="integration-activation"><p>{integration.enabled ? 'Die Schnittstelle ist aktiviert. Aktionen werden nur auf Ihren Auftrag ausgeführt.' : 'Aktivieren Sie die Schnittstelle, um ihre Aktionen zu verwenden.'}</p><button className="btn btn-sm btn-secondary" disabled={busy || Boolean(integration.persistence_error)} onClick={toggle}>{integration.enabled ? 'Deaktivieren' : 'Aktivieren'}</button></div>
        {fields.length > 0 && <form onSubmit={event => { event.preventDefault(); save(); }} className="integration-form"><fieldset disabled={busy || Boolean(integration.persistence_error)}><legend>Konfiguration</legend>
          <div className="integration-fields">{fields.map(field => <div key={field.key} className={field.multiline || ['array', 'object'].includes(field.type) ? 'integration-field-wide' : undefined}>
            <Field field={field} prefix={integration.id + '-config'} value={config[field.key]} stored={integration.config?.[field.key] === '***'} disabled={Boolean(clearSecrets[field.key])} onChange={value => { dirty.current = true; setConfigDirty(true); setResult(null); setRetry(null); setConfig(previous => ({ ...previous, [field.key]: value,
              ...(field.key === 'smtp_use_ssl' && value ? { smtp_use_tls: false } : {}), ...(field.key === 'smtp_use_tls' && value ? { smtp_use_ssl: false } : {}),
            })); }} />
            {field.secret && integration.config?.[field.key] === '***' && <label className="integration-check integration-secret-clear"><input type="checkbox" checked={Boolean(clearSecrets[field.key])} onChange={event => { dirty.current = true; setConfigDirty(true); setResult(null); setRetry(null); setClearSecrets(previous => ({ ...previous, [field.key]: event.target.checked })); if (event.target.checked) setConfig(previous => ({ ...previous, [field.key]: '' })); }} /><span>Gespeichertes Geheimnis entfernen</span></label>}
          </div>)}</div>
          {configDirty && <p className="integration-unsaved" role="status">Ungespeicherte Änderungen. Speichern Sie die Konfiguration, bevor Sie eine Aktion ausführen.</p>}
          <div className="integration-actions"><button type="button" className="btn btn-secondary" onClick={validate}>Konfiguration prüfen</button><button className="btn btn-primary">Konfiguration speichern</button></div>
        </fieldset></form>}
        {actions.length > 0 && <form onSubmit={event => { event.preventDefault(); run(); }} className="integration-form"><fieldset disabled={busy || configDirty || Boolean(integration.persistence_error)}><legend>Aktionen</legend>
          <div className="integration-field"><label htmlFor={integration.id + '-action'}>Aktion</label><select id={integration.id + '-action'} className="form-input" value={actionId} onChange={event => { setActionId(event.target.value); setInputs(initializeIntegrationValues(actions.find(item => item.id === event.target.value)?.inputs)); setResult(null); setRetry(null); }}>{actions.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}</select></div>
          <div className="integration-fields">{(action?.inputs || []).map(field => <Field key={field.key} field={field} prefix={integration.id + '-action'} value={inputs[field.key]} onChange={value => { setResult(null); setRetry(null); setInputs(previous => ({ ...previous, [field.key]: value })); }} />)}</div>
          {!integration.enabled && <p className="text-muted">Diese Schnittstelle ist deaktiviert.</p>}
          <div className="integration-actions"><button className="btn btn-primary" disabled={!integration.enabled || missing || busy}>{integration.id === 'email' && actionId === 'send' ? 'E-Mail versenden' : 'Aktion ausführen'}</button></div>
        </fieldset></form>}
      </>}
      {!canWrite && <p className="integration-notice">Nur Lesezugriff. Konfiguration und Aktionen sind für Ihre Rolle gesperrt.</p>}
      {busy && <p className="integration-working" role="status">Anfrage wird verarbeitet …</p>}
      {result && <div role={result.success ? 'status' : 'alert'} className={'integration-feedback ' + (result.success ? 'integration-feedback-success' : 'integration-feedback-error')}>
        <p>{result.message}</p>
        {href && <Link to={href} className="btn btn-primary">{action?.label || 'Zugehörigen Bereich öffnen'}</Link>}
        {typeof result.details?.preview === 'string' && <div className="integration-preview"><h3>Vorschau</h3><p>{result.details.preview}</p></div>}
        {typeof result.details?.summary === 'string' && <p className="integration-preview">{result.details.summary}</p>}
        {result.details && <details><summary>Ergebnisdetails</summary><pre>{JSON.stringify(result.details, null, 2)}</pre></details>}
        {result.history_warning && <p role="alert">{result.history_warning}</p>}
        {retry && <button className="btn btn-secondary" disabled={busy} onClick={() => perform(retry)}>Aktion erneut versuchen</button>}
      </div>}
      <div className="integration-history"><h3>Aktionsverlauf</h3><p className="text-muted">Ausführungen und bestätigte Ergebnisse dieser Schnittstelle.</p><button className="btn btn-secondary" disabled={historyBusy} onClick={() => loadHistory(0)}>{historyBusy ? 'Verlauf wird geladen …' : history ? 'Verlauf aktualisieren' : 'Verlauf anzeigen'}</button>
        {historyError && <div className="integration-feedback integration-feedback-error" role="alert"><p>{historyError.message}</p><button className="btn btn-secondary" disabled={historyBusy} onClick={() => loadHistory(historyError.skip)}>Verlauf erneut laden</button></div>}
        {history && <><p className="text-muted" role="status">{history.total} protokollierte Aktionen</p>
          {history.items.length === 0 ? <p>Noch keine Aktionen protokolliert.</p> : <ol className="integration-history-list">{history.items.map(item => <li key={item.id}><div className="integration-history-meta"><time dateTime={item.created_at}>{new Date(item.created_at).toLocaleString('de-DE')}</time><span>{item.success ? 'Erfolgreich' : 'Nicht bestätigt / fehlgeschlagen'}</span></div><p>{item.message}</p>{item.details && <details><summary>Ergebnisdetails</summary><pre>{JSON.stringify(item.details, null, 2)}</pre></details>}</li>)}</ol>}
          <div className="integration-actions"><button className="btn btn-secondary" disabled={historyBusy || historySkip === 0} onClick={() => loadHistory(Math.max(0, historySkip - 20))}>Vorherige Einträge</button><button className="btn btn-secondary" disabled={historyBusy || historySkip + 20 >= history.total} onClick={() => loadHistory(historySkip + 20)}>Weitere Einträge</button></div>
        </>}
      </div>
    </div>
  </section>;
}

export default function Integrations() {
  const { t } = useTranslation();
  const canWrite = useCanWrite('/integrations');
  const [params, setParams] = useSearchParams();
  const [integrations, setIntegrations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [search, setSearch] = useState('');
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let live = true;
    setLoading(true); setError(null);
    Promise.resolve().then(() => {
      const same = api.captureSession?.();
      return api.get('/integrations').then(response => {
      same?.();
      if (!Array.isArray(response?.integrations)) throw new Error('Die Schnittstellenliste ist unvollständig. Bitte erneut laden.');
        if (live) setIntegrations(response.integrations);
      });
    }).catch(failure => { if (live) { if (failure.code === 'SESSION_CHANGED') setIntegrations([]); setError(failure.message); } }).finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [attempt]);
  const requested = params.get('integration');
  const selected = requested ? integrations.find(item => item.id === requested)?.id : integrations[0]?.id;
  const found = integrations.filter(item => (item.name + ' ' + item.description + ' ' + (CATEGORIES[item.category] || item.category || '')).toLocaleLowerCase('de').includes(search.trim().toLocaleLowerCase('de')));
  const update = (id, changes) => setIntegrations(previous => previous.map(item => item.id === id ? { ...item, ...changes } : item));
  const title = t('pages.integrations.title');
  return <div className="page integrations-page">
    <div className="integrations-heading"><div><h1 className="page-title">{title && title !== 'pages.integrations.title' ? title : 'Schnittstellen'}</h1><p>Installationsweite Anbindungen einrichten, Verbindungen prüfen und Aktionen gezielt ausführen.</p></div><div className="integration-actions"><button className="btn btn-secondary" disabled={loading} onClick={() => setAttempt(value => value + 1)}>Aktuelle Werte laden</button><Link to="/integration-connections" className="btn btn-secondary">Verbindungen und Vorgänge</Link></div></div>
    {error && <div className="integration-feedback integration-feedback-error" role="alert"><p>{error}</p><button className="btn btn-secondary" onClick={() => setAttempt(value => value + 1)}>Erneut laden</button></div>}
    {loading && <p role="status">Lade Integrationen…</p>}
    {!loading && !error && integrations.length === 0 && <div className="panel integration-empty"><h2>Keine Schnittstellen verfügbar</h2><p>Für diese Installation wurden noch keine Schnittstellen bereitgestellt.</p><button className="btn btn-secondary" onClick={() => setAttempt(value => value + 1)}>Erneut laden</button></div>}
    {integrations.length > 0 && <div hidden={loading || Boolean(error)}><p className="integrations-summary">{integrations.length} Schnittstellen · {integrations.filter(item => item.enabled && !item.planned).length} aktiviert</p><div className="integrations-workspace">
      <aside className="integrations-directory" aria-label="Schnittstellen auswählen"><label htmlFor="integration-search">Schnittstelle suchen</label><input className="form-input" id="integration-search" type="search" value={search} onChange={event => setSearch(event.target.value)} placeholder="Name oder Bereich" /><p className="text-muted integrations-directory-count" role="status">{found.length} {found.length === 1 ? 'Schnittstelle' : 'Schnittstellen'}</p>
        <div className="integrations-list">{found.map(item => { const Icon = ICONS[item.category] || IntegrationIcon; return <button key={item.id} className={'integration-choice' + (selected === item.id ? ' is-selected' : '')} aria-pressed={selected === item.id} aria-controls={'integration-panel-' + item.id} onClick={() => setParams(current => { const next = new URLSearchParams(current); next.set('integration', item.id); return next; })}><Icon size={20} /><span><strong>{item.name}</strong><small>{statusFor(item)}</small></span></button>; })}</div>
        {found.length === 0 && <p>Keine passende Schnittstelle. Ändern Sie den Suchbegriff.</p>}
      </aside>
      <div className="integrations-detail">{requested && !selected && <div className="panel integration-empty" role="alert"><h2>Schnittstelle nicht gefunden</h2><p>Der gespeicherte Link ist nicht mehr gültig. Wählen Sie links eine verfügbare Schnittstelle.</p></div>}
        {integrations.map(integration => <div key={integration.id} id={'integration-panel-' + integration.id} hidden={selected !== integration.id}><IntegrationCard integration={integration} canWrite={canWrite} update={update} /></div>)}
      </div>
    </div></div>}
  </div>;
}
