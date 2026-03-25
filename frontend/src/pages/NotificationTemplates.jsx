import { useState, useEffect } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import { useConfirm } from '../components/ConfirmDialog';

export default function NotificationTemplates() {
  const { t } = useTranslation();
  const confirm = useConfirm();
  const [templates, setTemplates] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [modal, setModal] = useState(null);
  const [deleteError, setDeleteError] = useState(null);

  const refreshData = () => {
    setLoading(true);
    api.get('/notifications/templates')
      .then(data => setTemplates(data || []))
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    let cancelled = false;
    api.get('/notifications/templates')
      .then(data => {
        if (!cancelled) setTemplates(data || []);
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

  const COLUMNS = [
    { key: 'name', label: 'Name', filterType: 'text' },
    { key: 'notification_type', label: 'Typ', filterType: 'select' },
    { key: 'subject', label: 'Betreff', filterType: 'text' },
    { key: 'severity', label: 'Schwere', filterType: 'select' },
    { key: 'is_active', label: 'Aktiv', render: v => v ? '✓' : '—' },
  ];

  const fields = [
    { key: 'name', label: 'Name', required: true },
    { key: 'notification_type', label: 'Typ', required: true, type: 'select', options: [
      { value: 'overdue_payment', label: 'Überfällige Zahlung' },
      { value: 'contract_expiry', label: 'Vertragsende' },
      { value: 'task_due', label: 'Aufgabe fällig' },
      { value: 'escalation', label: 'Eskalation' },
      { value: 'general', label: 'Allgemein' },
    ]},
    { key: 'subject', label: 'Betreff', required: true },
    { key: 'body_template', label: 'Vorlage', type: 'textarea', required: true },
    { key: 'severity', label: 'Schwere', type: 'select', default: 'info', options: [
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
    const payload = { ...data, is_active: data.is_active === 'true' || data.is_active === true };
    if (modal === 'create') {
      await api.post('/notifications/templates', payload);
    } else {
      await api.put(`/notifications/templates/${modal.id}`, payload);
    }
    refreshData();
  };

  const handleDelete = async (row) => {
    if (!await confirm(`${t('modals.confirmDelete.body')}`)) return;
    setDeleteError(null);
    try {
      await api.del(`/notifications/templates/${row.id}`);
      refreshData();
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
      <DataTable
        title={t('settings.templates.dunning')}
        columns={COLUMNS}
        data={templates}
        onAdd={() => setModal('create')}
        onEdit={row => setModal(row)}
        onDelete={handleDelete}
      />
      {modal && (
        <FormModal
          title={modal === 'create' ? t('ui.buttons.create') : t('ui.buttons.edit')}
          fields={fields}
          initial={modal === 'create' ? null : modal}
          onSave={handleSave}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  );
}
