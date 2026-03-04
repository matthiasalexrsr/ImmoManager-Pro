import { useState, useEffect } from 'react';
import { api } from '../api';
import CrudPage from './CrudPage';

const COLUMNS = [
  { key: 'title', label: 'Titel', filterType: 'text' },
  { key: 'document_type', label: 'Typ', filterType: 'select' },
  { key: 'document_date', label: 'Datum', type: 'date', filterType: 'dateRange' },
  { key: 'tags', label: 'Tags', filterType: 'text' },
];

export default function Documents() {
  const [properties, setProperties] = useState([]);
  const [units, setUnits] = useState([]);
  const [contracts, setContracts] = useState([]);

  useEffect(() => {
    Promise.all([
      api.get('/properties').catch(err => { console.warn('[Documents] properties:', err.message); return []; }),
      api.get('/units').catch(err => { console.warn('[Documents] units:', err.message); return []; }),
      api.get('/contracts').catch(err => { console.warn('[Documents] contracts:', err.message); return []; }),
    ]).then(([p, u, c]) => { setProperties(p); setUnits(u); setContracts(c); });
  }, []);

  const fields = [
    { key: 'title', label: 'Titel', required: true },
    { key: 'document_type', label: 'Dokumententyp', type: 'select', options: [
      { value: 'Mietvertrag', label: 'Mietvertrag' },
      { value: 'Rechnung', label: 'Rechnung' },
      { value: 'Nebenkostenabrechnung', label: 'Nebenkostenabrechnung' },
      { value: 'Protokoll', label: 'Protokoll' },
      { value: 'Versicherung', label: 'Versicherung' },
      { value: 'Sonstiges', label: 'Sonstiges' },
    ]},
    { key: 'document_date', label: 'Datum', type: 'date' },
    { key: 'property_id', label: 'Immobilie', type: 'select',
      options: [{ value: '', label: '— Keine —' }, ...properties.map(p => ({ value: p.id, label: p.name }))] },
    { key: 'unit_id', label: 'Einheit', type: 'select',
      options: [{ value: '', label: '— Keine —' }, ...units.map(u => ({ value: u.id, label: u.label }))] },
    { key: 'contract_id', label: 'Vertrag', type: 'select',
      options: [{ value: '', label: '— Kein —' }, ...contracts.map(c => ({ value: c.id, label: c.contract_number }))] },
    { key: 'description', label: 'Beschreibung', type: 'textarea' },
    { key: 'tags', label: 'Tags', placeholder: 'kommagetrennt' },
    { key: 'file_url', label: 'Datei-URL', required: true, placeholder: '/dokumente/vertrag.pdf' },
  ];

  return <CrudPage title="Dokumente" endpoint="/documents" columns={COLUMNS} formFields={fields} />;
}
