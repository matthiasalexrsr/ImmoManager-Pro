import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { useTranslation } from '../i18n';
import DataTable from '../components/DataTable';
import { formatDateTime } from '../utils/format';
import { changeValue, fieldLabel, kindLabel } from '../utils/changeDisplay';

const PAGE = 500;
// long values stay on one line in the list and show in full on hover
const short = value => <span className="cell-text" style={{ maxWidth: '14rem' }} title={value}>{value}</span>;

// Search, filters and the CSV export see what the table shows, so the words are set on the rows.
function shown(entry, t) {
  return {
    ...entry,
    kind: kindLabel(entry.entity_type),
    record: entry.entity_title || `${String(entry.entity_id).slice(0, 8)}… (nicht mehr vorhanden)`,
    field: fieldLabel(entry.field_name),
    before: changeValue(entry.field_name, entry.old_value, t),
    after: changeValue(entry.field_name, entry.new_value, t),
    author: entry.changed_by_name || (entry.changed_by ? 'Unbekanntes Konto' : 'System'),
  };
}

export default function History() {
  const { t } = useTranslation();
  const [history, setHistory] = useState([]);
  const [more, setMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    api.get(`/history?limit=${PAGE}`)
      .then(data => {
        if (cancelled) return;
        setHistory(data || []);
        setMore((data || []).length === PAGE);
      })
      .catch(e => {
        if (!cancelled) setError(e.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const loadOlder = async () => {
    setLoadingMore(true);
    try {
      const data = await api.get(`/history?skip=${history.length}&limit=${PAGE}`) || [];
      setHistory(current => [...current, ...data]);
      setMore(data.length === PAGE);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoadingMore(false);
    }
  };

  const COLUMNS = [
    { key: 'changed_at', label: 'Zeitpunkt', type: 'date', filterType: 'dateRange',
      render: (v, row) => <span className="cell-stack"><span>{formatDateTime(v)}</span><span className="td-sub">{row.author}</span></span> },
    { key: 'record', label: 'Datensatz', filterType: 'text',
      render: (v, row) => <span className="cell-stack">
        <span className="cell-text" style={{ maxWidth: '18rem' }} title={v}>{row.entity_href
          ? <Link to={row.entity_href} className="entity-link" onClick={e => e.stopPropagation()}>{v}</Link>
          : <span className="text-muted">{v}</span>}</span>
        <span className="td-sub">{row.kind}</span>
      </span> },
    { key: 'field', label: 'Feld', filterType: 'select' },
    { key: 'before', label: 'Vorher', render: short },
    { key: 'after', label: 'Nachher', render: short },
    { key: 'kind', label: 'Art', filterType: 'select', hidden: true },
    { key: 'author', label: 'Geändert von', filterType: 'select', hidden: true },
    { key: 'reason', label: 'Anlass', hidden: true },
  ];

  if (loading) return <div className="page-loading">{t('ui.table.loading')}</div>;
  if (error) return <div className="page"><div className="alert alert-error">{error}</div></div>;

  return (
    <div className="page">
      <DataTable
        title={t('navigation.secondary.history')}
        columns={COLUMNS}
        data={history.map(entry => shown(entry, t))}
      />
      {more && <div style={{ marginTop: 'var(--space-3)' }}>
        <button type="button" className="btn btn-sm btn-secondary" onClick={loadOlder} disabled={loadingMore}>
          {loadingMore ? t('ui.table.loading') : 'Ältere Änderungen laden'}
        </button>
      </div>}
    </div>
  );
}
