import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import Units from '../pages/Units';
import Properties from '../pages/Properties';
import Contacts from '../pages/Contacts';
import { api } from '../api';
import { ownersLabel } from '../features/ownership/currentOwners';

const sources = vi.hoisted(() => ({ data: {} }));
vi.mock('../api', () => ({ api: { list: vi.fn(), get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() } }));
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
const current = {
  properties: { p1: [{ owner_contact_id: 'linda', name: 'Linda', percent: 55 }, { owner_contact_id: 'm', name: 'Matthias', percent: 45 }] },
  units: { u1: [{ owner_contact_id: 'linda', name: 'Linda', percent: 100 }] },
};
const holdings = { owner_contact_id: 'linda', name: 'Linda', as_of: '2026-10-22', shares: [
  { id: 's1', property_id: 'p1', property_name: 'Haus A', unit_id: 'u1', unit_label: 'Wohnung A', share_percent: 100,
    valid_from: '2024-01-01', valid_to: null, current: true },
  { id: 's2', property_id: 'p2', property_name: 'Haus B', unit_id: null, unit_label: null, share_percent: 33.3333,
    valid_from: null, valid_to: '2025-12-31', current: false },
] };

beforeEach(() => {
  vi.clearAllMocks(); localStorage.clear(); sessionStorage.clear();
  sources.data = { properties: { items: properties }, units: { items: units } };
  api.list.mockImplementation(async path => path === '/units' ? units : path === '/properties' ? properties
    : path === '/contacts' ? [{ id: 'linda', contact_type: 'owner', first_name: 'Linda' }, { id: 't', contact_type: 'tenant', first_name: 'Mia' }] : []);
  api.get.mockImplementation(async path => path === '/ownership-shares/current' ? current
    : path.startsWith('/ownership-shares/holdings') ? holdings : {});
});
afterEach(cleanup);

describe('owners in the lists and on the contact', () => {
  it('names a sole owner without the percent and co-owners with theirs', () => {
    expect(ownersLabel([{ name: 'Linda', percent: 100 }])).toBe('Linda');
    expect(ownersLabel(current.properties.p1)).toBe('Linda 55 %, Matthias 45 %');
    expect(ownersLabel([])).toBe('');
  });

  it('shows today\'s owners in the unit and property lists', async () => {
    render(<MemoryRouter><Units /></MemoryRouter>);
    await screen.findByRole('columnheader', { name: /Eigentümer/ });
    expect(screen.getByRole('row', { name: /Wohnung A/ })).toHaveTextContent('Linda');
    cleanup();
    render(<MemoryRouter><Properties /></MemoryRouter>);
    await screen.findByRole('columnheader', { name: /Eigentümer/ });
    expect(screen.getByRole('row', { name: /Haus A/ })).toHaveTextContent('Linda 55 %, Matthias 45 %');
  });

  it('keeps the column out of the way while no share is recorded', async () => {
    api.get.mockResolvedValue({ properties: {}, units: {} });
    render(<MemoryRouter><Units /></MemoryRouter>);
    await screen.findByText('Wohnung A');
    expect(screen.queryByRole('columnheader', { name: /Eigentümer/ })).not.toBeInTheDocument();
  });

  it('lists an owner\'s shares with links to the property, the unit and their bookings', async () => {
    render(<MemoryRouter><Contacts /></MemoryRouter>);
    await screen.findByText('Linda');
    expect(screen.queryAllByRole('button', { name: 'Anteile anzeigen' })).toHaveLength(1);   // owners only
    fireEvent.click(screen.getByRole('button', { name: 'Anteile anzeigen' }));
    const region = await screen.findByRole('region', { name: 'Anteile von Linda' });
    await within(region).findByRole('link', { name: 'Haus A' });
    expect(api.get).toHaveBeenCalledWith('/ownership-shares/holdings?owner_contact_id=linda');
    expect(within(region).getByRole('link', { name: 'Haus A' })).toHaveAttribute('href', '/properties/p1?tab=owners');
    expect(within(region).getByRole('link', { name: 'Wohnung A' })).toHaveAttribute('href', '/units/u1');
    const ended = within(region).getByRole('link', { name: 'Haus B' }).closest('tr');
    expect(ended).toHaveTextContent('ganzes Objekt');
    expect(ended).toHaveTextContent('33,3333 %');
    expect(ended).toHaveTextContent('nicht aktuell');
    expect(within(region).getByRole('link', { name: /Buchungen mit Anteil/ })).toHaveAttribute('href', '/bookings?owner_contact_id=linda');
  });
});
