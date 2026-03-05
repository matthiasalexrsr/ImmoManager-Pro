import { useState, useEffect } from 'react';
import { api } from '../api';
import CrudPage from './CrudPage';

const COLUMNS = [
  { key: 'provider', label: 'Versicherer', filterType: 'text' },
  { key: 'insurance_type', label: 'Art', filterType: 'select' },
  { key: 'policy_number', label: 'Policennr.', filterType: 'text' },
  { key: 'premium_amount', label: 'Prämie (€)', type: 'number', align: 'right',
    render: v => v != null ? `${Number(v).toFixed(2)} €` : '—' },
  { key: 'premium_interval', label: 'Intervall' },
  { key: 'end_date', label: 'Ablauf', type: 'date', filterType: 'dateRange' },
  { key: 'status', label: 'Status', type: 'status', filterType: 'select' },
];

export default function Insurances() {
  const [properties, setProperties] = useState([]);
  const [units, setUnits] = useState([]);

  useEffect(() => {
    Promise.all([
      api.get('/properties').catch(err => { console.warn('[Insurances] properties:', err.message); return []; }),
      api.get('/units').catch(err => { console.warn('[Insurances] units:', err.message); return []; }),
    ]).then(([p, u]) => { setProperties(p); setUnits(u); });
  }, []);

  const fields = [
    { key: 'property_id', label: 'Immobilie', required: true, type: 'select',
      options: properties.map(p => ({ value: p.id, label: p.name })) },
    { key: 'unit_id', label: 'Einheit (optional)', type: 'select',
      options: units.map(u => ({ value: u.id, label: u.label })) },
    { key: 'insurance_type', label: 'Versicherungsart', required: true, type: 'select', options: [
      { value: 'building', label: 'Gebäudeversicherung' },
      { value: 'liability', label: 'Haftpflicht' },
      { value: 'contents', label: 'Hausrat' },
      { value: 'legal', label: 'Rechtsschutz' },
      { value: 'rent_loss', label: 'Mietausfall' },
      { value: 'other', label: 'Sonstige' },
    ]},
    { key: 'provider', label: 'Versicherer', required: true, placeholder: 'z.B. Allianz' },
    { key: 'policy_number', label: 'Policennummer', placeholder: 'z.B. VP-2024-12345' },
    { key: 'coverage_amount', label: 'Deckungssumme (€)', type: 'number' },
    { key: 'premium_amount', label: 'Prämie (€)', type: 'number' },
    { key: 'premium_interval', label: 'Zahlungsintervall', type: 'select', default: 'annual', options: [
      { value: 'monthly', label: 'Monatlich' },
      { value: 'quarterly', label: 'Vierteljährlich' },
      { value: 'annual', label: 'Jährlich' },
    ]},
    { key: 'start_date', label: 'Vertragsbeginn', type: 'date' },
    { key: 'end_date', label: 'Vertragsende', type: 'date' },
    { key: 'contact_person', label: 'Ansprechpartner' },
    { key: 'contact_phone', label: 'Telefon' },
    { key: 'notes', label: 'Notizen', type: 'textarea' },
    { key: 'status', label: 'Status', type: 'select', default: 'active', options: [
      { value: 'active', label: 'Aktiv' },
      { value: 'expired', label: 'Abgelaufen' },
      { value: 'cancelled', label: 'Gekündigt' },
    ]},
  ];

  return <CrudPage title="Versicherungen" endpoint="/insurances" columns={COLUMNS} formFields={fields} />;
}
