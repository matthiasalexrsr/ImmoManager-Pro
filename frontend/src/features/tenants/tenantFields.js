// The tenant form, the same on the tenants list and on a tenant's account page.
export const PAYMENT_METHODS = [
  { value: 'bank_transfer', label: 'Überweisung' },
  { value: 'sepa_direct_debit', label: 'SEPA-Lastschrift' },
  { value: 'cash', label: 'Bar' },
];

export const TENANT_FIELDS = [
  { key: 'full_name', label: 'Vollständiger Name', required: true },
  { key: 'email', label: 'E-Mail', type: 'email' },
  { key: 'phone', label: 'Telefon' },
  { key: 'address_line', label: 'Straße' },
  { key: 'postal_code', label: 'PLZ' },
  { key: 'city', label: 'Stadt' },
  { key: 'country', label: 'Land', default: 'DE' },
  { key: 'payment_method', label: 'Zahlungsart', type: 'select', options: PAYMENT_METHODS },
  { key: 'sepa_mandate', label: 'SEPA-Mandat', placeholder: 'Mandatsreferenz' },
  { key: 'notes', label: 'Notizen', type: 'textarea' },
];
