import { revisionOptions } from '../editRevision';
import { useState, useEffect } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import { useConfirm } from '../components/ConfirmDialog';
import OperationalTickPanel from '../components/OperationalTickPanel';
import useWriteAccess from '../hooks/useWriteAccess';

export default function EscalationRules() {
  const { t } = useTranslation();
  const { canWrite, isAllowed, requireWrite } = useWriteAccess('/escalation', () => setModal(null));
  const confirm = useConfirm();
  const [rules, setRules] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [modal, setModal] = useState(null);
  const [deleteError, setDeleteError] = useState(null);
  const [runResult, setRunResult] = useState(null);
  const [running, setRunning] = useState(false);

  const loadData = () => {
    setLoading(true); setError(null);
    api.getAll('/escalation/rules')
      .then(data => setRules(data || []))
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => { loadData(); }, []);

  const handleRun = async () => {
    if (!isAllowed()) return;
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
      { value: 'rent_charge', label: t('pages.rentCharges.title') },
    ]},
    { key: 'condition_field', label: t('operational.deadlineField'), type: 'select', required: true, default: 'due_date', options: [{ value: 'due_date', label: t('operational.dueDate') }, { value: 'appointment_at', label: t('operational.appointment') }] },
    { key: 'action', type: 'hidden', default: 'notify' },
    { key: 'target_role', label: t('operational.targetRole'), type: 'select', options: [{ value: 'eigentuemer', label: t('userManagement.roles.eigentuemer') }, { value: 'verwalter', label: t('userManagement.roles.verwalter') }, { value: 'buchhaltung', label: t('userManagement.roles.buchhaltung') }, { value: 'techniker', label: t('userManagement.roles.techniker') }, { value: 'readonly', label: t('userManagement.roles.readonly') }] },
    { key: 'days_overdue', label: 'Tage überfällig', type: 'number', required: true, min: 0, max: 3660, step: 1 },
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
    requireWrite();
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
  };

  const afterSave = () => {
    loadData();
  };

  const handleDelete = async (row) => {
    if (!isAllowed()) return;
    if (!await confirm(`${t('modals.confirmDelete.body')}`)) return;
    if (!isAllowed()) return;
    setDeleteError(null);
    try {
      await api.del(`/escalation/rules/${row.id}`, revisionOptions(row));
      loadData();
    } catch (err) {
      setDeleteError(err.message || t('pages.deleteFailed'));
    }
  };

  if (loading) return <div className="page-loading">{t('ui.table.loading')}</div>;
  if (error) return <div className="page"><div className="alert alert-error">{error}</div></div>;

  return (
    <div className="page">
      <OperationalTickPanel onCompleted={loadData} />
      {deleteError && (
        <div className="alert alert-error" style={{ marginBottom: '1rem' }}>
          {deleteError}
          <button onClick={() => setDeleteError(null)} style={{ marginLeft: '1rem', cursor: 'pointer' }}>✕</button>
        </div>
      )}
      <div style={{ marginBottom: '1rem', display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
        {canWrite && <button type="button" className="btn btn-primary" onClick={handleRun} disabled={running}>
          {running ? t('ui.table.loading') : 'Eskalation ausführen'}
        </button>}
        {runResult && !runResult.error && (
          <span className="text-muted">
            {runResult.rules_checked} Regeln geprüft, {runResult.notifications_generated} Benachrichtigungen erzeugt
          </span>
        )}
        {runResult?.error && (
          <span style={{ color: 'var(--color-danger)' }}>{runResult.error}</span>
        )}
      </div>
      {runResult?.warnings?.length > 0 && <div role="alert">{runResult.warnings.map(warning => <p key={warning.source_id}>{warning.error}</p>)}</div>}
      <DataTable
        title="Eskalationsregeln"
        columns={COLUMNS}
        data={rules}
        onAdd={canWrite ? () => setModal('create') : undefined}
        onEdit={canWrite ? row => setModal(row) : undefined}
        onDelete={canWrite ? handleDelete : undefined}
      />
      {modal && (
        <FormModal onSaved={afterSave} draftConfig={{ collection: 'escalation/rules' }}
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
