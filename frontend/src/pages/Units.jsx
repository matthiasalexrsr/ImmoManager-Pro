import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';
import { useTranslation } from '../i18n';
import CrudPage from './CrudPage';

export default function Units() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [properties, setProperties] = useState([]);
  useEffect(() => { api.get('/properties').then(setProperties).catch(err => console.warn('[Units] properties:', err.message)); }, []);

  const columns = [
    { key: 'label', label: t('units.list.columns.label') || 'Bezeichnung', filterType: 'text' },
    { key: 'unit_type', label: t('units.list.columns.type') || 'Typ', filterType: 'select' },
    { key: 'area_sqm', label: t('units.list.columns.area') || 'Fläche (m²)', type: 'number', align: 'right', filterType: 'numberRange',
      render: v => v != null ? `${Number(v).toLocaleString('de-DE')} m²` : '—' },
    { key: 'cold_rent', label: t('units.list.columns.coldRent') || 'Kaltmiete (€)', type: 'number', align: 'right', filterType: 'numberRange',
      render: v => v != null ? `${Number(v).toFixed(2)} €` : '—' },
    { key: 'status', label: t('ui.form.status') || 'Status', type: 'status', filterType: 'select' },
  ];

  const fields = [
    { key: 'property_id', label: t('portfolio.properties.form.name') || 'Immobilie', required: true, type: 'select',
      options: properties.map(p => ({ value: p.id, label: p.name })) },
    { key: 'label', label: t('units.list.columns.label') || 'Bezeichnung', required: true, placeholder: 'z.B. Wohnung 1 OG links' },
    { key: 'unit_type', label: t('units.list.columns.type') || 'Typ', required: true, type: 'select', options: [
      { value: 'Wohnung', label: t('units.types.apartment') || 'Wohnung' },
      { value: 'Gewerbe', label: t('units.types.commercial') || 'Gewerbe' },
      { value: 'Stellplatz', label: t('units.types.parking') || 'Stellplatz' },
      { value: 'Keller', label: t('units.types.basement') || 'Keller' },
      { value: 'Sonstiges', label: t('units.types.other') || 'Sonstiges' },
    ]},
    { key: 'area_sqm', label: t('units.list.columns.area') || 'Fläche (m²)', type: 'number' },
    { key: 'rooms', label: t('units.form.rooms') || 'Zimmer', type: 'number' },
    { key: 'floor', label: t('units.form.floor') || 'Etage' },
    { key: 'cold_rent', label: t('units.list.columns.coldRent') || 'Kaltmiete (€)', type: 'number' },
    { key: 'service_charge_advance', label: t('units.form.serviceChargeAdvance') || 'NK-Vorauszahlung (€)', type: 'number' },
    { key: 'heating_advance', label: t('units.form.heatingAdvance') || 'Heizkosten-Vorauszahlung (€)', type: 'number' },
    { key: 'features', label: t('units.form.features') || 'Ausstattung', type: 'textarea', placeholder: 'z.B. Balkon, Einbauküche, Keller' },
    { key: 'status', label: t('ui.form.status') || 'Status', type: 'select', default: 'vacant', options: [
      { value: 'vacant', label: t('units.status.vacant') || 'Leer' },
      { value: 'occupied', label: t('units.status.occupied') || 'Vermietet' },
      { value: 'reserved', label: t('units.status.reserved') || 'Reserviert' },
    ]},
  ];

  return <CrudPage title={t('units.list.title') || 'Einheiten'} endpoint="/units" columns={columns} formFields={fields} onRowClick={row => navigate(`/units/${row.id}`)} />;
}
