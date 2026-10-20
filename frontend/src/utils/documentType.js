// Document types the program sets itself (and short keys of imported data) are stored as stable keys; people see a name.
import { codeLabel } from './codeLabels';

export function documentTypeLabel(type) {
  return codeLabel(type);
}

// Types of the document form: stored value and translation key of its name.
const FORM_TYPES = [['Mietvertrag', 'mietvertrag'], ['Rechnung', 'rechnung'], ['Nebenkostenabrechnung', 'nebenkostenabrechnung'],
  ['Protokoll', 'protokoll'], ['Versicherung', 'versicherung'], ['Grundbuchauszug', 'grundbuchauszug'],
  ['Energieausweis', 'energieausweis'], ['Betriebskostenabrechnung', 'betriebskostenabrechnung'], ['Mahnung', 'mahnung'],
  ['Kündigung', 'kuendigung'], ['Übergabeprotokoll', 'uebergabeprotokoll'], ['Handwerkerrechnung', 'handwerkerrechnung'],
  ['Steuerbescheid', 'steuerbescheid'], ['Sonstiges', 'sonstiges']];

export function documentTypeOptions(t) {
  return FORM_TYPES.map(([value, key]) => ({ value, label: t(`pages.documents.docTypes.${key}`) || value }));
}
