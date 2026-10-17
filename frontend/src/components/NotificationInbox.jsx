import NotificationArrival from './NotificationArrival';
import { useEffect, useRef, useState } from 'react';
import NotificationEmailPreview from './NotificationEmailPreview';
import { Link, useSearchParams } from 'react-router-dom';
import useNotificationInbox from '../hooks/useNotificationInbox';
import { formatDateTime } from '../utils/format';
import './notificationInbox.css';

export default function NotificationInbox({ compact = false }) {
  const [params] = useSearchParams();
  const [status, setStatus] = useState(params.get('status') || (params.has('severity') || params.has('focus_id') ? '' : 'unread'));
  const [severity, setSeverity] = useState(params.get('severity') || '');
  const [kind, setKind] = useState('');
  const [cursor, setCursor] = useState(null);
  const [history, setHistory] = useState([]);
  const [snapshot, setSnapshot] = useState(null);
  const [bulkConfirmation, setBulkConfirmation] = useState(null);
  const readAllRef = useRef(null);
  const cancelRef = useRef(null);
  const { page, error, busy, reload, mutate } = useNotificationInbox(status, cursor, compact ? 10 : 50, snapshot, compact ? '' : severity, compact ? '' : kind);
  useEffect(() => {
    if (bulkConfirmation) cancelRef.current?.focus();
  }, [bulkConfirmation]);

  const cancelBulk = () => {
    setBulkConfirmation(null);
    readAllRef.current?.focus();
  };
  const confirmBulk = () => {
    const proof = bulkConfirmation;
    if (!proof || busy || page?.snapshot !== proof.snapshot || page?.unread_count !== proof.count) return;
    setBulkConfirmation(null);
    // The exact preview that was confirmed determines the server command.
    // Changes made by other tabs are refused by the backend's snapshot fence.
    void mutate('all', { action: 'read_all', snapshot: proof.snapshot });
  };

  useEffect(() => {
    const reset = () => { setCursor(null); setHistory([]); setSnapshot(null); };
    window.addEventListener('notification-receipt', reset);
    return () => window.removeEventListener('notification-receipt', reset);
  }, []);
  return <section className="personal-inbox" aria-label="Persönliche Benachrichtigungen">
    {!compact && <><h2>Persönlicher Eingang</h2><label>Ansicht <select aria-label="Ansicht" value={status} onChange={e => { setStatus(e.target.value); setCursor(null); setHistory([]); setSnapshot(null); }}>
      <option value="unread">Ungelesen</option><option value="archived">Gelesen und archiviert</option><option value="">Gesamte Historie</option>
    </select></label>
      <label>Dringlichkeit <select aria-label="Dringlichkeit" value={severity} onChange={e => { setSeverity(e.target.value); setCursor(null); setHistory([]); setSnapshot(null); }}><option value="">Alle</option><option value="info">Information</option><option value="warning">Warnung</option><option value="error">Fehler</option><option value="critical">Kritisch</option></select></label>
      <label>Quelle <select aria-label="Quelle" value={kind} onChange={e => { setKind(e.target.value); setCursor(null); setHistory([]); setSnapshot(null); }}><option value="">Alle Quellen</option>
        {Object.entries({ task: 'Aufgaben', receivable: 'Forderungen', contract: 'Mietvertraege', property: 'Immobilien', tenant: 'Parteien', document: 'Dokumente', service_contract: 'Objektvertraege', billing_period: 'Abrechnungen' }).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </select></label></>}
    {error && <div role="alert">{error} <button onClick={() => { setCursor(null); setHistory([]); setSnapshot(null); reload(); }}>Neu laden</button></div>}
    {!page && !error && <p role="status">Hinweise werden geladen …</p>}
    {page && <>
      <p role="status">{page.unread_count} ungelesen · {page.total} in dieser Ansicht</p>
      {page.unread_count > 0 && <p>Bestätigungsumfang: alle {page.unread_count} aktuell berechtigten ungelesenen Hinweise aus der geladenen Vorschau, unabhängig von den Filtern. Bei Änderungen wird eine neue Vorschau verlangt.</p>}
      {page.unread_count > 0 && <button type="button" ref={readAllRef} className="btn btn-secondary"
        disabled={busy} aria-expanded={Boolean(bulkConfirmation)}
        onClick={() => setBulkConfirmation({ count: page.unread_count, snapshot: page.snapshot })}>
        Alle berechtigten Hinweise gelesen archivieren
      </button>}
      {bulkConfirmation && <div className="inbox-bulk-confirm" role="group" aria-label="Sammelbestätigung"
        onKeyDown={event => {
          if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); cancelBulk(); }
        }}>
        <strong>{bulkConfirmation.count === 1
          ? 'Diesen einen ungelesenen Hinweis wirklich gelesen archivieren?'
          : `Alle ${bulkConfirmation.count} ungelesenen Hinweise wirklich gelesen archivieren?`}</strong>
        <p>Diese Aktion betrifft alle aktuell berechtigten ungelesenen Hinweise, unabhängig von den eingestellten Filtern und der angezeigten Seite.</p>
        {(page?.snapshot !== bulkConfirmation.snapshot || page?.unread_count !== bulkConfirmation.count) &&
          <p role="alert">Die Vorschau hat sich geändert. Bitte abbrechen und den Eingang neu prüfen.</p>}
        <div className="inbox-bulk-actions">
          <button type="button" ref={cancelRef} className="btn btn-secondary" onClick={cancelBulk}>Abbrechen</button>
          <button type="button" className="btn btn-danger" onClick={confirmBulk}
            disabled={busy || page?.snapshot !== bulkConfirmation.snapshot || page?.unread_count !== bulkConfirmation.count}>
            {bulkConfirmation.count === 1 ? 'Einen Hinweis jetzt archivieren' : `${bulkConfirmation.count} Hinweise jetzt archivieren`}
          </button>
        </div>
      </div>}
      {page.items.length === 0 && <p>Keine Hinweise in dieser Ansicht.</p>}
      <NotificationArrival rows={page.items} />
      <ul className="personal-inbox-list">{page.items.map(n => <li key={n.id}>
        <strong>{n.target ? <Link to={n.open_href}>{n.title}</Link> : n.title}</strong>
        <p>{n.content}</p>
        <small>{n.email_eligible ? 'E-Mail-Kanal zugelassen · ' : 'E-Mail für diesen Hinweis nicht vorgesehen · '}{n.target ? `Quelle: ${n.target.title}` : n.target_error} · {formatDateTime(n.created_at)}</small>
        {!compact && n.email_eligible && n.target && <NotificationEmailPreview notice={n} />}
        {n.archived_at && <><p>Persönlich gelesen: {formatDateTime(n.read_at)}</p><button disabled={busy} onClick={() => mutate(n.id, { action: 'reopen', base_revision: n.revision })}>Wieder in den Eingang</button></>}
      </li>)}</ul>
      {history.length > 0 && <button onClick={() => { setCursor(history[history.length - 1]); setHistory(history.slice(0, -1)); }}>Zurück</button>}
      {page.next_cursor && <button onClick={() => { setSnapshot(page.snapshot); setHistory(previous => [...previous, cursor]); setCursor(page.next_cursor); }}>Weitere Hinweise</button>}
    </>}
    {compact && <Link to="/notifications">Vollständiger Eingang und Archiv</Link>}
  </section>;
}
