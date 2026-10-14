import { afterEach, describe, expect, it } from 'vitest';
import { formatArea, formatDate, formatMoney, formatMonth, formatPercent, setFormatLocale } from '../utils/format';
import { codeLabel } from '../utils/codeLabels';

const nbsp = s => s.replace(/\u00a0|\u202f/g, ' ');

describe('format', () => {
  afterEach(() => setFormatLocale('de-DE'));

  it('writes amounts, dates and percentages the German way', () => {
    expect(nbsp(formatMoney(1018330))).toBe('1.018.330,00 €');
    expect(nbsp(formatMoney(-6000))).toBe('-6.000,00 €');
    expect(formatDate('2025-01-03')).toBe('03.01.2025');
    expect(formatDate('2026-09-01T22:30:00')).toBe('01.09.2026');
    expect(formatMonth('2025-01')).toBe('01/2025');
    expect(nbsp(formatPercent(19))).toBe('19 %');
    expect(nbsp(formatPercent(3.5))).toBe('3,5 %');
    expect(nbsp(formatArea(62))).toBe('62 m²');
  });

  it('shows a dash for missing values', () => {
    expect(formatMoney(null)).toBe('—');
    expect(formatMoney('')).toBe('—');
    expect(formatDate(null)).toBe('—');
  });

  it('follows the chosen language', () => {
    setFormatLocale('en-US');
    expect(formatMoney(1234.5)).toBe('€1,234.50');
    expect(formatDate('2025-01-03')).toBe('01/03/2025');
  });
});

describe('codeLabel', () => {
  afterEach(() => setFormatLocale('de-DE'));

  it('turns stored codes into words and leaves names alone', () => {
    expect(codeLabel('single_family')).toBe('Einfamilienhaus');
    expect(codeLabel('yearly')).toBe('Jährlich');
    expect(codeLabel('Familie Schulz')).toBe('Familie Schulz');
    expect(codeLabel('verwalter')).toBe('verwalter');
    setFormatLocale('en-US');
    expect(codeLabel('single_family')).toBe('Single family');
  });
});
