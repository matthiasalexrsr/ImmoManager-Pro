import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  getBlob: vi.fn(),
  saveBlob: vi.fn(),
}));
vi.mock('../api', () => ({ api: { get: mocks.get, getBlob: mocks.getBlob } }));
vi.mock('../utils/bookingCsv', () => ({ saveBlob: mocks.saveBlob }));

import { financialWorkspaceApi } from '../features/financialWorkspace/financialWorkspaceApi';

const hash = 'b'.repeat(64);
const filters = {
  date_from: '2026-01-01', date_to: '2026-12-31', portfolio_id: 'portfolio-1',
  property_ids: ['property-1', 'property-2'], unit_id: null, account_id: 'account-1',
  basis: 'confirmed_cash', as_of: '2026-12-31',
};
const response = {
  basis: 'confirmed_cash', currency: 'EUR', filters, source_hash: hash,
  income: '10.00', expense: '2.00', net: '8.00', source_count: 1, excluded_count: 0,
  categories: [], months: [], locations: [], items: [], has_more: false, next_after: null,
};

describe('financial workspace API contract', () => {
  beforeEach(() => vi.clearAllMocks());

  it('requests report and sources with the exact applied filters, hash and cursor', async () => {
    mocks.get.mockResolvedValueOnce(response).mockResolvedValueOnce({
      ...response,
      items: [{
        id: 'booking-1', booking_date: '2026-01-01', account_id: 'account-1', account_name: 'Bank',
        category_name: null, property_name: null, unit_label: null, amount: '10.00', amount_cents: '1000',
        status: 'confirmed', included: true, exclusion_reason: null, payment_text: null, receipt_url: null,
      }],
    });
    await financialWorkspaceApi.report(filters);
    await financialWorkspaceApi.sources(filters, { sourceHash: hash, after: 'opaque-cursor', limit: 50 });

    const reportUrl = new URL(mocks.get.mock.calls[0][0], 'http://local');
    expect(reportUrl.pathname).toBe('/reports/cash');
    expect(reportUrl.searchParams.getAll('property_ids')).toEqual(['property-1', 'property-2']);

    const sourceUrl = new URL(mocks.get.mock.calls[1][0], 'http://local');
    expect(sourceUrl.pathname).toBe('/reports/cash/sources');
    expect(sourceUrl.searchParams.get('source_hash')).toBe(hash);
    expect(sourceUrl.searchParams.get('after')).toBe('opaque-cursor');
    expect(sourceUrl.searchParams.get('limit')).toBe('50');
  });

  it('exports the complete applied filter without a visible-page cursor or source hash', async () => {
    const blob = new Blob(['id;amount\r\nbooking-1;10.00\r\n'], { type: 'text/csv' });
    mocks.getBlob.mockResolvedValue(blob);
    await financialWorkspaceApi.exportCsv(filters);

    const url = new URL(mocks.getBlob.mock.calls[0][0], 'http://local');
    expect(url.pathname).toBe('/reports/cash/export.csv');
    expect(url.searchParams.getAll('property_ids')).toEqual(['property-1', 'property-2']);
    expect(url.searchParams.has('after')).toBe(false);
    expect(url.searchParams.has('source_hash')).toBe(false);
    expect(mocks.saveBlob).toHaveBeenCalledWith(blob, 'zahlungsquellen.csv');
  });
});
