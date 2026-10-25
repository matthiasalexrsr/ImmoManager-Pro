// The cost types of the utility statement (backend services/billing_guide.BETRKV, ai_surfaces.COST_CATEGORIES):
// stored as codes, shown with these names.
export const COST_CATEGORIES = [
  ['heating', 'Heizkosten'], ['hot_water', 'Warmwasser'], ['water', 'Wasser und Abwasser'], ['electricity', 'Allgemeinstrom'],
  ['garbage', 'Müllabfuhr'], ['street_cleaning', 'Straßenreinigung'], ['cleaning', 'Gebäudereinigung'], ['garden', 'Gartenpflege'],
  ['caretaker', 'Hauswart'], ['insurance', 'Versicherung'], ['property_tax', 'Grundsteuer'], ['elevator', 'Aufzug'],
  ['chimney', 'Schornsteinfeger'], ['cable', 'Kabel/Antenne'], ['laundry', 'Wäschepflege'], ['maintenance', 'Instandhaltung'],
  ['administration', 'Verwaltung'], ['other', 'Sonstiges'],
];

export const costCategoryLabel = code => COST_CATEGORIES.find(([value]) => value === code)?.[1] || code;
