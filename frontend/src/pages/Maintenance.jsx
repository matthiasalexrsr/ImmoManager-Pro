import { useState, useEffect } from 'react';
import { api } from '../api';
import CrudPage from './CrudPage';

const COLUMNS = [
  { key: 'title', label: 'Titel' },
  { key: 'category', label: 'Kategorie' },
  { key: 'priority', label: 'Priorität', type: 'status' },
  { key: 'assignee', label: 'Zuständig' },
  { key: 'due_date', label: 'Fällig am' },
  { key: 'status', label: 'Status', type: 'status' },
];

export default function Maintenance() {
  const [properties, setProperties] = useState([]);
  useEffect(() => { api.get('/properties').then(setProperties).catch(() => {}); }, []);

  const fields = [
    { key: 'property_id', label: 'Immobilie', required: true, type: 'select',
      options: properties.map(p => ({ value: p.id, label: p.name })) },
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
    { key: 'assignee', label: 'Zuständig' },
    { key: 'contractor', label: 'Handwerker' },
    { key: 'due_date', label: 'Fällig am', type: 'date' },
    { key: 'estimated_cost', label: 'Geschätzte Kosten (€)', type: 'number' },
    { key: 'status', label: 'Status', type: 'select', default: 'open', options: [
      { value: 'open', label: 'Offen' }, { value: 'in_progress', label: 'In Bearbeitung' },
      { value: 'completed', label: 'Erledigt' }, { value: 'cancelled', label: 'Abgebrochen' },
    ]},
  ];

  return <CrudPage title="Wartung & Instandhaltung" endpoint="/maintenance" columns={COLUMNS} formFields={fields} />;
}
