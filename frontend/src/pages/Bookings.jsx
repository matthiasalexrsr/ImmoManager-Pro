import { useState, useEffect } from 'react';
import { api } from '../api';
import CrudPage from './CrudPage';

const COLUMNS = [
  { key: 'booking_date', label: 'Datum', type: 'date', filterType: 'dateRange' },
  { key: 'amount', label: 'Betrag (€)', type: 'number', align: 'right', filterType: 'numberRange',
    render: v => {
      const n = Number(v);
      const cls = n < 0 ? 'text-red' : 'text-green';
      return <span className={cls}>{n.toFixed(2)} €</span>;
    }},
  { key: 'payment_text', label: 'Buchungstext', filterType: 'text' },
  { key: 'status', label: 'Status', type: 'status', filterType: 'select' },
];

export default function Bookings() {
  const [accounts, setAccounts] = useState([]);
  useEffect(() => { api.get('/accounts').then(setAccounts).catch(err => console.warn('[Bookings] accounts:', err.message)); }, []);

  const fields = [
    { key: 'account_id', label: 'Konto', required: true, type: 'select',
      options: accounts.map(a => ({ value: a.id, label: a.name })) },
    { key: 'booking_date', label: 'Buchungsdatum', type: 'date', required: true },
    { key: 'amount', label: 'Betrag (€)', type: 'number', required: true },
    { key: 'payment_text', label: 'Buchungstext' },
    { key: 'status', label: 'Status', type: 'select', default: 'open', options: [
      { value: 'open', label: 'Offen' }, { value: 'matched', label: 'Zugeordnet' },
      { value: 'booked', label: 'Gebucht' },
    ]},
  ];

  return <CrudPage title="Buchungen" endpoint="/bookings" columns={COLUMNS} formFields={fields} />;
}
