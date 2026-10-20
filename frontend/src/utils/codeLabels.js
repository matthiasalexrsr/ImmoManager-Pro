// Stored codes (residential, yearly, income …) as words in lists; forms keep their own option labels.
import { getFormatLocale } from './format';

const DE = {
  residential: 'Wohnen', commercial: 'Gewerbe', mixed: 'Gemischt', parking: 'Stellplatz', garage: 'Garage',
  flat: 'Wohnung', apartment: 'Wohnung',
  condominium: 'Eigentumswohnung', single_family: 'Einfamilienhaus', multi_family: 'Mehrfamilienhaus',
  office: 'Büro', storage: 'Lager', land: 'Grundstück',
  income: 'Einnahme', expense: 'Ausgabe',
  monthly: 'Monatlich', quarterly: 'Vierteljährlich', yearly: 'Jährlich', annual: 'Jährlich', half_yearly: 'Halbjährlich',
  building: 'Gebäudeversicherung', liability: 'Haftpflicht', contents: 'Hausrat', legal: 'Rechtsschutz',
  rent_loss: 'Mietausfall', elementary: 'Elementarschaden',
  increase: 'Erhöhung', decrease: 'Senkung', index: 'Indexmiete', stepped: 'Staffelmiete', fixed: 'Festmiete',
  comparative: 'Vergleichsmiete', modernization: 'Modernisierung',
  contract: 'Vertrag', invoice: 'Rechnung', receipt: 'Beleg', protocol: 'Protokoll', statement: 'Abrechnung',
  receivable: 'Forderung', maintenance: 'Wartung', task: 'Aufgabe',
  move_in: 'Einzug', move_out: 'Auszug',
  cold_water: 'Kaltwasser', hot_water: 'Warmwasser', heating: 'Heizung', electricity: 'Strom', gas: 'Gas',
  area_sqm: 'Fläche (m²)', unit_count: 'Anzahl Einheiten', person_count: 'Personenzahl', consumption: 'Verbrauch',
  bank_transfer: 'Überweisung', transfer: 'Überweisung', sepa_direct_debit: 'SEPA-Lastschrift', cash: 'Bar',
  bank: 'Bank', cashbox: 'Kasse', savings: 'Sparkonto',
  good: 'Gut', fair: 'Befriedigend', poor: 'Mangelhaft',
  tenant: 'Mieter', owner: 'Eigentümer', manager: 'Verwalter', supplier: 'Dienstleister',
  published: 'Veröffentlicht',
  // statuses, as the status badges name them
  accepted: 'Angenommen', active: 'Aktiv', applied: 'Angewendet', approved: 'Freigegeben', archived: 'Archiviert',
  booked: 'Gebucht', cancelled: 'Storniert', closed: 'Geschlossen', completed: 'Erledigt', confirmed: 'Bestätigt',
  contacted: 'Kontaktiert', corrected: 'Korrigiert', critical: 'Kritisch', delivered: 'Zugestellt', disputed: 'Widersprochen',
  done: 'Erledigt', draft: 'Entwurf', expired: 'Ausgelaufen', failed: 'Fehlgeschlagen', finalized: 'Abgeschlossen',
  held: 'Verwahrt', high: 'Hoch', in_progress: 'In Bearbeitung', inactive: 'Inaktiv', low: 'Niedrig', matched: 'Zugeordnet',
  medium: 'Mittel', new: 'Neu', no_show: 'Nicht erschienen', normal: 'Normal', occupied: 'Vermietet',
  offer_sent: 'Angebot gesendet', open: 'Offen', overdue: 'Überfällig', paid: 'Bezahlt', partial: 'Teilbezahlt',
  partially_paid: 'Teilbezahlt', partially_returned: 'Teilweise zurückgezahlt', paused: 'Pausiert', pending: 'Ausstehend',
  planned: 'Geplant', processing: 'In Bearbeitung', proposed: 'Vorgeschlagen', read: 'Gelesen', received: 'Eingegangen',
  rejected: 'Abgelehnt', renovation: 'Renovierung', reserved: 'Reserviert', resolved: 'Erledigt', returned: 'Zurückgezahlt',
  review: 'In Prüfung', scheduled: 'Geplant', sent: 'Gesendet', signed: 'Unterschrieben', succeeded: 'Erfolgreich',
  terminated: 'Gekündigt', unread: 'Ungelesen', urgent: 'Dringend', vacant: 'Leer', viewing_scheduled: 'Besichtigung geplant',
  warning: 'Warnung', info: 'Hinweis', withdrawn: 'Zurückgezogen', written_off: 'Ausgebucht', not_configured: 'Nicht eingerichtet',
  configured: 'Eingerichtet', connected: 'Verbunden', unknown: 'Unbekannt',
  // appointments, notification kinds and other short keys
  viewing: 'Besichtigung', inspection: 'Begehung', meeting: 'Besprechung', deadline: 'Frist', other: 'Sonstiges',
  general: 'Allgemein', overdue_payment: 'Überfällige Zahlung', contract_expiry: 'Vertragsende', task_due: 'Aufgabe fällig',
  document_expiry: 'Dokument läuft ab',
  escalation: 'Eskalation', dunning_proposal: 'Mahnvorschlag', notify: 'Benachrichtigen', escalate_priority: 'Priorität erhöhen',
  vacancy: 'Leerstand', property: 'Immobilie', unit: 'Einheit', contact: 'Kontakt', document: 'Dokument',
  installation: 'Einbau', replacement: 'Austausch', reading: 'Ablesung', manual: 'Manuell', auto: 'Automatisch',
  deposit_account: 'Kautionskonto', guarantee: 'Bürgschaft', pledged_savings: 'Verpfändetes Sparbuch',
  credit_note: 'Gutschrift', service_contract: 'Objektvertrag', letter: 'Schreiben', rent_adjustment: 'Mietanpassung',
  housing_confirmation: 'Wohnungsgeberbestätigung', handover_protocol: 'Übergabeprotokoll', dunning_letter: 'Mahnschreiben',
  billing_statement_letter: 'Abrechnungsschreiben', template_letter: 'Brief',
  deposit_settlement: 'Kautionsabrechnung', maintenance_protocol: 'Instandhaltungsprotokoll', teha_original: 'TEHA-Original',
  true: 'Ja', false: 'Nein',
};

const CODE = /^[a-z][a-z_]*$/;

export function codeLabel(value) {
  if (typeof value === 'boolean') return getFormatLocale().startsWith('de') ? (value ? 'Ja' : 'Nein') : (value ? 'Yes' : 'No');
  if (typeof value !== 'string' || !CODE.test(value)) return value;
  if (getFormatLocale().startsWith('de')) return DE[value] ?? value;
  return value.includes('_') ? value[0].toUpperCase() + value.slice(1).replace(/_/g, ' ') : value;
}
