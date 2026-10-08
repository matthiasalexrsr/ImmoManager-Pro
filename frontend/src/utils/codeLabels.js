// Stored codes (residential, yearly, income …) as words in lists; forms keep their own option labels.
import { getFormatLocale } from './format';

const DE = {
  residential: 'Wohnen', commercial: 'Gewerbe', mixed: 'Gemischt', parking: 'Stellplatz', garage: 'Garage',
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
  bank_transfer: 'Überweisung', transfer: 'Überweisung', sepa_direct_debit: 'SEPA-Lastschrift', cash: 'Bar',
  bank: 'Bank', cashbox: 'Kasse', savings: 'Sparkonto',
  good: 'Gut', fair: 'Befriedigend', poor: 'Mangelhaft',
  tenant: 'Mieter', owner: 'Eigentümer', manager: 'Verwalter', supplier: 'Dienstleister',
};

const CODE = /^[a-z][a-z_]*$/;

export function codeLabel(value) {
  if (typeof value !== 'string' || !CODE.test(value)) return value;
  if (getFormatLocale().startsWith('de')) return DE[value] ?? value;
  return value.includes('_') ? value[0].toUpperCase() + value.slice(1).replace(/_/g, ' ') : value;
}
