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

export default function Integrations() {
  const { t } = useTranslation();
  const auth = useAuth();
  const [integrations, setIntegrations] = useState([]);
  const [messages, setMessages] = useState({});
  const [checking, setChecking] = useState({});
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
  const pendingTests = useRef(new Map());

  useLayoutEffect(() => {
    currentGrant.current = grant;
    const actions = pendingActions.current;
    const tests = pendingTests.current;
    return () => {
      currentGrant.current = null;
      for (const controller of actions) controller.abort();
      actions.clear();
      tests.clear();
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
    setChecking({});
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

  const testConnection = async (id) => {
    if (pendingTests.current.has(id)) return;
    const action = beginAction();
    if (!action) return;
    pendingTests.current.set(id, action.controller);
    setChecking(prev => ({ ...prev, [id]: true }));
    setMessages(prev => ({ ...prev, [id]: '' }));
    try {
      const res = await api.post(`/integrations/${id}/connection-test`, {}, { signal: action.controller.signal });
      if (!action.allowed()) return;
      let key = 'connectionUnconfirmed';
      if (res?.integration_id === id && res.business_action_performed === false && res.test_message_sent === false) {
        if (res.status === 'configuration_invalid') key = 'connectionConfigInvalid';
        else if (res.status === 'not_supported' && res.configured && res.network_checked === false) key = 'connectionConfigOnly';
        else if (res.status === 'checked' && res.configured && res.probe_supported && res.network_checked === true) key = 'connectionChecked';
        else if (res.status === 'failed') key = 'connectionFailed';
      }
      setMessages(prev => ({ ...prev, [id]: t(`pages.integrations.${key}`) }));
    } catch (err) {
      if (!action.allowed()) return;
      setMessages((prev) => ({ ...prev, [id]: `${t('pages.integrations.error') || 'Fehler'}: ${err.message}` }));
    } finally {
      if (pendingTests.current.get(id) === action.controller) {
        pendingTests.current.delete(id);
        if (action.allowed()) setChecking(prev => ({ ...prev, [id]: false }));
      }
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

                {canWrite && <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem' }}>
                  <button className="btn btn-sm btn-secondary" disabled={checking[intg.id]} onClick={() => toggleIntegration(intg.id, !intg.enabled)}>
                    {intg.enabled ? t('pages.integrations.disable') || 'Deaktivieren' : t('pages.integrations.enable') || 'Aktivieren'}
                  </button>
                  <button className="btn btn-sm btn-primary" disabled={intg.planned || checking[intg.id]} onClick={() => testConnection(intg.id)}>
                    {t(checking[intg.id] ? 'pages.integrations.connectionChecking' : 'pages.integrations.runTest')}
                  </button>
                </div>}
                {messages[intg.id] && <div role="status" className="text-muted" style={{ marginBottom: '1rem' }}>{messages[intg.id]}</div>}

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
