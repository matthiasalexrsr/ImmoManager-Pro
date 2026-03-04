import { useState, useEffect } from 'react';
import { api } from '../api';
import CrudPage from './CrudPage';

const COLUMNS = [
  { key: 'name', label: 'Name', filterType: 'text' },
  { key: 'property_type', label: 'Typ', filterType: 'select' },
  { key: 'city', label: 'Stadt', filterType: 'text' },
  { key: 'zip_code', label: 'PLZ', filterType: 'text' },
  { key: 'year_built', label: 'Baujahr', type: 'number' },
  { key: 'total_area', label: 'Fläche (m²)', type: 'number', align: 'right',
    render: v => v != null ? `${Number(v).toLocaleString('de-DE')} m²` : '—' },
  { key: 'status', label: 'Status', type: 'status', filterType: 'select' },
];

export default function Properties() {
  const [portfolios, setPortfolios] = useState([]);
  useEffect(() => { api.get('/portfolios').then(setPortfolios).catch(() => {}); }, []);

  const fields = [
    { key: 'portfolio_id', label: 'Portfolio', required: true, type: 'select',
      options: portfolios.map(p => ({ value: p.id, label: p.name })) },
    { key: 'name', label: 'Name', required: true },
    { key: 'property_type', label: 'Typ', required: true, type: 'select', options: [
      { value: 'residential', label: 'Wohngebäude' },
      { value: 'commercial', label: 'Gewerbe' },
      { value: 'mixed', label: 'Gemischt' },
    ]},
    { key: 'street', label: 'Straße' },
    { key: 'zip_code', label: 'PLZ' },
    { key: 'city', label: 'Stadt' },
    { key: 'country', label: 'Land', default: 'DE' },
    { key: 'year_built', label: 'Baujahr', type: 'number' },
    { key: 'total_area', label: 'Gesamtfläche (m²)', type: 'number' },
    { key: 'status', label: 'Status', type: 'select', default: 'active', options: [
      { value: 'active', label: 'Aktiv' }, { value: 'inactive', label: 'Inaktiv' },
    ]},
  ];

  return <CrudPage title="Immobilien" endpoint="/properties" columns={COLUMNS} formFields={fields} />;
}
