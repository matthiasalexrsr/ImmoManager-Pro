import { Fragment, useEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api } from '../api';
import { receiptCommand } from '../hooks/useNotificationInbox';
import { formatDate, formatMoney } from '../utils/format';
import StatusBadge from '../components/StatusBadge';

// Rendering the actual authorized source is the landing. The receipt is sent
// only after that source has mounted; failure/offline keeps a retryable command.
function SourceLanding({ data, identifier, onReload }) {
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
    }).catch(failure => { if (live) setError({ message: failure.message, conflict: (failure.statusCode || failure.status) === 409 }); });
    return () => { live = false; };
  }, [identifier, attempt]);
  const labels = { description: 'Beschreibung', content: 'Inhalt', status: 'Status', due_date: 'Fällig am',
    start_date: 'Beginn', end_date: 'Ende', document_date: 'Dokumentdatum', amount_due: 'Forderungsbetrag',
    contract_number: 'Vertragsnummer', notes: 'Notizen', address: 'Adresse' };
  const shown = (key, value) => key === 'status' ? <StatusBadge status={value} />
    : key.endsWith('_date') ? formatDate(value)
      : key === 'amount_due' ? formatMoney(value, { currency: source.values.currency || 'EUR' }) : String(value);
  return <article className="page personal-inbox">
    <div className="page-header"><h1 className="page-title">{source.title}</h1></div>
    <section className="card"><div className="card-body">
      <p>{notice.content}</p>
      <dl className="overview-dl">{Object.entries(labels).filter(([key]) => source.values[key] != null).map(([key, label]) => <Fragment key={key}>
        <dt>{label}</dt><dd>{shown(key, source.values[key])}</dd>
      </Fragment>)}</dl>
      <div className="notification-landing-actions">
        <Link className="btn btn-primary" to={source.href}>Vollständige Akte öffnen</Link>
        <Link className="btn btn-secondary" to="/notifications">Zum Eingang</Link>
      </div>
    </div></section>
    {done && <p role="status" className="text-muted">Persönlich gelesen und archiviert.</p>}
    {error && <div className="alert alert-error" role="alert">Die Lesebestätigung wurde nicht bestätigt: {error.message}{' '}
      {error.conflict ? <button type="button" className="btn btn-sm btn-secondary" onClick={onReload}>Aktuelle Quelle laden</button>
        : <button type="button" className="btn btn-sm btn-secondary" onClick={() => setAttempt(n => n + 1)}>Erneut bestätigen</button>}</div>}
  </article>;
}

export default function NotificationLanding() {
  const { id } = useParams();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let live = true; const same = api.captureSession(); setData(null); setError(null);
    api.get(`/notifications/${encodeURIComponent(id)}/source`).then(value => { same(); if (live) setData({ identifier: id, value }); })
      .catch(failure => { if (live) setError(failure.message); });
    return () => { live = false; };
  }, [id, attempt]);
  if (error) return <div className="page"><div className="alert alert-error" role="alert">Quelle konnte nicht geöffnet werden: {error}. Der Hinweis bleibt im Eingang.{' '}
    <button type="button" className="btn btn-sm btn-secondary" onClick={() => setAttempt(n => n + 1)}>Erneut versuchen</button>{' '}
    <Link to="/notifications">Zum Eingang</Link></div></div>;
  return data?.identifier === id ? <SourceLanding key={`${id}:${attempt}`} data={data.value} identifier={id} onReload={() => { setData(null); setAttempt(n => n + 1); }} /> : <div className="page-loading" role="status">Quelle wird geprüft …</div>;
}
