import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import FinanceTab from '../features/serviceContracts/FinanceTab';
import { api } from '../api';

vi.mock('../api', () => ({ api: { get: vi.fn(), list: vi.fn(), post: vi.fn(), del: vi.fn() } }));
vi.mock('../i18n', () => {
  const t = key => key;
  return { useTranslation: () => ({ t, locale: 'de-DE' }) };
});
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => null, useCanWrite: () => true }));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => async () => true }));

const contract = { id: 'sc1', property_ids: ['p1'], recoverable: true, provider_name: 'Stadtwerke' };
const figures = { expected: 0, invoiced: 0, credited: 0, paid: 0, open: 0, costs: 0, instalments: [] };
const mount = () => render(<MemoryRouter><FinanceTab contract={contract} canWrite today="2026-10-19" /></MemoryRouter>);
const base = '/service-contracts/sc1';
const response = path => path.includes('/reconciliation?') ? figures : [];
const ready = () => screen.findByTestId('sc-figures');
const booking = number => ({ booking_id: `b${number}`, booking_date: '2026-03-02', amount: -100,
  open_amount: 100, payment_text: `Abschlag ${number}` });
beforeEach(() => {
  vi.resetAllMocks(); localStorage.clear();
  api.get.mockImplementation(path => Promise.resolve(response(path)));
  api.list.mockResolvedValue([]);
});
afterEach(cleanup);

it('opens arbitrary historic and future years without a rolling five-year limit', async () => {
  mount(); await ready();
  fireEvent.change(screen.getByLabelText('serviceContracts.year'), { target: { value: '2001' } });
  await waitFor(() => expect(api.get.mock.calls.some(([path]) => path === `${base}/reconciliation?date_from=2001-01-01&date_to=2001-12-31`)).toBe(true));
  await ready();
  fireEvent.change(screen.getByLabelText('serviceContracts.year'), { target: { value: '2046' } });
  await waitFor(() => expect(api.get.mock.calls.some(([path]) => path === `${base}/reconciliation?date_from=2046-01-01&date_to=2046-12-31`)).toBe(true));
});

it('loads payment choices beyond item 200 and uses the selected calendar year', async () => {
  api.get.mockImplementation(path => {
    if (!path.includes('payment-candidates?')) return Promise.resolve(response(path));
    const query = new URLSearchParams(path.split('?')[1]);
    return Promise.resolve({ total: 201, has_more: query.get('skip') !== '200',
      items: query.get('skip') === '200' ? [booking(201)] : Array.from({ length: 200 }, (_, index) => booking(index + 1)) });
  });
  mount(); await ready();
  fireEvent.click(screen.getByRole('button', { name: 'serviceContracts.linkPayment' }));
  const select = await screen.findByRole('combobox', { name: 'serviceContracts.fields.booking *' });
  await waitFor(() => expect(select).toHaveTextContent('Abschlag 201'));
  const requests = api.get.mock.calls.map(([path]) => path).filter(path => path.includes('payment-candidates?'));
  expect(requests).toHaveLength(2);
  for (const path of requests) {
    const query = new URLSearchParams(path.split('?')[1]);
    expect(query.get('date_from')).toBe('2026-01-01'); expect(query.get('date_to')).toBe('2026-12-31');
  }
});

it.each([
  ['serviceContracts.linkBill', '/invoices'],
  ['serviceContracts.transfer', '/billing/periods'],
])('keeps a failed choice source retryable instead of presenting an empty form: %s', async (button, failedPath) => {
  api.list.mockImplementation(path => path === failedPath ? Promise.reject(new Error('Auswahl offline')) : Promise.resolve([]));
  mount(); await ready();
  fireEvent.click(screen.getByRole('button', { name: button }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Auswahl offline');
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  api.list.mockResolvedValue([]);
  fireEvent.click(screen.getByRole('button', { name: 'Auswahl erneut laden' }));
  expect(await screen.findByRole('dialog', { name: button })).toBeInTheDocument();
});

it('does not replace a new year with a late answer from the previous year', async () => {
  let finish;
  const previous = new Promise(resolve => { finish = resolve; });
  api.get.mockImplementation(path => path.includes('date_from=2026-01-01') ? previous : Promise.resolve(response(path)));
  mount();
  fireEvent.change(screen.getByLabelText('serviceContracts.year'), { target: { value: '2001' } });
  await ready();
  await act(async () => finish({ ...figures, expected: 123456 }));
  expect(screen.getByTestId('sc-figures')).not.toHaveTextContent('123.456');
});
