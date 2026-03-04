import CrudPage from './CrudPage';

const COLUMNS = [
  { key: 'name', label: 'Name', filterType: 'text' },
  { key: 'description', label: 'Beschreibung' },
  { key: 'status', label: 'Status', type: 'status', filterType: 'select' },
];

const FIELDS = [
  { key: 'name', label: 'Name', required: true },
  { key: 'description', label: 'Beschreibung', type: 'textarea' },
  { key: 'status', label: 'Status', type: 'select', default: 'active', options: [
    { value: 'active', label: 'Aktiv' }, { value: 'inactive', label: 'Inaktiv' },
  ]},
];

export default function Portfolios() {
  return <CrudPage title="Portfolios" endpoint="/portfolios" columns={COLUMNS} formFields={FIELDS} />;
}
