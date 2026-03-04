import { useState, useEffect } from 'react';
import { api } from '../api';
import CrudPage from './CrudPage';

const COLUMNS = [
  { key: 'contract_number', label: 'Vertragsnr.', filterType: 'text' },
  { key: 'start_date', label: 'Beginn', type: 'date', filterType: 'dateRange' },
  { key: 'end_date', label: 'Ende', type: 'date', filterType: 'dateRange' },
  { key: 'deposit_amount', label: 'Kaution (€)', type: 'number', align: 'right',
    render: v => v != null ? `${Number(v).toFixed(2)} €` : '—' },
  { key: 'status', label: 'Status', type: 'status', filterType: 'select' },
];

export default function Contracts() {
  const [properties, setProperties] = useState([]);
  const [units, setUnits] = useState([]);
  const [tenants, setTenants] = useState([]);

  useEffect(() => {
    Promise.all([
      api.get('/properties').catch(() => []),
      api.get('/units').catch(() => []),
      api.get('/tenants').catch(() => []),
    ]).then(([p, u, t]) => { setProperties(p); setUnits(u); setTenants(t); });
  }, []);

  const fields = [
    { key: 'contract_number', label: 'Vertragsnr.', required: true, placeholder: 'z.B. MV-2024-001' },
    { key: 'property_id', label: 'Immobilie', required: true, type: 'select',
      options: properties.map(p => ({ value: p.id, label: p.name })) },
    { key: 'unit_id', label: 'Einheit', required: true, type: 'select',
      options: units.map(u => ({ value: u.id, label: u.label })) },
    { key: 'tenant_id', label: 'Mieter', required: true, type: 'select',
      options: tenants.map(t => ({ value: t.id, label: t.full_name })) },
    { key: 'start_date', label: 'Vertragsbeginn', type: 'date', required: true },
    { key: 'end_date', label: 'Vertragsende', type: 'date' },
    { key: 'deposit_amount', label: 'Kaution (€)', type: 'number' },
    { key: 'notice_period', label: 'Kündigungsfrist', placeholder: 'z.B. 3 Monate' },
    { key: 'status', label: 'Status', type: 'select', default: 'active', options: [
      { value: 'active', label: 'Aktiv' }, { value: 'terminated', label: 'Gekündigt' },
      { value: 'expired', label: 'Ausgelaufen' }, { value: 'draft', label: 'Entwurf' },
    ]},
  ];

  return <CrudPage title="Verträge" endpoint="/contracts" columns={COLUMNS} formFields={fields} />;
}
