import { useEffect, useState } from 'react';
import { api } from '../api';
import { AlertIcon, MessageIcon, ContractIcon, DocumentIcon } from '../components/Icons';

const INTEGRATIONS = [
  {
    id: 'email',
    name: 'E-Mail API',
    description: 'E-Mails direkt an Mieter, Handwerker und Makler senden. Automatische Benachrichtigungen bei Vertragsänderungen und Wartungsanfragen.',
    icon: MessageIcon,
    features: ['E-Mail-Vorlagen für Standardkommunikation', 'Automatische Mieterhöhungsmitteilungen', 'Wartungsbestätigungen', 'Nebenkostenabrechnungsversand'],
  },
  {
    id: 'whatsapp',
    name: 'WhatsApp Business API',
    description: 'WhatsApp-Nachrichten an Kontakte senden. Schnelle Kommunikation mit Mietern und Dienstleistern.',
    icon: MessageIcon,
    features: ['Textnachrichten und Medien', 'Automatische Erinnerungen', 'Wartungsstatus-Updates', 'Besichtigungsterminbestätigungen'],
  },
  {
    id: 'contract-wizard',
    name: 'Mietvertrags-Assistent',
    description: 'Mietverträge direkt in der Anwendung erstellen. Vorlagen basierend auf deutschen Mietrecht-Standards.',
    icon: ContractIcon,
    features: ['Vorkonfigurierte Vertragsvorlagen', 'Automatische Klauselauswahl nach Wohnungstyp', 'Nebenkostenpauschale oder Vorauszahlung', 'Staffelmiete und Indexmiete', 'PDF-Export und digitale Signatur'],
  },
  {
    id: 'deutsche-post',
    name: 'Deutsche Post API',
    description: 'Physische Briefe direkt aus der Anwendung versenden. Einschreiben, Standardbriefe und Dokumente per Post.',
    icon: DocumentIcon,
    features: ['Standardbrief und Einschreiben', 'Automatische Adressformatierung', 'Sendungsverfolgung', 'Sammelversand für Nebenkostenabrechnungen'],
  },
];

export default function Integrations() {
  const [statusMap, setStatusMap] = useState({});
  const [messages, setMessages] = useState({});

  useEffect(() => {
    api.get('/integrations/status')
      .then((res) => {
        const mapped = {};
        (res.integrations || []).forEach((item) => { mapped[item.id] = item; });
        setStatusMap(mapped);
      })
      .catch((err) => console.warn('[Integrations] status:', err.message));
  }, []);

  const toggleIntegration = async (id, enabled) => {
    try {
      const res = await api.patch(`/integrations/${id}`, { enabled });
      setStatusMap(prev => ({ ...prev, [id]: { ...(prev[id] || {}), enabled: res.enabled } }));
    } catch (err) {
      console.warn('[Integrations] toggle:', err.message);
    }
  };

  const runIntegration = async (id) => {
    try {
      const payload = id === 'email'
        ? { recipient: 'demo@example.com', subject: 'ImmoManager Pro Test', body: 'Integrationstest erfolgreich.' }
        : { tenant_name: 'Max Mustermann', property_name: 'Musterstraße 1' };
      const res = await api.post(`/integrations/${id}/run`, { payload });
      setMessages(prev => ({ ...prev, [id]: res.message || 'Aktion ausgeführt' }));
    } catch (err) {
      setMessages(prev => ({ ...prev, [id]: `Fehler: ${err.message}` }));
    }
  };

  return (
    <div className="page">
      <h1 className="page-title">Integrationen</h1>
      <p className="text-muted" style={{ marginBottom: '1.5rem' }}>
        Integrationen konfigurieren, aktivieren und testen.
      </p>

      <div className="integrations-grid">
        {INTEGRATIONS.map((intg) => {
          const Ico = intg.icon;
          const status = statusMap[intg.id];
          const isEnabled = !!status?.enabled;
          return (
            <div key={intg.id} className="panel integration-card">
              <div className="panel-header" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <Ico size={20} />
                <span>{intg.name}</span>
                <span className={`badge ${isEnabled ? 'badge-green' : 'badge-planned'}`} style={{ marginLeft: 'auto' }}>
                  <AlertIcon size={12} /> {isEnabled ? 'Aktiv' : 'Inaktiv'}
                </span>
              </div>
              <div className="panel-body">
                <p style={{ marginBottom: '0.5rem' }}>{intg.description}</p>
                <p className="text-muted" style={{ marginBottom: '1rem', fontSize: '0.85rem' }}>
                  {status?.message || 'Status wird geladen...'}
                </p>
                <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem' }}>
                  <button className="btn btn-sm btn-secondary" onClick={() => toggleIntegration(intg.id, !isEnabled)}>
                    {isEnabled ? 'Deaktivieren' : 'Aktivieren'}
                  </button>
                  <button className="btn btn-sm btn-primary" onClick={() => runIntegration(intg.id)}>
                    Test ausführen
                  </button>
                </div>
                {messages[intg.id] && <div className="text-muted" style={{ marginBottom: '1rem' }}>{messages[intg.id]}</div>}
                <h4 style={{ fontSize: '0.85rem', marginBottom: '0.5rem' }}>Funktionen:</h4>
                <ul className="integration-features">
                  {intg.features.map((f, i) => (
                    <li key={i}>{f}</li>
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
