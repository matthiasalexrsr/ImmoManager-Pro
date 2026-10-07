// Document types the program sets itself are stored as stable keys; people see a name.
const GENERATED = { housing_confirmation: 'Wohnungsgeberbestätigung' };

export function documentTypeLabel(type) {
  return GENERATED[type] || type;
}
