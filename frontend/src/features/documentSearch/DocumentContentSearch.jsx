import { useEffect, useId, useRef, useState } from 'react';
import { Search } from 'lucide-react';
import { formatDate } from '../../utils/format';
import { documentTypeLabel } from '../../utils/documentType';
import { contentSearchService } from './contentSearchApi';
import './documentContentSearch.css';

function Highlight({ text, needle }) {
  if (!needle) return text;
  const parts = [];
  const lower = text.toLowerCase();
  let start = 0;
  let index = lower.indexOf(needle);
  while (index >= 0) {
    parts.push(text.slice(start, index), <mark key={index}>{text.slice(index, index + needle.length)}</mark>);
    start = index + needle.length;
    index = lower.indexOf(needle, start);
  }
  parts.push(text.slice(start));
  return parts;
}

/** Search in the text of documents (PDF text layer, office files, recognized scans). */
export default function DocumentContentSearch(props) {
  return <ScopedContentSearch key={JSON.stringify(props.scope || {})} {...props} />;
}

function ScopedContentSearch({ onOpen, places = {}, canWrite = false, service = contentSearchService, scope = {} }) {
  const id = useId();
  const [query, setQuery] = useState('');
  const [result, setResult] = useState(null);
  const [status, setStatus] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const request = useRef(null);
  const scopeKey = JSON.stringify(scope);

  useEffect(() => {
    const controller = new AbortController();
    service.status({ signal: controller.signal, scope: JSON.parse(scopeKey) }).then(value => {
      if (!controller.signal.aborted) setStatus(value);
    }).catch(() => {});
    return () => controller.abort();
  }, [service, scopeKey]);
  useEffect(() => () => request.current?.abort(), []);

  const run = async (event, more = false) => {
    event?.preventDefault();
    const needle = more ? result?.query : query.trim();
    request.current?.abort();
    if (!needle || needle.length < 2) { request.current = null; setBusy(false); setResult(null); setError('Bitte mindestens zwei Zeichen eingeben.'); return; }
    const controller = new AbortController();
    request.current = controller;
    setBusy(true); setError('');
    try {
      const found = await service.search(needle, { signal: controller.signal, scope, skip: more ? result.next_skip : 0 });
      if (controller.signal.aborted) return;
      if (!Array.isArray(found.items)) throw new Error('Die Suchergebnisse konnten nicht vollständig gelesen werden.');
      const existing = new Set(more ? result.items.map(item => item.id) : []);
      const added = found.items.filter(item => !existing.has(item.id));
      if (more && found.items.length && !added.length) throw new Error('Die Trefferliste hat sich geändert. Bitte die Suche erneut starten.');
      if (found.has_more && (!added.length || !Number.isInteger(found.next_skip) || found.next_skip <= (more ? result.next_skip : 0))) {
        throw new Error('Die nächste Ergebnisseite konnte nicht bestimmt werden. Bitte die Suche erneut starten.');
      }
      setResult({ ...found, items: more ? [...result.items, ...added] : added, query: needle, needle: needle.toLowerCase() });
      if (found.index) setStatus(found.index);
    } catch (problem) { if (!controller.signal.aborted) setError(problem.message || 'Die Suche ist fehlgeschlagen.'); }
    finally { if (request.current === controller) { request.current = null; setBusy(false); } }
  };

  const refresh = async () => {
    request.current?.abort();
    const controller = new AbortController(); request.current = controller;
    setBusy(true); setError('');
    try {
      const updated = await service.refresh({ signal: controller.signal, scope });
      if (!controller.signal.aborted) setStatus(updated);
    } catch (problem) { if (!controller.signal.aborted) setError(problem.message || 'Die Indexierung konnte nicht gestartet werden.'); }
    finally { if (request.current === controller) { request.current = null; setBusy(false); } }
  };

  const pending = status ? Math.max(0, status.documents - status.indexed) : 0;
  return (
    <section className="document-content-search" aria-label="Volltextsuche in Dokumenten">
      <form className="document-content-search-form" onSubmit={run} role="search">
        <label htmlFor={`${id}-q`}>Im Dokumentinhalt suchen</label>
        <div className="document-content-search-row">
          <input id={`${id}-q`} type="search" value={query} placeholder="z. B. Rauchwarnmelder, Zählernummer, IBAN"
            onChange={event => setQuery(event.target.value)} aria-describedby={`${id}-status`} />
          <button type="submit" className="btn btn-primary" disabled={busy}><Search size={16} aria-hidden="true" /> {busy ? 'Sucht …' : 'Suchen'}</button>
        </div>
        <small id={`${id}-status`} className="document-content-search-status">
          {status ? <>{status.indexed} von {status.documents} Dokumenten im Inhalt durchsuchbar{status.unreadable ? `, ${status.unreadable} ohne lesbaren Text (z. B. Fotos ohne Texterkennung)` : ''}.
            {pending > 0 && <> {pending} werden noch gelesen.{canWrite && <> <button type="button" className="btn btn-sm btn-secondary" disabled={busy} onClick={refresh}>Jetzt lesen</button></>}</>}</> : 'Durchsucht den Text von PDFs, Office- und Textdateien sowie erkannte Scans.'}
        </small>
      </form>
      {error && <p className="document-content-search-error" role="alert">{error}</p>}
      {result && <div className="document-content-search-results" aria-live="polite">
        <p className="document-content-search-count">{result.total === 0 ? `Kein Dokument enthält „${result.query}“.`
          : `${result.total} ${result.total === 1 ? 'Dokument enthält' : 'Dokumente enthalten'} „${result.query}“${result.total > result.items.length ? ` – ${result.items.length} werden gezeigt` : ''}.`}</p>
        <ul>{result.items.map(item => <li key={item.id}>
          <button type="button" className="document-content-search-title" onClick={() => onOpen?.(item)} disabled={!item.file_url}>{item.title}</button>
          <span className="document-content-search-meta">{[documentTypeLabel(item.document_type), places[item.property_id], item.document_date && formatDate(item.document_date)].filter(Boolean).join(' · ')}</span>
          <p className="document-content-search-snippet"><Highlight text={item.snippet} needle={result.needle} /></p>
        </li>)}</ul>
        {result.has_more && <button type="button" className="btn btn-secondary" disabled={busy} onClick={event => run(event, true)}>Weitere Suchergebnisse laden</button>}
      </div>}
    </section>
  );
}
