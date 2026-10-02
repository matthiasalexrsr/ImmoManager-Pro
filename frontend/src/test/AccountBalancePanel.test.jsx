import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import AccountBalancePanel from '../components/AccountBalancePanel';
import german from '../../../i18n/de-DE.json';

const mocks = vi.hoisted(() => ({ get: vi.fn(), user: { id: 'synthetic-owner', role: 'eigentuemer' } }));
vi.mock('../api', () => ({ api: { get: mocks.get } }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: mocks.user }) }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ locale: 'de-DE', t: key => key.split('.').reduce((value, part) => value?.[part], german) || key }) }));

const summary = (id = 'bank', hash = 'a'.repeat(64)) => ({ account_id: id, account_name: 'Synthetic bank', source_kind: 'stored_account_and_cash_bookings',
  account_updated_at: '2026-10-01T12:00:00.123456Z',
  source_hash: hash, snapshot_started_at: '2026-10-01T12:00:00Z', as_of: null, first_booking_date: '2026-01-01', last_booking_date: '2026-01-02',
  opening_balance_cents: '10000', comparison_balance_cents: '12000', bookings_sum_cents: '1800', income_sum_cents: '2500', expense_sum_cents: '-700',
  calculated_balance_cents: '11800', difference_cents: '-200', is_computable: true, booking_count: 2, issues_count: 0, issues_sample: [],
  status_totals: Object.fromEntries(['open', 'matched', 'booked', 'confirmed', 'other'].map(key => [key, { booking_count: 0, amount_cents: '0', invalid_count: 0 }])) });
const sourcePage = (items = [], next = null) => ({ items, source_count: items.length, has_more: !!next, next_cursor: next });
const cashRow = (id = 'cash-1') => ({ id, booking_date: '2026-01-01', amount_cents: '2500', status: 'open', payment_text: 'Actual stored cash', valid_amount: true });
beforeEach(() => {
  vi.clearAllMocks();
  mocks.user = { id: 'synthetic-owner', role: 'eigentuemer' };
  mocks.get.mockImplementation(async path => {
    const url = new URL(path, 'http://localhost');
    if (url.pathname.includes('/lookup/')) return { items: [{ id: 'bank', label: 'Synthetic bank' }, { id: 'second', label: 'Second bank' }], selected: null, has_more: false };
    if (url.pathname.endsWith('balance-summary')) return summary(url.pathname.split('/')[2]);
    return sourcePage([cashRow()]);
  });
});

it('selects and reads one account on demand without loading all bookings', async () => {
  render(<AccountBalancePanel onClose={vi.fn()} />);
  await screen.findByRole('option', { name: 'Synthetic bank' });
  expect(mocks.get.mock.calls).toHaveLength(1);
  expect(new URL(mocks.get.mock.calls[0][0], 'http://localhost').searchParams.has('selected_id')).toBe(false);
  fireEvent.change(screen.getByLabelText('Konto'), { target: { value: 'bank' } });
  await screen.findByText('118,00 €');
  expect(screen.getByText('−2,00 €')).toBeInTheDocument();
  expect(screen.getByText(german.accountBalance.undatedNote)).toBeInTheDocument();
  expect(screen.getByRole('link', { name: german.accountBalance.manageBookings })).toHaveAttribute('href', '/bookings?account_id=bank');
  expect(mocks.get.mock.calls.every(([path]) => path.startsWith('/bookings/lookup/accounts?') || path.startsWith('/accounts/bank/'))).toBe(true);
});

it('does not publish zero or a previous total when a summary fails and retries explicitly', async () => {
  const original = mocks.get.getMockImplementation();
  let failed = true;
  mocks.get.mockImplementation((path, options) => path.includes('balance-summary') && failed ? Promise.reject(new Error('Source unavailable')) : original(path, options));
  render(<AccountBalancePanel initialAccount="bank" onClose={vi.fn()} />);
  expect(await screen.findByRole('alert')).toHaveTextContent('Source unavailable');
  expect(screen.queryByText('118,00 €')).not.toBeInTheDocument();
  expect(mocks.get.mock.calls.some(([path]) => path.includes('balance-sources'))).toBe(false);
  failed = false;
  fireEvent.click(within(screen.getByRole('alert')).getByRole('button'));
  await screen.findByText('118,00 €');
});

it('requires explicit summary reload after source hash changes instead of retrying an obsolete hash', async () => {
  const original = mocks.get.getMockImplementation();
  let changed = false;
  mocks.get.mockImplementation((path, options) => {
    if (path.includes('balance-sources') && !changed) return Promise.reject(Object.assign(new Error('Stored sources changed'), { code: 'balance_source_changed' }));
    if (path.includes('balance-summary')) return Promise.resolve(summary('bank', changed ? 'b'.repeat(64) : 'a'.repeat(64)));
    return original(path, options);
  });
  render(<AccountBalancePanel initialAccount="bank" onClose={vi.fn()} />);
  expect(await screen.findByRole('alert')).toHaveTextContent('Stored sources changed');
  const previous = mocks.get.mock.calls.filter(([path]) => path.includes('balance-summary')).length;
  changed = true;
  fireEvent.click(within(screen.getByRole('alert')).getByRole('button'));
  await screen.findByText('Actual stored cash');
  expect(mocks.get.mock.calls.filter(([path]) => path.includes('balance-summary'))).toHaveLength(previous + 1);
  expect(mocks.get.mock.calls.filter(([path]) => path.includes('balance-sources')).at(-1)[0]).toContain('source_hash=' + 'b'.repeat(64));
});

it('applies an inclusive cutoff explicitly and uses the server cursor for reachable invalid sources', async () => {
  const original = mocks.get.getMockImplementation();
  mocks.get.mockImplementation((path, options) => {
    const url = new URL(path, 'http://localhost');
    if (url.searchParams.get('kind') === 'issues') return Promise.resolve(sourcePage([{ source_id: url.searchParams.has('cursor') ? 'late-issue' : 'first-issue',
      source_type: 'booking', field: 'amount', code: 'amount_fractional_cent', value_preview: '1.001', repair: 'edit_booking' }], url.searchParams.has('cursor') ? null : 'server-issue-cursor'));
    return original(path, options);
  });
  render(<AccountBalancePanel initialAccount="bank" onClose={vi.fn()} />);
  await screen.findByText('118,00 €');
  fireEvent.change(screen.getByLabelText(german.accountBalance.asOf), { target: { value: '2026-01-31' } });
  expect(mocks.get.mock.calls.some(([path]) => path.includes('as_of='))).toBe(false);
  fireEvent.click(screen.getByRole('button', { name: german.accountBalance.applyCutoff }));
  await waitFor(() => expect(mocks.get.mock.calls.some(([path]) => path.includes('balance-summary?as_of=2026-01-31'))).toBe(true));
  await screen.findByText('118,00 €');
  fireEvent.click(screen.getByRole('button', { name: 'Prüfbefunde (0)' }));
  await screen.findByText('first-issue');
  fireEvent.click(screen.getByRole('button', { name: german.accountBalance.nextPage }));
  await screen.findByText('late-issue');
  expect(mocks.get.mock.calls.at(-1)[0]).toContain('cursor=server-issue-cursor');
});

it('aborts old requests and suppresses late data when changing accounts or principal', async () => {
  const original = mocks.get.getMockImplementation();
  let resolveOld;
  mocks.get.mockImplementation((path, options) => path.startsWith('/accounts/bank/balance-summary')
    ? new Promise(resolve => { resolveOld = resolve; }) : original(path, options));
  const rendered = render(<AccountBalancePanel initialAccount="bank" onClose={vi.fn()} />);
  await screen.findByRole('option', { name: 'Second bank' });
  const signal = mocks.get.mock.calls.find(([path]) => path.includes('/bank/balance-summary'))[1].signal;
  fireEvent.change(screen.getByLabelText('Konto'), { target: { value: 'second' } });
  await screen.findByText('118,00 €');
  expect(signal.aborted).toBe(true);
  await act(async () => resolveOld({ ...summary(), calculated_balance_cents: '999999' }));
  expect(screen.queryByText('9.999,99 €')).not.toBeInTheDocument();
  mocks.user = { id: 'selected-reader', role: 'readonly', portfolio_access: 'selected', portfolio_ids: [] };
  mocks.get.mockRejectedValue(new Error('Account no longer accessible'));
  rendered.rerender(<AccountBalancePanel initialAccount="bank" onClose={vi.fn()} />);
  await waitFor(() => expect(screen.getAllByRole('alert')[0]).toHaveTextContent('Account no longer accessible'));
  expect(screen.queryByText('118,00 €')).not.toBeInTheDocument();
});

it('retains the source findings while a blocked balance stays unknown', async () => {
  const original = mocks.get.getMockImplementation();
  mocks.get.mockImplementation((path, options) => path.includes('balance-summary') ? Promise.resolve({ ...summary(), is_computable: false,
    calculated_balance_cents: null, bookings_sum_cents: null, difference_cents: null, issues_count: 1 }) : original(path, options));
  render(<AccountBalancePanel initialAccount="bank" onClose={vi.fn()} />);
  expect(await screen.findByRole('alert')).toHaveTextContent(german.accountBalance.blocked);
  expect(screen.queryByText('118,00 €')).not.toBeInTheDocument();
  await screen.findByText('Actual stored cash');
});

it('rejects malformed monetary DTOs and never renders a floating projection', async () => {
  const original = mocks.get.getMockImplementation();
  mocks.get.mockImplementation((path, options) => path.includes('balance-summary') ? Promise.resolve({ ...summary(), calculated_balance_cents: 11800 }) : original(path, options));
  render(<AccountBalancePanel initialAccount="bank" onClose={vi.fn()} />);
  expect(await screen.findByRole('alert')).toHaveTextContent(german.accountBalance.invalidResponse);
  expect(screen.queryByText('118,00 €')).not.toBeInTheDocument();
});
