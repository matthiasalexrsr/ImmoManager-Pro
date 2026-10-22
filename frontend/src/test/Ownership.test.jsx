import { render, screen, fireEvent, cleanup, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import PropertyOwnership from '../features/ownership/PropertyOwnership';
import Budgets from '../pages/Budgets';
import { api } from '../api';

const fixture = vi.hoisted(() => ({ entities: {} }));
vi.mock('../api', () => ({ api: { list: vi.fn(), get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() } }));
vi.mock('../contexts/AuthContext', () => ({ useCanWrite: () => true, useAuth: () => ({ user: { id: 'u1' } }) }));
vi.mock('../contexts/DataStoreContext', () => ({ useDataStore: () => null, useEntities: key => ({ items: fixture.entities[key] || [], loading: false, error: null }) }));
vi.mock('../components/DataTable', () => ({ default: ({ data }) => <ul>{data.map(row => <li key={row.id}>{row.property_name}</li>)}</ul> }));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => vi.fn().mockResolvedValue(true) }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: key => key, locale: 'de-DE' }) }));

const owners = [{ id: 'linda', name: 'Linda', shares: 2 }, { id: 'm', name: 'Matthias', shares: 2 }];
const units = [{ id: 'we1', label: 'WE 1' }, { id: 'we3', label: 'WE 3' }];
const overview = { property_id: 'house', as_of: '2026-03-01', common_basis: 'area',
  common: [{ owner_contact_id: 'linda', name: 'Linda', percent: 55 }, { owner_contact_id: 'm', name: 'Matthias', percent: 45 }],
  units: [{ unit_id: 'we1', label: 'WE 1', basis: 'unit', owners: [{ owner_contact_id: 'm', name: 'Matthias', percent: 100 }] },
    { unit_id: 'we3', label: 'WE 3', basis: 'unit', owners: [{ owner_contact_id: 'linda', name: 'Linda', percent: 50 }, { owner_contact_id: 'm', name: 'Matthias', percent: 50 }] }] };
const shares = [{ id: 's1', owner_contact_id: 'm', property_id: 'house', unit_id: 'we1', share_percent: 100, valid_from: null, valid_to: null }];
const past = { property_id: 'house', objects: [{ unit_id: 'we1', label: 'WE 1', periods: [
  { from: null, to: '2026-07-15', owners: [{ owner_contact_id: 'm', name: 'Matthias', percent: 100 }] },
  { from: '2026-07-16', to: null, owners: [{ owner_contact_id: 'linda', name: 'Linda', percent: 100 }] }] }],
transfers: [{ id: 't1', effective_date: '2026-07-16', kind_label: 'Kauf', from_name: 'Matthias', fraction_percent: 100, scope: 'object',
  unit_label: 'WE 1', receivers: [{ owner_contact_id: 'linda', name: 'Linda', percent: 100 }], note: 'Notarvertrag', revertible: true }] };

beforeEach(() => {
  vi.resetAllMocks();
  fixture.entities = { properties: [{ id: 'house', name: 'Haus' }], owners };
});
afterEach(cleanup);

describe('Eigentümer', () => {
  it('shows who owns the house and each unit, and records a share for the whole house', async () => {
    api.get.mockImplementation(path => Promise.resolve(path.includes('/history') ? past : overview));
    api.list.mockImplementation(path => Promise.resolve(path.startsWith('/ownership-shares/owners') ? owners : shares));
    api.post.mockResolvedValue({});
    render(<MemoryRouter><PropertyOwnership propertyId="house" units={units} /></MemoryRouter>);
    expect(await screen.findByText(/Linda 55 %, Matthias 45 %/)).toBeInTheDocument();
    expect(screen.getByText('(nach Wohnfläche der Einheiten)')).toBeInTheDocument();
    const perUnit = screen.getByRole('region', { name: 'Eigentümer je Einheit' });
    expect(within(perUnit).getByText('Linda 50 %, Matthias 50 %')).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Erfasste Anteile' })).toHaveTextContent('Matthias');

    fireEvent.click(screen.getByRole('button', { name: 'Anteil erfassen' }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.change(within(dialog).getByLabelText(/^Eigentümer/), { target: { value: 'linda' } });
    fireEvent.change(within(dialog).getByLabelText(/^Anteil/), { target: { value: '60' } });
    fireEvent.submit(dialog.querySelector('form'));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/ownership-shares', expect.objectContaining(
      { owner_contact_id: 'linda', property_id: 'house', unit_id: null, share_percent: 60 })));
  });

  it('records a change of owners and shows the history', async () => {
    api.get.mockImplementation(path => Promise.resolve(path.includes('/history') ? past : overview));
    api.list.mockImplementation(path => Promise.resolve(path.startsWith('/ownership-shares/owners') ? owners : shares));
    api.post.mockResolvedValue({});
    render(<MemoryRouter><PropertyOwnership propertyId="house" units={units} /></MemoryRouter>);
    const history = await screen.findByRole('region', { name: 'Verlauf WE 1' });
    expect(within(history).getByText('seit jeher bis 15.07.2026')).toBeInTheDocument();
    expect(within(history).getByText('Linda 100 %')).toBeInTheDocument();
    expect(screen.getByRole('list', { name: 'Eigentümerwechsel' })).toHaveTextContent('16.07.2026 · Kauf: Matthias → Linda (100 %)');

    fireEvent.click(screen.getByRole('button', { name: 'Eigentümerwechsel erfassen' }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.change(within(dialog).getByLabelText(/^Art des Wechsels/), { target: { value: 'inheritance' } });
    fireEvent.change(within(dialog).getByLabelText(/^Wirksam ab/), { target: { value: '2026-09-01' } });
    fireEvent.change(within(dialog).getByLabelText(/^Bisheriger Eigentümer/), { target: { value: 'm' } });
    fireEvent.change(within(dialog).getByLabelText(/^Gilt für/), { target: { value: 'we1' } });
    fireEvent.change(within(dialog).getByLabelText('Empfänger 1'), { target: { value: 'linda' } });
    fireEvent.submit(dialog.querySelector('form'));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/ownership-shares/transfers', expect.objectContaining({
      property_id: 'house', unit_id: 'we1', scope: 'object', effective_date: '2026-09-01', from_owner_contact_id: 'm',
      kind: 'inheritance', fraction_percent: 100, receivers: [{ owner_contact_id: 'linda', percent: 100 }] })));
  });

  it('shows an owner\'s part of the budgets', async () => {
    api.list.mockResolvedValue([{ id: 'b1', property_id: 'house', year: 2026, category: 'maintenance', planned_amount: 1000, actual_amount: 200 }]);
    api.get.mockResolvedValue({ total_planned: 450, total_actual: 90, total_deviation: -360, by_category: [] });
    render(<MemoryRouter><Budgets /></MemoryRouter>);
    fireEvent.change(await screen.findByRole('combobox', { name: 'Eigentümer' }), { target: { value: 'm' } });
    await waitFor(() => expect(api.get).toHaveBeenCalledWith('/budgets/analysis?owner_contact_id=m'));
    expect(await screen.findByText('Geplant – Anteil Matthias')).toBeInTheDocument();
    expect(screen.getByText(/450,00/)).toBeInTheDocument();
  });

  it('undoes the latest change from the history', async () => {
    api.get.mockImplementation(path => Promise.resolve(path.includes('/history') ? past : overview));
    api.list.mockImplementation(path => Promise.resolve(path.startsWith('/ownership-shares/owners') ? owners : shares));
    api.post.mockResolvedValue({});
    render(<MemoryRouter><PropertyOwnership propertyId="house" units={units} /></MemoryRouter>);
    const journal = await screen.findByRole('list', { name: 'Eigentümerwechsel' });
    fireEvent.click(within(journal).getByRole('button', { name: 'Rückgängig machen' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/ownership-shares/transfers/t1/revert', {}));
  });
});
