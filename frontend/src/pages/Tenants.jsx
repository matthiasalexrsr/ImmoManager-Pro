import CrudPage from './CrudPage';

const COLUMNS = [
  { key: 'full_name', label: 'Name' },
  { key: 'email', label: 'E-Mail' },
  { key: 'phone', label: 'Telefon' },
  { key: 'company', label: 'Firma' },
];

const FIELDS = [
  { key: 'full_name', label: 'Vollständiger Name', required: true },
  { key: 'email', label: 'E-Mail', type: 'email' },
  { key: 'phone', label: 'Telefon' },
  { key: 'date_of_birth', label: 'Geburtsdatum', type: 'date' },
  { key: 'company', label: 'Firma' },
  { key: 'notes', label: 'Notizen', type: 'textarea' },
];

export default function Tenants() {
  return <CrudPage title="Mieter" endpoint="/tenants" columns={COLUMNS} formFields={FIELDS} />;
}
