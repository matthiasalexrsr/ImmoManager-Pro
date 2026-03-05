import { useState, useEffect } from 'react';
import { api } from '../api';
import CrudPage from './CrudPage';

const BASE_COLUMNS = [
  { key: 'contract_id', label: 'Vertrag', filterType: 'text' },
  { key: 'amount', label: 'Betrag (€)', type: 'number', align: 'right',
    render: v => v != null ? `${Number(v).toFixed(2)} €` : '—' },
  { key: 'status', label: 'Status', type: 'status', filterType: 'select' },
  { key: 'held_date', label: 'Hinterlegt am', type: 'date' },
  { key: 'return_date', label: 'Rückgabe', type: 'date' },
  { key: 'deductions', label: 'Abzüge (€)', type: 'number', align: 'right',
    render: v => v != null ? `${Number(v).toFixed(2)} €` : '—' },
];

export default function Deposits() {
  const [contracts, setContracts] = useState([]);
  useEffect(() => { api.get('/contracts').then(setContracts).catch(err => console.warn('[Deposits] contracts:', err.message)); }, []);

  const contractById = Object.fromEntries(contracts.map(contract => [contract.id, contract]));
  const columns = BASE_COLUMNS.map((column) => {
    if (column.key !== 'contract_id') return column;
    return {
      ...column,
      render: value => contractById[value]?.contract_number || value || '—',
    };
  });

  const fields = [
    { key: 'contract_id', label: 'Vertrag', required: true, type: 'select',
      options: contracts.map(c => ({ value: c.id, label: c.contract_number })) },
    { key: 'amount', label: 'Kautionsbetrag (€)', type: 'number', required: true },
    { key: 'status', label: 'Status', type: 'select', default: 'held', options: [
      { value: 'held', label: 'Hinterlegt' },
      { value: 'partially_returned', label: 'Teilweise zurückgegeben' },
      { value: 'returned', label: 'Zurückgegeben' },
    ]},
    { key: 'held_date', label: 'Hinterlegungsdatum', type: 'date' },
    { key: 'return_date', label: 'Rückgabedatum', type: 'date' },
    { key: 'deductions', label: 'Abzüge (€)', type: 'number' },
    { key: 'deduction_reason', label: 'Abzugsgrund', type: 'textarea' },
    { key: 'notes', label: 'Notizen', type: 'textarea' },
  ];

  return <CrudPage title="Kautionen" endpoint="/deposits" columns={columns} formFields={fields} />;
}
