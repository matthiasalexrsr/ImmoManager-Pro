import { useEntities } from '../contexts/DataStoreContext';
import { useTranslation } from '../i18n';
import CrudPage from './CrudPage';

export default function Maintenance() {
  const { t } = useTranslation();
  const { items: properties } = useEntities('properties', '/properties');
  const { items: units } = useEntities('units', '/units');

  const COLUMNS = [
    { key: 'title', label: t('pages.maintenance.columns.title') || 'Titel', filterType: 'text' },
    { key: 'category', label: t('pages.maintenance.columns.category') || 'Kategorie', filterType: 'select' },
    { key: 'priority', label: t('pages.maintenance.columns.priority') || 'Priorität', type: 'status', filterType: 'select' },
    { key: 'assignee', label: t('pages.maintenance.columns.assignee') || 'Zuständig', filterType: 'text' },
    { key: 'estimated_cost', label: t('pages.maintenance.columns.cost') || 'Kosten (€)', type: 'number', align: 'right',
      render: v => v != null ? `${Number(v).toFixed(2)} €` : '—' },
    { key: 'due_date', label: t('pages.maintenance.columns.dueDate') || 'Fällig am', type: 'date', filterType: 'dateRange' },
    { key: 'status', label: t('pages.maintenance.columns.status') || 'Status', type: 'status', filterType: 'select' },
  ];

  const fields = [
    { key: 'property_id', label: t('pages.maintenance.form.property') || 'Immobilie', required: true, type: 'select',
      options: properties.map(p => ({ value: p.id, label: p.name })) },
    { key: 'unit_id', label: t('pages.maintenance.form.unit') || 'Einheit', type: 'select',
      options: [{ value: '', label: t('pages.maintenance.form.noneOption') || '— Keine —' }, ...units.map(u => ({ value: u.id, label: u.label }))] },
    { key: 'title', label: t('pages.maintenance.form.title') || 'Titel', required: true },
    { key: 'description', label: t('pages.maintenance.form.description') || 'Beschreibung', type: 'textarea' },
    { key: 'category', label: t('pages.maintenance.form.category') || 'Kategorie', type: 'select', options: [
      { value: 'Sanitär', label: t('pages.maintenance.categories.plumbing') || 'Sanitär' },
      { value: 'Elektrik', label: t('pages.maintenance.categories.electrical') || 'Elektrik' },
      { value: 'Heizung', label: t('pages.maintenance.categories.heating') || 'Heizung' },
      { value: 'Dach', label: t('pages.maintenance.categories.roof') || 'Dach' },
      { value: 'Fassade', label: t('pages.maintenance.categories.facade') || 'Fassade' },
      { value: 'Sonstiges', label: t('pages.maintenance.categories.other') || 'Sonstiges' },
    ]},
    { key: 'priority', label: t('pages.maintenance.form.priority') || 'Priorität', type: 'select', default: 'medium', options: [
      { value: 'low', label: t('pages.maintenance.priority.low') || 'Niedrig' },
      { value: 'medium', label: t('pages.maintenance.priority.medium') || 'Mittel' },
      { value: 'high', label: t('pages.maintenance.priority.high') || 'Hoch' },
      { value: 'urgent', label: t('pages.maintenance.priority.urgent') || 'Dringend' },
    ]},
    { key: 'reported_by', label: t('pages.maintenance.form.reportedBy') || 'Gemeldet von' },
    { key: 'assignee', label: t('pages.maintenance.form.assignee') || 'Zuständig' },
    { key: 'contractor', label: t('pages.maintenance.form.contractor') || 'Handwerker' },
    { key: 'due_date', label: t('pages.maintenance.form.dueDate') || 'Fällig am', type: 'date' },
    { key: 'appointment_at', label: t('pages.maintenance.form.appointment') || 'Termin', type: 'date' },
    { key: 'estimated_cost', label: t('pages.maintenance.form.estimatedCost') || 'Geschätzte Kosten (€)', type: 'number' },
    { key: 'status', label: t('pages.maintenance.form.status') || 'Status', type: 'select', default: 'open', options: [
      { value: 'open', label: t('pages.maintenance.status.open') || 'Offen' },
      { value: 'in_progress', label: t('pages.maintenance.status.inProgress') || 'In Bearbeitung' },
      { value: 'completed', label: t('pages.maintenance.status.completed') || 'Erledigt' },
      { value: 'cancelled', label: t('pages.maintenance.status.cancelled') || 'Abgebrochen' },
    ]},
  ];

  return <CrudPage title={t('pages.maintenance.title') || 'Wartung & Instandhaltung'} endpoint="/maintenance" columns={COLUMNS} formFields={fields} />;
}
