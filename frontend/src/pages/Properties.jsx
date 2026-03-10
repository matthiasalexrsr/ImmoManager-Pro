import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';
import { useTranslation } from '../i18n';
import CrudPage from './CrudPage';

export default function Properties() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [portfolios, setPortfolios] = useState([]);
  useEffect(() => { api.get('/portfolios').then(setPortfolios).catch(() => {}); }, []);

  const columns = [
    { key: 'name', label: t('portfolio.properties.form.name') || 'Name', filterType: 'text' },
    { key: 'property_type', label: t('portfolio.properties.form.type') || 'Typ', filterType: 'select' },
    { key: 'city', label: t('portfolio.properties.form.city') || 'Stadt', filterType: 'text' },
    { key: 'postal_code', label: t('portfolio.properties.form.postalCode') || 'PLZ', filterType: 'text' },
    { key: 'year_built', label: t('portfolio.properties.form.yearBuilt') || 'Baujahr', type: 'number' },
    { key: 'living_area_sqm', label: t('portfolio.properties.form.livingArea') || 'Wohnfläche (m²)', type: 'number', align: 'right',
      render: v => v != null ? `${Number(v).toLocaleString('de-DE')} m²` : '—' },
    { key: 'status', label: t('ui.form.status') || 'Status', type: 'status', filterType: 'select' },
  ];

  const fields = [
    { key: 'portfolio_id', label: 'Portfolio', required: true, type: 'select',
      options: portfolios.map(p => ({ value: p.id, label: p.name })) },
    { key: 'name', label: t('portfolio.properties.form.name') || 'Name', required: true },
    { key: 'property_type', label: t('portfolio.properties.form.type') || 'Typ', required: true, type: 'select', options: [
      { value: 'residential', label: t('portfolio.properties.types.residential') || 'Wohngebäude' },
      { value: 'commercial', label: t('portfolio.properties.types.commercial') || 'Gewerbe' },
      { value: 'mixed', label: t('portfolio.properties.types.mixed') || 'Gemischt' },
    ]},
    { key: 'address_line', label: t('portfolio.properties.form.address') || 'Straße' },
    { key: 'postal_code', label: t('portfolio.properties.form.postalCode') || 'PLZ' },
    { key: 'city', label: t('portfolio.properties.form.city') || 'Stadt' },
    { key: 'country', label: t('portfolio.properties.form.country') || 'Land', default: 'DE' },
    { key: 'year_built', label: t('portfolio.properties.form.yearBuilt') || 'Baujahr', type: 'number' },
    { key: 'living_area_sqm', label: t('portfolio.properties.form.livingArea') || 'Wohnfläche (m²)', type: 'number' },
    { key: 'usable_area_sqm', label: t('portfolio.properties.form.usableArea') || 'Nutzfläche (m²)', type: 'number' },
    { key: 'plot_area_sqm', label: t('portfolio.properties.form.plotArea') || 'Grundstücksfläche (m²)', type: 'number' },
    { key: 'ownership_share', label: t('portfolio.properties.form.ownershipShare') || 'Eigentumsanteil (%)', type: 'number' },
    { key: 'purchase_price', label: t('portfolio.properties.form.purchasePrice') || 'Kaufpreis (€)', type: 'number' },
    { key: 'purchase_date', label: t('portfolio.properties.form.purchaseDate') || 'Kaufdatum', type: 'date' },
    { key: 'market_value', label: t('portfolio.properties.form.marketValue') || 'Marktwert (€)', type: 'number' },
    { key: 'valuation_date', label: t('portfolio.properties.form.valuationDate') || 'Bewertungsdatum', type: 'date' },
    { key: 'status', label: t('ui.form.status') || 'Status', type: 'select', default: 'active', options: [
      { value: 'active', label: t('tenantsContracts.contracts.status.active') || 'Aktiv' },
      { value: 'inactive', label: t('portfolio.properties.status.inactive') || 'Inaktiv' },
    ]},
  ];

  return (
    <CrudPage
      title={t('portfolio.properties.title') || 'Immobilien'}
      endpoint="/properties"
      columns={columns}
      formFields={fields}
      onRowClick={row => navigate(`/properties/${row.id}`)}
    />
  );
}
