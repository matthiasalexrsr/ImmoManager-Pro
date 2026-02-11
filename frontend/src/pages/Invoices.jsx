import CrudPage from './CrudPage';

const COLUMNS = [
  { key: 'supplier', label: 'Lieferant' },
  { key: 'invoice_date', label: 'Rechnungsdatum' },
  { key: 'due_date', label: 'Fällig am' },
  { key: 'gross_amount', label: 'Brutto (€)', render: v => v != null ? `${Number(v).toFixed(2)} €` : '—' },
  { key: 'status', label: 'Status', type: 'status' },
];

const FIELDS = [
  { key: 'supplier', label: 'Lieferant', required: true },
  { key: 'invoice_date', label: 'Rechnungsdatum', type: 'date', required: true },
  { key: 'due_date', label: 'Fälligkeitsdatum', type: 'date' },
  { key: 'net_amount', label: 'Netto (€)', type: 'number', required: true },
  { key: 'vat_amount', label: 'MwSt (€)', type: 'number', default: 0 },
  { key: 'gross_amount', label: 'Brutto (€)', type: 'number', required: true },
  { key: 'payment_terms', label: 'Zahlungsbedingungen' },
  { key: 'status', label: 'Status', type: 'select', default: 'open', options: [
    { value: 'open', label: 'Offen' }, { value: 'paid', label: 'Bezahlt' },
    { value: 'overdue', label: 'Überfällig' }, { value: 'cancelled', label: 'Storniert' },
  ]},
];

export default function Invoices() {
  return <CrudPage title="Rechnungen" endpoint="/invoices" columns={COLUMNS} formFields={FIELDS} />;
}
