import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import UnitOverview from '../pages/UnitOverview';

const mocks = vi.hoisted(() => ({ get: vi.fn(), id: 'unit-a', user: null, locale: 'de-DE' }));
vi.mock('../api', () => ({ api: { get: mocks.get } }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: mocks.user }) }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ locale: mocks.locale, t: key => key }) }));
vi.mock('react-router-dom', async original => ({ ...await original(), useParams: () => ({ id: mocks.id }) }));
vi.mock('../components/PhotoDropZone', () => ({ default: ({ entityId }) => <div>Photo context {entityId}</div> }));
vi.mock('../components/StatusBadge', () => ({ default: ({ status }) => <span>{status}</span> }));

const deferred = () => { let resolve; const promise = new Promise(yes => { resolve = yes; }); return { promise, resolve }; };
const page = (items = [], next_cursor = null) => ({ items, has_more: next_cursor !== null, next_cursor });
const lease = (id = 'lease-a', unitId = 'unit-a', name = 'Exact tenant') => ({
  id, unit_id: unitId, property_id: `property-${unitId}`, tenant_name: name, contract_number: id,
  status: 'active', start_date: '2026-01-01', end_date: null, deposit_amount: 0,
});
const data = (unitId = 'unit-a', name = 'Exact tenant') => ({
  unit: { id: unitId, property_id: `property-${unitId}`, label: `Apartment ${unitId}`, unit_type: 'apartment',
    status: 'occupied', floor: '0', area_sqm: 0, rooms: 0, person_count: 0, features: null,
    cold_rent: 1234.56, service_charge_advance: 0, heating_advance: null },
  property: { id: `property-${unitId}`, name: `Building ${unitId}`, address_line: 'Synthetic street 1', postal_code: '12345', city: 'Teststadt' },
  active_contracts: page([lease(`lease-${unitId}`, unitId, name)]),
  contract_history: page([lease(`lease-${unitId}`, unitId, name)]), insurances: page(),
});
const view = () => render(<MemoryRouter><UnitOverview /></MemoryRouter>);
const amount = label => screen.getByText(label, { selector: 'dt' }).parentElement.querySelector('dd');

beforeEach(() => {
  mocks.get.mockReset(); mocks.id = 'unit-a'; mocks.locale = 'de-DE';
  mocks.user = { id: 'reader-a', role: 'readonly', portfolio_access: 'selected', portfolio_ids: ['portfolio-a'], write_permissions: [] };
  mocks.get.mockResolvedValue(data());
});

describe('unit workspace reads exact bounded context', () => {
  it('renders the real money fields, preserves zero and distinguishes missing values', async () => {
    view();
    await screen.findByRole('heading', { name: 'Apartment unit-a' });
    expect(amount('Kaltmiete')).toHaveTextContent('1.234,56 €');
    expect(amount('Nebenkostenvorauszahlung')).toHaveTextContent('0,00 €');
    expect(amount('Heizkostenvorauszahlung')).toHaveTextContent('—');
    expect(amount('Personenzahl')).toHaveTextContent('0');
    expect(screen.getAllByText('Exact tenant')).toHaveLength(2);
    expect(mocks.get).toHaveBeenCalledTimes(1);
    expect(mocks.get.mock.calls[0][0]).toBe('/units/unit-a/workspace?page_size=25');
  });

  it('shows all returned active parties instead of choosing the first one', async () => {
    const result = data(); result.active_contracts.items.push(lease('Second lease', 'unit-a', 'Second party'));
    mocks.get.mockResolvedValue(result);
    view();
    expect(await screen.findByText('Second party')).toBeVisible();
    expect(screen.getByText(/Mehrere aktive Verträge/)).toBeVisible();
  });

  it('does not turn a server failure into vacant tenancy and supports retry', async () => {
    mocks.get.mockRejectedValueOnce(new Error('Temporary server failure'));
    view();
    expect(await screen.findByRole('alert')).toHaveTextContent('Temporary server failure');
    expect(screen.queryByText(/Kein Vertrag/)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Erneut laden' }));
    expect(await screen.findByRole('heading', { name: 'Apartment unit-a' })).toBeVisible();
  });

  it('rejects an unrelated contract response without displaying another tenant', async () => {
    const result = data(); result.active_contracts.items = [lease('Wrong lease', 'unit-b', 'Private other tenant')];
    mocks.get.mockResolvedValue(result); view();
    expect(await screen.findByRole('alert')).toHaveTextContent('Antwort passt nicht');
    expect(screen.queryByText('Private other tenant')).not.toBeInTheDocument();
  });

  it.each(['unit', 'user', 'scope', 'role'])('removes prior names synchronously when %s changes', async change => {
    const rendered = view(); await screen.findByRole('heading', { name: 'Apartment unit-a' });
    const oldSignal = mocks.get.mock.calls[0][1].signal;
    const pending = deferred(); mocks.get.mockReturnValue(pending.promise);
    if (change === 'unit') mocks.id = 'unit-b';
    if (change === 'user') mocks.user = { ...mocks.user, id: 'reader-b' };
    if (change === 'scope') mocks.user = { ...mocks.user, portfolio_ids: ['portfolio-b'] };
    if (change === 'role') mocks.user = { ...mocks.user, role: 'buchhaltung' };
    rendered.rerender(<MemoryRouter><UnitOverview /></MemoryRouter>);
    expect(screen.queryByText('Exact tenant')).not.toBeInTheDocument();
    expect(screen.queryByText('Building unit-a')).not.toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('wird geladen');
    expect(oldSignal.aborted).toBe(true);
    await act(async () => pending.resolve(data(mocks.id, 'Current party')));
    expect(screen.getAllByText('Current party')).toHaveLength(2);
  });

  it('discards an old late response after a new unit has loaded', async () => {
    const old = deferred(); mocks.get.mockReturnValueOnce(old.promise);
    const rendered = view(); const oldSignal = mocks.get.mock.calls[0][1].signal;
    mocks.id = 'unit-b'; mocks.get.mockResolvedValue(data('unit-b', 'New party'));
    rendered.rerender(<MemoryRouter><UnitOverview /></MemoryRouter>);
    await screen.findByRole('heading', { name: 'Apartment unit-b' });
    expect(oldSignal.aborted).toBe(true);
    await act(async () => old.resolve(data('unit-a', 'Old private party')));
    expect(screen.queryByText('Old private party')).not.toBeInTheDocument();
    expect(screen.getAllByText('New party')).toHaveLength(2);
  });

  it('traverses history without advancing active leases and returns to the first page', async () => {
    const first = data(); first.contract_history.next_cursor = 'history-token'; first.contract_history.has_more = true;
    const second = data(); second.contract_history = page([{ ...lease('Historic lease'), status: 'terminated' }]);
    mocks.get.mockImplementation(path => Promise.resolve(path.includes('history_cursor=history-token') ? second : first));
    view(); await screen.findByRole('heading', { name: 'Apartment unit-a' });
    await userEvent.click(within(screen.getByRole('navigation', { name: 'Vertragshistorie' })).getByRole('button', { name: 'Nächste Seite' }));
    expect(await screen.findByRole('heading', { name: 'Historic lease' })).toBeVisible();
    const path = mocks.get.mock.calls.at(-1)[0];
    expect(path).toContain('history_cursor=history-token');
    expect(path).not.toContain('active_cursor');
    await userEvent.click(within(screen.getByRole('navigation', { name: 'Vertragshistorie' })).getByRole('button', { name: 'Vorherige Seite' }));
    await waitFor(() => expect(screen.queryByRole('heading', { name: 'Historic lease' })).not.toBeInTheDocument());
    expect(mocks.get.mock.calls.at(-1)[0]).not.toContain('cursor=');
  });

  it('removes loaded private data when a refresh returns denied access', async () => {
    view(); await screen.findByRole('heading', { name: 'Apartment unit-a' });
    mocks.get.mockRejectedValue(Object.assign(new Error('Private server detail'), { statusCode: 403 }));
    await userEvent.click(screen.getByRole('button', { name: 'Aktualisieren' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Zugriff wurde geändert');
    expect(screen.queryByText('Private server detail')).not.toBeInTheDocument();
    expect(screen.queryByText('Exact tenant')).not.toBeInTheDocument();
  });

  it('does not describe a concurrently emptied later page as having no contracts', async () => {
    const first = data(); first.active_contracts = page(first.active_contracts.items, 'active-token');
    const later = data(); later.active_contracts = page();
    mocks.get.mockImplementation(path => Promise.resolve(path.includes('active_cursor=active-token') ? later : first));
    view(); await screen.findByRole('heading', { name: 'Apartment unit-a' });
    await userEvent.click(within(screen.getByRole('navigation', { name: 'Aktive Mietverträge' })).getByRole('button', { name: 'Nächste Seite' }));
    expect(await screen.findByText('Auf dieser Seite sind aktuell keine Einträge vorhanden.')).toBeVisible();
    expect(screen.queryByText(/Kein Vertrag/)).not.toBeInTheDocument();
    expect(within(screen.getByRole('navigation', { name: 'Aktive Mietverträge' })).getByRole('button', { name: 'Vorherige Seite' })).toBeEnabled();
  });

  it('keeps the same workflow usable with the existing English locale', async () => {
    mocks.locale = 'en-US'; view();
    await screen.findByRole('heading', { name: 'Active leases' });
    expect(amount('Base rent')).toHaveTextContent('€1,234.56');
    expect(screen.getByRole('heading', { name: 'Lease history' })).toBeVisible();
  });
});
