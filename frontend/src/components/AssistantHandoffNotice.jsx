import { Link } from 'react-router-dom';

export default function AssistantHandoffNotice({ handoff, onClose }) {
  if (!handoff.identifier) return null;
  const record = handoff.proposal?.record;
  return <section className="card" aria-label="Geprüfter Assistentenentwurf">
    {handoff.loading ? <p role="status">Geprüfter Entwurf wird geladen …</p>
      : handoff.error ? <p role="alert">{handoff.error} <button type="button" onClick={handoff.retry}>Erneut laden</button></p>
        : record ? <p role="status">Dieser Vorschlag ist bereits gespeichert. <Link to={record.href}>Eintrag öffnen: {record.title}</Link></p>
          : <p>Angaben aus dem Assistenten prüfen. Speichern legt den Eintrag einmal an und führt zur Unterhaltung zurück.</p>}
    <button type="button" className="btn btn-secondary btn-sm" onClick={onClose || handoff.clear}>Assistentenentwurf schließen</button>
  </section>;
}
