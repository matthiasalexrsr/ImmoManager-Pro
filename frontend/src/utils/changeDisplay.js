// Recorded field changes in words: the field's name and its old and new value as the forms show them.
import { codeLabel } from './codeLabels';
import { formatDate, formatMoney } from './format';

const FIELD_LABELS = {
  title: 'Titel', name: 'Name', full_name: 'Name', label: 'Bezeichnung', status: 'Status', priority: 'Priorität',
  description: 'Beschreibung', notes: 'Notizen', body: 'Notiz', reason: 'Grund', assignee: 'Zuständigkeit',
  email: 'E-Mail', phone: 'Telefon', address: 'Anschrift', address_line: 'Straße', street: 'Straße',
  city: 'Ort', postal_code: 'Postleitzahl', country: 'Land', company_name: 'Firma', first_name: 'Vorname', last_name: 'Nachname',
  type: 'Art', property_type: 'Immobilienart', document_type: 'Dokumentart', payment_method: 'Zahlungsart',
  frequency: 'Intervall', role: 'Rolle', due_date: 'Fälligkeit', start_date: 'Beginn', end_date: 'Ende',
  booking_date: 'Buchungsdatum', invoice_date: 'Rechnungsdatum', received_on: 'Eingangsdatum', protocol_date: 'Protokolldatum',
  next_inspection: 'Nächste Prüfung', actual_move_in_date: 'Tatsächlicher Einzug', amount: 'Betrag', total_amount: 'Gesamtbetrag',
  cold_rent: 'Kaltmiete', service_charge_advance: 'Nebenkostenvorauszahlung', heating_advance: 'Heizkostenvorauszahlung',
  amount_paid: 'Bezahlt', deposit: 'Kaution', area: 'Fläche', archived: 'Archiviert', active: 'Aktiv',
  recoverable: 'Umlagefähig', is_recoverable: 'Umlagefähig', sepa_mandate: 'SEPA-Mandat',
  severity: 'Schweregrad', location: 'Ort', condition: 'Zustand', remedy: 'Maßnahme',
  property_id: 'Immobilienkennung', unit_id: 'Einheitenkennung', tenant_id: 'Parteikennung', contract_id: 'Vertragskennung',
  document_id: 'Dokumentkennung', account_id: 'Kontokennung', category_id: 'Kategorienkennung',
  statement_id: 'Abrechnungskennung',
  area_sqm: 'Fläche (m²)', rooms: 'Zimmerzahl', person_count: 'Personenzahl',
  net_amount: 'Nettobetrag', gross_amount: 'Bruttobetrag', vat_amount: 'Mehrwertsteuerbetrag', vat_rate: 'Mehrwertsteuersatz',
  invoice_number: 'Rechnungsnummer', supplier: 'Lieferant', currency: 'Währung', payment_reference: 'Verwendungszweck',
  amount_due: 'Forderungsbetrag', deposit_amount: 'Kautionsbetrag', account_number: 'Kontonummer', iban: 'IBAN', bic: 'BIC',
  carried_on: 'Stichtag der Kautionsübernahme', carried_amount: 'Übernommener Kautionsbetrag', carried_interest: 'Übernommene Zinsen', carried_note: 'Übernahmevermerk',
};
const DATE_FIELDS = new Set(['due_date', 'start_date', 'end_date', 'booking_date', 'invoice_date', 'received_on', 'protocol_date', 'next_inspection', 'actual_move_in_date', 'carried_on']);
const BOOLEAN_FIELDS = new Set(['archived', 'active', 'recoverable', 'is_recoverable']);
const CODE_FIELDS = new Set(['status', 'priority', 'type', 'property_type', 'document_type', 'payment_method', 'frequency', 'role', 'condition']);
const MONEY_FIELDS = new Set(['amount', 'total_amount', 'cold_rent', 'service_charge_advance', 'heating_advance', 'amount_paid', 'deposit',
  'net_amount', 'gross_amount', 'vat_amount', 'amount_due', 'deposit_amount', 'carried_amount', 'carried_interest']);

// the record kinds the history names
const KIND_LABELS = {
  property: 'Immobilie', unit: 'Einheit', tenant: 'Partei', contract: 'Vertrag', receivable: 'Forderung',
  maintenance: 'Schadensfall', task: 'Aufgabe', invoice: 'Rechnung', contact: 'Kontakt', booking: 'Buchung',
  document: 'Dokument', deposit: 'Kaution', meter: 'Zähler', insurance: 'Versicherung', lead: 'Interessent',
  handover_protocol: 'Übergabeprotokoll', service_contract: 'Objektvertrag', rent_charge: 'Mietsoll',
};

export const plainField = field => field?.startsWith('defect:') ? field.split(':').slice(2).join(':') : field;

export function fieldLabel(field) {
  const key = plainField(field);
  const label = FIELD_LABELS[key] || (key?.endsWith('_id') ? `${key.slice(0, -3)} (Kennung)` : key);
  return field?.startsWith('defect:') ? `Mangel (Kennung ${field.split(':')[1]}) – ${label}` : label;
}

export function kindLabel(kind) {
  return KIND_LABELS[kind] || codeLabel(kind);
}

export function changeValue(field, value, t) {
  const key = plainField(field);
  if (value == null || (typeof value === 'string' && !value.trim())) return 'Nicht angegeben';
  if (typeof value === 'boolean') return value ? 'Ja' : 'Nein';
  if (BOOLEAN_FIELDS.has(key) && /^(true|false)$/i.test(String(value))) return String(value).toLowerCase() === 'true' ? 'Ja' : 'Nein';
  if (DATE_FIELDS.has(key) && typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value)) return formatDate(value);
  if (MONEY_FIELDS.has(key) && /^-?\d+(\.\d+)?$/.test(String(value).trim())) return formatMoney(Number(value));
  if (CODE_FIELDS.has(key) && typeof value === 'string') {
    const translation = t?.(`status.badge.${value}`);
    return translation && translation !== `status.badge.${value}` ? translation : codeLabel(value);
  }
  return typeof value === 'object' ? JSON.stringify(value) : String(value);
}
