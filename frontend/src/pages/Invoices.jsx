import { useState, useEffect } from 'react';
import { api } from '../api';
import CrudPage from './CrudPage';

const COLUMNS = [
  { key: 'supplier', label: 'Lieferant', filterType: 'text' },
  { key: 'invoice_date', label: 'Rechnungsdatum', type: 'date', filterType: 'dateRange' },
  { key: 'due_date', label: 'Fällig am', type: 'date', filterType: 'dateRange' },
  { key: 'gross_amount', label: 'Brutto (€)', type: 'number', align: 'right', filterType: 'numberRange',
    render: v => v != null ? `${Number(v).toFixed(2)} €` : '—' },
  { key: 'status', label: 'Status', type: 'status', filterType: 'select' },
];

export default function Invoices() {
  const [properties, setProperties] = useState([]);
  useEffect(() => { api.get('/properties').then(setProperties).catch(err => console.warn('[Invoices] properties:', err.message)); }, []);

  const fields = [
    { key: 'supplier', label: 'Lieferant', required: true },
    { key: 'property_id', label: 'Immobilie', type: 'select',
      options: [{ value: '', label: '— Keine —' }, ...properties.map(p => ({ value: p.id, label: p.name }))] },
    { key: 'invoice_date', label: 'Rechnungsdatum', type: 'date', required: true },
    { key: 'due_date', label: 'Fälligkeitsdatum', type: 'date' },
    { key: 'net_amount', label: 'Netto (€)', type: 'number', required: true },
    { key: 'vat_rate', label: 'MwSt-Satz (%)', type: 'number', default: 19 },
    { key: 'vat_amount', label: 'MwSt (€)', type: 'number', default: 0 },
    { key: 'gross_amount', label: 'Brutto (€)', type: 'number', required: true },
    { key: 'payment_terms', label: 'Zahlungsbedingungen' },
    { key: 'status', label: 'Status', type: 'select', default: 'open', options: [
      { value: 'open', label: 'Offen' }, { value: 'paid', label: 'Bezahlt' },
      { value: 'overdue', label: 'Überfällig' }, { value: 'cancelled', label: 'Storniert' },
    ]},
  ];

  return <CrudPage title="Rechnungen" endpoint="/invoices" columns={COLUMNS} formFields={fields} />;
}
