// A required choice that has nothing to choose from yet (a fresh installation): what is missing
// and where it is created. The target lists open their New form for ?neu=1.
export const PREREQUISITES = {
  portfolio_id: { text: 'Noch kein Portfolio angelegt.', to: '/portfolios?neu=1', label: 'Portfolio anlegen' },
  property_id: { text: 'Noch keine Immobilie angelegt.', to: '/properties?neu=1', label: 'Immobilie anlegen' },
  unit_id: { text: 'Noch keine Einheit angelegt.', to: '/units?neu=1', label: 'Einheit anlegen' },
  tenant_id: { text: 'Noch kein Mieter angelegt.', to: '/tenants?neu=1', label: 'Mieter anlegen' },
  account_id: { text: 'Noch kein Konto angelegt.', to: '/accounts?neu=1', label: 'Konto anlegen' },
  category_id: { text: 'Noch keine Kategorie angelegt.', to: '/categories?neu=1', label: 'Kategorie anlegen' },
  contract_id: { text: 'Noch kein Mietvertrag angelegt.', to: '/contracts?neu=1', label: 'Vertrag anlegen' },
};

/** The hint for an empty required choice, or null. Choices that depend on another field
 * (units of the chosen property) only get one when the page names it: before the other field
 * is chosen they are empty for a different reason. */
export function prerequisiteFor(field, options) {
  if (field.type !== 'select' || !field.required || (options && options.length > 0)) return null;
  if (field.emptyHint !== undefined) return field.emptyHint;
  return typeof field.options === 'function' ? null : PREREQUISITES[field.key] || null;
}

/** Required choices with exactly one possibility, made already: {key: value}. */
export function onlyChoices(fields, values) {
  const picks = {};
  fields.forEach(field => {
    if (field.type !== 'select' || !field.required || field.autoSelect === false) return;
    if (values[field.key] !== '' && values[field.key] != null) return;
    const options = typeof field.options === 'function' ? field.options(values) : field.options;
    if (options?.length === 1) picks[field.key] = String(options[0].value);
  });
  return picks;
}
