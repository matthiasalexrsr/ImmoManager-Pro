import { useEntities } from '../contexts/DataStoreContext';
import CrudPage from './CrudPage';

const COLUMNS = [
  { key: 'title', label: 'Titel', filterType: 'text' },
  { key: 'category', label: 'Kategorie', filterType: 'select' },
  { key: 'priority', label: 'Priorität', type: 'status', filterType: 'select' },
  { key: 'assignee', label: 'Zuständig', filterType: 'text' },
  { key: 'estimated_cost', label: 'Kosten (€)', type: 'number', align: 'right',
    render: v => v != null ? `${Number(v).toFixed(2)} €` : '—' },
  { key: 'due_date', label: 'Fällig am', type: 'date', filterType: 'dateRange' },
  { key: 'status', label: 'Status', type: 'status', filterType: 'select' },
];

export default function Maintenance() {
  const { items: properties } = useEntities('properties', '/properties');
  const { items: units } = useEntities('units', '/units');

  const fields = [
    { key: 'property_id', label: 'Immobilie', required: true, type: 'select',
      options: properties.map(p => ({ value: p.id, label: p.name })) },
    { key: 'unit_id', label: 'Einheit', type: 'select',
      options: [{ value: '', label: '— Keine —' }, ...units.map(u => ({ value: u.id, label: u.label }))] },
    { key: 'title', label: 'Titel', required: true },
    { key: 'description', label: 'Beschreibung', type: 'textarea' },
    { key: 'category', label: 'Kategorie', type: 'select', options: [
      { value: 'Sanitär', label: 'Sanitär' }, { value: 'Elektrik', label: 'Elektrik' },
      { value: 'Heizung', label: 'Heizung' }, { value: 'Dach', label: 'Dach' },
      { value: 'Fassade', label: 'Fassade' }, { value: 'Sonstiges', label: 'Sonstiges' },
    ]},
    { key: 'priority', label: 'Priorität', type: 'select', default: 'medium', options: [
      { value: 'low', label: 'Niedrig' }, { value: 'medium', label: 'Mittel' },
      { value: 'high', label: 'Hoch' }, { value: 'urgent', label: 'Dringend' },
    ]},
    { key: 'reported_by', label: 'Gemeldet von' },
    { key: 'assignee', label: 'Zuständig' },
    { key: 'contractor', label: 'Handwerker' },
    { key: 'due_date', label: 'Fällig am', type: 'date' },
    { key: 'appointment_at', label: 'Termin', type: 'date' },
    { key: 'estimated_cost', label: 'Geschätzte Kosten (€)', type: 'number' },
    { key: 'status', label: 'Status', type: 'select', default: 'open', options: [
      { value: 'open', label: 'Offen' }, { value: 'in_progress', label: 'In Bearbeitung' },
      { value: 'completed', label: 'Erledigt' }, { value: 'cancelled', label: 'Abgebrochen' },
    ]},
  ];

  return <CrudPage title="Wartung & Instandhaltung" endpoint="/maintenance" columns={COLUMNS} formFields={fields} />;
}
