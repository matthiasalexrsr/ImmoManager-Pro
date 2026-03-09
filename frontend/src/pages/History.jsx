import { useState, useEffect } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import DataTable from '../components/DataTable';

export default function History() {
  const { t } = useTranslation();
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    setLoading(true);
    api.get('/history?limit=500')
      .then(data => setHistory(data || []))
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const COLUMNS = [
    { key: 'changed_at', label: t('properties.list.status'), type: 'date', filterType: 'dateRange',
      render: v => v ? new Date(v).toLocaleString('de-DE') : '—' },
    { key: 'action', label: 'Aktion', filterType: 'select' },
    { key: 'entity_type', label: 'Entität', filterType: 'select' },
    { key: 'entity_id', label: 'ID', render: v => v ? String(v).slice(0, 8) + '…' : '—' },
    { key: 'username', label: t('pages.login.username'), filterType: 'text' },
    { key: 'field_name', label: 'Feld', filterType: 'text' },
    { key: 'old_value', label: 'Alt', render: v => v != null ? String(v).slice(0, 50) : '—' },
    { key: 'new_value', label: 'Neu', render: v => v != null ? String(v).slice(0, 50) : '—' },
  ];

  if (loading) return <div className="page-loading">{t('ui.table.loading')}</div>;
  if (error) return <div className="page"><div className="alert alert-error">{error}</div></div>;

  return (
    <div className="page">
      <DataTable
        title={t('navigation.secondary.history')}
        columns={COLUMNS}
        data={history}
      />
    </div>
  );
}
