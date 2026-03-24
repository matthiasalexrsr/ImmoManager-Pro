import { useEntities } from '../contexts/DataStoreContext';
import { useTranslation } from '../i18n';
import CrudPage from './CrudPage';

export default function Tasks() {
  const { t } = useTranslation();
  const { items: properties } = useEntities('properties', '/properties');
  const { items: units } = useEntities('units', '/units');

  const COLUMNS = [
    { key: 'title', label: t('pages.tasks.columns.title') || 'Titel', filterType: 'text' },
    { key: 'assignee', label: t('pages.tasks.columns.assignee') || 'Zuständig', filterType: 'text' },
    { key: 'due_date', label: t('pages.tasks.columns.dueDate') || 'Fällig am', type: 'date', filterType: 'dateRange' },
    { key: 'priority', label: t('pages.tasks.columns.priority') || 'Priorität', type: 'status', filterType: 'select' },
    { key: 'status', label: t('pages.tasks.columns.status') || 'Status', type: 'status', filterType: 'select' },
  ];

  const fields = [
    { key: 'title', label: t('pages.tasks.form.title') || 'Titel', required: true },
    { key: 'description', label: t('pages.tasks.form.description') || 'Beschreibung', type: 'textarea' },
    { key: 'assignee', label: t('pages.tasks.form.assignee') || 'Zuständig' },
    { key: 'property_id', label: t('pages.tasks.form.property') || 'Immobilie', type: 'select',
      options: [{ value: '', label: t('pages.tasks.form.noneOption') || '— Keine —' }, ...properties.map(p => ({ value: p.id, label: p.name }))] },
    { key: 'unit_id', label: t('pages.tasks.form.unit') || 'Einheit', type: 'select',
      options: [{ value: '', label: t('pages.tasks.form.noneOption') || '— Keine —' }, ...units.map(u => ({ value: u.id, label: u.label }))] },
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

  return <CrudPage title={t('pages.tasks.title') || 'Aufgaben'} endpoint="/tasks" columns={COLUMNS} formFields={fields} />;
}
