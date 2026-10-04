const MONEY = /^-?\d+\.\d{2}$/;
const CENTS = /^-?\d+$/;
const HASH = /^[a-f0-9]{64}$/;

export function moneyStringToCents(value) {
  if (typeof value !== 'string' || !MONEY.test(value)) throw new Error('invalid_money_string');
  const negative = value.startsWith('-');
  const source = negative ? value.slice(1) : value;
  const [whole, fraction] = source.split('.');
  const cents = BigInt(whole) * 100n + BigInt(fraction);
  return negative ? -cents : cents;
}

export function centsString(value) {
  if (typeof value !== 'string' || !CENTS.test(value)) throw new Error('invalid_cents_string');
  return BigInt(value);
}

export function formatMoneyString(value, locale = 'de-DE') {
  const cents = moneyStringToCents(value);
  const negative = cents < 0n;
  const absolute = negative ? -cents : cents;
  const digits = (absolute / 100n).toString();
  const fraction = (absolute % 100n).toString().padStart(2, '0');
  const groups = [];
  for (let end = digits.length; end > 0; end -= 3) groups.unshift(digits.slice(Math.max(0, end - 3), end));
  const config = locale === 'en-US'
    ? { group: ',', decimal: '.', prefix: '€', suffix: '' }
    : { group: '.', decimal: ',', prefix: '', suffix: ' €' };
  return `${negative ? '-' : ''}${config.prefix}${groups.join(config.group)}${config.decimal}${fraction}${config.suffix}`;
}

export function ratioPercent(value, maximum) {
  const amount = value < 0n ? -value : value;
  const max = maximum < 0n ? -maximum : maximum;
  if (max === 0n) return '0%';
  return `${(amount * 100n) / max}%`;
}

const isObject = value => Boolean(value) && typeof value === 'object' && !Array.isArray(value);
const isString = value => typeof value === 'string' && value.length > 0;
const optionalString = value => value == null || typeof value === 'string';

function checkMoney(value) {
  moneyStringToCents(value);
  return value;
}

function aggregateRow(row, kind) {
  if (!isObject(row) || !Number.isInteger(row.count) || row.count < 0) throw new Error('invalid_cash_report');
  const result = {
    ...row,
    income: checkMoney(row.income),
    expense: checkMoney(row.expense),
    net: checkMoney(row.net),
  };
  if (kind === 'month' && !/^\d{4}-\d{2}$/.test(row.month || '')) throw new Error('invalid_cash_report');
  if (kind === 'category' && !(row.category_id == null || isString(row.category_id))) throw new Error('invalid_cash_report');
  if (kind === 'location') {
    if (!(row.property_id == null || isString(row.property_id))
        || !(row.unit_id == null || isString(row.unit_id))
        || !optionalString(row.property_name) || !optionalString(row.unit_label)) {
      throw new Error('invalid_cash_report');
    }
  }
  return result;
}

export function validateCashReport(value, expectedFilters = null) {
  if (!isObject(value) || !['confirmed_cash', 'recorded_bookings'].includes(value.basis)
      || value.currency !== 'EUR' || !isObject(value.filters)
      || !HASH.test(value.source_hash || '')
      || !Number.isInteger(value.source_count) || value.source_count < 0
      || !Number.isInteger(value.excluded_count) || value.excluded_count < 0
      || !Array.isArray(value.categories) || !Array.isArray(value.months) || !Array.isArray(value.locations)) {
    throw new Error('invalid_cash_report');
  }
  if (expectedFilters && filterIdentity(value.filters) !== filterIdentity(expectedFilters)) {
    throw new Error('invalid_cash_report');
  }
  return {
    ...value,
    income: checkMoney(value.income),
    expense: checkMoney(value.expense),
    net: checkMoney(value.net),
    categories: value.categories.map(row => aggregateRow(row, 'category')),
    months: value.months.map(row => aggregateRow(row, 'month')),
    locations: value.locations.map(row => aggregateRow(row, 'location')),
  };
}

export function validateCashSource(row) {
  if (!isObject(row) || !isString(row.id) || !isString(row.booking_date)
      || !isString(row.account_id) || !isString(row.account_name)
      || typeof row.included !== 'boolean'
      || !(row.exclusion_reason == null || ['after_cutoff', 'cancelled', 'unconfirmed'].includes(row.exclusion_reason))
      || !optionalString(row.category_name) || !optionalString(row.property_name)
      || !optionalString(row.unit_label) || !optionalString(row.payment_text)
      || !optionalString(row.receipt_url) || !isString(row.status)) {
    throw new Error('invalid_cash_sources');
  }
  const amount = checkMoney(row.amount);
  const cents = centsString(row.amount_cents);
  if (moneyStringToCents(amount) !== cents) throw new Error('invalid_cash_sources');
  return { ...row, amount, amount_cents: row.amount_cents };
}

export function validateCashSources(value, expectedHash, expectedFilters = null) {
  const report = validateCashReport(value, expectedFilters);
  if (report.source_hash !== expectedHash || !Array.isArray(value.items)
      || typeof value.has_more !== 'boolean'
      || !(value.next_after == null || isString(value.next_after))
      || (value.has_more && !value.next_after)
      || (!value.has_more && value.next_after != null)) {
    throw new Error('invalid_cash_sources');
  }
  return { ...report, items: value.items.map(validateCashSource) };
}

export function normalizeFilters(draft) {
  if (draft.date_from && draft.date_to && draft.date_from > draft.date_to) {
    throw new Error('invalid_date_range');
  }
  if (!draft.as_of) throw new Error('missing_as_of');
  return {
    date_from: draft.date_from || null,
    date_to: draft.date_to || null,
    portfolio_id: draft.portfolio?.id || null,
    property_ids: [...draft.properties].map(row => row.id).sort(),
    unit_id: draft.unit?.id || null,
    account_id: draft.account?.id || null,
    basis: draft.basis,
    as_of: draft.as_of,
  };
}

export function cashFilterQuery(filters, extras = {}) {
  const params = new URLSearchParams();
  for (const key of ['date_from', 'date_to', 'portfolio_id', 'unit_id', 'account_id', 'basis', 'as_of']) {
    if (filters[key] != null && filters[key] !== '') params.set(key, filters[key]);
  }
  for (const id of filters.property_ids || []) params.append('property_ids', id);
  for (const [key, value] of Object.entries(extras)) {
    if (value != null && value !== '') params.set(key, String(value));
  }
  return params.toString();
}

export function filterIdentity(filters) {
  return JSON.stringify([
    filters.date_from, filters.date_to, filters.portfolio_id,
    [...(filters.property_ids || [])], filters.unit_id, filters.account_id,
    filters.basis, filters.as_of,
  ]);
}

export function exclusionTextKey(reason) {
  if (reason === 'after_cutoff') return 'excludedAfterCutoff';
  if (reason === 'cancelled') return 'excludedCancelled';
  if (reason === 'unconfirmed') return 'excludedUnconfirmed';
  return 'included';
}
