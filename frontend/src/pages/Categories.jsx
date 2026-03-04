import { useState, useEffect } from 'react';
import { api } from '../api';
import CrudPage from './CrudPage';

const COLUMNS = [
  { key: 'name', label: 'Name', filterType: 'text' },
  { key: 'category_type', label: 'Typ', filterType: 'select' },
];

export default function Categories() {
  const [portfolios, setPortfolios] = useState([]);
  useEffect(() => { api.get('/portfolios').then(setPortfolios).catch(err => console.warn('[Categories] portfolios:', err.message)); }, []);

  const fields = [
    { key: 'portfolio_id', label: 'Portfolio', required: true, type: 'select',
      options: portfolios.map(p => ({ value: p.id, label: p.name })) },
    { key: 'name', label: 'Name', required: true },
    { key: 'category_type', label: 'Typ', required: true, type: 'select', options: [
      { value: 'income', label: 'Einnahme' },
      { value: 'expense', label: 'Ausgabe' },
      { value: 'maintenance', label: 'Instandhaltung' },
      { value: 'other', label: 'Sonstige' },
    ]},
  ];

  return <CrudPage title="Kategorien" endpoint="/categories" columns={COLUMNS} formFields={fields} />;
}
