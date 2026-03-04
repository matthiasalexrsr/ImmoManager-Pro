import CrudPage from './CrudPage';

const COLUMNS = [
  { key: 'full_name', label: 'Name', filterType: 'text' },
  { key: 'email', label: 'E-Mail', filterType: 'text' },
  { key: 'phone', label: 'Telefon' },
  { key: 'city', label: 'Stadt', filterType: 'text' },
  { key: 'payment_method', label: 'Zahlungsart', filterType: 'select' },
];

const FIELDS = [
  { key: 'full_name', label: 'Vollständiger Name', required: true },
  { key: 'email', label: 'E-Mail', type: 'email' },
  { key: 'phone', label: 'Telefon' },
  { key: 'address_line', label: 'Straße' },
  { key: 'postal_code', label: 'PLZ' },
  { key: 'city', label: 'Stadt' },
  { key: 'country', label: 'Land', default: 'DE' },
  { key: 'payment_method', label: 'Zahlungsart', type: 'select', options: [
    { value: 'bank_transfer', label: 'Überweisung' },
    { value: 'sepa_direct_debit', label: 'SEPA-Lastschrift' },
    { value: 'cash', label: 'Bar' },
  ]},
  { key: 'sepa_mandate', label: 'SEPA-Mandat', placeholder: 'Mandatsreferenz' },
  { key: 'notes', label: 'Notizen', type: 'textarea' },
];

export default function Tenants() {
  return <CrudPage title="Mieter" endpoint="/tenants" columns={COLUMNS} formFields={FIELDS} />;
}
