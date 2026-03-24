import { useEffect, useState } from 'react';
import { useTranslation } from '../i18n';
import { api } from '../api';
import { AlertIcon, MessageIcon, ContractIcon, DocumentIcon, BuildingIcon } from '../components/Icons';

const ICONS = {
  communication: MessageIcon,
  workflow: ContractIcon,
  delivery: DocumentIcon,
  listing: BuildingIcon,
};

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
  const [integrations, setIntegrations] = useState([]);
  const [messages, setMessages] = useState({});
  const [loading, setLoading] = useState(true);

  const loadIntegrations = () => {
    setLoading(true);
    api.get('/integrations')
      .then((res) => setIntegrations(res.integrations || []))
      .catch((err) => console.warn('[Integrations] load:', err.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    loadIntegrations();
  }, []);

  const toggleIntegration = async (id, enabled) => {
    try {
      await api.patch(`/integrations/${id}`, { enabled });
      setIntegrations((prev) => prev.map((it) => (it.id === id ? { ...it, enabled } : it)));
    } catch (err) {
      setMessages((prev) => ({ ...prev, [id]: `${t('pages.integrations.error') || 'Fehler'}: ${err.message}` }));
    }
  };

  const runIntegration = async (id) => {
    try {
      const res = await api.post(`/integrations/${id}/run`, { payload: runPayloadFor(id) });
      setMessages((prev) => ({ ...prev, [id]: res.message || t('pages.integrations.actionExecuted') || 'Aktion ausgeführt' }));
      const history = await api.get(`/integrations/${id}/history?limit=1`);
      const latest = history?.items?.[0];
      if (latest) {
        setMessages((prev) => ({
          ...prev,
          [id]: `${res.message || t('pages.integrations.actionExecuted') || 'Aktion ausgeführt'} (${latest.created_at})`,
        }));
      }
    } catch (err) {
      setMessages((prev) => ({ ...prev, [id]: `${t('pages.integrations.error') || 'Fehler'}: ${err.message}` }));
    }
  };

  return (
    <div className="page">
      <h1 className="page-title">{t('pages.integrations.title') || 'Integrationen'}</h1>
      <p className="text-muted" style={{ marginBottom: '1.5rem' }}>
        {t('pages.integrations.subtitle') || 'Integrationsmodule verwalten, Konfiguration validieren und Testläufe ausführen.'}
      </p>

      {loading && <p className="text-muted">{t('pages.integrations.loading') || 'Lade Integrationen...'}</p>}

      <div className="integrations-grid">
        {integrations.map((intg) => {
          const Ico = ICONS[intg.category] || AlertIcon;
          return (
            <div key={intg.id} className="panel integration-card">
              <div className="panel-header" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <Ico size={20} />
                <span>{intg.name}</span>
                <span className={`badge ${intg.enabled ? 'badge-green' : 'badge-planned'}`} style={{ marginLeft: 'auto' }}>
                  <AlertIcon size={12} /> {intg.message || (intg.enabled ? t('pages.integrations.active') || 'Aktiv' : t('pages.integrations.inactive') || 'Inaktiv')}
                </span>
              </div>
              <div className="panel-body">
                <p style={{ marginBottom: '0.5rem' }}>{intg.description}</p>
                <p className="text-muted" style={{ marginBottom: '0.5rem', fontSize: '0.85rem' }}>
                  {t('pages.integrations.category') || 'Kategorie'}: {intg.category} · {intg.configured ? t('pages.integrations.configured') || 'Konfiguriert' : t('pages.integrations.notConfigured') || 'Nicht konfiguriert'}
                </p>
                <p className="text-muted" style={{ marginBottom: '0.5rem', fontSize: '0.85rem' }}>
                  Health: {intg.health?.status || 'unknown'}
                </p>
                <p className="text-muted" style={{ marginBottom: '1rem', fontSize: '0.85rem' }}>
                  {t('pages.integrations.requiredConfig') || 'Pflicht-Konfiguration'}: {(intg.required_config_keys || []).join(', ') || t('pages.integrations.none') || 'Keine'}
                </p>

                <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem' }}>
                  <button className="btn btn-sm btn-secondary" onClick={() => toggleIntegration(intg.id, !intg.enabled)}>
                    {intg.enabled ? t('pages.integrations.disable') || 'Deaktivieren' : t('pages.integrations.enable') || 'Aktivieren'}
                  </button>
                  <button className="btn btn-sm btn-primary" onClick={() => runIntegration(intg.id)}>
                    {t('pages.integrations.runTest') || 'Test ausführen'}
                  </button>
                </div>
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
    </div>
  );
}
