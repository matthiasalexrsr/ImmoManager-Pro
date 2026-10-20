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
  { key: 'sepa_mandate', label: 'SEPA-Mandat', placeholder: 'Mandatsreferenz', hint: 'Bis 35 Zeichen ohne Leerzeichen und Umlaute, z. B. MR-2024-017' },
  { key: 'sepa_mandate_date', label: 'Mandat unterschrieben am', type: 'date' },
  { key: 'sepa_iban', label: 'IBAN für die Lastschrift', placeholder: 'DE12 3456 7890 1234 5678 90',
    hint: 'Für die SEPA-Lastschriftdatei; die Prüfziffer wird geprüft.' },
  { key: 'sepa_bic', label: 'BIC (optional)', placeholder: '8 oder 11 Zeichen' },
  { key: 'sepa_account_holder', label: 'Kontoinhaber', placeholder: 'Nur wenn nicht der Mieter selbst' },
  { key: 'notes', label: 'Notizen', type: 'textarea' },
];
