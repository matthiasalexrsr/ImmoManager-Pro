import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider, useLocation, useNavigate } from 'react-router-dom';
import Contracts from '../pages/Contracts';
import Units from '../pages/Units';
import Tenants from '../pages/Tenants';
import Meters from '../pages/Meters';

const mocks = vi.hoisted(() => ({ list: vi.fn(), get: vi.fn(), readings: vi.fn(), sources: {}, reload: vi.fn() }));
vi.mock('../api', () => ({ api: { list: mocks.list, get: mocks.get } }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: key => key, locale: 'de-DE' }) }));
vi.mock('../contexts/AuthContext', () => ({ useCanWrite: () => true, useAuth: () => null }));
vi.mock('../contexts/DataStoreContext', () => ({
  useDataStore: () => null,
  // Return stable source objects and arrays: Meters reloads when these change.
  useEntities: key => mocks.sources[key] || mocks.sources.empty,
}));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => async () => true }));
vi.mock('../components/Toast', () => ({ useToast: () => ({ error: vi.fn(), success: vi.fn() }) }));
vi.mock('../features/partyWorkspace/PartyWorkspace', () => ({
  usePartyWorkspace: () => ({ openParty: vi.fn() }),
  PartyLink: ({ children }) => <button>{children}</button>,
}));

const properties = [{ id: 'p1', name: 'Testhaus' }];
const units = [
  { id: 'u1', label: 'Bewohnte Einheit', property_id: 'p1', status: 'occupied', area_sqm: 60 },
  { id: 'u2', label: 'Leere Einheit', property_id: 'p1', status: 'vacant', area_sqm: 70 },
];
const tenants = [
  { id: 't1', full_name: 'Aktive Partei', archived: false },
  { id: 't2', full_name: 'Archivierte Partei', archived: true },
];
const contracts = [
  { id: 'c1', contract_number: 'MV-AKTIV', property_id: 'p1', unit_id: 'u1', tenant_id: 't1', status: 'active', start_date: '2020-01-01' },
  { id: 'c2', contract_number: 'MV-BEENDET', property_id: 'p1', unit_id: 'u2', tenant_id: 't2', status: 'terminated', start_date: '2020-01-01', end_date: '2021-12-31' },
];
const meters = [
  { id: 'm1', serial_number: 'ALT-001', meter_type: 'cold_water', unit_id: 'u1', is_active: true },
  { id: 'm2', serial_number: 'NEU-002', meter_type: 'electricity', unit_id: 'u2', is_active: false },
];
const readings = [
  { id: 'r1', meter_id: 'm2', reading_date: '2026-01-01', value: 100, notes: 'Neuer Januarstand' },
  { id: 'r2', meter_id: 'm2', reading_date: '2026-02-01', value: 130, notes: 'Neuer Februarstand' },
  { id: 'r3', meter_id: 'm2', reading_date: '2026-03-01', value: 160, notes: 'Neuer Märzstand' },
];

function Navigation({ page, targets }) {
  const Page = page;
  const navigate = useNavigate();
  const location = useLocation();
  return <>
    {Object.entries(targets).map(([name, target]) => <button key={name} onClick={() => navigate(target)}>{name}</button>)}
    <button onClick={() => navigate(-1)}>Browser zurück</button>
    <output aria-label="Aktuelle Route">{location.pathname}{location.search}</output>
    <Page />
  </>;
}

function mount(Page, initial, targets) {
  const router = createMemoryRouter([{ path: '*', element: <Navigation page={Page} targets={targets} /> }], { initialEntries: [initial] });
  return render(<RouterProvider router={router} />);
}

function deferred() {
  let resolve;
  const promise = new Promise(yes => { resolve = yes; });
  return { promise, resolve };
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  sessionStorage.clear();
  mocks.readings.mockReset().mockResolvedValue([]);
  const source = items => ({ items, loading: false, error: null, reload: mocks.reload });
  mocks.sources = { properties: source(properties), units: source(units), contracts: source(contracts),
    tenants: source(tenants), tenants_all: source(tenants), documents: source([]), empty: source([]) };
  mocks.get.mockResolvedValue({});
  mocks.list.mockImplementation((path, options) => {
    if (path === '/units') return Promise.resolve(units);
    if (path === '/contracts') return Promise.resolve(contracts);
    if (path === '/tenants?include_archived=true') return Promise.resolve(tenants);
    if (path === '/meters') return Promise.resolve(meters);
    if (path === '/meters/readings/all') return Promise.resolve([]);
    if (/^\/meters\/[^/]+\/readings$/.test(path)) return mocks.readings(path, options);
    return Promise.reject(new Error(`Unexpected list ${path}`));
  });
});
afterEach(cleanup);

describe('list pages follow route sources and browser history', () => {
  it('follows contract workflow links and Back while an exact historical contract bypasses the active filter', async () => {
    mount(Contracts, '/contracts?filter=active', {
      'Beendete Verträge öffnen': '/contracts?filter=terminated',
      'Historischen Vertrag öffnen': '/contracts?filter=active&contract_id=c2',
    });
    await screen.findByText('MV-AKTIV');
    expect(screen.queryByText('MV-BEENDET')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Beendete Verträge öffnen' }));
    await screen.findByText('MV-BEENDET');
    expect(screen.queryByText('MV-AKTIV')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Browser zurück' }));
    await screen.findByText('MV-AKTIV');
    expect(screen.queryByText('MV-BEENDET')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Historischen Vertrag öffnen' }));
    await screen.findByText('MV-BEENDET');
    expect(screen.queryByText('MV-AKTIV')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Aktiv', exact: true }));
    await screen.findByText('MV-AKTIV');
    expect(screen.getByLabelText('Aktuelle Route')).toHaveTextContent(/^\/contracts\?filter=active$/);
    fireEvent.click(screen.getByRole('button', { name: 'Browser zurück' }));
    await screen.findByText('MV-BEENDET');
  });

  it('writes unit workflow tabs to the URL, restores them on Back, and reveals an exact vacant target', async () => {
    mount(Units, '/units?filter=occupied', {
      'Vermietete Einheiten öffnen': '/units?filter=occupied',
      'Exakte leere Einheit öffnen': '/units?filter=occupied&focus_id=u2',
    });
    await screen.findByText('Bewohnte Einheit');
    expect(screen.queryByText('Leere Einheit')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Leer', exact: true }));
    await screen.findByText('Leere Einheit');
    expect(screen.getByLabelText('Aktuelle Route')).toHaveTextContent(/^\/units\?filter=vacant$/);
    fireEvent.click(screen.getByRole('button', { name: 'Vermietete Einheiten öffnen' }));
    await screen.findByText('Bewohnte Einheit');
    fireEvent.click(screen.getByRole('button', { name: 'Browser zurück' }));
    await screen.findByText('Leere Einheit');
    expect(screen.queryByText('Bewohnte Einheit')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Exakte leere Einheit öffnen' }));
    await screen.findByText('Leere Einheit');
    expect(screen.queryByText('Bewohnte Einheit')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Aktuelle Route')).toHaveTextContent('focus_id=u2');
  });

  it('opens an archived tenant from an already mounted active list and restores the active list on Back', async () => {
    mount(Tenants, '/tenants', { 'Archivierte Akte öffnen': '/tenants?focus_id=t2' });
    await screen.findByRole('button', { name: 'Aktive Partei', exact: true });
    expect(screen.queryByRole('button', { name: 'Archivierte Partei', exact: true })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Archivierte Akte öffnen' }));
    await screen.findByRole('button', { name: 'Archivierte Partei', exact: true });
    expect(screen.queryByRole('button', { name: 'Aktive Partei', exact: true })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Alle', exact: true })).toHaveAttribute('aria-pressed', 'true');
    fireEvent.click(screen.getByRole('button', { name: 'Browser zurück' }));
    await screen.findByRole('button', { name: 'Aktive Partei', exact: true });
    expect(screen.queryByRole('button', { name: 'Archivierte Partei', exact: true })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Aktiv', exact: true })).toHaveAttribute('aria-pressed', 'true');
  });

  it('aborts the old meter reading request and keeps all three new readings after a late old response', async () => {
    const oldReadings = deferred();
    const newReadings = deferred();
    mocks.readings.mockImplementation(path => path.includes('/m1/') ? oldReadings.promise : newReadings.promise);
    mount(Meters, '/meters?focus_id=m1', { 'Anderen Zähler öffnen': '/meters?focus_id=m2' });
    await waitFor(() => expect(mocks.readings).toHaveBeenCalledWith('/meters/m1/readings', expect.anything()));
    const firstSignal = mocks.readings.mock.calls[0][1].signal;
    fireEvent.click(screen.getByRole('button', { name: 'Anderen Zähler öffnen' }));
    await waitFor(() => expect(mocks.readings).toHaveBeenCalledWith('/meters/m2/readings', expect.anything()));
    expect(firstSignal.aborted).toBe(true);
    await act(async () => newReadings.resolve(readings));
    await screen.findByText('Neuer Märzstand');
    const readingTable = screen.getAllByRole('table')[1];
    expect(within(readingTable).getAllByRole('row')).toHaveLength(4);
    expect(within(readingTable).getByText('Neuer Januarstand')).toBeInTheDocument();
    expect(within(readingTable).getByText('Neuer Februarstand')).toBeInTheDocument();
    await act(async () => oldReadings.resolve([{ id: 'old-r', meter_id: 'm1', reading_date: '2026-01-01', value: 1, notes: 'Veralteter Zählerstand' }]));
    expect(screen.queryByText('Veralteter Zählerstand')).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /Ablesungen — NEU-002/ })).toBeInTheDocument();
    expect(within(readingTable).getByText('Neuer Märzstand')).toBeInTheDocument();
  });

  it('shows a reading failure with retry instead of a false empty table', async () => {
    mocks.readings.mockRejectedValueOnce(new Error('Messdienst nicht erreichbar')).mockResolvedValueOnce(readings);
    mount(Meters, '/meters?focus_id=m2', {});
    expect(await screen.findByRole('alert')).toHaveTextContent('Messdienst nicht erreichbar');
    expect(screen.getAllByRole('table')).toHaveLength(1);
    expect(screen.queryByText('Keine Einträge vorhanden.')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '+ Ablesung erfassen' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Ablesungen erneut laden' }));
    await screen.findByText('Neuer Märzstand');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getAllByRole('table')).toHaveLength(2);
    expect(screen.getByRole('button', { name: '+ Ablesung erfassen' })).toBeEnabled();
    expect(mocks.readings).toHaveBeenCalledTimes(2);
  });
});
