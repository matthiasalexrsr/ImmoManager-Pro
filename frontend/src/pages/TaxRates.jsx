import CrudPage from './CrudPage';

const COLUMNS = [
  { key: 'name', label: 'Bezeichnung', filterType: 'text' },
  { key: 'rate', label: 'Satz (%)', type: 'number', align: 'right',
    render: v => v != null ? `${Number(v).toFixed(1)} %` : '—' },
  { key: 'description', label: 'Beschreibung' },
  { key: 'is_default', label: 'Standard',
    render: v => v ? 'Ja' : 'Nein' },
  { key: 'valid_from', label: 'Gültig ab', type: 'date' },
  { key: 'valid_until', label: 'Gültig bis', type: 'date' },
];

const FIELDS = [
  { key: 'name', label: 'Bezeichnung', required: true, placeholder: 'z.B. Regelsteuersatz' },
  { key: 'rate', label: 'Steuersatz (%)', type: 'number', required: true, placeholder: 'z.B. 19.0' },
  { key: 'description', label: 'Beschreibung' },
  { key: 'is_default', label: 'Standard', type: 'select', options: [
    { value: 'true', label: 'Ja' },
    { value: 'false', label: 'Nein' },
  ]},
  { key: 'valid_from', label: 'Gültig ab', type: 'date' },
  { key: 'valid_until', label: 'Gültig bis', type: 'date' },
];

export default function TaxRates() {
  return <CrudPage title="Steuersätze" endpoint="/tax-rates" columns={COLUMNS} formFields={FIELDS} />;
}
