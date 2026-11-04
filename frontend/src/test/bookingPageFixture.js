// Adapt pre-existing review fixtures to the paged API contract. Dedicated page
// tests use explicit server responses and assert that no full-list call occurs.
import { cashflowSide } from '../utils/cashflowBasis';

export function bookingPageReply(rows, path, categories = [], overview = { allocations: [], reserved_amounts: {} }) {
  const params = new URLSearchParams(path.split('?')[1]);
  const basis = rows.filter(row => (!params.get('account_id') || row.account_id === params.get('account_id'))
    && (!params.get('date_from') || row.booking_date >= params.get('date_from'))
    && (!params.get('date_to') || row.booking_date <= params.get('date_to'))
    && (!params.get('property_id') || row.property_id === params.get('property_id'))
    && (!params.get('unit_id') || row.unit_id === params.get('unit_id'))
    && (!params.get('category_id') || row.category_id === params.get('category_id'))
    && (!params.get('tenant_id') || row.tenant_id === params.get('tenant_id'))
    && (!params.get('status') || row.status === params.get('status')));
  const summary = { count: basis.length, income: 0, expense: 0, withdrawal: 0, contribution: 0,
    no_category: basis.filter(row => !row.category_id).length, no_receipt: basis.filter(row => !row.receipt_url).length };
  for (const row of basis) {
    const side = cashflowSide(row, categories);
    summary[side] += Number(row.owner_part ?? row.amount) * (['expense', 'withdrawal'].includes(side) ? -1 : 1);
  }
  const flow = params.get('flow') || 'all';
  const selected = basis.filter(row => flow === 'all' || (flow === 'open' && row.status === 'open')
    || (flow === 'no_category' && !row.category_id) || (flow === 'no_receipt' && !row.receipt_url)
    || cashflowSide(row, categories) === flow || (flow === 'unassigned' && row.tenant_id));
  const skip = Number(params.get('skip') || 0), limit = Number(params.get('limit') || 25);
  return { items: selected.slice(skip, skip + limit), total: selected.length, skip, limit, summary, ...overview };
}

export function installBookingPageFixture(api, { categories = [] } = {}) {
  const get = api.get.getMockImplementation();
  api.get.mockImplementation((path, options) => {
    if (path.startsWith('/bookings/page?')) {
      const params = new URLSearchParams(path.split('?')[1]);
      const owner = params.get('owner_contact_id');
      return Promise.resolve(api.list(owner ? `/bookings?owner_contact_id=${encodeURIComponent(owner)}` : '/bookings', options) || [])
        .then(rows => bookingPageReply(rows, path, categories));
    }
    if (/^\/bookings\/[^/]+\/allocation-overview$/.test(path)) return get('/bookings/allocations?include_reservations=true', options);
    return get(path, options);
  });
}
