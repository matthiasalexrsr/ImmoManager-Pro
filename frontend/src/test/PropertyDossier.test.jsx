import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import PropertyDetail from '../pages/PropertyDetail';
import UnitOverview from '../pages/UnitOverview';
import { api } from '../api';

const pdfSources = vi.hoisted(() => []);
vi.mock('pdfjs-dist/legacy/build/pdf.mjs', () => ({ GlobalWorkerOptions: {}, getDocument: options => {
  pdfSources.push(options.url);
  return { promise: new Promise(() => {}), destroy: async () => {} };
} }));

const access = vi.hoisted(() => ({ canWrite: true, write: null }));
vi.mock('../api', () => ({ api: { get: vi.fn(), list: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), del: vi.fn() } }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: () => undefined, locale: 'de-DE' }) }));
vi.mock('../contexts/AuthContext', () => ({
  useCanWrite: path => access.canWrite && (access.write === null || access.write.includes(path)),
  useAuth: () => ({ user: { id: 'viewer' }, write: access.canWrite ? access.write : [] }),
}));
vi.mock('../components/PhotoDropZone', () => ({ default: () => null }));
// Personal workspace requests have their own workflow coverage. Keep domain
// request assertions in these existing dossier tests independent of that traffic.
vi.mock('../utils/workspaceClient', async importOriginal => {
  const actual = await importOriginal();
  return { ...actual, workspace: { ...actual.workspace,
    list: async () => ({ items: [], next_cursor: null }),
    get: async () => { throw Object.assign(new Error('Nicht gemerkt'), { statusCode: 404 }); },
    touch: async () => ({}),
    put: async (resource, id, body) => ({ ...body, id, revision: 1 }),
    remove: async () => ({ deleted: true }),
  } };
});

const properties = {
  p1: { id: 'p1', name: 'Haus Alpha', address_line: 'Am Park 1', city: 'Berlin', status: 'active' },
  p2: { id: 'p2', name: 'Haus Beta', address_line: 'Am See 2', city: 'Berlin', status: 'active' },
};
const units = {
  p1: [{ id: 'u1', property_id: 'p1', label: 'Wohnung Alpha', unit_type: 'apartment', area_sqm: 60, cold_rent: 900, service_charge_advance: 100, heating_advance: 80, status: 'vacant' }],
  p2: [{ id: 'u2', property_id: 'p2', label: 'Wohnung Beta', unit_type: 'apartment', area_sqm: 75, cold_rent: 1200, status: 'vacant' }],
};
const documents = {
  p1: [
    { id: 'd1', property_id: 'p1', title: 'Energieausweis Alpha', document_type: 'Energieausweis', document_date: '2026-09-15', file_url: '/uploads/alpha.pdf' },
    { id: 'd2', property_id: 'p1', title: 'Rechnung Alpha', document_type: 'Rechnung', document_date: '2026-09-16', file_url: '/uploads/invoice.png' },
    { id: 'd3', property_id: 'p1', title: 'Papierakte', document_type: 'Sonstiges', document_date: null, file_url: '' },
    { id: 'd4', property_id: 'p1', title: 'Alter Verweis', document_type: 'Sonstiges', document_date: null, file_url: 'javascript:alert(1)' },
  ],
  p2: [{ id: 'd5', property_id: 'p2', title: 'Energieausweis Beta', document_type: 'Energieausweis', document_date: '2026-08-10', file_url: '/uploads/beta.pdf' }],
};
const deferred = () => {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
};

function NewFormTarget() {
  const location = useLocation();
  return <pre data-testid="new-form-target">{JSON.stringify({ path: location.pathname + location.search, state: location.state })}</pre>;
}

function RoutesUnderTest() {
  const navigate = useNavigate();
  const location = useLocation();
  return <>
    <output data-testid="location">{location.pathname + location.search}</output>
    <button onClick={() => navigate('/properties/p2')}>Anderes Objekt</button>
    <button onClick={() => navigate(-1)}>Browser zurück</button>
    <Routes>
      <Route path="/properties/:id" element={<PropertyDetail />} />
      <Route path="/units/:id" element={<UnitOverview />} />
      <Route path="/properties" element={<h1>Immobilienliste</h1>} />
      <Route path="/units" element={<h1>Einheitenliste</h1>} />
      <Route path="/tasks" element={<NewFormTarget />} />
      <Route path="/bookings" element={<NewFormTarget />} />
    </Routes>
  </>;
}
const show = (path = '/properties/p1') => render(<MemoryRouter initialEntries={[path]}><RoutesUnderTest /></MemoryRouter>);

beforeEach(() => {
  pdfSources.length = 0;
  vi.resetAllMocks();
  access.canWrite = true;
  access.write = null;
  api.get.mockImplementation(path => {
    if (path === '/auth/me') return Promise.resolve({ id: 'reader' });
    if (path.startsWith('/properties/')) return Promise.resolve(properties[path.split('/').pop()]);
    if (path.startsWith('/units/')) return Promise.resolve(Object.values(units).flat().find(unit => unit.id === path.split('/').pop()));
    if (path.startsWith('/files/ocr-text?')) return Promise.resolve({ has_ocr: false });
    return Promise.reject(new Error(`Unexpected GET ${path}`));
  });
  api.list.mockImplementation(path => {
    const [route, query] = path.split('?');
    const id = new URLSearchParams(query).get('property_id');
    if (route === '/units') return Promise.resolve(units[id] || []);
    if (route === '/documents') return Promise.resolve(documents[id] || []);
    if (['/contracts', '/maintenance', '/insurances'].includes(route)) return Promise.resolve([]);
    return Promise.reject(new Error(`Unexpected LIST ${path}`));
  });
});
afterEach(cleanup);

describe('property dossier loading', () => {
  it('discards a late result from the previous property', async () => {
    const previous = deferred();
    api.get.mockImplementation(path => path === '/properties/p1' ? previous.promise : Promise.resolve(properties.p2));
    show();
    fireEvent.click(screen.getByRole('button', { name: 'Anderes Objekt' }));
    await screen.findByRole('heading', { name: 'Haus Beta' });
    await act(async () => previous.resolve(properties.p1));
    expect(screen.getByRole('heading', { name: 'Haus Beta' })).toBeInTheDocument();
    expect(screen.queryByText('Wohnung Alpha')).not.toBeInTheDocument();
    expect(screen.queryByText('Energieausweis Alpha')).not.toBeInTheDocument();
  });

  it('clears the previous property while the next property is loading and aborts its requests', async () => {
    const next = deferred();
    api.get.mockImplementation(path => path === '/properties/p1' ? Promise.resolve(properties.p1) : next.promise);
    show();
    await screen.findByRole('heading', { name: 'Haus Alpha' });
    const oldOptions = api.get.mock.calls.find(([path]) => path === '/properties/p1')[1];
    fireEvent.click(screen.getByRole('button', { name: 'Anderes Objekt' }));
    expect(screen.queryByRole('heading', { name: 'Haus Alpha' })).not.toBeInTheDocument();
    expect(screen.queryByText('Wohnung Alpha')).not.toBeInTheDocument();
    expect(oldOptions?.signal.aborted).toBe(true);
    await act(async () => next.resolve(properties.p2));
    expect(screen.getByRole('heading', { name: 'Haus Beta' })).toBeInTheDocument();
  });

  it.each(['units', 'contracts', 'documents', 'maintenance'])('shows a failed %s request instead of an empty dossier and retries', async resource => {
    const normalList = api.list.getMockImplementation();
    let failed = true;
    api.list.mockImplementation(path => failed && path.startsWith(`/${resource}?`)
      ? Promise.reject(new Error('Verbindung unterbrochen')) : normalList(path));
    show();
    expect(await screen.findByRole('alert')).toHaveTextContent('Verbindung unterbrochen');
    expect(screen.queryByText('Keine Dokumente')).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Haus Alpha' })).not.toBeInTheDocument();
    failed = false;
    fireEvent.click(screen.getByRole('button', { name: 'Erneut laden' }));
    await screen.findByRole('heading', { name: 'Haus Alpha' });
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByText('Wohnung Alpha')).toBeInTheDocument();
  });

  it('keeps a failed property request retryable', async () => {
    api.get.mockRejectedValueOnce(new Error('Immobilie nicht gefunden'));
    show();
    expect(await screen.findByRole('alert')).toHaveTextContent('Immobilie nicht gefunden');
    fireEvent.click(screen.getByRole('button', { name: 'Erneut laden' }));
    expect(await screen.findByRole('heading', { name: 'Haus Alpha' })).toBeInTheDocument();
  });
});

describe('property dossier actions', () => {
  it('shows missing area as unknown instead of zero or a misleading price per square metre', async () => {
    const base = api.list.getMockImplementation();
    api.list.mockImplementation(path => path.startsWith('/units?') ? Promise.resolve([{ ...units.p1[0], area_sqm: null }]) : base(path));
    show();
    await screen.findByRole('heading', { name: 'Haus Alpha' });
    expect(screen.getByRole('button', { name: /Plan-Kaltmiete €\/m²/ })).toHaveTextContent('—');
    expect(screen.getByText(/Für 1 von 1 Einheiten fehlt die Fläche/)).toBeInTheDocument();
    expect(screen.queryByText('0 m²')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('tab', { name: 'Einheiten (1)' }));
    const total = screen.getByRole('row', { name: /Summe/ });
    expect(within(total).getAllByRole('cell')[2]).toHaveTextContent('—');
  });
  it('reopens a linked tab after reload, preserves unrelated parameters and supports roving keyboard tabs', async () => {
    show('/properties/p1?tab=documents&notice_id=receipt');
    const documents = await screen.findByRole('tab', { name: 'Dokumente (4)' });
    expect(documents).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tabpanel')).toHaveAttribute('aria-labelledby', documents.id);
    documents.focus();
    fireEvent.keyDown(documents, { key: 'ArrowLeft' });
    const finance = screen.getByRole('tab', { name: 'Finanzen' });
    expect(finance).toHaveFocus(); expect(finance).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByTestId('location')).toHaveTextContent('tab=finance');
    expect(screen.getByTestId('location')).toHaveTextContent('notice_id=receipt');
    fireEvent.keyDown(finance, { key: 'Home' });
    expect(screen.getByRole('tab', { name: 'Übersicht' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByTestId('location')).not.toHaveTextContent('tab=');
  });
  it('opens a unit from each view and returns to its actual property', async () => {
    show();
    await screen.findByRole('heading', { name: 'Haus Alpha' });
    expect(screen.getByRole('link', { name: 'Wohnung Alpha' })).toHaveAttribute('href', '/units/u1');
    fireEvent.click(screen.getByRole('tab', { name: 'Einheiten (1)' }));
    expect(screen.getByRole('link', { name: 'Wohnung Alpha' })).toHaveAttribute('href', '/units/u1');
    fireEvent.click(screen.getByRole('tab', { name: 'Finanzen' }));
    expect(screen.getByRole('link', { name: 'Wohnung Alpha' })).toHaveAttribute('href', '/units/u1');
    expect(screen.getByText(/Stammdaten.*Einheiten/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('link', { name: 'Wohnung Alpha' }));
    await screen.findByRole('heading', { name: 'Wohnung Alpha' });
    const back = screen.getByRole('link', { name: /Zur Immobilie/ });
    expect(back).toHaveAttribute('href', '/properties/p1');
    fireEvent.click(back);
    expect(await screen.findByRole('heading', { name: 'Haus Alpha' })).toBeInTheDocument();
  });

  it('adds only one history entry when a unit link is inside a clickable table row', async () => {
    show('/properties/p1?tab=units');
    fireEvent.click(await screen.findByRole('link', { name: 'Wohnung Alpha', exact: true }));
    await screen.findByRole('heading', { name: 'Wohnung Alpha', exact: true });
    fireEvent.click(screen.getByRole('button', { name: 'Browser zurück' }));
    await screen.findByRole('heading', { name: 'Haus Alpha', exact: true });
    expect(screen.getByRole('tab', { name: 'Einheiten (1)' })).toHaveAttribute('aria-selected', 'true');
  });

  it('opens the selected document with the shared viewer and restores keyboard focus', async () => {
    const user = userEvent.setup();
    show();
    await screen.findByRole('heading', { name: 'Haus Alpha' });
    const open = screen.getByRole('button', { name: 'Dokument ansehen: Energieausweis Alpha' });
    open.focus();
    await user.keyboard('{Enter}');
    const viewer = screen.getByRole('dialog', { name: 'Energieausweis Alpha' });
    expect(within(viewer).getByRole('link', { name: 'Öffnen' })).toHaveAttribute('href', `${window.location.origin}/uploads/alpha.pdf`);
    await waitFor(() => expect(pdfSources).toContain(`${window.location.origin}/uploads/alpha.pdf`));
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(open).toHaveFocus();
  });

  it('shows document metadata and missing or invalid files without offering an empty preview to readers', async () => {
    access.canWrite = false;
    show();
    await screen.findByRole('heading', { name: 'Haus Alpha' });
    fireEvent.click(screen.getByRole('tab', { name: 'Dokumente (4)' }));
    const pdfRow = screen.getByText('Energieausweis Alpha').closest('tr');
    expect(within(pdfRow).getByText('Energieausweis')).toBeInTheDocument();
    expect(within(pdfRow).getByText('15.09.2026')).toBeInTheDocument();
    const missing = screen.getByText('Papierakte').closest('tr');
    expect(within(missing).getByText('Datei fehlt')).toBeInTheDocument();
    expect(within(missing).queryByRole('button')).not.toBeInTheDocument();
    const invalid = screen.getByText('Alter Verweis').closest('tr');
    expect(within(invalid).getByText('Ungültiger Dateiverweis')).toBeInTheDocument();
    expect(within(invalid).queryByRole('button')).not.toBeInTheDocument();
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Dokument ansehen: Rechnung Alpha' })));
    expect(screen.getByRole('dialog', { name: 'Rechnung Alpha' })).toBeInTheDocument();
    expect(screen.getByRole('img', { name: 'Rechnung Alpha' })).toHaveAttribute('src', `${window.location.origin}/uploads/invoice.png`);
    expect(api.post).not.toHaveBeenCalled();
    expect(api.put).not.toHaveBeenCalled();
    expect(api.patch).not.toHaveBeenCalled();
    expect(api.del).not.toHaveBeenCalled();
  });

  it('closes the previous document when the property changes', async () => {
    show();
    await screen.findByRole('heading', { name: 'Haus Alpha' });
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Dokument ansehen: Energieausweis Alpha' })));
    expect(screen.getByRole('dialog', { name: 'Energieausweis Alpha' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Anderes Objekt' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    await screen.findByRole('heading', { name: 'Haus Beta' });
    expect(screen.queryByText('Energieausweis Alpha')).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByText('Energieausweis Beta')).toBeInTheDocument());
  });
});

describe('property page as the place to act on a property', () => {
  const contract = { id: 'c1', contract_number: 'MV-7', property_id: 'p1', unit_id: 'u1', tenant_id: 't1',
    start_date: '2019-05-01', end_date: null, status: 'active' };
  const withContract = () => {
    const base = api.list.getMockImplementation();
    api.list.mockImplementation(path => {
      if (path.startsWith('/contracts')) return Promise.resolve([contract]);
      if (path === '/tenants') return Promise.resolve([{ id: 't1', full_name: 'Lena Langzeit' }]);
      if (path === '/portfolios') return Promise.resolve([{ id: 'pf1', name: 'Nord' }]);
      return base(path);
    });
  };

  it('persists a KPI subset and its tab in a single navigation, and restores the subset on direct entry', async () => {
    withContract();
    const view = show();
    fireEvent.click(await screen.findByRole('button', { name: /Aktive Verträge\s*1/ }));
    const url = screen.getByTestId('location').textContent;
    expect(new URLSearchParams(url.split('?')[1]).get('tab')).toBe('contracts');
    expect(new URLSearchParams(url.split('?')[1]).get('contracts')).toBe('active');
    view.unmount();
    show(url);
    expect(await screen.findByRole('tab', { name: 'Mieter & Verträge (1)' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('button', { name: 'Aktive Verträge' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByText('MV-7')).toBeInTheDocument();
  });

  it('opens exactly the active contracts and open maintenance behind their counts', async () => {
    const base = api.list.getMockImplementation();
    api.list.mockImplementation(path => {
      if (path.startsWith('/contracts')) return Promise.resolve([contract, { ...contract, id: 'c2', contract_number: 'MV-Alt', status: 'ended' }]);
      if (path.startsWith('/maintenance')) return Promise.resolve([
        { id: 'm1', title: 'Heizung offen', status: 'open' }, { id: 'm2', title: 'Dach erledigt', status: 'completed' },
      ]);
      return base(path);
    });
    show();
    fireEvent.click(await screen.findByRole('button', { name: /Aktive Verträge\s*1/ }));
    expect(screen.getByText('MV-7')).toBeInTheDocument();
    expect(screen.queryByText('MV-Alt')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Offene Wartung\s*1/ }));
    expect(screen.getByText('Heizung offen')).toBeInTheDocument();
    expect(screen.queryByText('Dach erledigt')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('tab', { name: 'Finanzen' }));
    fireEvent.click(screen.getByRole('button', { name: /Jährliche Plan-Kaltmiete/ }));
    expect(screen.getByRole('region', { name: 'Planmieten nach Einheit' })).toHaveFocus();
    expect(screen.getByRole('link', { name: 'Buchungen dieser Immobilie' })).toHaveAttribute('href', '/bookings?property_id=p1');
  });

  it('lists who lives in the property with links to the party and the unit', async () => {
    withContract();
    show();
    const contracts = await screen.findByRole('tab', { name: 'Mieter & Verträge (1)' });
    // Opening this section also loads its named views; flush the updates as a user sees them.
    await act(async () => { fireEvent.click(contracts); });
    const row = screen.getByRole('row', { name: /MV-7/ });
    expect(within(row).getByText('Lena Langzeit')).toBeInTheDocument();
    expect(within(row).getByRole('link', { name: 'Wohnung Alpha' })).toHaveAttribute('href', '/units/u1');
  });

  it('offers New forms of other lists that start with this property', async () => {
    show();
    fireEvent.click(await screen.findByRole('button', { name: 'Neu für dieses Objekt' }));
    for (const [name, path] of [['Einheit', '/units'], ['Mietvertrag', '/contracts'], ['Wartungsfall', '/maintenance'],
      ['Buchung', '/bookings'], ['Rechnung', '/invoices'], ['Aufgabe', '/tasks']]) {
      expect(screen.getByRole('link', { name })).toHaveAttribute('href', `${path}?neu=1`);
    }
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('link', { name: 'Einheit' })).not.toBeInTheDocument();
  });

  it('offers only permitted target actions even without permission to edit the property', async () => {
    access.write = ['/tasks'];
    show();
    fireEvent.click(await screen.findByRole('button', { name: 'Neu für dieses Objekt' }));
    expect(screen.queryByRole('button', { name: 'Bearbeiten' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Einheit' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Buchung' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('link', { name: 'Aufgabe' }));
    expect(JSON.parse(screen.getByTestId('new-form-target').textContent)).toEqual({ path: '/tasks?neu=1', state: { prefill: { property_id: 'p1' } } });
  });

  it('edits the property in place and shows the saved values', async () => {
    withContract();
    api.put.mockResolvedValue({});
    show();
    fireEvent.click(await screen.findByRole('button', { name: 'Bearbeiten' }));
    const form = await screen.findByRole('dialog', { name: 'Immobilie bearbeiten' });
    expect(within(form).getByLabelText('Name *')).toHaveValue('Haus Alpha');
    api.get.mockImplementation(path => (path === '/properties/p1'
      ? Promise.resolve({ ...properties.p1, year_built: 1928 }) : Promise.resolve(undefined)));
    fireEvent.change(within(form).getByLabelText('Baujahr'), { target: { value: '1928' } });
    fireEvent.submit(form.querySelector('form'));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith('/properties/p1', expect.objectContaining({ year_built: 1928 })));
    expect(await screen.findByText('1928')).toBeInTheDocument();
  });

  it('offers no actions to roles that may not change the property', async () => {
    access.canWrite = false;
    show();
    await screen.findByRole('heading', { name: 'Haus Alpha' });
    expect(screen.queryByRole('button', { name: 'Bearbeiten' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Neu für dieses Objekt' })).not.toBeInTheDocument();
  });
});

describe('unit page as the place to act on a unit', () => {
  it('permits a booking action independently of unit or contract write permission', async () => {
    access.write = ['/bookings'];
    show('/units/u1');
    fireEvent.click(await screen.findByRole('button', { name: 'Neu für diese Einheit' }));
    expect(screen.queryByRole('link', { name: 'Mietvertrag anlegen' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Mietvertrag' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Wartungsfall' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('link', { name: 'Buchung' }));
    expect(JSON.parse(screen.getByTestId('new-form-target').textContent)).toEqual({ path: '/bookings?neu=1', state: { prefill: { property_id: 'p1', unit_id: 'u1' } } });
  });
  it('offers a contract for a vacant unit and New forms that start with the unit', async () => {
    show('/units/u1');
    expect(await screen.findByText('Nicht vermietet')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Mietvertrag anlegen' })).toHaveAttribute('href', '/contracts?neu=1');
    fireEvent.click(screen.getByRole('button', { name: 'Neu für diese Einheit' }));
    expect(screen.getByRole('link', { name: 'Wartungsfall' })).toHaveAttribute('href', '/maintenance?neu=1');
  });

  it('offers nothing to roles that may not change units or contracts', async () => {
    access.canWrite = false;
    show('/units/u1');
    expect(await screen.findByText('Nicht vermietet')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Mietvertrag anlegen' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Neu für diese Einheit' })).not.toBeInTheDocument();
  });
});
