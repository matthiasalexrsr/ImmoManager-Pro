// One place for how numbers, amounts and dates look: in the user's locale (1.234,56 € / 03.01.2025).
let locale = 'de-DE';
let dateFormat = null;
let currencyDisplay = 'symbol';
export function setCurrencyDisplay(value) { currencyDisplay = value === 'code' ? 'code' : 'symbol'; cache.clear(); }
export function setDateFormat(value) { dateFormat = value || null; }
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
  return formatter(`money:${currency}:${currencyDisplay}`, () => new Intl.NumberFormat(locale, { style: 'currency', currency, currencyDisplay }))
    .format(Number(v) === 0 ? 0 : Number(v));
}

/** Short amounts for chart axes: 426 €, 45.000 €, 1,5 Mio. € */
export function formatMoneyCompact(v, { blank = '' } = {}) {
  if (isBlank(v)) return blank;
  const n = Number(v);
  if (Math.abs(n) < 100000) {
    return formatter('money:whole', () => new Intl.NumberFormat(locale, {
      style: 'currency', currency: 'EUR', maximumFractionDigits: 0,
    })).format(n);
  }
  return `${formatter('compact', () => new Intl.NumberFormat(locale, { notation: 'compact', maximumFractionDigits: 1 }))
    .format(n)} €`;
}

/** An IBAN as it is printed: groups of four (DE29 8605 5592 …), so it can be read and wrap. */
export function formatIban(v, { blank = '—' } = {}) {
  const compact = String(v ?? '').replace(/\s+/g, '').toUpperCase();
  return compact ? compact.replace(/(.{4})(?=.)/g, '$1 ') : blank;
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
  if (!dateFormat) return formatter('date', () => new Intl.DateTimeFormat(locale, { day: '2-digit', month: '2-digit', year: 'numeric' })).format(d);
  const parts = [String(d.getFullYear()).padStart(4, '0'), String(d.getMonth() + 1).padStart(2, '0'), String(d.getDate()).padStart(2, '0')];
  if (dateFormat === 'YYYY-MM-DD') return parts.join('-');
  if (dateFormat === 'MM/DD/YYYY') return `${parts[1]}/${parts[2]}/${parts[0]}`;
  return `${parts[2]}.${parts[1]}.${parts[0]}`;
}

export function formatDateTime(v, { blank = '—' } = {}) {
  if (!v) return blank;
  const d = toDate(v);
  if (Number.isNaN(d.getTime())) return String(v);
  return `${formatDate(d)} ${formatter('time', () => new Intl.DateTimeFormat(locale, { hour: '2-digit', minute: '2-digit' })).format(d)}`;
}

// "2025-01" → "01/2025"
export function formatMonth(v, { blank = '—' } = {}) {
  if (!v) return blank;
  const m = /^(\d{4})-(\d{2})/.exec(String(v));
  return m ? `${m[2]}/${m[1]}` : String(v);
}

// 2048 → "2.0 KB" (binary units, as file managers show archive sizes)
export function formatBytes(value, { blank = '—' } = {}) {
  if (value == null || Number.isNaN(Number(value))) return blank;
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let size = Number(value);
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}

// "Kaltmiete (€)" → "Kaltmiete": where the value shows its unit itself.
export function plainLabel(label) {
  return typeof label === 'string' ? label.replace(/\s*\((€|m²|EUR)\)\s*$/, '') : label;
}
