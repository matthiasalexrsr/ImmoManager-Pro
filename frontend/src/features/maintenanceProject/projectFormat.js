import { formatDate, formatMoney } from '../../utils/format';

export const money = value => formatMoney(value);
export const day = value => (value ? formatDate(value) : '—');

export function contactLabel(contact) {
  if (!contact) return '';
  const person = [contact.first_name, contact.last_name].filter(Boolean).join(' ');
  return contact.company_name || person || contact.email || contact.id;
}

// A select's options from a mapping of codes to the text keys of text.js
export const choices = (tx, prefix, codes) => codes.map(code => ({ value: code, label: tx[`${prefix}${code}`] || code }));
