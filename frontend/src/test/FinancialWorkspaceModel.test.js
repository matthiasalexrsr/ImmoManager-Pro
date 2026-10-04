import { describe, expect, it } from 'vitest';
import {
  cashFilterQuery,
  centsString,
  filterIdentity,
  formatMoneyString,
  moneyStringToCents,
  normalizeFilters,
  validateCashReport,
  validateCashSources,
} from '../features/financialWorkspace/financialWorkspaceModel';

const hash = 'a'.repeat(64);

function filters() {
  return {
    date_from: '2026-01-01',
    date_to: '2026-12-31',
    portfolio_id: 'portfolio-1',
    property_ids: ['property-1', 'property-2'],
    unit_id: null,
    account_id: 'account-1',
    basis: 'confirmed_cash',
    as_of: '2026-12-31',
  };
}

function report() {
  return {
    basis: 'confirmed_cash',
    currency: 'EUR',
    filters: filters(),
    source_hash: hash,
    income: '123456789012345678901234567890.12',
    expense: '20.10',
    net: '123456789012345678901234567870.02',
    source_count: 2,
    excluded_count: 1,
    categories: [{ category_id: 'cat-1', name: 'Betrieb', category_type: 'expense',
      income: '0.00', expense: '20.10', net: '-20.10', count: 1 }],
    months: [{ month: '2026-01', income: '10.00', expense: '0.00', net: '10.00', count: 1 }],
    locations: [{ property_id: 'property-1', property_name: 'Haus A', unit_id: null, unit_label: null,
      income: '10.00', expense: '20.10', net: '-10.10', count: 2 }],
    items: [],
    has_more: false,
    next_after: null,
  };
}

describe('financial workspace exact model', () => {
  it('formats arbitrarily large and negative MoneyStrings without Number conversion', () => {
    expect(moneyStringToCents('123456789012345678901234567890.12'))
      .toBe(12345678901234567890123456789012n);
    expect(centsString('-123456')).toBe(-123456n);
    expect(formatMoneyString('123456789012345678901234567890.12', 'de-DE'))
      .toBe('123.456.789.012.345.678.901.234.567.890,12 €');
    expect(formatMoneyString('-1234.56', 'en-US')).toBe('-€1,234.56');
  });

  it('keeps repeated property_ids in the canonical query and never serializes them as one array value', () => {
    const params = new URLSearchParams(cashFilterQuery(filters()));
    expect(params.getAll('property_ids')).toEqual(['property-1', 'property-2']);
    expect(params.get('portfolio_id')).toBe('portfolio-1');
    expect(params.get('account_id')).toBe('account-1');
  });

  it('validates aggregate and source cents exactly', () => {
    expect(validateCashReport(report()).income).toBe('123456789012345678901234567890.12');
    const source = {
      ...report(),
      items: [{
        id: 'booking-1', booking_date: '2026-01-01', account_id: 'account-1', account_name: 'Bank',
        category_name: 'Miete', property_name: 'Haus A', unit_label: '1. OG',
        amount: '-12.34', amount_cents: '-1234', status: 'confirmed', included: true,
        exclusion_reason: null, payment_text: 'Miete Januar', receipt_url: null,
      }],
      has_more: false,
      next_after: null,
    };
    expect(validateCashSources(source, hash).items[0].amount_cents).toBe('-1234');
    expect(() => validateCashSources({
      ...source,
      items: [{ ...source.items[0], amount_cents: '-1235' }],
    }, hash)).toThrow('invalid_cash_sources');
  });

  it('rejects a valid-looking response bound to different filters', () => {
    expect(() => validateCashReport({
      ...report(),
      filters: { ...filters(), portfolio_id: 'portfolio-other' },
    }, filters())).toThrow('invalid_cash_report');

    expect(() => validateCashSources({
      ...report(),
      filters: { ...filters(), account_id: 'account-other' },
      items: [],
      has_more: false,
      next_after: null,
    }, hash, filters())).toThrow('invalid_cash_report');
  });

  it('separates draft validation from filter identity', () => {
    const draft = {
      date_from: '2026-12-31', date_to: '2026-01-01', as_of: '2026-12-31',
      basis: 'confirmed_cash', portfolio: null, properties: [], unit: null, account: null,
    };
    expect(() => normalizeFilters(draft)).toThrow('invalid_date_range');
    expect(filterIdentity(filters())).toBe(filterIdentity({ ...filters(), property_ids: ['property-1', 'property-2'] }));
  });
});
