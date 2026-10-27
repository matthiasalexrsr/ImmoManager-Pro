// German states by their two-letter code (backend: domain/calendar_days.STATES)
export const FEDERAL_STATES = [
  ['BW', 'Baden-Württemberg'], ['BY', 'Bayern'], ['BE', 'Berlin'], ['BB', 'Brandenburg'], ['HB', 'Bremen'],
  ['HH', 'Hamburg'], ['HE', 'Hessen'], ['MV', 'Mecklenburg-Vorpommern'], ['NI', 'Niedersachsen'],
  ['NW', 'Nordrhein-Westfalen'], ['RP', 'Rheinland-Pfalz'], ['SL', 'Saarland'], ['SN', 'Sachsen'],
  ['ST', 'Sachsen-Anhalt'], ['SH', 'Schleswig-Holstein'], ['TH', 'Thüringen'],
].map(([value, label]) => ({ value, label }));

// The property form, shared by the property list and the property page.
export function propertyFields(t, portfolios) {
  const sStamm = t('portfolio.properties.sections.basic') || 'Stammdaten';
  const sAddr = t('portfolio.properties.sections.address') || 'Adresse';
  const sArea = t('portfolio.properties.sections.areas') || 'Flächen';
  const sFin = t('portfolio.properties.sections.valuation') || 'Kauf & Bewertung';

  return [
    { section: sStamm, key: 'portfolio_id', label: 'Portfolio', required: true, type: 'select',
      options: portfolios.map(p => ({ value: p.id, label: p.name })) },
    { section: sStamm, key: 'name', label: t('portfolio.properties.form.name') || 'Name', required: true },
    { section: sStamm, key: 'property_type', label: t('portfolio.properties.form.type') || 'Typ', required: true, type: 'select', default: 'residential', options: [
      { value: 'residential', label: t('portfolio.properties.types.residential') || 'Wohngebäude' },
      { value: 'commercial', label: t('portfolio.properties.types.commercial') || 'Gewerbe' },
      { value: 'mixed', label: t('portfolio.properties.types.mixed') || 'Gemischt' },
    ]},
    { section: sStamm, key: 'status', label: t('ui.form.status') || 'Status', type: 'select', default: 'active', options: [
      { value: 'active', label: t('status.general.active') || 'Aktiv' },
      { value: 'inactive', label: t('portfolio.properties.status.inactive') || 'Inaktiv' },
    ]},
    { section: sAddr, key: 'address_line', label: t('portfolio.properties.form.address') || 'Straße' },
    { section: sAddr, key: 'postal_code', label: t('portfolio.properties.form.postalCode') || 'PLZ' },
    { section: sAddr, key: 'city', label: t('portfolio.properties.form.city') || 'Stadt' },
    { section: sAddr, key: 'federal_state', label: 'Bundesland', type: 'select', options: FEDERAL_STATES,
      hint: 'Seine Feiertage zählen für die Fälligkeit der Miete, Kündigungsfristen und Fristen in der Arbeitszentrale. '
        + 'Ohne Angabe zählen nur die bundesweiten.' },
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
}
