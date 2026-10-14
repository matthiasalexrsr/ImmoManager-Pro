import { useEffect, useState } from 'react';
import { useTranslation } from '../i18n';
import { api } from '../api';
import { useCanWrite } from '../contexts/AuthContext';
import { AlertIcon, MessageIcon, ContractIcon, DocumentIcon, BuildingIcon } from '../components/Icons';

const ICONS = { communication: MessageIcon, workflow: ContractIcon, delivery: DocumentIcon, listing: BuildingIcon };
const initialConfig = integration => Object.fromEntries((integration.config_fields || []).map(field => [field.key,
  field.secret ? '' : integration.config?.[field.key] ?? field.default ?? (field.type === 'boolean' ? false : '')]));

function valuesFor(fields, values, configuration = false) {
  const result = {};
  for (const field of fields) {
    const value = values[field.key];
    if (value === '' || value === undefined) {
      if (configuration && !field.secret) result[field.key] = null;
      continue;
    }
    if (field.type === 'object' || field.type === 'array') {
      try { result[field.key] = JSON.parse(value); }
      catch { throw new Error(`${field.label}: gültiges JSON ist erforderlich`); }
    } else if (field.type === 'integer' || field.type === 'number') result[field.key] = Number(value);
    else result[field.key] = value;
  }
  return result;
}

function Field({ field, prefix, value, onChange, stored }) {
  const id = `${prefix}-${field.key}`;
  const properties = { id, value: value ?? '', onChange: event => onChange(event.target.value),
    className: 'form-input', required: field.required, min: field.min, max: field.max };
  return <div className="form-group" style={{ marginBottom: '.75rem' }}>
    <label htmlFor={id}>
      {field.type === 'boolean' && <input id={id} type="checkbox" checked={Boolean(value)}
        onChange={event => onChange(event.target.checked)} style={{ marginRight: '.4rem' }} />}
      {field.label || field.key}
    </label>
    {field.type !== 'boolean' && (field.options
      ? <select {...properties}><option value="">Bitte wählen</option>{field.options.map(option => <option key={option}>{option}</option>)}</select>
      : field.multiline || field.type === 'object' || field.type === 'array'
        ? <textarea {...properties} rows={3} />
        : <input {...properties} required={field.required && !stored} type={field.secret ? 'password'
          : field.format === 'email' ? 'email' : ['integer', 'number'].includes(field.type) ? 'number' : 'text'}
          step={field.type === 'number' ? 'any' : undefined} autoComplete={field.secret ? 'new-password' : undefined}
          placeholder={field.secret && stored ? 'Gespeichert – leer lassen zum Beibehalten' : undefined} />)}
  </div>;
}

function IntegrationCard({ integration, canWrite, update }) {
  const [config, setConfig] = useState(() => initialConfig(integration));
  const [actionId, setActionId] = useState(integration.actions?.[0]?.id || '');
  const [inputs, setInputs] = useState({});
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [retry, setRetry] = useState(null);
  const [clearSecrets, setClearSecrets] = useState({});
  const [history, setHistory] = useState(null);
  const [historySkip, setHistorySkip] = useState(0);
  const [historyBusy, setHistoryBusy] = useState(false);
  const [historyError, setHistoryError] = useState(null);
  const fields = integration.config_fields || [];
  const actions = integration.actions || [];
  const action = actions.find(item => item.id === actionId);
  const Icon = ICONS[integration.category] || AlertIcon;
  const missing = action?.inputs?.some(field => field.required && !inputs[field.key]);

  const loadHistory = async skip => {
    setHistoryBusy(true); setHistoryError(null);
    try {
      const response = await api.get(`/integrations/${integration.id}/history?limit=20&skip=${skip}`);
      setHistory(response); setHistorySkip(skip);
    } catch (error) { setHistoryError({ message: error.message, skip }); }
    finally { setHistoryBusy(false); }
  };

  const perform = async (operation, retryable = true) => {
    if (!canWrite || busy) return;
    setBusy(true); setRetry(null); setResult(null);
    try { await operation(); }
    catch (error) {
      setResult({ success: false, message: error.message + (retryable ? '' : ' Ergebnis unbestätigt; vor erneutem Versand beim Empfänger prüfen.') });
      if (retryable) setRetry(() => operation);
    }
    finally { setBusy(false); }
  };
  const configuration = () => ({ ...valuesFor(fields, config, true),
    ...Object.fromEntries(Object.keys(clearSecrets).filter(key => clearSecrets[key]).map(key => [key, null])) });
  const save = () => perform(async () => {
    const response = await api.put(`/integrations/${integration.id}/config`, { config: configuration() });
    update(integration.id, response);
    setConfig(initialConfig({ ...integration, config: response.config })); setClearSecrets({});
    setResult({ success: true, message: 'Konfiguration gespeichert' });
  });
  const validate = () => perform(async () => {
    const response = await api.post(`/integrations/${integration.id}/validate`, { config: configuration() });
    setResult({ success: response.valid, message: response.message, details: response.errors });
  });
  const toggle = () => perform(async () => {
    const response = await api.patch(`/integrations/${integration.id}`, { enabled: !integration.enabled });
    update(integration.id, response);
    setResult({ success: true, message: response.enabled ? 'Integration aktiviert' : 'Integration deaktiviert' });
  });
  const run = () => {
    const operation = async () => {
      const response = await api.post(`/integrations/${integration.id}/run`, {
        payload: { action: actionId, ...valuesFor(action.inputs || [], inputs) },
      });
      setResult(response);
      if (!response.success && !(integration.id === 'email' && actionId === 'send')) setRetry(() => operation);
    };
    perform(operation, !(integration.id === 'email' && actionId === 'send'));
  };

  return <section className="panel integration-card" aria-label={integration.name}>
    <div className="panel-header" style={{ display: 'flex', alignItems: 'center', gap: '.5rem' }}>
      <Icon size={20} /><span>{integration.name}</span>
      <span className={`badge ${integration.enabled && !integration.planned ? 'badge-green' : 'badge-planned'}`}
        style={{ marginLeft: 'auto' }}>{integration.message}</span>
    </div>
    <div className="panel-body">
      <p>{integration.description}</p>
      <p className="text-muted">{integration.configured ? 'Konfiguriert' : 'Nicht konfiguriert'} · {integration.health?.message || integration.health?.status}</p>
      {integration.planned && <p>Diese Anbindung ist noch nicht implementiert.</p>}
      {integration.persistence_error && <p role="alert">{integration.persistence_error}</p>}
      {canWrite && <>
        <button className="btn btn-sm btn-secondary" disabled={busy || Boolean(integration.persistence_error)} onClick={toggle}>{integration.enabled ? 'Deaktivieren' : 'Aktivieren'}</button>
        {fields.length > 0 && <form onSubmit={event => { event.preventDefault(); save(); }} style={{ marginTop: '1rem' }}>
          <fieldset disabled={busy || Boolean(integration.persistence_error)} style={{ border: 0, padding: 0 }}><legend>Konfiguration</legend>
            {fields.map(field => <div key={field.key}>
              <Field field={field} prefix={`${integration.id}-config`} value={config[field.key]} stored={integration.config?.[field.key] === '***'}
                onChange={value => setConfig(previous => ({ ...previous, [field.key]: value,
                  ...(field.key === 'smtp_use_ssl' && value ? { smtp_use_tls: false } : {}),
                  ...(field.key === 'smtp_use_tls' && value ? { smtp_use_ssl: false } : {}),
                }))} />
              {field.secret && integration.config?.[field.key] === '***' && <label style={{ display: 'block', marginBottom: '.75rem' }}>
                <input type="checkbox" checked={Boolean(clearSecrets[field.key])} onChange={event => setClearSecrets(previous => ({ ...previous, [field.key]: event.target.checked }))} /> Gespeichertes Geheimnis entfernen
              </label>}
            </div>)}
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '.5rem' }}>
              <button type="button" className="btn btn-sm btn-secondary" onClick={validate}>Konfiguration prüfen</button>
              <button className="btn btn-sm btn-primary">Konfiguration speichern</button>
            </div>
          </fieldset>
        </form>}
        {actions.length > 0 && !integration.planned && <form onSubmit={event => { event.preventDefault(); run(); }} style={{ marginTop: '1rem' }}>
          <fieldset disabled={busy || Boolean(integration.persistence_error)} style={{ border: 0, padding: 0 }}>
            <div className="form-group"><label htmlFor={`${integration.id}-action`}>Aktion</label>
              <select id={`${integration.id}-action`} className="form-input" value={actionId} onChange={event => { setActionId(event.target.value); setInputs({}); setResult(null); setRetry(null); }}>
                {actions.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
              </select>
            </div>
            {(action?.inputs || []).map(field => <Field key={field.key} field={field} prefix={`${integration.id}-action`} value={inputs[field.key]}
              onChange={value => setInputs(previous => ({ ...previous, [field.key]: value }))} />)}
            <button className="btn btn-sm btn-primary" disabled={!integration.enabled || missing || busy}>
              {integration.id === 'email' && actionId === 'send' ? 'E-Mail versenden' : 'Aktion ausführen'}
            </button>
          </fieldset>
        </form>}
      </>}
      {!canWrite && <p className="text-muted">Nur Lesezugriff</p>}
      {result && <div role={result.success ? 'status' : 'alert'} style={{ marginTop: '1rem' }}>
        <p>{result.message}</p>{result.details && <pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{JSON.stringify(result.details, null, 2)}</pre>}
        {result.history_warning && <p role="alert">{result.history_warning}</p>}
        {retry && <button className="btn btn-sm btn-secondary" disabled={busy} onClick={() => perform(retry)}>Aktion erneut versuchen</button>}
      </div>}
      <div style={{ marginTop: '1rem' }}>
        <button className="btn btn-sm btn-secondary" disabled={historyBusy} onClick={() => loadHistory(0)}>Verlauf anzeigen</button>
        {historyError && <div role="alert"><p>{historyError.message}</p>
          <button className="btn btn-sm btn-secondary" disabled={historyBusy} onClick={() => loadHistory(historyError.skip)}>Verlauf erneut laden</button>
        </div>}
        {history && <>
          <p className="text-muted">{history.total || 0} protokollierte Aktionen</p>
          <ol style={{ paddingLeft: '1.25rem' }}>{(history.items || []).map(item => <li key={item.id} style={{ marginBottom: '.75rem' }}>
            <time dateTime={item.created_at}>{new Date(item.created_at).toLocaleString()}</time> · {item.success ? 'Erfolgreich' : 'Nicht bestätigt / fehlgeschlagen'}
            <p>{item.message}</p>
            {item.details && <details><summary>Ergebnisdetails</summary><pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{JSON.stringify(item.details, null, 2)}</pre></details>}
          </li>)}</ol>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '.5rem' }}>
            <button className="btn btn-sm btn-secondary" disabled={historyBusy || historySkip === 0} onClick={() => loadHistory(Math.max(0, historySkip - 20))}>Vorherige Einträge</button>
            <button className="btn btn-sm btn-secondary" disabled={historyBusy || historySkip + 20 >= history.total} onClick={() => loadHistory(historySkip + 20)}>Weitere Einträge</button>
          </div>
        </>}
      </div>
    </div>
  </section>;
}

export default function Integrations() {
  const { t } = useTranslation();
  const canWrite = useCanWrite('/integrations');
  const [integrations, setIntegrations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const loadIntegrations = () => {
    setLoading(true); setError(null);
    api.get('/integrations').then(response => setIntegrations(response.integrations || []))
      .catch(failure => setError(failure.message)).finally(() => setLoading(false));
  };
  useEffect(() => { loadIntegrations(); }, []);
  const update = (id, changes) => setIntegrations(previous => previous.map(item => item.id === id ? { ...item, ...changes } : item));
  return <div className="page">
    <h1 className="page-title">{t('pages.integrations.title') || 'Integrationen'}</h1>
    <p className="text-muted" style={{ marginBottom: '1.5rem' }}>Verbindungen konfigurieren, prüfen und ausgewählte Aktionen ausführen.</p>
    {loading && <p role="status">Lade Integrationen…</p>}
    {error && <div role="alert"><p>{error}</p><button className="btn btn-secondary" onClick={loadIntegrations}>Erneut laden</button></div>}
    <div className="integrations-grid">{integrations.map(integration => <IntegrationCard key={integration.id} integration={integration} canWrite={canWrite} update={update} />)}</div>
  </div>;
}
