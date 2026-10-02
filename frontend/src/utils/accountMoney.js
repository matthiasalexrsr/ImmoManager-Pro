// Server projections remain integer-cent strings throughout rendering.
export function euroCents(cents, locale = 'de-DE') {
  if (typeof cents !== 'string' || !/^-?\d+$/.test(cents)) return '—';
  const value = BigInt(cents), absolute = value < 0n ? -value : value;
  const decimal = new Intl.NumberFormat(locale).formatToParts(1.1).find(part => part.type === 'decimal').value;
  return `${value < 0n ? '−' : ''}${new Intl.NumberFormat(locale).format(absolute / 100n)}${decimal}${String(absolute % 100n).padStart(2, '0')} €`;
}

export function storedCents(value) {
  if (value === null || value === undefined || typeof value === 'boolean') return null;
  const match = String(value).match(/^([+-]?)(\d+)(?:\.(\d+))?(?:[eE]([+-]?\d+))?$/);
  if (!match) return null;
  const fraction = match[3] || '', exponent = Number(match[4] || 0);
  if (!Number.isSafeInteger(exponent) || Math.abs(exponent) > 1000) return null;
  let digits = match[2] + fraction, shift = 2 + exponent - fraction.length;
  if (shift < 0) {
    if (-shift > digits.length - digits.replace(/0+$/, '').length) return null;
    digits = digits.slice(0, shift); shift = 0;
  }
  return (BigInt(digits || '0') * 10n**BigInt(shift) * (match[1] === '-' ? -1n : 1n)).toString();
}

export function centsInput(value) {
  if (typeof value !== 'string' || !/^-?\d+$/.test(value)) return '';
  const cents = BigInt(value), absolute = cents < 0n ? -cents : cents;
  return `${cents < 0n ? '-' : ''}${absolute / 100n}.${String(absolute % 100n).padStart(2, '0')}`;
}
