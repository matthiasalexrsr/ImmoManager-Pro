import { Link } from 'react-router-dom';
import { contextHref } from './assistantLinks';

const steps = { immo_search: 'Akten gesucht', immo_read: 'Originalakte gelesen', immo_related: 'Verknüpfte Vorgänge geprüft', immo_timeline: 'Chronik geprüft', immo_report: 'Lokale Auswertung berechnet', immo_document: 'Dokumentbeleg gelesen', immo_investigate: 'Auffälligkeiten geprüft' };

export default function AssistantActivity({ run }) {
  const activity = run?.activity || []; const omissions = [...new Set([...(run?.omissions || []), ...(run?.events || []).filter(event => event.message && event.message !== 'Auftrag gestartet.').map(event => event.message)])];
  if (!activity.length && !omissions.length && !run?.tool_budget?.exhausted) return null;
  const last = activity.at(-1);
  return <div>{run?.state === 'running' && last && <p className="assistant-research-status" role="status">{steps[last.tool] || 'Recherche'}{last.status === 'failed' ? ' · Rückfrage oder anderer Prüfweg erforderlich' : ` · ${activity.filter(item => item.status === 'completed').length} Arbeitsschritte abgeschlossen`}</p>}
  <details className="assistant-activity"><summary>Arbeitsprotokoll{activity.length ? ` · ${activity.length} ${activity.length === 1 ? 'Schritt' : 'Schritte'}` : ''}{omissions.length ? ` · ${omissions.length} ${omissions.length === 1 ? 'Hinweis' : 'Hinweise'}` : ''}</summary>
    {activity.length > 0 && <ol>{activity.map(item => <li key={item.id || item.sequence}><strong>{item.summary || 'Anwendungsschritt'}</strong><span>{item.status === 'failed' ? 'Konnte nicht abgeschlossen werden' : 'Abgeschlossen'}</span>{item.error?.message && <p role="status">{item.error.message}</p>}{item.coverage && <p>{item.coverage.returned ?? 0} Ergebnisse{item.coverage.has_more ? ' · Weitere Ergebnisse vorhanden' : ''}{item.coverage.truncated ? ' · Nur ein Auszug wurde verarbeitet' : ''}</p>}{item.sources?.length > 0 && <div className="assistant-sources">{item.sources.map(source => contextHref(source) ? <Link key={`${source.kind}:${source.id}`} to={contextHref(source)}>{source.title || 'Quelle öffnen'}</Link> : null)}</div>}<details><summary>Nachweisdetails</summary><small>{item.tool} · {item.at}</small>{(item.sources || []).map(source => <p key={`${source.kind}:${source.id}`}>{source.title} · Stand {source.revision}{source.sha256 ? ` · SHA-256 ${source.sha256}` : ''}</p>)}</details></li>)}</ol>}
    {omissions.length > 0 && <div className="assistant-coverage"><strong>Verarbeitung und fehlende Grundlagen</strong>{omissions.map((item, index) => <p key={index}>{item}</p>)}</div>}
    {run?.tool_budget?.exhausted && <p role="status">Das Arbeitsbudget dieses Auftrags ist ausgeschöpft. Noch offene Arbeit kann mit einer Folgefrage fortgesetzt werden. Bisherige Ergebnisse und Quellen bleiben erhalten.</p>}
  </details></div>;
}
