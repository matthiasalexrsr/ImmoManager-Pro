import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { CheckCircle2, CircleSlash } from 'lucide-react';
import { api } from '../../api';
import { aiReadingApi } from '../../features/aiReading/aiReadingApi';
import { SettingField } from './SettingsCatalogue';
import './catalogue.css';

const CONTEXT = { none: 'keine Angaben zur Immobilie', standard: 'Immobilie, Einheiten, Lieferanten und Zähler (ohne interne Nummern)',
  extended: 'Immobilie, Einheiten, Lieferanten, Zähler und die Namen der Mieter' };

/** Settings → KI-Verarbeitung: how reading documents works, what goes to the AI, the connections and every setting of it. */
export default function AiSettingsSection({ service = aiReadingApi }) {
  const [options, setOptions] = useState(null);
  const [items, setItems] = useState(null);
  const [error, setError] = useState(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let live = true;
    const same = api.captureSession();
    setError(null);
    Promise.all([service.options(), api.get('/auth/users/me/settings')]).then(([found, settings]) => {
      same();
      if (!live) return;
      if (!Array.isArray(settings?.items)) throw new Error('Die Einstellungsantwort ist unvollständig. Bitte erneut laden.');
      setOptions(found);
      setItems(settings.items.filter(item => item.group === 'KI-Verarbeitung'));
    }).catch(failure => { if (live) setError(failure.message || 'Die Einstellungen zur KI-Verarbeitung sind nicht erreichbar.'); });
    return () => { live = false; };
  }, [service, attempt]);

  if (error) return <section className="panel"><div className="panel-body"><p role="alert">{error}{' '}
    <button type="button" className="btn btn-secondary btn-sm" onClick={() => setAttempt(value => value + 1)}>Erneut laden</button></p></div></section>;
  if (!options || !items) return <p role="status" className="text-muted">Einstellungen zur KI-Verarbeitung werden geladen …</p>;
  const policy = options.policy || {};
  const ai = (options.readers || []).filter(reader => reader.ai);
  const personal = items.filter(item => item.scope === 'personal');
  const installation = items.filter(item => item.scope === 'global');
  const reload = () => setAttempt(value => value + 1);

  return <section className="settings-catalogue ai-settings" aria-labelledby="ai-settings-title">
    <h2 id="ai-settings-title">KI-Verarbeitung</h2>
    <div className="panel"><div className="panel-body settings-section">
      <h3>So werden Dokumente eingelesen</h3>
      <ul className="ai-settings-list">
        <li>An jeder Einlesestelle liest entweder das Programm selbst (lokale Regeln, nichts verlässt diesen Rechner) oder die KI Ihres
          eigenen, im <Link to="/assistant">Assistenten</Link> verbundenen Claude- oder ChatGPT-Kontos.</li>
        <li>Die KI bekommt die Aufgabe der jeweiligen Stelle (z. B. Rechnungseingang oder Kostenposition), den Text des Dokuments
          {policy.send_images ? `, bei Scans und Fotos bis zu ${policy.max_pages} Seitenbilder` : ' (keine Seitenbilder)'}, als Abgleich {CONTEXT[policy.context] || CONTEXT.standard},
          die Hausregeln der Stelle sowie Ihre Anweisung und das Gespräch.</li>
        <li>Jeder gelesene Wert kommt mit der Stelle im Dokument und einer Einschätzung, wie sicher er ist. Ungültige Werte verwirft das
          Programm. In der Maske ist jeder Wert markiert; je nach Einstellung bestätigen Sie ihn einzeln, bevor gespeichert wird.</li>
        <li>{policy.check_duplicates === false ? 'Die Suche nach vorhandenen Datensätzen ist ausgeschaltet.'
          : 'Vor dem Übernehmen sucht das Programm nach vorhandenen Datensätzen zum selben Dokument (gleiche Datei, gleicher Text, gleiche Rechnung) und fragt nach.'}</li>
        <li>Je Person höchstens {policy.calls_per_window || 40} Anfragen an die KI in {policy.window_minutes || 10} Minuten. Lesevorgänge und Gespräche
          werden nach {policy.keep_days || 30} Tagen gelöscht.</li>
      </ul>
    </div></div>

    <div className="panel"><div className="panel-body settings-section">
      <h3>Verbindungen</h3>
      <ul className="ai-settings-readers">
        {ai.map(reader => <li key={reader.id}>
          {reader.available ? <CheckCircle2 size={16} aria-hidden="true" className="text-success" /> : <CircleSlash size={16} aria-hidden="true" />}
          <strong>{reader.label}</strong> {reader.available ? 'verbunden' : 'nicht verbunden'}
        </li>)}
      </ul>
      {!options.ai_enabled && <p role="status">Die KI-Auswertung ist installationsweit ausgeschaltet; es lesen nur die lokalen Regeln.</p>}
      <p><Link to="/assistant">Konto im Assistenten verbinden oder trennen</Link></p>
    </div></div>

    <div className="panel"><div className="panel-body settings-section">
      <h3>Einlesestellen</h3>
      <div className="table-scroll"><table className="data-table">
        <caption className="sr-only">Wo Dokumente eingelesen werden</caption>
        <thead><tr><th>Stelle</th><th>Zu finden unter</th><th>KI</th><th>Für Sie</th></tr></thead>
        <tbody>{(options.surfaces || []).map(surface => <tr key={surface.id}>
          <th scope="row">{surface.label}<small className="td-sub">{surface.purpose}</small></th>
          <td>{surface.entry}</td>
          <td>{surface.ai_allowed ? (surface.needs_ai ? 'ja (nötig)' : 'ja') : 'aus'}</td>
          <td>{surface.may_use ? 'nutzbar' : 'nicht in Ihrer Rolle'}</td>
        </tr>)}</tbody>
      </table></div>
    </div></div>

    <div className="panel" role="note" aria-label="Datenschutz"><div className="panel-body settings-section">
      <h3>Datenschutz</h3>
      <p>Beim Einlesen mit Claude oder ChatGPT gehen die Inhalte des Dokuments an den Anbieter Ihres verbundenen Kontos (Anthropic bzw. OpenAI),
        auch personenbezogene Angaben von Mietern, wenn sie im Dokument stehen. Für den geschäftlichen Einsatz klären Sie bitte mit dem Anbieter
        die Auftragsverarbeitung und die Übermittlung in Drittländer (Art. 28 und Art. 44 ff. DSGVO) und nehmen das Einlesen in Ihr
        Verzeichnis der Verarbeitungstätigkeiten auf. Wer das nicht möchte, schaltet die KI-Auswertung unten aus oder nutzt die lokalen Regeln.</p>
      <p>Das Auditjournal vermerkt, wer wann ein Dokument gelesen, nachgefragt und Werte übernommen hat – ohne die Inhalte.</p>
    </div></div>

    <h3>Für mich</h3>
    <div className="setting-grid">{personal.map(item => <SettingField key={`${item.scope}:${item.key}`} item={item} onSaved={reload} />)}</div>
    <h3>Installationsweit</h3>
    {installation.length ? <div className="setting-grid">{installation.map(item => <SettingField key={`${item.scope}:${item.key}`} item={item} onSaved={reload} />)}</div>
      : <p className="text-muted">Die installationsweiten Vorgaben (KI an oder aus, Seitenbilder, Angaben zur Immobilie, Hausregeln je Stelle,
        Aufbewahrung) legt die Verwaltung fest.</p>}
  </section>;
}
