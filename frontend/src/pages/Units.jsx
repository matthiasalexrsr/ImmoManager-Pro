import { useState, useEffect } from 'react';
import { api } from '../api';
import CrudPage from './CrudPage';

const COLUMNS = [
  { key: 'label', label: 'Bezeichnung' },
  { key: 'unit_type', label: 'Typ' },
  { key: 'area_sqm', label: 'Fläche (m²)' },
  { key: 'cold_rent', label: 'Kaltmiete (€)', render: v => v ? `${Number(v).toFixed(2)} €` : '—' },
  { key: 'status', label: 'Status', type: 'status' },
];

export default function Units() {
  const [properties, setProperties] = useState([]);
  useEffect(() => { api.get('/properties').then(setProperties).catch(() => {}); }, []);

  const fields = [
    { key: 'property_id', label: 'Immobilie', required: true, type: 'select',
      options: properties.map(p => ({ value: p.id, label: p.name })) },
    { key: 'label', label: 'Bezeichnung', required: true, placeholder: 'z.B. Wohnung 1 OG links' },
    { key: 'unit_type', label: 'Typ', required: true, type: 'select', options: [
      { value: 'Wohnung', label: 'Wohnung' },
      { value: 'Gewerbe', label: 'Gewerbe' },
      { value: 'Stellplatz', label: 'Stellplatz' },
      { value: 'Keller', label: 'Keller' },
      { value: 'Sonstiges', label: 'Sonstiges' },
    ]},
    { key: 'area_sqm', label: 'Fläche (m²)', type: 'number' },
    { key: 'rooms', label: 'Zimmer', type: 'number' },
    { key: 'floor', label: 'Etage' },
    { key: 'cold_rent', label: 'Kaltmiete (€)', type: 'number' },
    { key: 'service_charge_advance', label: 'NK-Vorauszahlung (€)', type: 'number' },
    { key: 'heating_advance', label: 'Heizkosten-Vorauszahlung (€)', type: 'number' },
    { key: 'status', label: 'Status', type: 'select', default: 'vacant', options: [
      { value: 'vacant', label: 'Leer' }, { value: 'occupied', label: 'Vermietet' },
      { value: 'reserved', label: 'Reserviert' },
    ]},
  ];

  return <CrudPage title="Einheiten" endpoint="/units" columns={COLUMNS} formFields={fields} />;
}
