import { useState, useEffect } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';

export default function EscalationRules() {
  const { t } = useTranslation();
  const [rules, setRules] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [modal, setModal] = useState(null);
  const [deleteError, setDeleteError] = useState(null);
  const [runResult, setRunResult] = useState(null);
  const [running, setRunning] = useState(false);

  const loadData = () => {
    setLoading(true);
    api.get('/escalation/rules')
      .then(data => setRules(data || []))
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => { loadData(); }, []);

  const handleRun = async () => {
    setRunning(true);
    setRunResult(null);
    try {
      const result = await api.post('/escalation/run');
      setRunResult(result);
    } catch (err) {
      setRunResult({ error: err.message });
    } finally {
      setRunning(false);
    }
  };

  const COLUMNS = [
    { key: 'name', label: 'Name', filterType: 'text' },
    { key: 'entity_type', label: 'Entität', filterType: 'select' },
    { key: 'days_overdue', label: 'Tage überfällig', type: 'number' },
    { key: 'notification_severity', label: 'Schwere', filterType: 'select' },
    { key: 'is_active', label: 'Aktiv', render: v => v ? '✓' : '—' },
  ];

  const fields = [
    { key: 'name', label: 'Regelname', required: true },
    { key: 'entity_type', label: 'Entität', required: true, type: 'select', options: [
      { value: 'task', label: t('navigation.main.tasks') },
      { value: 'maintenance', label: t('navigation.main.maintenance') },
      { value: 'receivable', label: t('finance.receivables.openReceivables') },
    ]},
    { key: 'days_overdue', label: 'Tage überfällig', type: 'number', required: true },
    { key: 'notification_severity', label: 'Schwere', type: 'select', default: 'warning', options: [
      { value: 'info', label: 'Info' },
      { value: 'warning', label: 'Warnung' },
      { value: 'critical', label: 'Kritisch' },
    ]},
    { key: 'is_active', label: 'Aktiv', type: 'select', default: 'true', options: [
      { value: 'true', label: 'Ja' },
      { value: 'false', label: 'Nein' },
    ]},
  ];

  const handleSave = async (data) => {
    const payload = {
      ...data,
      is_active: data.is_active === 'true' || data.is_active === true,
      days_overdue: Number(data.days_overdue),
    };
    if (modal === 'create') {
      await api.post('/escalation/rules', payload);
    } else {
      await api.put(`/escalation/rules/${modal.id}`, payload);
    }
    loadData();
  };

  const handleDelete = async (row) => {
    if (!window.confirm(`${t('modals.confirmDelete.body')}`)) return;
    setDeleteError(null);
    try {
      await api.del(`/escalation/rules/${row.id}`);
      loadData();
    } catch (err) {
      setDeleteError(err.message || t('pages.deleteFailed'));
    }
  };

  if (loading) return <div className="page-loading">{t('ui.table.loading')}</div>;
  if (error) return <div className="page"><div className="alert alert-error">{error}</div></div>;

  return (
    <div className="page">
      {deleteError && (
        <div className="alert alert-error" style={{ marginBottom: '1rem' }}>
          {deleteError}
          <button onClick={() => setDeleteError(null)} style={{ marginLeft: '1rem', cursor: 'pointer' }}>✕</button>
        </div>
      )}
      <div style={{ marginBottom: '1rem', display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
        <button className="btn btn-primary" onClick={handleRun} disabled={running}>
          {running ? t('ui.table.loading') : 'Eskalation ausführen'}
        </button>
        {runResult && !runResult.error && (
          <span className="text-muted">
            {runResult.rules_checked} Regeln geprüft, {runResult.notifications_generated} Benachrichtigungen erzeugt
          </span>
        )}
        {runResult?.error && (
          <span style={{ color: 'var(--color-danger)' }}>{runResult.error}</span>
        )}
      </div>
      <DataTable
        title="Eskalationsregeln"
        columns={COLUMNS}
        data={rules}
        onAdd={() => setModal('create')}
        onEdit={row => setModal(row)}
        onDelete={handleDelete}
      />
      {modal && (
        <FormModal
          title={modal === 'create' ? 'Regel erstellen' : 'Regel bearbeiten'}
          fields={fields}
          initial={modal === 'create' ? null : modal}
          onSave={handleSave}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  );
}
