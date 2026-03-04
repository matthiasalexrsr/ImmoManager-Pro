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
  const [categories, setCategories] = useState([]);
  const [properties, setProperties] = useState([]);
  const [units, setUnits] = useState([]);
  const [tenants, setTenants] = useState([]);

  useEffect(() => {
    Promise.all([
      api.get('/accounts').catch(err => { console.warn('[Bookings] accounts:', err.message); return []; }),
      api.get('/categories').catch(err => { console.warn('[Bookings] categories:', err.message); return []; }),
      api.get('/properties').catch(err => { console.warn('[Bookings] properties:', err.message); return []; }),
      api.get('/units').catch(err => { console.warn('[Bookings] units:', err.message); return []; }),
      api.get('/tenants').catch(err => { console.warn('[Bookings] tenants:', err.message); return []; }),
    ]).then(([a, c, p, u, t]) => {
      setAccounts(a);
      setCategories(c);
      setProperties(p);
      setUnits(u);
      setTenants(t);
    });
  }, []);

  const fields = [
    { key: 'account_id', label: 'Konto', required: true, type: 'select',
      options: accounts.map(a => ({ value: a.id, label: a.name })) },
    { key: 'category_id', label: 'Kategorie', type: 'select',
      options: [{ value: '', label: '— Keine —' }, ...categories.map(c => ({ value: c.id, label: c.name }))] },
    { key: 'property_id', label: 'Immobilie', type: 'select',
      options: [{ value: '', label: '— Keine —' }, ...properties.map(p => ({ value: p.id, label: p.name }))] },
    { key: 'unit_id', label: 'Einheit', type: 'select',
      options: [{ value: '', label: '— Keine —' }, ...units.map(u => ({ value: u.id, label: u.label }))] },
    { key: 'tenant_id', label: 'Mieter', type: 'select',
      options: [{ value: '', label: '— Kein —' }, ...tenants.map(t => ({ value: t.id, label: t.full_name }))] },
    { key: 'booking_date', label: 'Buchungsdatum', type: 'date', required: true },
    { key: 'amount', label: 'Betrag (€)', type: 'number', required: true },
    { key: 'payment_text', label: 'Buchungstext' },
    { key: 'receipt_url', label: 'Beleg-URL', placeholder: '/belege/beleg.pdf' },
    { key: 'status', label: 'Status', type: 'select', default: 'open', options: [
      { value: 'open', label: 'Offen' }, { value: 'matched', label: 'Zugeordnet' },
      { value: 'booked', label: 'Gebucht' },
    ]},
  ];

  return <CrudPage title="Buchungen" endpoint="/bookings" columns={COLUMNS} formFields={fields} />;
}
