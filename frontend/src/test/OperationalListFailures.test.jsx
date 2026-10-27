import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { Link, MemoryRouter } from 'react-router-dom';
import Calendar from '../pages/Calendar';
import Contacts from '../pages/Contacts';
import Listings from '../pages/Listings';
import Viewings from '../pages/Viewings';
import RentAdjustments from '../pages/RentAdjustments';
import RentCharges from '../pages/RentCharges';
import Portfolios from '../pages/Portfolios';
import AllocationKeys from '../pages/AllocationKeys';
import { api } from '../api';

const shared = vi.hoisted(() => ({ lookups: {}, lookupErrors: {}, reload: vi.fn(), invalidate: vi.fn(), toast: vi.fn() }));
vi.mock('../api', () => ({ api: { list: vi.fn(), get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() } }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: key => key, locale: 'de-DE' }) }));
vi.mock('../contexts/AuthContext', () => ({ useCanWrite: () => true }));
vi.mock('../contexts/DataStoreContext', () => ({
  useDataStore: () => ({ invalidateRelated: shared.invalidate }),
  useEntities: key => ({ items: shared.lookups[key] || [], error: shared.lookupErrors[key] || null,
    loading: false, reload: () => shared.reload(key) }),
}));
vi.mock('../components/Toast', () => ({ useToast: () => ({ success: shared.toast, error: shared.toast, warning: shared.toast }) }));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => async () => true }));
vi.mock('../components/NotificationArrival', () => ({ default: () => null }));
vi.mock('../features/channels/MarketingPanel', () => ({ default: () => null }));
vi.mock('../features/channels/ChannelPanel', () => ({ default: () => null }));
vi.mock('../features/partyWorkspace/PartyWorkspace', () => ({ PartyLink: ({ children }) => <span>{children}</span> }));
vi.mock('../components/FormModal', () => ({ default: ({ onSave, onClose }) => <div role="dialog">
  <button onClick={async () => { await onSave({}); onClose(); }}>Speichern</button>
  <button onClick={onClose}>Abbrechen</button>
</div> }));
vi.mock('../components/DataTable', () => ({ default: ({ data, onAdd, onEdit, onDelete, bulkActions = [] }) => <section data-testid="list">
  {onAdd && <button onClick={onAdd}>Neu anlegen</button>}
  {!data.length && <p>Erfolgreich geladene leere Liste</p>}
  {data.map(row => <div key={row.id} data-testid={row.id}>
    <span>{row.title || row.name || row.display_name || row.contract_label || row.contract_number || row.lead_name}</span>
    {'property_count' in row && <span data-testid="counts">{row.property_count === null ? 'Anzahl unbekannt' : `${row.property_count} Immobilien und ${row.total_units} Einheiten`}</span>}
    {onEdit && <button onClick={() => onEdit(row)}>Bearbeiten</button>}
    {onDelete && <button onClick={() => onDelete(row)}>Löschen</button>}
  </div>)}
  {bulkActions.length > 0 && <span>Stapelaktionen</span>}
</section> }));

const cases = [
  { Page: Calendar, endpoint: '/calendar', path: '/calendar', row: { id: 'row', title: 'Geladener Termin', event_date: '2027-08-20' }, lookup: 'properties' },
  { Page: Contacts, endpoint: '/contacts', path: '/contacts', row: { id: 'row', first_name: 'Geladener Kontakt', contact_type: 'tenant' } },
  { Page: Listings, endpoint: '/listings', path: '/listings', row: { id: 'row', title: 'Geladenes Inserat', unit_id: 'u1' }, lookup: 'units' },
  { Page: Viewings, endpoint: '/viewings', path: '/viewings?focus_id=row', row: { id: 'row', lead_id: 'l1', unit_id: 'u1', scheduled_at: '2027-08-20T12:00:00Z' }, lookup: 'leads' },
  { Page: RentAdjustments, endpoint: '/rent-adjustments', path: '/rent-adjustments', row: { id: 'row', contract_id: 'c1', status: 'pending' }, lookup: 'contracts' },
  { Page: RentCharges, endpoint: '/rent-charges', path: '/rent-charges', row: { id: 'row', contract_id: 'c1', month: '2026-10' }, lookup: 'tenants' },
  { Page: Portfolios, endpoint: '/portfolios', path: '/portfolios', row: { id: 'row', name: 'Geladenes Portfolio' } },
  { Page: AllocationKeys, endpoint: '/billing/allocation-keys', path: '/allocation-keys', row: { id: 'row', name: 'Geladener Schlüssel', property_id: 'p1' }, lookup: 'properties' },
];

function mount(entry, extra = null) {
  const Page = entry.Page;
  return render(<MemoryRouter initialEntries={[entry.path]}>{extra}<Page /></MemoryRouter>);
}

function defer() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

beforeEach(() => {
  vi.resetAllMocks();
  shared.lookupErrors = {};
  shared.lookups = { properties: [{ id: 'p1', name: 'Haus' }], units: [{ id: 'u1', label: 'Einheit' }],
    leads: [{ id: 'l1', full_name: 'Geladene Besichtigung' }], contracts: [{ id: 'c1', contract_number: 'Mietvertrag', tenant_id: 't1' }],
    tenants: [{ id: 't1', full_name: 'Mieterin' }] };
  api.post.mockResolvedValue({}); api.put.mockResolvedValue({}); api.del.mockResolvedValue(null);
});
afterEach(cleanup);

describe.each(cases)('$endpoint read failures', entry => {
  it('blocks false empty states on initial failure and recovers through retry', async () => {
    let attempt = 0;
    api.list.mockImplementation(path => path === entry.endpoint
      ? (++attempt === 1 ? Promise.reject(new Error('Quelle nicht erreichbar')) : Promise.resolve([entry.row]))
      : Promise.resolve(shared.lookups.properties));
    mount(entry);
    expect(await screen.findByRole('alert')).toHaveTextContent('Quelle nicht erreichbar');
    expect(screen.queryByTestId('list')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Neu anlegen' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Erneut laden' }));
    expect(await screen.findByTestId('row')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('treats malformed responses as a failed source and accepts a real empty array', async () => {
    let attempt = 0;
    api.list.mockImplementation(path => Promise.resolve(path === entry.endpoint ? (++attempt === 1 ? { items: [] } : []) : []));
    mount(entry);
    expect(await screen.findByRole('alert')).toHaveTextContent('nicht vollständig');
    expect(screen.queryByTestId('list')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Erneut laden' }));
    if (entry.endpoint === '/viewings') {
      await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
      fireEvent.click(screen.getByRole('button', { name: 'Tabelle' }));
    }
    expect(await screen.findByText('Erfolgreich geladene leere Liste')).toBeInTheDocument();
  });

  it('retains the previous list with an explicit warning after a mutation refresh fails', async () => {
    let attempt = 0;
    api.list.mockImplementation(path => path === entry.endpoint
      ? (++attempt === 1 ? Promise.resolve([entry.row]) : Promise.reject(new Error('Aktualisierung offline')))
      : Promise.resolve(shared.lookups.properties));
    mount(entry);
    await screen.findByTestId('row');
    fireEvent.click(screen.getByRole('button', { name: 'Neu anlegen' }));
    fireEvent.click(screen.getByRole('button', { name: 'Speichern' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Aktualisierung offline');
    expect(screen.getByRole('alert')).toHaveTextContent('zuletzt geladene Stand');
    expect(screen.getByTestId('row')).toBeInTheDocument();
  });

  it('aborts superseded reloads and prevents late responses from replacing newer results', async () => {
    const older = defer(), newer = defer(); let attempt = 0;
    api.list.mockImplementation(path => {
      if (path !== entry.endpoint) return Promise.resolve(shared.lookups.properties);
      attempt += 1;
      return attempt === 1 ? Promise.resolve([entry.row]) : attempt === 2 ? Promise.reject(new Error('Offline'))
        : attempt === 3 ? older.promise : newer.promise;
    });
    const view = mount(entry);
    await screen.findByTestId('row');
    fireEvent.click(screen.getByRole('button', { name: 'Neu anlegen' }));
    fireEvent.click(screen.getByRole('button', { name: 'Speichern' }));
    await screen.findByRole('alert');
    fireEvent.click(screen.getByRole('button', { name: 'Erneut laden' }));
    await waitFor(() => expect(attempt).toBe(3));
    const oldSignal = api.list.mock.calls.filter(([path]) => path === entry.endpoint)[2][1].signal;
    fireEvent.click(screen.getByRole('button', { name: 'Erneut laden' }));
    await waitFor(() => expect(attempt).toBe(4));
    expect(oldSignal.aborted).toBe(true);
    await act(async () => newer.resolve([{ ...entry.row, id: 'new' }]));
    expect(await screen.findByTestId('new')).toBeInTheDocument();
    await act(async () => older.resolve([entry.row]));
    expect(screen.getByTestId('new')).toBeInTheDocument();
    expect(screen.queryByTestId('row')).not.toBeInTheDocument();
    view.unmount();
    expect(api.list.mock.calls.filter(([path]) => path === entry.endpoint).at(-1)[1].signal.aborted).toBe(true);
  });
});

it.each(cases.filter(entry => entry.lookup))('$endpoint exposes failed form choices while retaining valid records', async entry => {
  if (entry.endpoint === '/calendar') api.list.mockImplementation(path => path === '/properties'
    ? Promise.reject(new Error('Auswahl offline')) : Promise.resolve([entry.row]));
  else {
    shared.lookupErrors[entry.lookup] = 'Auswahl offline';
    api.list.mockResolvedValue([entry.row]);
  }
  mount(entry);
  expect(await screen.findByTestId('row')).toBeInTheDocument();
  expect(screen.getByRole('alert')).toHaveTextContent('Auswahl offline');
  expect(screen.queryByRole('button', { name: 'Neu anlegen' })).not.toBeInTheDocument();
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Auswahl erneut laden' })));
  if (entry.endpoint !== '/calendar') expect(shared.reload).toHaveBeenCalledWith(entry.lookup);
});

it.each(['focus_id=row', 'suche=Geladener'])('reveals a contact from a same-route %s link despite the previous role tab', async query => {
  api.list.mockResolvedValue([cases[1].row]);
  mount(cases[1], <Link to={`/contacts?${query}`}>Kontaktquelle öffnen</Link>);
  await screen.findByTestId('row');
  fireEvent.click(screen.getByRole('button', { name: 'Dienstleister (0)' }));
  expect(screen.queryByTestId('row')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('link', { name: 'Kontaktquelle öffnen' }));
  expect(await screen.findByTestId('row')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Alle (1)' })).toHaveClass('active');
});

it.each(['/properties', '/units'])('keeps failed portfolio aggregate input %s unknown and recovers counts', async failedPath => {
  let failed = true;
  api.list.mockImplementation(path => path === '/portfolios' ? Promise.resolve([{ id: 'row', name: 'Bestand', owner_name: 'Matthias' }])
    : failed && path === failedPath ? Promise.reject(new Error('Bestandsquelle offline'))
      : Promise.resolve(path === '/properties' ? [{ id: 'p1', portfolio_id: 'row' }] : [{ id: 'u1', property_id: 'p1' }]));
  mount(cases.find(entry => entry.endpoint === '/portfolios'));
  expect(await screen.findByTestId('row')).toBeInTheDocument();
  expect(screen.getByRole('alert')).toHaveTextContent('Bestandsquelle offline');
  expect(screen.getByTestId('counts')).toHaveTextContent('Anzahl unbekannt');
  expect(screen.getByText(/Immobilien und Einheiten unbekannt/)).toBeInTheDocument();
  expect(screen.queryByText(/0 Immobilien/)).not.toBeInTheDocument();
  failed = false;
  fireEvent.click(screen.getByRole('button', { name: 'Bestandszahlen erneut laden' }));
  await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
  expect(screen.getByTestId('counts')).toHaveTextContent('1 Immobilien und 1 Einheiten');
});
