import useWriteAccess from '../hooks/useWriteAccess';
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from '../i18n';
import { api } from '../api';
import { useAuth } from '../contexts/AuthContext';
import { AlertIcon, MessageIcon, ContractIcon, DocumentIcon, BuildingIcon } from '../components/Icons';

const ICONS = {
  communication: MessageIcon,
  workflow: ContractIcon,
  delivery: DocumentIcon,
  listing: BuildingIcon,
};

const CONFIG_LABELS = {
  phone_number_id: 'WhatsApp Phone Number ID', api_token: 'API Token',
  graph_version: 'Graph API Version (z. B. v23.0)', allow_direct_text: 'Direkttext erlauben',
  vendor_id: 'E-POST Vendor ID', ekp: 'E-POST EKP', secret: 'E-POST Secret',
  password: 'E-POST Passwort', vendor_sub_id: 'Vendor Sub-ID', test_email: 'Test-E-Mail',
  production_enabled: 'Produktivversand freigeben', sender_name: 'Absender / Firma',
  sender_street: 'Absender Straße', sender_zip_code: 'Absender PLZ', sender_city: 'Absender Ort',
  sender_email: 'Absender E-Mail', smtp_host: 'SMTP Host', smtp_port: 'SMTP Port',
  smtp_user: 'SMTP Benutzer', smtp_password: 'SMTP Passwort', smtp_use_tls: 'STARTTLS verwenden',
  smtp_use_ssl: 'SMTP über TLS/SSL', smtp_timeout_seconds: 'SMTP Timeout (Sek.)',
};

const OPTIONAL_CONFIG = {
  email: ['sender_name', 'smtp_port', 'smtp_user', 'smtp_password', 'smtp_use_tls', 'smtp_use_ssl', 'smtp_timeout_seconds'],
  whatsapp: ['graph_version', 'allow_direct_text'],
  'deutsche-post': ['vendor_sub_id', 'test_email'],
};
const BOOLEAN_CONFIG = new Set(['allow_direct_text', 'production_enabled', 'smtp_use_tls', 'smtp_use_ssl']);
const SECRET_CONFIG = new Set(['api_token', 'secret', 'password', 'smtp_password']);

const runPayloadFor = (integrationId) => {
  if (integrationId === 'email') {
    return {
      recipient: 'demo@example.com',
      subject: 'ImmoManager Pro Test',
      body: 'Integrationstest erfolgreich.',
    };
  }

  if (integrationId === 'contract-wizard') {
    return { tenant_name: 'Max Mustermann', property_name: 'Musterstraße 1' };
  }

  return {};
};

export default function Integrations() {
  const { t } = useTranslation();
  const auth = useAuth();
  const [integrations, setIntegrations] = useState([]);
  const [messages, setMessages] = useState({});
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);
  const { canWrite, isAllowed } = useWriteAccess('/integrations');
  const role = auth?.user?.role || auth?.role;
  const canAdminister = canWrite && (role === 'eigentuemer'
    || (role === 'verwalter' && auth?.user?.portfolio_access === 'all'));
  const principal = `${auth?.user?.id || ''}:${role || ''}:${auth?.user?.portfolio_access || ''}`;
  const pendingLoad = useRef(null);
  const grant = useMemo(() => ({ principal, canAdminister }), [principal, canAdminister]);
  const currentGrant = useRef(grant);
  const pendingActions = useRef(new Set());

  useLayoutEffect(() => {
    currentGrant.current = grant;
    const actions = pendingActions.current;
    return () => {
      currentGrant.current = null;
      for (const controller of actions) controller.abort();
      actions.clear();
    };
  }, [grant]);

  const beginAction = () => {
    if (!canAdminister || !isAllowed() || currentGrant.current !== grant) return null;
    const controller = new AbortController();
    pendingActions.current.add(controller);
    return {
      controller,
      allowed: () => !controller.signal.aborted && currentGrant.current === grant && isAllowed(),
      finish: () => pendingActions.current.delete(controller),
    };
  };

  const loadIntegrations = useCallback(() => {
    pendingLoad.current?.abort();
    setIntegrations([]);
    setMessages({});
    if (!canAdminister) { setLoading(false); setLoadError(null); return; }
    const controller = new AbortController();
    pendingLoad.current = controller;
    setLoading(true);
    setLoadError(null);
    api.get('/integrations', { signal: controller.signal })
      .then((res) => { if (!controller.signal.aborted) setIntegrations(res.integrations || []); })
      .catch((err) => { if (!controller.signal.aborted) setLoadError(err.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
  }, [canAdminister]);

  useEffect(() => {
    loadIntegrations();
    return () => pendingLoad.current?.abort();
  }, [loadIntegrations, principal]);

  const toggleIntegration = async (id, enabled) => {
    const action = beginAction();
    if (!action) return;
    try {
      await api.patch(`/integrations/${id}`, { enabled }, { signal: action.controller.signal });
      if (!action.allowed()) return;
      setIntegrations((prev) => prev.map((it) => (it.id === id ? { ...it, enabled } : it)));
    } catch (err) {
      if (!action.allowed()) return;
      setMessages((prev) => ({ ...prev, [id]: `${t('pages.integrations.error') || 'Fehler'}: ${err.message}` }));
    } finally {
      action.finish();
    }
  };

  const saveIntegrationConfig = async (event, integration) => {
    event.preventDefault();
    if (!isAllowed()) return;
    const form = new FormData(event.currentTarget);
    const fields = [...new Set([...(integration.required_config_keys || []), ...(OPTIONAL_CONFIG[integration.id] || [])])];
    const config = {};
    for (const key of fields) {
      if (BOOLEAN_CONFIG.has(key)) {
        config[key] = form.get(key) === 'on';
        continue;
      }
      const value = String(form.get(key) ?? '').trim();
      if (SECRET_CONFIG.has(key) && !value) continue;
      config[key] = value;
    }
    try {
      await api.put(`/integrations/${integration.id}/config`, { config });
      setMessages((prev) => ({ ...prev, [integration.id]: 'Konfiguration gespeichert.' }));
      loadIntegrations();
    } catch (err) {
      setMessages((prev) => ({ ...prev, [integration.id]: `Fehler: ${err.message}` }));
    }
  };

  const runIntegration = async (id) => {
    const action = beginAction();
    if (!action) return;
    try {
      const res = await api.post(`/integrations/${id}/run`, { payload: runPayloadFor(id) }, { signal: action.controller.signal });
      if (!action.allowed()) return;
      setMessages((prev) => ({ ...prev, [id]: res.message || t('pages.integrations.actionExecuted') || 'Aktion ausgeführt' }));
      const history = await api.get(`/integrations/${id}/history?limit=1`, { signal: action.controller.signal });
      if (!action.allowed()) return;
      const latest = history?.items?.[0];
      if (latest) {
        setMessages((prev) => ({
          ...prev,
          [id]: `${res.message || t('pages.integrations.actionExecuted') || 'Aktion ausgeführt'} (${latest.created_at})`,
        }));
      }
    } catch (err) {
      if (!action.allowed()) return;
      setMessages((prev) => ({ ...prev, [id]: `${t('pages.integrations.error') || 'Fehler'}: ${err.message}` }));
    } finally {
      action.finish();
    }
  };

  return (
    <div className="page">
      <h1 className="page-title">{t('pages.integrations.title') || 'Integrationen'}</h1>
      <p className="text-muted" style={{ marginBottom: '1.5rem' }}>
        {t('pages.integrations.subtitle') || 'Integrationsmodule verwalten, Konfiguration validieren und Testläufe ausführen.'}
      </p>

      {!canAdminister ? <div role="status" className="panel"><div className="panel-body">
        {t('pages.integrations.administrationRequired')}
      </div></div> : <>

      {loading && <p className="text-muted">{t('pages.integrations.loading') || 'Lade Integrationen...'}</p>}
      {loadError && <div role="alert">{loadError} <button className="btn btn-secondary" onClick={loadIntegrations}>{t('ui.buttons.retry')}</button></div>}

      <div className="integrations-grid">
        {integrations.map((intg) => {
          const Ico = ICONS[intg.category] || AlertIcon;
          const configFields = [...new Set([...(intg.required_config_keys || []), ...(OPTIONAL_CONFIG[intg.id] || [])])];
          return (
            <div key={intg.id} className="panel integration-card">
              <div className="panel-header" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <Ico size={20} />
                <span>{intg.name}</span>
                <span className={`badge ${intg.operational ? 'badge-green' : 'badge-planned'}`} style={{ marginLeft: 'auto' }}>
                  <AlertIcon size={12} /> {intg.message || (intg.enabled ? t('pages.integrations.active') || 'Aktiv' : t('pages.integrations.inactive') || 'Inaktiv')}
                </span>
              </div>
              <div className="panel-body">
                <p style={{ marginBottom: '0.5rem' }}>{intg.description}</p>
                {intg.planned && <p>{t('pages.integrations.adapterPlanned')}</p>}
                <p className="text-muted" style={{ marginBottom: '0.5rem', fontSize: '0.85rem' }}>
                  {t('pages.integrations.category') || 'Kategorie'}: {intg.category} · {intg.configured ? t('pages.integrations.configured') || 'Konfiguriert' : t('pages.integrations.notConfigured') || 'Nicht konfiguriert'}
                </p>
                <p className="text-muted" style={{ marginBottom: '0.5rem', fontSize: '0.85rem' }}>
                  Health: {intg.health?.status || 'unknown'}
                </p>
                <p className="text-muted" style={{ marginBottom: '1rem', fontSize: '0.85rem' }}>
                  {t('pages.integrations.requiredConfig') || 'Pflicht-Konfiguration'}: {(intg.required_config_keys || []).join(', ') || t('pages.integrations.none') || 'Keine'}
                </p>

                {canWrite && configFields.length > 0 && <form onSubmit={(event) => saveIntegrationConfig(event, intg)}
                  style={{ display: 'grid', gap: '0.55rem', marginBottom: '1rem' }}>
                  {configFields.map((key) => BOOLEAN_CONFIG.has(key) ? (
                    <label key={key} style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', fontSize: '0.85rem' }}>
                      <input name={key} type="checkbox"
                        defaultChecked={Boolean(intg.config?.[key] ?? (key === 'smtp_use_tls'))} />
                      {CONFIG_LABELS[key] || key}
                    </label>
                  ) : (
                    <label key={key} style={{ display: 'grid', gap: '0.25rem', fontSize: '0.82rem' }}>
                      {CONFIG_LABELS[key] || key}
                      <input name={key} type={SECRET_CONFIG.has(key) ? 'password' : 'text'}
                        defaultValue={intg.config?.[key] || ''}
                        required={(intg.required_config_keys || []).includes(key)}
                        autoComplete={SECRET_CONFIG.has(key) ? 'new-password' : 'off'} />
                    </label>
                  ))}
                  <button className="btn btn-sm btn-secondary" type="submit">Konfiguration speichern</button>
                </form>}

                {canWrite && <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem', flexWrap: 'wrap' }}>
                  <button className="btn btn-sm btn-secondary" onClick={() => toggleIntegration(intg.id, !intg.enabled)}>
                    {intg.enabled ? t('pages.integrations.disable') || 'Deaktivieren' : t('pages.integrations.enable') || 'Aktivieren'}
                  </button>
                  <button className="btn btn-sm btn-primary"
                    disabled={intg.planned || ['email', 'whatsapp', 'deutsche-post'].includes(intg.id)}
                    onClick={() => runIntegration(intg.id)}>
                    {t('pages.integrations.runTest') || 'Test ausführen'}
                  </button>
                </div>}
                {messages[intg.id] && <div className="text-muted" style={{ marginBottom: '1rem' }}>{messages[intg.id]}</div>}

                <h4 style={{ fontSize: '0.85rem', marginBottom: '0.5rem' }}>{t('pages.integrations.capabilities') || 'Capabilities:'}</h4>
                <ul className="integration-features">
                  {(intg.capabilities || []).map((feature, i) => (
                    <li key={i}>{feature}</li>
                  ))}
                </ul>
              </div>
            </div>
          );
        })}
      </div>
      </>}
    </div>
  );
}
