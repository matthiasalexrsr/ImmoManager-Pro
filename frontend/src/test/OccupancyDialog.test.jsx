import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, within, waitFor } from '@testing-library/react';
import OccupancyDialog from '../features/contracts/OccupancyDialog';
import { api } from '../api';

vi.mock('../api', () => ({ api: { get: vi.fn(), post: vi.fn(), del: vi.fn() } }));
const t = (key, params) => (params ? `${key} ${JSON.stringify(params)}` : key);
vi.mock('../i18n', () => ({ useTranslation: () => ({ t, locale: 'de-DE' }) }));

const contract = { id: 'c1', contract_number: 'V-1', start_date: '2020-01-01', end_date: null, persons: 2 };

describe('Dated occupants of a contract', () => {
  let entries;

  beforeEach(() => {
    vi.clearAllMocks();
    entries = [{ id: 'o1', contract_id: 'c1', valid_from: '2025-07-01', persons: 3, notes: 'Geburt' }];
    api.get.mockImplementation(() => Promise.resolve([...entries]));
    api.post.mockImplementation((path, body) => {
      entries.push({ id: 'o2', ...body });
      return Promise.resolve({ id: 'o2', ...body });
    });
    api.del.mockImplementation(() => {
      entries = [];
      return Promise.resolve(null);
    });
  });

  it('shows the household size of the contract and every dated change', async () => {
    render(<OccupancyDialog contract={contract} onClose={() => {}} />);

    const row = (await screen.findByText('Geburt')).closest('tr');
    expect(within(row).getByText('01.07.2025')).toBeInTheDocument();
    expect(within(row).getByText('3')).toBeInTheDocument();
    expect(screen.getByText(/"persons":2/)).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith('/contracts/c1/occupancies');
  });

  it('adds a change with a whole number of persons and removes one', async () => {
    const { container } = render(<OccupancyDialog contract={contract} onClose={() => {}} />);
    await screen.findByText('Geburt');

    fireEvent.change(container.querySelector('input[type="date"]'), { target: { value: '2025-10-01' } });
    fireEvent.change(container.querySelector('input[type="number"]'), { target: { value: '4' } });
    fireEvent.click(screen.getByText('tenantsContracts.contracts.occupants.add'));

    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/contracts/c1/occupancies', {
      contract_id: 'c1', valid_from: '2025-10-01', persons: 4, notes: null,
    }));
    expect(await screen.findByText('01.10.2025')).toBeInTheDocument();

    fireEvent.click(screen.getAllByText('tenantsContracts.contracts.occupants.remove')[0]);
    await waitFor(() => expect(api.del).toHaveBeenCalledWith('/contracts/c1/occupancies/o1'));
    expect(await screen.findByText('tenantsContracts.contracts.occupants.empty')).toBeInTheDocument();
  });

  it('shows the server refusal, e.g. a date before the contract start', async () => {
    api.post.mockRejectedValueOnce(new Error('Ein Bewohnerstand kann nicht vor Vertragsbeginn gelten'));
    const { container } = render(<OccupancyDialog contract={contract} onClose={() => {}} />);
    await screen.findByText('Geburt');

    fireEvent.change(container.querySelector('input[type="date"]'), { target: { value: '2019-12-01' } });
    fireEvent.change(container.querySelector('input[type="number"]'), { target: { value: '1' } });
    fireEvent.submit(container.querySelector('form'));

    expect(await screen.findByRole('alert')).toHaveTextContent('vor Vertragsbeginn');
  });
});
