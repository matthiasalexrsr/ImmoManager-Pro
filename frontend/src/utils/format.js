// One place for how numbers, amounts and dates look: in the user's locale (1.234,56 € / 03.01.2025).
let locale = 'de-DE';
const cache = new Map();

export function getFormatLocale() {
  return locale;
}

export function setFormatLocale(next) {
  if (next && next !== locale) {
    locale = next;
    cache.clear();
  }
}

function formatter(key, make) {
  if (!cache.has(key)) cache.set(key, make());
  return cache.get(key);
}

const isBlank = v => v == null || v === '' || Number.isNaN(Number(v));

export function formatMoney(v, { blank = '—', currency = 'EUR' } = {}) {
  if (isBlank(v)) return blank;
  return formatter(`money:${currency}`, () => new Intl.NumberFormat(locale, { style: 'currency', currency }))
    .format(Number(v));
}

export function formatNumber(v, digits = 0, { blank = '—' } = {}) {
  if (isBlank(v)) return blank;
  return formatter(`num:${digits}`, () => new Intl.NumberFormat(locale, {
    minimumFractionDigits: digits, maximumFractionDigits: digits,
  })).format(Number(v));
}

// Without digits: as many as the value has, at most two (19 %, 7,5 %).
export function formatPercent(v, digits = null, { blank = '—' } = {}) {
  if (isBlank(v)) return blank;
  if (digits == null) {
    const text = formatter('pct', () => new Intl.NumberFormat(locale, { maximumFractionDigits: 2 })).format(Number(v));
    return `${text} %`;
  }
  return `${formatNumber(v, digits)} %`;
}

export function formatArea(v, { blank = '—' } = {}) {
  if (isBlank(v)) return blank;
  return `${formatNumber(v, Number(v) % 1 ? 2 : 0)} m²`;
}

// ISO dates ("2025-01-03") are calendar days: format them without a time zone shift.
function toDate(v) {
  if (v instanceof Date) return v;
  if (typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v)) {
    const [y, m, d] = v.split('-').map(Number);
    return new Date(y, m - 1, d);
  }
  return new Date(v);
}

export function formatDate(v, { blank = '—' } = {}) {
  if (!v) return blank;
  const d = toDate(v);
  if (Number.isNaN(d.getTime())) return String(v);
  return formatter('date', () => new Intl.DateTimeFormat(locale, { day: '2-digit', month: '2-digit', year: 'numeric' }))
    .format(d);
}

export function formatDateTime(v, { blank = '—' } = {}) {
  if (!v) return blank;
  const d = toDate(v);
  if (Number.isNaN(d.getTime())) return String(v);
  return formatter('datetime', () => new Intl.DateTimeFormat(locale, {
    day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
  })).format(d);
}

// "2025-01" → "01/2025"
export function formatMonth(v, { blank = '—' } = {}) {
  if (!v) return blank;
  const m = /^(\d{4})-(\d{2})/.exec(String(v));
  return m ? `${m[2]}/${m[1]}` : String(v);
}

// "Kaltmiete (€)" → "Kaltmiete": where the value shows its unit itself.
export function plainLabel(label) {
  return typeof label === 'string' ? label.replace(/\s*\((€|m²|EUR)\)\s*$/, '') : label;
}
