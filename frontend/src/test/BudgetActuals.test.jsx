import { render, screen, fireEvent, cleanup, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import Budgets from '../pages/Budgets';
import { api } from '../api';

const fixture = vi.hoisted(() => ({ entities: {} }));
vi.mock('../api', () => ({ api: { list: vi.fn(), get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() } }));
vi.mock('../contexts/DataStoreContext', () => ({ useDataStore: () => null, useEntities: key => ({ items: fixture.entities[key] || [], loading: false, error: null }) }));
vi.mock('../components/DataTable', () => ({
  default: ({ data, rowActions }) => <ul>{data.map(row => <li key={row.id}>{row.property_name} {row.year}
    {rowActions(row).map(action => <button key={action.label} onClick={() => action.onClick(row)}>{action.label}</button>)}</li>)}</ul>,
}));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => vi.fn() }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: key => key, locale: 'de-DE' }) }));

const budget = { id: 'b1', property_id: 'house', year: 2026, category: 'maintenance', planned_amount: 1500,
  actual_amount: 100, booking_category_ids: ['repairs'] };
const preview = { budget_id: 'b1', year: 2026, actual_amount: 100, from_bookings: 949.99, difference: 849.99,
  categories: [{ id: 'repairs', name: 'Reparaturen' }],
  bookings: [{ id: 'k1', booking_date: '2026-04-02', category: 'Reparaturen', amount: 800, payment_text: 'Dachdecker' },
    { id: 'k2', booking_date: '2026-03-20', category: 'Reparaturen', amount: -1200.5, reverses_booking_id: 'k0' }] };

beforeEach(() => {
  vi.resetAllMocks();
  fixture.entities = { properties: [{ id: 'house', name: 'Haus' }] };
  api.list.mockResolvedValue([budget]);
});
afterEach(cleanup);

describe('Budget-Ist aus Buchungen', () => {
  it('shows the amount and its bookings first and saves only on request', async () => {
    api.get.mockResolvedValue(preview);
    api.post.mockResolvedValue({ ...budget, actual_amount: 949.99 });
    render(<MemoryRouter><Budgets /></MemoryRouter>);
    fireEvent.click(await screen.findByRole('button', { name: 'Ist aus Buchungen' }));

    const dialog = await screen.findByRole('dialog', { name: 'Ist aus Buchungen' });
    expect(api.get).toHaveBeenCalledWith('/budgets/b1/actual-from-bookings');
    expect(dialog).toHaveTextContent('949,99');
    expect(dialog).toHaveTextContent('„Reparaturen“');
    expect(within(dialog).getAllByRole('row')).toHaveLength(3);
    expect(dialog).toHaveTextContent('Storno');
    expect(api.post).not.toHaveBeenCalled();

    fireEvent.click(within(dialog).getByRole('button', { name: 'Als tatsächlichen Betrag übernehmen' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/budgets/b1/actual-from-bookings', { expected_amount: 949.99 }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });

  it('explains when no categories are chosen', async () => {
    api.get.mockRejectedValue(new Error('Für dieses Budget sind keine Buchungskategorien gewählt.'));
    render(<MemoryRouter><Budgets /></MemoryRouter>);
    fireEvent.click(await screen.findByRole('button', { name: 'Ist aus Buchungen' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('keine Buchungskategorien');
    expect(screen.queryByRole('button', { name: 'Als tatsächlichen Betrag übernehmen' })).not.toBeInTheDocument();
  });
});
