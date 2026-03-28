import { useState, useEffect, useMemo } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import { useEntities, useDataStore } from '../contexts/DataStoreContext';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import StatusBadge from '../components/StatusBadge';
import { useConfirm } from '../components/ConfirmDialog';

function parseRecurrence(rule) {
  if (!rule) return '—';
  if (rule.includes('FREQ=DAILY')) return 'Täglich';
  if (rule.includes('FREQ=WEEKLY')) return 'Wöchentlich';
  if (rule.includes('FREQ=MONTHLY')) return 'Monatlich';
  if (rule.includes('FREQ=YEARLY')) return 'Jährlich';
  return rule;
}

function isOverdue(dueDate, status) {
  if (!dueDate || status === 'completed') return false;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const due = new Date(dueDate);
  due.setHours(0, 0, 0, 0);
  return due < today;
}

function isToday(dueDate) {
  if (!dueDate) return false;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const due = new Date(dueDate);
  due.setHours(0, 0, 0, 0);
  return due.getTime() === today.getTime();
}

function isWithinWeek(dueDate) {
  if (!dueDate) return false;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const due = new Date(dueDate);
  due.setHours(0, 0, 0, 0);
  const weekFromNow = new Date(today);
  weekFromNow.setDate(weekFromNow.getDate() + 7);
  return due >= today && due <= weekFromNow;
}

export default function Tasks() {
  const { t } = useTranslation();
  const confirm = useConfirm();
  const store = useDataStore();
  const { items: properties } = useEntities('properties', '/properties');
  const { items: units } = useEntities('units', '/units');

  const [tasks, setTasks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(null);
  const [filter, setFilter] = useState('all');

  const noneOpt = t('pages.tasks.form.noneOption') || '— Keine —';

  const refreshData = () => {
    setLoading(true);
    api.get('/tasks').catch(() => [])
      .then(data => setTasks(Array.isArray(data) ? data : []))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    let cancelled = false;
    api.get('/tasks').catch(err => { console.warn('[Tasks] load:', err.message); return []; })
      .then(data => { if (!cancelled) setTasks(Array.isArray(data) ? data : []); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  // Lookup maps
  const propertyMap = Object.fromEntries(properties.map(p => [p.id, p.name]));
  const unitMap = Object.fromEntries(units.map(u => [u.id, u.label]));

  // Enriched data
  const enriched = tasks.map(task => ({
    ...task,
    property_name: propertyMap[task.property_id] || '—',
    unit_label: unitMap[task.unit_id] || '—',
    is_overdue: isOverdue(task.due_date, task.status),
    recurrence_label: parseRecurrence(task.recurrence_rule),
  }));

  // Filtered data
  const filtered = useMemo(() => {
    switch (filter) {
      case 'open': return enriched.filter(t => t.status === 'open');
      case 'today': return enriched.filter(t => isToday(t.due_date));
      case 'week': return enriched.filter(t => isWithinWeek(t.due_date));
      case 'overdue': return enriched.filter(t => t.is_overdue);
      case 'recurring': return enriched.filter(t => !!t.recurrence_rule);
      default: return enriched;
    }
  }, [enriched, filter]);

  // Summary stats
  const totalCount = enriched.length;
  const openCount = enriched.filter(t => t.status === 'open').length;
  const overdueCount = enriched.filter(t => t.is_overdue).length;
  const inProgressCount = enriched.filter(t => t.status === 'in_progress').length;
  const recurringCount = enriched.filter(t => !!t.recurrence_rule).length;

  const columns = [
    { key: 'title', label: t('pages.tasks.columns.title') || 'Titel', filterType: 'text' },
    { key: 'property_name', label: t('portfolio.properties.form.name') || 'Immobilie', filterType: 'text' },
    { key: 'unit_label', label: t('units.list.columns.label') || 'Einheit', filterType: 'text' },
    { key: 'assignee', label: t('pages.tasks.columns.assignee') || 'Zuständig', filterType: 'text' },
    { key: 'due_date', label: t('pages.tasks.columns.dueDate') || 'Fällig am', type: 'date', filterType: 'dateRange',
      render: (v, row) => {
        if (!v) return '—';
        const display = new Date(v).toLocaleDateString('de-DE');
        if (isOverdue(v, row.status)) {
          return <span style={{ color: 'var(--danger)', fontWeight: 700 }}>{display}</span>;
        }
        return display;
      }},
    { key: 'is_overdue', label: 'Überfällig',
      render: v => v ? <StatusBadge status="danger" label="Überfällig" /> : '—' },
    { key: 'recurrence_label', label: t('pages.tasks.form.recurrence') || 'Wiederholung', filterType: 'text' },
    { key: 'priority', label: t('pages.tasks.columns.priority') || 'Priorität', type: 'status', filterType: 'select' },
    { key: 'status', label: t('pages.tasks.columns.status') || 'Status', type: 'status', filterType: 'select',
      render: v => <StatusBadge status={v} /> },
  ];

  const fields = [
    { key: 'title', label: t('pages.tasks.form.title') || 'Titel', required: true },
    { key: 'description', label: t('pages.tasks.form.description') || 'Beschreibung', type: 'textarea' },
    { key: 'assignee', label: t('pages.tasks.form.assignee') || 'Zuständig' },
    { key: 'property_id', label: t('pages.tasks.form.property') || 'Immobilie', type: 'select',
      options: [{ value: '', label: noneOpt }, ...properties.map(p => ({ value: p.id, label: p.name }))] },
    { key: 'unit_id', label: t('pages.tasks.form.unit') || 'Einheit', type: 'select',
      options: [{ value: '', label: noneOpt }, ...units.map(u => ({ value: u.id, label: u.label }))] },
    { key: 'due_date', label: t('pages.tasks.form.dueDate') || 'Fällig am', type: 'date' },
    { key: 'recurrence_rule', label: t('pages.tasks.form.recurrence') || 'Wiederholung (iCal RRULE)', placeholder: t('pages.tasks.form.recurrencePlaceholder') || 'z.B. FREQ=MONTHLY;COUNT=12' },
    { key: 'priority', label: t('pages.tasks.form.priority') || 'Priorität', type: 'select', default: 'medium', options: [
      { value: 'low', label: t('pages.tasks.priority.low') || 'Niedrig' },
      { value: 'medium', label: t('pages.tasks.priority.medium') || 'Mittel' },
      { value: 'high', label: t('pages.tasks.priority.high') || 'Hoch' },
      { value: 'urgent', label: t('pages.tasks.priority.urgent') || 'Dringend' },
    ]},
    { key: 'status', label: t('pages.tasks.form.status') || 'Status', type: 'select', default: 'open', options: [
      { value: 'open', label: t('pages.tasks.status.open') || 'Offen' },
      { value: 'in_progress', label: t('pages.tasks.status.inProgress') || 'In Bearbeitung' },
      { value: 'completed', label: t('pages.tasks.status.completed') || 'Erledigt' },
    ]},
  ];

  const handleSave = async (data) => {
    if (modal === 'create') {
      await api.post('/tasks', data);
    } else {
      await api.put(`/tasks/${modal.id}`, data);
    }
    refreshData();
    if (store) store.invalidateRelated('tasks', 'properties', 'units');
  };

  const handleDelete = async (row) => {
    if (!await confirm(`"${row.title || row.id}" ${t('modals.confirmDelete.body')}`)) return;
    await api.del(`/tasks/${row.id}`);
    refreshData();
    if (store) store.invalidateRelated('tasks', 'properties', 'units');
  };

  if (loading) return <div className="page-loading">Lade Aufgaben...</div>;

  return (
    <div className="page">
      <h1 className="page-title">{t('pages.tasks.title') || 'Aufgaben'}</h1>

      {/* Summary cards */}
      <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', marginBottom: '1.5rem' }}>
        <div className="panel" style={{ padding: '0.75rem 1rem', minWidth: '140px', textAlign: 'center' }}>
          <div style={{ fontSize: '1.4rem', fontWeight: 700 }}>{totalCount}</div>
          <div className="text-muted" style={{ fontSize: '0.8rem' }}>Gesamt</div>
        </div>
        <div className="panel" style={{ padding: '0.75rem 1rem', minWidth: '140px', textAlign: 'center' }}>
          <div style={{ fontSize: '1.4rem', fontWeight: 700, color: 'var(--info)' }}>{openCount}</div>
          <div className="text-muted" style={{ fontSize: '0.8rem' }}>Offen</div>
        </div>
        <div className="panel" style={{ padding: '0.75rem 1rem', minWidth: '140px', textAlign: 'center' }}>
          <div style={{ fontSize: '1.4rem', fontWeight: 700, color: overdueCount > 0 ? 'var(--danger)' : undefined }}>{overdueCount}</div>
          <div className="text-muted" style={{ fontSize: '0.8rem' }}>Überfällig</div>
        </div>
        <div className="panel" style={{ padding: '0.75rem 1rem', minWidth: '140px', textAlign: 'center' }}>
          <div style={{ fontSize: '1.4rem', fontWeight: 700, color: 'var(--warning)' }}>{inProgressCount}</div>
          <div className="text-muted" style={{ fontSize: '0.8rem' }}>In Bearbeitung</div>
        </div>
        <div className="panel" style={{ padding: '0.75rem 1rem', minWidth: '140px', textAlign: 'center' }}>
          <div style={{ fontSize: '1.4rem', fontWeight: 700 }}>{recurringCount}</div>
          <div className="text-muted" style={{ fontSize: '0.8rem' }}>Wiederkehrend</div>
        </div>
      </div>

      {/* Filter tabs */}
      <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem', flexWrap: 'wrap' }}>
        {[
          { key: 'all', label: 'Alle' },
          { key: 'open', label: 'Offen' },
          { key: 'today', label: 'Heute' },
          { key: 'week', label: 'Diese Woche' },
          { key: 'overdue', label: 'Überfällig' },
          { key: 'recurring', label: 'Wiederkehrend' },
        ].map(f => (
          <button
            key={f.key}
            className={`btn btn-sm ${filter === f.key ? 'btn-primary' : 'btn-secondary'}`}
            onClick={() => setFilter(f.key)}
          >{f.label}</button>
        ))}
      </div>

      <DataTable
        title={t('pages.tasks.title') || 'Aufgaben'}
        columns={columns}
        data={filtered}
        onAdd={() => setModal('create')}
        onEdit={row => setModal(row)}
        onDelete={handleDelete}
      />

      {modal && (
        <FormModal
          title={modal === 'create' ? 'Aufgabe erstellen' : 'Aufgabe bearbeiten'}
          fields={fields}
          initial={modal === 'create' ? null : modal}
          onSave={handleSave}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  );
}
