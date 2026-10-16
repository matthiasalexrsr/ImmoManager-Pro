import { useEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api } from '../api';
import { receiptCommand } from '../hooks/useNotificationInbox';
import { formatDate, formatMoney } from '../utils/format';

// Rendering the actual authorized source is the landing. The receipt is sent
// only after that source has mounted; failure/offline keeps a retryable command.
function SourceLanding({ data, identifier }) {
  const { source, notice } = data;
  const [error, setError] = useState(null);
  const [done, setDone] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const body = useRef(receiptCommand({ action: 'landed', base_revision: notice.revision,
    source_kind: source.kind, source_id: source.entity_id, source_revision: source.revision }));
  useEffect(() => {
    let live = true; const same = api.captureSession();
    api.post(`/notifications/${encodeURIComponent(identifier)}/receipt`, body.current).then(() => {
      same(); if (live) { setDone(true); setError(null); window.dispatchEvent(new Event('notification-receipt')); }
    }).catch(failure => { if (live) setError(failure.message); });
    return () => { live = false; };
  }, [identifier, attempt]);
  const labels = { description: 'Beschreibung', content: 'Inhalt', status: 'Status', due_date: 'Fällig am',
    start_date: 'Beginn', end_date: 'Ende', document_date: 'Dokumentdatum', amount_due: 'Forderungsbetrag',
    contract_number: 'Vertragsnummer', notes: 'Notizen', address: 'Adresse' };
  return <article className="page personal-inbox"><h1 className="page-title">{source.title}</h1>
    <p>{notice.content}</p>
    <dl>{Object.entries(labels).filter(([key]) => source.values[key] != null).map(([key, label]) => <div key={key}>
      <dt>{label}</dt><dd>{key.endsWith('_date') ? formatDate(source.values[key]) : key === 'amount_due' ? formatMoney(source.values[key], { currency: source.values.currency || 'EUR' }) : String(source.values[key])}</dd>
    </div>)}</dl>
    <Link className="btn btn-primary" to={source.href}>Vollständige Akte öffnen</Link>{' '}<Link to="/notifications">Zum Eingang</Link>
    {done && <p role="status">Persönlich gelesen und archiviert.</p>}
    {error && <div role="alert">Die Lesebestätigung wurde nicht bestätigt: {error} <button onClick={() => setAttempt(n => n + 1)}>Erneut bestätigen</button></div>}
  </article>;
}

export default function NotificationLanding() {
  const { id } = useParams();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let live = true; const same = api.captureSession(); setData(null); setError(null);
    api.get(`/notifications/${encodeURIComponent(id)}/source`).then(value => { same(); if (live) setData(value); })
      .catch(failure => { if (live) setError(failure.message); });
    return () => { live = false; };
  }, [id, attempt]);
  if (error) return <div className="page" role="alert">Quelle konnte nicht geöffnet werden: {error}. Der Hinweis bleibt im Eingang. <button onClick={() => setAttempt(n => n + 1)}>Erneut versuchen</button> <Link to="/notifications">Zum Eingang</Link></div>;
  return data ? <SourceLanding key={id} data={data} identifier={id} /> : <p role="status">Quelle wird geprüft …</p>;
}
