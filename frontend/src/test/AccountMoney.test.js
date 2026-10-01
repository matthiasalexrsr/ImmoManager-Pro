import { expect, it } from 'vitest';
import { centsInput, euroCents, storedCents } from '../utils/accountMoney';

it.each([
  ['de-DE', '18014398509481986000', '180.143.985.094.819.860,00 €'],
  ['en-US', '-200', '−2.00 €'], ['es-ES', '75', '0,75 €'], ['de-DE', '0', '0,00 €'],
])('renders authoritative cents without a floating conversion (%s)', (locale, value, expected) => {
  expect(euroCents(value, locale)).toBe(expected);
});

it.each([null, undefined, 0, 11800, '12.34', 'NaN', 'Infinity', 'not-money'])('does not render absent or invalid authoritative cents as zero (%s)', value => {
  expect(euroCents(value)).toBe('—');
});

it('keeps stored manual comparisons exact and rejects fractional-cent evidence', () => {
  expect(['0.1', '0.2'].map(storedCents).reduce((sum, value) => sum + BigInt(value), 0n)).toBe(30n);
  expect(storedCents('-1.2300')).toBe('-123');
  expect(storedCents('1e2')).toBe('10000');
  expect(storedCents('1.001')).toBeNull();
  expect(storedCents('NaN')).toBeNull();
  expect(storedCents(null)).toBeNull();
  expect(centsInput('-123')).toBe('-1.23');
  expect(centsInput(null)).toBe('');
});
