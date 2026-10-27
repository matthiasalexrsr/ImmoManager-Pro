import { Link } from 'react-router-dom';
import { useState } from 'react';
import { CircleAlert, CheckCheck } from 'lucide-react';
import { contextHref } from './assistantLinks';

export default function AssistantFindings({ findings = [], checks, run, disabled, canTask, onPrepare, onDiscuss }) {
  const [showAll, setShowAll] = useState(false);
  if (!findings.length) return null;
  const stale = run?.verification_status === 'stale';
  const visible = showAll ? findings : findings.slice(0, 3);
  return <section className="assistant-findings" aria-label="Belegte Prüfhinweise">
    <div className="assistant-findings-heading"><CircleAlert size={18} aria-hidden="true" /><strong>{findings.length} {findings.length === 1 ? 'Prüfhinweis' : 'Prüfhinweise'}</strong>{checks?.as_of && <small>Prüftag {checks.as_of}</small>}</div>
    <p className="assistant-findings-scope">Hinweise aus lokalen Regeln; Original und Bearbeitungsstand prüfen.{checks?.scope === 'explicit_selection' && ' Untersucht wurden nur die ausgewählten Akten.'}{stale && ' Quellen inzwischen geändert: zuerst erneut prüfen.'}</p>
    <ul>{visible.map((finding, index) => {
      const evidence = finding.evidence || []; const existingTask = evidence.some(source => source.kind === 'task');
      const prepared = run?.finding_proposals?.[finding.id];
      return <li key={finding.id || `${finding.code}:${index}`} className={finding.severity === 'error' ? 'error' : ''}>
        <p>{finding.message}</p>{finding.next_step && <small>{finding.next_step}</small>}
        <div className="assistant-sources">{evidence.map(source => contextHref(source) ? <Link key={`${source.kind}:${source.id}`} to={contextHref(source)}>{source.title || 'Originalakte öffnen'}</Link> : null)}</div>
        <div className="assistant-inline-actions">{onDiscuss && <button type="button" className="btn btn-sm btn-secondary" disabled={disabled || stale} onClick={() => onDiscuss(finding)}>Genauer untersuchen</button>}
          {canTask && onPrepare && !existingTask && !prepared && <button type="button" className="btn btn-sm btn-secondary" disabled={disabled || stale || run?.state !== 'completed'} onClick={() => onPrepare(finding)}>Klärungsaufgabe vorbereiten</button>}
          {prepared && <span className="assistant-finding-prepared"><CheckCheck size={14} aria-hidden="true" /> Im Arbeitskorb vorbereitet</span>}
        </div>
      </li>;
    })}</ul>
    {findings.length > 3 && <button type="button" className="btn btn-sm btn-secondary" aria-expanded={showAll} onClick={() => setShowAll(value => !value)}>{showAll ? 'Weniger Hinweise anzeigen' : `Alle ${findings.length} Hinweise anzeigen`}</button>}
  </section>;
}
