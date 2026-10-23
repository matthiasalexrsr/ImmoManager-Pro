import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth, useCanWrite } from '../contexts/AuthContext';
import './SetupChecklist.css';

// The order in which a holding is entered: each step needs the one before.
const STEPS = [
  { key: 'portfolios', label: 'Portfolio anlegen', detail: 'Der Bestand, zu dem Immobilien und Konten gehören.', to: '/portfolios?neu=1' },
  { key: 'properties', label: 'Immobilie anlegen', detail: 'Adresse und Eckdaten des Objekts.', to: '/properties?neu=1' },
  { key: 'units', label: 'Einheiten anlegen', detail: 'Wohnungen, Gewerbe, Stellplätze mit Fläche und Miete.', to: '/units?neu=1' },
  { key: 'accounts', label: 'Bankkonto anlegen', detail: 'Auf dieses Konto werden Mieten und Kosten gebucht.', to: '/accounts?neu=1' },
  { key: 'contracts', label: 'Mietverträge erfassen', detail: 'Mieter und Vertrag je vermieteter Einheit. Laufende Verträge mit „Mietkonto hier geführt ab“ und Saldo, damit keine alten Monate als offen gelten.', to: '/contracts?neu=1' },
];

const storageKey = user => `immo.setup.dismissed.${user?.id || user?.username || 'local'}`;
const readDismissed = user => { try { return localStorage.getItem(storageKey(user)) === '1'; } catch { return false; } };

/** "Erste Schritte" for a new installation: what is entered, what is next, one click to it.
 * Shown to roles that may enter the holding until every step is done or it is put away. */
export default function SetupChecklist({ stats, ready }) {
  const auth = useAuth();
  const canEnter = useCanWrite('/properties');
  const [dismissed, setDismissed] = useState(() => readDismissed(auth?.user));
  if (!ready || !canEnter || dismissed) return null;
  const done = STEPS.map(step => Number(stats[step.key] || 0) > 0);
  if (done.every(Boolean)) return null;
  const next = done.indexOf(false);
  const dismiss = () => {
    try { localStorage.setItem(storageKey(auth?.user), '1'); } catch { /* the card simply returns next time */ }
    setDismissed(true);
  };
  return (
    <section className="dashboard-card setup-checklist" aria-labelledby="setup-checklist-title">
      <div className="setup-checklist-head">
        <div>
          <p className="setup-checklist-eyebrow">Einrichtung · {done.filter(Boolean).length} von {STEPS.length} erledigt</p>
          <h2 id="setup-checklist-title">Erste Schritte</h2>
        </div>
        <button type="button" className="btn btn-ghost btn-sm" onClick={dismiss}>Ausblenden</button>
      </div>
      <ol className="setup-checklist-steps">
        {STEPS.map((step, index) => (
          <li key={step.key} className={done[index] ? 'is-done' : index === next ? 'is-next' : undefined}>
            <span className="setup-checklist-mark" aria-hidden="true">{done[index] ? '✓' : index + 1}</span>
            <span className="setup-checklist-text">
              <strong>{step.label}</strong>
              <small>{step.detail}</small>
            </span>
            {done[index]
              ? <span className="setup-checklist-state">erledigt</span>
              : <Link className={`btn btn-sm ${index === next ? 'btn-primary' : 'btn-secondary'}`} to={step.to}>{step.label}</Link>}
          </li>
        ))}
      </ol>
      <p className="setup-checklist-note">
        Ob und wann automatische Sicherungen laufen, sehen Sie unter{' '}
        <Link to="/settings?section=system">Einstellungen → System</Link>.
        Prüfen Sie dort Zeitplan, letzte erfolgreiche Sicherung und Wiederherstellungsprobe.
      </p>
    </section>
  );
}
