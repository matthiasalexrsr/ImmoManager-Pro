import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import Units from '../pages/Units';
import Properties from '../pages/Properties';
import { api } from '../api';

const sources = vi.hoisted(() => ({ data: {} }));
vi.mock('../api', () => ({ api: { list: vi.fn(), get: vi.fn() } }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: () => undefined, locale: 'de-DE' }) }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => null, useCanWrite: () => false }));
vi.mock('../contexts/DataStoreContext', () => ({ useDataStore: () => null,
  useEntities: name => sources.data[name] || { items: [], loading: false, error: null } }));
vi.mock('../features/partyWorkspace/PartyWorkspace', () => ({ PartyLink: ({ children }) => <span>{children}</span> }));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => async () => true }));
vi.mock('../components/Toast', () => ({ useToast: () => ({ error: vi.fn() }) }));

const properties = [{ id: 'p1', name: 'Haus A' }, { id: 'p2', name: 'Haus B' }];
const units = [{ id: 'u1', property_id: 'p1', label: 'Wohnung A', status: 'occupied', cold_rent: 600 },
  { id: 'u2', property_id: 'p2', label: 'Wohnung B', status: 'vacant', cold_rent: null }];
beforeEach(() => {
  vi.clearAllMocks(); localStorage.clear(); sessionStorage.clear();
  sources.data = { properties: { items: properties } };
  api.list.mockImplementation(async path => path === '/units' ? units : path === '/properties' ? properties : []);
  api.get.mockResolvedValue({});
});
afterEach(cleanup);

describe('estate lists', () => {
  it('includes an explicitly rent-free unit in the average and its exact KPI source', async () => {
    api.list.mockResolvedValue([...units, { id: 'free', property_id: 'p1', label: 'Mietfrei', cold_rent: 0 }]);
    render(<MemoryRouter><Units /></MemoryRouter>);
    const card = await screen.findByRole('button', { name: 'Ø Plan-Kaltmiete: Quellvorgänge anzeigen' });
    expect(card).toHaveTextContent('300,00 €');
    fireEvent.click(card);
    expect(screen.getByText('Mietfrei')).toBeInTheDocument();
    expect(screen.queryByText('Wohnung B')).not.toBeInTheDocument();
  });
  it('keeps the property context in the unit list and lets the user return to the full list', async () => {
    render(<MemoryRouter initialEntries={['/units?property_id=p2']}><Units /></MemoryRouter>);
    await screen.findByText('Wohnung B');
    expect(screen.queryByText('Wohnung A')).not.toBeInTheDocument();
    expect(within(screen.getByLabelText('Einheitenauswahl')).getByRole('link', { name: 'Haus B' })).toHaveAttribute('href', '/properties/p2?tab=units');
    fireEvent.click(screen.getByRole('button', { name: 'Objektfilter aufheben' }));
    expect(await screen.findByText('Wohnung A')).toBeInTheDocument();
  });
  it('shows a failed property lookup instead of misleading empty names or zero KPIs', async () => {
    sources.data.properties = { items: [], loading: false, error: 'Immobilien fehlen', reload: vi.fn() };
    render(<MemoryRouter><Units /></MemoryRouter>);
    expect(await screen.findByRole('alert')).toHaveTextContent('Immobilien fehlen');
    expect(screen.queryByText('Wohnung A')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Erneut laden' }));
    expect(sources.data.properties.reload).toHaveBeenCalledOnce();
  });
  it('weights occupancy by units and does not present missing planned rent as zero', async () => {
    sources.data.units = { items: [units[0], ...Array.from({ length: 9 }, (_, i) => ({ ...units[1], id: 'b' + i }))] };
    render(<MemoryRouter><Properties /></MemoryRouter>);
    const card = await screen.findByRole('button', { name: 'Vermietungsquote: Quellvorgänge anzeigen' });
    expect(card).toHaveTextContent(/10\s%/);
    const row = screen.getByRole('row', { name: /Haus B/ });
    expect(within(row).queryByText('0,00 €')).not.toBeInTheDocument();
  });
});
