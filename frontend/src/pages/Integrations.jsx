import { AlertIcon, MessageIcon, ContractIcon, DocumentIcon } from '../components/Icons';
import { useTranslation } from '../i18n';

const INTEGRATIONS = [
  {
    id: 'email',
    name: 'E-Mail API',
    description: 'E-Mails direkt an Mieter, Handwerker und Makler senden. Automatische Benachrichtigungen bei Vertragsänderungen und Wartungsanfragen.',
    icon: MessageIcon,
    status: 'planned',
    features: [
      'E-Mail-Vorlagen für Standardkommunikation',
      'Automatische Mieterhöhungsmitteilungen',
      'Wartungsbestätigungen',
      'Nebenkostenabrechnungsversand',
    ],
  },
  {
    id: 'whatsapp',
    name: 'WhatsApp Business API',
    description: 'WhatsApp-Nachrichten an Kontakte senden. Schnelle Kommunikation mit Mietern und Dienstleistern.',
    icon: MessageIcon,
    status: 'planned',
    features: [
      'Textnachrichten und Medien',
      'Automatische Erinnerungen',
      'Wartungsstatus-Updates',
      'Besichtigungsterminbestätigungen',
    ],
  },
  {
    id: 'contract-wizard',
    name: 'Mietvertrags-Assistent',
    description: 'Mietverträge direkt in der Anwendung erstellen. Vorlagen basierend auf deutschen Mietrecht-Standards.',
    icon: ContractIcon,
    status: 'planned',
    features: [
      'Vorkonfigurierte Vertragsvorlagen',
      'Automatische Klauselauswahl nach Wohnungstyp',
      'Nebenkostenpauschale oder Vorauszahlung',
      'Staffelmiete und Indexmiete',
      'PDF-Export und digitale Signatur',
    ],
  },
  {
    id: 'deutsche-post',
    name: 'Deutsche Post API',
    description: 'Physische Briefe direkt aus der Anwendung versenden. Einschreiben, Standardbriefe und Dokumente per Post.',
    icon: DocumentIcon,
    status: 'planned',
    features: [
      'Standardbrief und Einschreiben',
      'Automatische Adressformatierung',
      'Sendungsverfolgung',
      'Sammelversand für Nebenkostenabrechnungen',
    ],
  },
];

export default function Integrations() {
  const { t } = useTranslation();
  return (
    <div className="page">
      <h1 className="page-title">{t('pages.integrations.title')}</h1>
      <p className="text-muted" style={{ marginBottom: '1.5rem' }}>
        {t('pages.integrations.subtitle')}
      </p>

      <div className="integrations-grid">
        {INTEGRATIONS.map(intg => {
          const Ico = intg.icon;
          return (
            <div key={intg.id} className="panel integration-card">
              <div className="panel-header" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <Ico size={20} />
                <span>{intg.name}</span>
                <span className="badge badge-planned" style={{ marginLeft: 'auto' }}>
                  <AlertIcon size={12} /> {t('pages.integrations.planned')}
                </span>
              </div>
              <div className="panel-body">
                <p style={{ marginBottom: '1rem' }}>{intg.description}</p>
                <h4 style={{ fontSize: '0.85rem', marginBottom: '0.5rem' }}>{t('pages.integrations.plannedFeatures')}</h4>
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
