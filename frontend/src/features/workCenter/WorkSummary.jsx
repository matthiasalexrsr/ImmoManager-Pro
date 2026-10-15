import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../../api';
import { formatDate, formatDateTime } from '../../utils/format';
import './workCenter.css';

const LABELS = { task: 'Offene Aufgaben', maintenance: 'Offene Instandhaltung', invoice: 'Offene Rechnungen',
  receivable: 'Offene Forderungen', document: 'Dokumenteneingang', dunning: 'Mahnvorgänge', contract: 'Fehlende Vertragsunterlagen',
  service_contract: 'Kündigungsfristen', meter: 'Zählerprüfungen', meter_reading: 'Fehlende Ablesungen im Abrechnungszeitraum', tenant_change: 'Offene Mieterwechsel' };
export default function WorkSummary({ query = '', revision = 0 }) {
  return <Summary key={`${query}:${revision}`} query={query} />;
}
function Summary({ query }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const request = new AbortController();
    setError(null);
    api.get(`/work-center/summary${query ? `?${query}` : ''}`, { signal: request.signal }).then(result => {
      if (!result?.counts || !result?.drilldowns) throw new Error('Die Quellenübersicht konnte nicht gelesen werden.');
      if (!request.signal.aborted) setData(result);
    }).catch(failure => { if (!request.signal.aborted) setError(failure.message); });
    return () => request.abort();
  }, [query, attempt]);
  return <section aria-label="Offene Vorgänge nach Quelle">
    <div className="work-shelf-heading"><h2>Offene Vorgänge nach Quelle</h2>{data?.as_of && <small>Stand: {String(data.as_of).length === 10 ? formatDate(data.as_of) : formatDateTime(data.as_of)}</small>}</div>
    {error && <p role="alert">{error} <button type="button" className="btn btn-sm btn-secondary" onClick={() => setAttempt(value => value + 1)}>Erneut laden</button></p>}
    {!data && !error && <p role="status">Quellenübersicht wird geladen…</p>}
    {data && <div className="work-summary-grid">{Object.entries(LABELS).filter(([kind]) => Number.isFinite(data.counts[kind])).map(([kind, label]) => {
      const href = data.drilldowns[kind]?.href;
      const content = <><span>{label}</span><strong>{data.counts[kind]}</strong><small>Gezählte Vorgänge ansehen</small></>;
      return href ? <Link className="work-summary-metric" key={kind} to={href} aria-label={`${label}: ${data.counts[kind]} – gezählte Vorgänge ansehen`}>{content}</Link> : <div className="work-summary-metric" key={kind}>{content}</div>;
    })}</div>}
  </section>;
}
