import { useState, useEffect } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api } from '../api';
import { useTranslation } from '../i18n';
import DataTable from '../components/DataTable';
import { formatDateTime } from '../utils/format';
import { entityHref } from '../utils/entityLinks';
import { changeValue, fieldLabel, kindLabel } from '../utils/changeDisplay';
import { safeInternalHref } from '../utils/internalLinks';

const PAGE_SIZE = 100;
const ENTITY_KINDS = { maintenance_case: 'maintenance', service_contract: 'serviceContract' };

function fullValue(value) {
  if (value == null) return '—';
  const text = String(value);
  if (text.length <= 80) return text;
  return <div>
    <span>{text.slice(0, 80)}…</span>
    <details><summary>Vollständiger Wert ({text.length} Zeichen)</summary>
      <pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', maxWidth: '40rem' }}>{text}</pre>
    </details>
  </div>;
}

function shown(entry, t) {
  const hasMetadata = Object.prototype.hasOwnProperty.call(entry, 'entity_title');
  return { ...entry, kind: kindLabel(entry.entity_type),
    record: entry.entity_title || `${entry.entity_id || 'Unbekannter Datensatz'}${hasMetadata ? ' (nicht verfügbar)' : ''}`,
    record_href: safeInternalHref(entry.entity_href) || (!hasMetadata ? entityHref(ENTITY_KINDS[entry.entity_type] || entry.entity_type, entry.entity_id) : null),
    field: fieldLabel(entry.field_name), before: changeValue(entry.field_name, entry.old_value, t),
    after: changeValue(entry.field_name, entry.new_value, t),
    author: entry.changed_by_name || (entry.changed_by ? 'Unbekanntes Konto' : 'System'),
  };
}

export default function History() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const entityType = params.get('entity_type') || '';
  const entityId = params.get('entity_id') || '';
  const cursor = params.get('cursor') || '';
  const requestKey = JSON.stringify([entityType, entityId, cursor]);
  const [page, setPage] = useState(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const request = new AbortController();
    const query = new URLSearchParams({ limit: String(PAGE_SIZE) });
    if (entityType) query.set('entity_type', entityType);
    if (entityId) query.set('entity_id', entityId);
    if (cursor) query.set('cursor', cursor);
    setPage({ key: requestKey, loading: true });
    api.get(`/history/page?${query}`, { signal: request.signal })
      .then(data => {
        if (!data || !Array.isArray(data.items) || !(data.next_cursor === null || typeof data.next_cursor === 'string')) {
          throw new Error('Die Änderungsseite ist unvollständig. Bitte erneut laden.');
        }
        if (!request.signal.aborted) setPage({ key: requestKey, ...data });
      })
      .catch(e => {
        if (!request.signal.aborted) setPage({ key: requestKey, error: e.message || 'Die Änderungen konnten nicht geladen werden.' });
      });
    return () => request.abort();
  }, [entityType, entityId, cursor, requestKey, attempt]);

  const current = page?.key === requestKey ? page : null;
  const loading = !current || current.loading;
  const navigatePage = nextCursor => setParams(previous => {
    const next = new URLSearchParams(previous);
    if (nextCursor) next.set('cursor', nextCursor); else next.delete('cursor');
    return next;
  });
  const applyFilters = event => {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    const next = new URLSearchParams();
    for (const key of ['entity_type', 'entity_id']) {
      const value = String(values.get(key) || '').trim();
      if (value) next.set(key, value);
    }
    setParams(next);
  };

  const COLUMNS = [
    { key: 'changed_at', label: 'Zeitpunkt', type: 'date',
      render: v => formatDateTime(v) },
    { key: 'record', label: 'Datensatz', render: (value, row) => <span className="cell-stack">
      <span>{row.record_href ? <Link to={row.record_href} className="entity-link" title={`Datensatz ${row.entity_id} öffnen`}>{value}</Link> : value}</span>
      <span className="td-sub">{row.kind}</span>
    </span>, wrap: true },
    { key: 'field', label: 'Feld' },
    { key: 'before', label: 'Vorher', render: fullValue, wrap: true },
    { key: 'after', label: 'Nachher', render: fullValue, wrap: true },
    { key: 'author', label: 'Geändert von' },
    { key: 'kind', label: 'Art', hidden: true },
    { key: 'reason', label: 'Grund', render: fullValue, wrap: true },
  ];

  return (
    <div className="page">
      <form key={JSON.stringify([entityType, entityId])} onSubmit={applyFilters} className="toolbar">
        <label>Entität <input name="entity_type" defaultValue={entityType} placeholder="z. B. contract" /></label>
        <label>Datensatz-ID <input name="entity_id" defaultValue={entityId} /></label>
        <button type="submit" className="btn btn-secondary">Historie filtern</button>
        {(entityType || entityId) && <button type="button" className="btn btn-ghost" onClick={() => setParams({})}>Filter zurücksetzen</button>}
      </form>
      <nav aria-label="Änderungshistorie durchblättern" className="toolbar">
        <button type="button" className="btn btn-secondary" disabled={loading}
          onClick={() => cursor ? navigatePage(null) : setAttempt(value => value + 1)}>Neueste Änderungen</button>
        <button type="button" className="btn btn-secondary" disabled={loading || Boolean(current?.error) || !current?.next_cursor}
          onClick={() => navigatePage(current.next_cursor)}>Ältere Änderungen</button>
      </nav>
      {loading ? <p role="status">{t('ui.table.loading') || 'Änderungen werden geladen …'}</p>
        : current.error ? <div className="alert alert-error" role="alert">{current.error}
          <button type="button" className="btn btn-secondary" onClick={() => setAttempt(value => value + 1)}>Erneut laden</button>
        </div> : <>
      <p role="status">{current.items.length} Änderungen auf dieser Seite. {current.next_cursor ? 'Weitere ältere Änderungen sind verfügbar.' : 'Keine weiteren älteren Änderungen.'}
        {' '}Der CSV-Export enthält ausschließlich diese Seite.</p>
      <DataTable serverPaged inheritRouteFocus={false} exportLabel="CSV – aktuelle Seite"
        title={t('navigation.secondary.history')}
        columns={COLUMNS}
        data={current.items.map(entry => shown(entry, t))}
      />
      </>}
    </div>
  );
}
