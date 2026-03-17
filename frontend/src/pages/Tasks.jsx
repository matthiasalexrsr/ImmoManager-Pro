import { useEntities } from '../contexts/DataStoreContext';
import CrudPage from './CrudPage';

const COLUMNS = [
  { key: 'title', label: 'Titel', filterType: 'text' },
  { key: 'assignee', label: 'Zuständig', filterType: 'text' },
  { key: 'due_date', label: 'Fällig am', type: 'date', filterType: 'dateRange' },
  { key: 'priority', label: 'Priorität', type: 'status', filterType: 'select' },
  { key: 'status', label: 'Status', type: 'status', filterType: 'select' },
];

export default function Tasks() {
  const { items: properties } = useEntities('properties', '/properties');
  const { items: units } = useEntities('units', '/units');

  const fields = [
    { key: 'title', label: 'Titel', required: true },
    { key: 'description', label: 'Beschreibung', type: 'textarea' },
    { key: 'assignee', label: 'Zuständig' },
    { key: 'property_id', label: 'Immobilie', type: 'select',
      options: [{ value: '', label: '— Keine —' }, ...properties.map(p => ({ value: p.id, label: p.name }))] },
    { key: 'unit_id', label: 'Einheit', type: 'select',
      options: [{ value: '', label: '— Keine —' }, ...units.map(u => ({ value: u.id, label: u.label }))] },
    { key: 'due_date', label: 'Fällig am', type: 'date' },
    { key: 'recurrence_rule', label: 'Wiederholung (iCal RRULE)', placeholder: 'z.B. FREQ=MONTHLY;COUNT=12' },
    { key: 'priority', label: 'Priorität', type: 'select', default: 'medium', options: [
      { value: 'low', label: 'Niedrig' }, { value: 'medium', label: 'Mittel' },
      { value: 'high', label: 'Hoch' }, { value: 'urgent', label: 'Dringend' },
    ]},
    { key: 'status', label: 'Status', type: 'select', default: 'open', options: [
      { value: 'open', label: 'Offen' }, { value: 'in_progress', label: 'In Bearbeitung' },
      { value: 'completed', label: 'Erledigt' },
    ]},
  ];

  return <CrudPage title="Aufgaben" endpoint="/tasks" columns={COLUMNS} formFields={fields} />;
}
