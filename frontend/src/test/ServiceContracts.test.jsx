import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import ServiceContracts from '../pages/ServiceContracts';
import ServiceContractDetail from '../pages/ServiceContractDetail';
import { api } from '../api';
import {
  contractPayload, createPayload, decimalText, tariffInitial, tariffPayload,
} from '../features/serviceContracts/model';

vi.mock('../api', () => ({ api: { get: vi.fn(), list: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() } }));
const t = (key, params) => (params ? `${key} ${JSON.stringify(params)}` : key);
vi.mock('../i18n', () => ({ useTranslation: () => ({ t }) }));
const access = vi.hoisted(() => ({ canWrite: true }));
vi.mock('../contexts/AuthContext', () => ({ useCanWrite: () => access.canWrite }));

const CONTRACT = {
  id: 'sc1', title: 'Allgemeinstrom Nordhaus', contract_type: 'electricity', provider_contact_id: 'sw',
  provider_name: 'Stadtwerke Muster', provider: { id: 'sw', company_name: 'Stadtwerke Muster', phone: '0351 1' },
  contract_number: 'SW-4711', customer_number: 'K-99', start_date: '2025-01-01', end_date: null,
  minimum_term_months: 24, renewal_mode: 'fixed', renewal_months: 12, notice_period_value: 3, notice_period_unit: 'month',
  notice_to: 'term_end', reminder_days: 30, cancelled_on: null, cancellation_effective: null, recoverable: true,
  recoverable_percent: 100, cost_category: 'allgemeinstrom', notes: null, updated_at: '2026-10-01T08:00:00+00:00',
  status: 'active', effective_end: null, current_advance: 100, current_advance_interval: 'monthly',
  next_deadline: { kind: 'notice', date: '2026-09-30', days_left: 29 },
  property_ids: ['p1'],
  locations: [{ id: 'l1', property_id: 'p1', label: 'Nordhaus / electricity · Z-4711', share_weight: 1, supply_point: 'DE000' }],
  tariffs: [{ id: 't1', valid_from: '2025-01-01', label: 'Fix 24', advance_amount: 100, advance_interval: 'monthly',
    base_price: 12.5, base_price_period: 'month', unit_prices: [{ label: 'Arbeitspreis', unit: 'kWh', price: '0.3247' }],
    price_guarantee_until: '2026-12-31' }],
  terms: { as_of: '2026-09-01', status: 'active', first_term_end: '2026-12-31',
    current_term: { start: '2025-01-01', end: '2026-12-31' }, renewal_mode: 'fixed', renewal_months: 12,
    notice: { value: 3, unit: 'month', to: 'term_end' },
    next_notice_deadline: { date: '2026-09-30', end: '2026-12-31', days_left: 29, renews_to: '2027-12-31' },
    earliest_end_if_cancelled_today: '2026-12-31', current_tariff_id: 't1',
    upcoming: [{ kind: 'notice', date: '2026-09-30', days_left: 29 }, { kind: 'price_guarantee', date: '2026-12-31', days_left: 121 }] },
  restricted: false,
};

const RECONCILIATION = { expected: 1200, invoiced: 1350, credited: 1200, invoice_balance: 150, obligations: 1350,
  paid: 1350, open: 0, costs: 1350, partial: false, instalments: [{ due_date: '2026-01-01', amount: 100 }], invoices: [] };

function showDetail(contract = CONTRACT) {
  api.get.mockImplementation(path => {
    if (path === '/service-contracts/sc1') return Promise.resolve(contract);
    if (path.startsWith('/service-contracts/sc1/reconciliation')) return Promise.resolve(RECONCILIATION);
    if (path === '/service-contracts/sc1/invoices') return Promise.resolve([{ id: 'b1', invoice_id: 'i1', kind: 'settlement',
      period_start: '2026-01-01', period_end: '2026-12-31', advances_credited: 1200, planned_advances: 1200, paid: 150, open: 0,
      transfers: [{ billing_period_label: 'BK 2026', amount: 1350 }],
      invoice: { id: 'i1', invoice_date: '2027-02-10', gross_amount: 1350, supplier: 'Stadtwerke Muster', invoice_number: 'R-1' } }]);
    if (path === '/service-contracts/sc1/payments') return Promise.resolve([]);
    if (path === '/service-contracts/sc1/documents') return Promise.resolve([
      { id: 'd1', link_id: 'x1', source: 'contract', title: 'Vertrag Strom', document_date: '2025-01-01', file_url: '/uploads/a.pdf' },
      { id: 'd2', link_id: null, source: 'invoice', title: 'Rechnung 2026', file_url: '/uploads/b.pdf' }]);
    return Promise.reject(new Error(`unexpected ${path}`));
  });
  return render(<MemoryRouter initialEntries={['/service-contracts/sc1']}>
    <Routes><Route path="/service-contracts/:id" element={<ServiceContractDetail />} /></Routes></MemoryRouter>);
}

describe('service contract model', () => {
  it('keeps unit prices exact and builds the create payload with location and first tariff', () => {
    expect(decimalText('0,3247')).toBe('0.3247');
    expect(decimalText(' 12 ')).toBe('12');
    expect(decimalText('')).toBeNull();
    expect(() => decimalText('1,2,3')).toThrow();
    const body = createPayload({
      contract_type: 'gas', title: 'Gas Nord', provider_contact_id: 'sw', start_date: '2026-01-01',
      minimum_term_months: 12, renewal_mode: 'fixed', renewal_months: 12, notice_period_value: 1,
      notice_period_unit: 'month', notice_to: 'term_end', recoverable: true, property_id: 'p1', unit_id: '',
      meter_id: 'm1', tariff_valid_from: '2026-01-01', tariff_advance_amount: 80, tariff_advance_interval: 'monthly',
      tariff_price: '0,1199', tariff_price_label: 'Arbeitspreis', tariff_price_unit: 'kWh',
    });
    expect(body.locations).toEqual([{ property_id: 'p1', unit_id: null, meter_id: 'm1', supply_point: null }]);
    expect(body.tariff.unit_prices).toEqual([{ label: 'Arbeitspreis', unit: 'kWh', price: '0.1199' }]);
    expect(body.tariff.advance_interval).toBe('monthly');
    expect(body.recoverable).toBe(true);
    expect(createPayload({ ...body, renewal_mode: 'none', property_id: 'p1' }).tariff).toBeNull();
  });

  it('normalizes the terms like the server expects', () => {
    const indefinite = contractPayload({ renewal_mode: 'indefinite', notice_to: 'term_end', renewal_months: 12,
      notice_period_value: 1, notice_period_unit: 'month' });
    expect(indefinite.notice_to).toBe('month_end');
    expect(indefinite.renewal_months).toBeNull();
    expect(contractPayload({ end_date: '2026-12-31', minimum_term_months: 12 }).minimum_term_months).toBeNull();
    expect(contractPayload({ notice_period_value: null, notice_period_unit: 'month' }).notice_period_unit).toBeNull();
    // a form without the cancellation fields keeps the stored cancellation
    expect(contractPayload({ title: 'x' }, { cancelled_on: '2026-09-01' }).cancelled_on).toBe('2026-09-01');
  });

  it('edits the first unit price of a tariff and keeps the others', () => {
    const tariff = { valid_from: '2026-01-01', unit_prices: [{ label: 'HT', unit: 'kWh', price: '0.35' },
      { label: 'NT', unit: 'kWh', price: '0.28' }] };
    const initial = tariffInitial(tariff);
    expect(initial.price).toBe('0.35');
    const body = tariffPayload({ ...initial, price: '0,36' }, '', tariff.unit_prices);
    expect(body.unit_prices).toEqual([{ label: 'HT', unit: 'kWh', price: '0.36' }, { label: 'NT', unit: 'kWh', price: '0.28' }]);
  });
});

describe('ServiceContracts list', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    access.canWrite = true;
    api.list.mockResolvedValue([{ ...CONTRACT }]);
    api.get.mockResolvedValue([{ service_contract_id: 'sc1', kind: 'notice', date: '2026-09-30', days_left: 10,
      title: 'Allgemeinstrom Nordhaus' }]);
  });

  it('lists contracts with their next deadline and the deadlines of the next 90 days', async () => {
    render(<MemoryRouter><ServiceContracts /></MemoryRouter>);
    const links = await screen.findAllByRole('link', { name: 'Allgemeinstrom Nordhaus' });
    expect(links).toHaveLength(2);                      // the table row and the deadline
    links.forEach(link => expect(link).toHaveAttribute('href', '/service-contracts/sc1'));
    expect(screen.getAllByText(/serviceContracts.deadlines.notice/).length).toBeGreaterThan(0);
    const urgent = screen.getByText('serviceContracts.daysLeft {"days":10}').closest('li');
    expect(urgent).toHaveClass('is-urgent');
    expect(api.get).toHaveBeenCalledWith('/service-contracts/deadlines?days=90', expect.anything());
  });

  it('filters on the server', async () => {
    render(<MemoryRouter><ServiceContracts /></MemoryRouter>);
    await screen.findAllByText('Allgemeinstrom Nordhaus');
    fireEvent.change(screen.getByRole('combobox', { name: 'serviceContracts.fields.type' }), { target: { value: 'gas' } });
    await waitFor(() => expect(api.list).toHaveBeenLastCalledWith('/service-contracts?contract_type=gas', expect.anything()));
  });

  it('offers no creation without write access', async () => {
    access.canWrite = false;
    render(<MemoryRouter><ServiceContracts /></MemoryRouter>);
    await screen.findAllByText('Allgemeinstrom Nordhaus');
    expect(screen.queryByRole('button', { name: /ui.table.add|Neu|serviceContracts.create/ })).not.toBeInTheDocument();
  });
});

describe('ServiceContractDetail', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    access.canWrite = true;
  });

  it('shows master data, tariffs with exact prices and the notice deadline', async () => {
    showDetail();
    expect(await screen.findByRole('heading', { name: 'Allgemeinstrom Nordhaus' })).toBeInTheDocument();
    const tabs = screen.getAllByRole('tab');
    expect(tabs.map(tab => tab.textContent)).toEqual(['serviceContracts.tabs.master', 'serviceContracts.tabs.locations (1)',
      'serviceContracts.tabs.tariffs (1)', 'serviceContracts.tabs.deadlines', 'serviceContracts.tabs.finance',
      'serviceContracts.tabs.documents']);
    fireEvent.click(screen.getByRole('tab', { name: 'serviceContracts.tabs.tariffs (1)' }));
    expect(screen.getByText('Arbeitspreis: 0,3247 €/kWh')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('tab', { name: 'serviceContracts.tabs.deadlines' }));
    const card = screen.getByTestId('sc-next-notice');
    expect(card).toHaveTextContent('serviceContracts.noticeDeadlineText');
    expect(card).toHaveTextContent('"days":29');
    expect(card).toHaveTextContent('serviceContracts.renewsTo');
  });

  it('keeps expectation, bills and payments apart in the finance tab', async () => {
    showDetail();
    fireEvent.click(await screen.findByRole('tab', { name: 'serviceContracts.tabs.finance' }));
    const figures = await screen.findByTestId('sc-figures');
    expect(within(figures).getByText('serviceContracts.figures.expected').nextSibling.textContent).toMatch(/1[.,]?200/);
    expect(within(figures).getByText('serviceContracts.figures.open').nextSibling.textContent).toMatch(/0,00|0\.00/);
    expect(screen.getByText(/BK 2026/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'serviceContracts.transfer' })).toBeInTheDocument();
  });

  it('is read only with a note when locations of other portfolios exist', async () => {
    showDetail({ ...CONTRACT, restricted: true });
    expect(await screen.findByRole('note')).toHaveTextContent('serviceContracts.restrictedNote');
    expect(screen.queryByRole('button', { name: 'serviceContracts.edit' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'serviceContracts.delete' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('tab', { name: 'serviceContracts.tabs.finance' }));
    await screen.findByTestId('sc-figures');
    expect(screen.queryByRole('button', { name: 'serviceContracts.linkPayment' })).not.toBeInTheDocument();
  });

  it('records a cancellation through the dialog', async () => {
    api.post.mockResolvedValue({});
    showDetail();
    fireEvent.click(await screen.findByRole('button', { name: 'serviceContracts.cancel' }));
    const dialog = screen.getByRole('dialog', { name: 'serviceContracts.cancel' });
    fireEvent.change(within(dialog).getByLabelText(/serviceContracts.fields.cancelledOn/), { target: { value: '2026-09-15' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'ui.buttons.save' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/service-contracts/sc1/cancel',
      { cancelled_on: '2026-09-15', effective_date: null }));
  });

  it('lists linked documents and bill scans', async () => {
    showDetail();
    fireEvent.click(await screen.findByRole('tab', { name: 'serviceContracts.tabs.documents' }));
    expect(await screen.findByRole('button', { name: 'serviceContracts.openDocument: Vertrag Strom' })).toBeInTheDocument();
    expect(screen.getByText('serviceContracts.fromBill')).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: /serviceContracts.unlink/ })).toHaveLength(1);   // only own links
  });
});
