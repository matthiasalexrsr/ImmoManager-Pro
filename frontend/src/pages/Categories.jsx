import { useEntities } from '../contexts/DataStoreContext';
import CrudPage from './CrudPage';

const COLUMNS = [
  { key: 'name', label: 'Name', filterType: 'text' },
  { key: 'category_type', label: 'Typ', filterType: 'select' },
];

export default function Categories() {
  const { items: portfolios } = useEntities('portfolios', '/portfolios');

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
