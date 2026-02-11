import CrudPage from './CrudPage';

const COLUMNS = [
  { key: 'title', label: 'Titel' },
  { key: 'assignee', label: 'Zuständig' },
  { key: 'due_date', label: 'Fällig am' },
  { key: 'priority', label: 'Priorität', type: 'status' },
  { key: 'status', label: 'Status', type: 'status' },
];

const FIELDS = [
  { key: 'title', label: 'Titel', required: true },
  { key: 'description', label: 'Beschreibung', type: 'textarea' },
  { key: 'assignee', label: 'Zuständig' },
  { key: 'due_date', label: 'Fällig am', type: 'date' },
  { key: 'priority', label: 'Priorität', type: 'select', default: 'medium', options: [
    { value: 'low', label: 'Niedrig' }, { value: 'medium', label: 'Mittel' },
    { value: 'high', label: 'Hoch' }, { value: 'urgent', label: 'Dringend' },
  ]},
  { key: 'status', label: 'Status', type: 'select', default: 'open', options: [
    { value: 'open', label: 'Offen' }, { value: 'in_progress', label: 'In Bearbeitung' },
    { value: 'completed', label: 'Erledigt' },
  ]},
];

export default function Tasks() {
  return <CrudPage title="Aufgaben" endpoint="/tasks" columns={COLUMNS} formFields={FIELDS} />;
}
