import { useState, useEffect } from 'react';
import { api } from '../api';
import CrudPage from './CrudPage';

const COLUMNS = [
  { key: 'name', label: 'Kontoname', filterType: 'text' },
  { key: 'bank_name', label: 'Bank', filterType: 'text' },
  { key: 'iban', label: 'IBAN' },
  { key: 'account_type', label: 'Typ', filterType: 'select' },
  { key: 'balance', label: 'Saldo (€)', type: 'number', align: 'right', filterType: 'numberRange',
    render: v => v != null ? `${Number(v).toFixed(2)} €` : '—' },
];

export default function Accounts() {
  const [portfolios, setPortfolios] = useState([]);
  useEffect(() => { api.get('/portfolios').then(setPortfolios).catch(() => {}); }, []);

  const fields = [
    { key: 'portfolio_id', label: 'Portfolio', required: true, type: 'select',
      options: portfolios.map(p => ({ value: p.id, label: p.name })) },
    { key: 'name', label: 'Kontoname', required: true },
    { key: 'bank_name', label: 'Bank' },
    { key: 'iban', label: 'IBAN' },
    { key: 'bic', label: 'BIC' },
    { key: 'account_type', label: 'Kontotyp', required: true, type: 'select', options: [
      { value: 'Girokonto', label: 'Girokonto' },
      { value: 'Mietkonto', label: 'Mietkonto' },
      { value: 'Sparkonto', label: 'Sparkonto' },
      { value: 'Kautionskonto', label: 'Kautionskonto' },
    ]},
    { key: 'opening_balance', label: 'Anfangssaldo (€)', type: 'number', default: 0 },
    { key: 'balance', label: 'Aktueller Saldo (€)', type: 'number', default: 0 },
  ];

  return <CrudPage title="Konten" endpoint="/accounts" columns={COLUMNS} formFields={fields} />;
}
