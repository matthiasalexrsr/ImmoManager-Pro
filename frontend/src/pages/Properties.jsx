import { useNavigate } from 'react-router-dom';
import { useTranslation } from '../i18n';
import { useEntities } from '../contexts/DataStoreContext';
import CrudPage from './CrudPage';

export default function Properties() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { items: portfolios } = useEntities('portfolios', '/portfolios');

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

  const sStamm = t('portfolio.properties.sections.basic') || 'Stammdaten';
  const sAddr = t('portfolio.properties.sections.address') || 'Adresse';
  const sArea = t('portfolio.properties.sections.areas') || 'Flächen';
  const sFin = t('portfolio.properties.sections.valuation') || 'Kauf & Bewertung';

  const fields = [
    { section: sStamm, key: 'portfolio_id', label: 'Portfolio', required: true, type: 'select',
      options: portfolios.map(p => ({ value: p.id, label: p.name })) },
    { section: sStamm, key: 'name', label: t('portfolio.properties.form.name') || 'Name', required: true },
    { section: sStamm, key: 'property_type', label: t('portfolio.properties.form.type') || 'Typ', required: true, type: 'select', options: [
      { value: 'residential', label: t('portfolio.properties.types.residential') || 'Wohngebäude' },
      { value: 'commercial', label: t('portfolio.properties.types.commercial') || 'Gewerbe' },
      { value: 'mixed', label: t('portfolio.properties.types.mixed') || 'Gemischt' },
    ]},
    { section: sStamm, key: 'status', label: t('ui.form.status') || 'Status', type: 'select', default: 'active', options: [
      { value: 'active', label: t('tenantsContracts.contracts.status.active') || 'Aktiv' },
      { value: 'inactive', label: t('portfolio.properties.status.inactive') || 'Inaktiv' },
    ]},
    { section: sAddr, key: 'address_line', label: t('portfolio.properties.form.address') || 'Straße' },
    { section: sAddr, key: 'postal_code', label: t('portfolio.properties.form.postalCode') || 'PLZ' },
    { section: sAddr, key: 'city', label: t('portfolio.properties.form.city') || 'Stadt' },
    { section: sAddr, key: 'country', label: t('portfolio.properties.form.country') || 'Land', default: 'DE' },
    { section: sArea, key: 'year_built', label: t('portfolio.properties.form.yearBuilt') || 'Baujahr', type: 'number' },
    { section: sArea, key: 'living_area_sqm', label: t('portfolio.properties.form.livingArea') || 'Wohnfläche (m²)', type: 'number' },
    { section: sArea, key: 'usable_area_sqm', label: t('portfolio.properties.form.usableArea') || 'Nutzfläche (m²)', type: 'number' },
    { section: sArea, key: 'plot_area_sqm', label: t('portfolio.properties.form.plotArea') || 'Grundstücksfläche (m²)', type: 'number' },
    { section: sArea, key: 'ownership_share', label: t('portfolio.properties.form.ownershipShare') || 'Eigentumsanteil (%)', type: 'number' },
    { section: sFin, key: 'purchase_price', label: t('portfolio.properties.form.purchasePrice') || 'Kaufpreis (€)', type: 'number' },
    { section: sFin, key: 'purchase_date', label: t('portfolio.properties.form.purchaseDate') || 'Kaufdatum', type: 'date' },
    { section: sFin, key: 'market_value', label: t('portfolio.properties.form.marketValue') || 'Marktwert (€)', type: 'number' },
    { section: sFin, key: 'valuation_date', label: t('portfolio.properties.form.valuationDate') || 'Bewertungsdatum', type: 'date' },
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
