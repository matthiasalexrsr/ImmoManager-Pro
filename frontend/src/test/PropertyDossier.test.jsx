import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom';
import PropertyDetail from '../pages/PropertyDetail';
import UnitOverview from '../pages/UnitOverview';
import { api } from '../api';

const pdfSources = vi.hoisted(() => []);
vi.mock('pdfjs-dist', () => ({ GlobalWorkerOptions: {}, getDocument: options => {
  pdfSources.push(options.url);
  return { promise: new Promise(() => {}), destroy: async () => {} };
} }));

const access = vi.hoisted(() => ({ canWrite: true }));
vi.mock('../api', () => ({ api: { get: vi.fn(), list: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), del: vi.fn() } }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: () => undefined, locale: 'de-DE' }) }));
vi.mock('../contexts/AuthContext', () => ({ useCanWrite: () => access.canWrite }));
vi.mock('../components/PhotoDropZone', () => ({ default: () => null }));

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

function RoutesUnderTest() {
  const navigate = useNavigate();
  return <>
    <button onClick={() => navigate('/properties/p2')}>Anderes Objekt</button>
    <Routes>
      <Route path="/properties/:id" element={<PropertyDetail />} />
      <Route path="/units/:id" element={<UnitOverview />} />
      <Route path="/properties" element={<h1>Immobilienliste</h1>} />
      <Route path="/units" element={<h1>Einheitenliste</h1>} />
    </Routes>
  </>;
}
const show = (path = '/properties/p1') => render(<MemoryRouter initialEntries={[path]}><RoutesUnderTest /></MemoryRouter>);

beforeEach(() => {
  pdfSources.length = 0;
  vi.resetAllMocks();
  access.canWrite = true;
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
  it('opens a unit from each view and returns to its actual property', async () => {
    show();
    await screen.findByRole('heading', { name: 'Haus Alpha' });
    expect(screen.getByRole('link', { name: 'Wohnung Alpha' })).toHaveAttribute('href', '/units/u1');
    fireEvent.click(screen.getByRole('button', { name: 'Einheiten (1)' }));
    expect(screen.getByRole('link', { name: 'Wohnung Alpha' })).toHaveAttribute('href', '/units/u1');
    fireEvent.click(screen.getByRole('button', { name: 'Finanzen' }));
    expect(screen.getByRole('link', { name: 'Wohnung Alpha' })).toHaveAttribute('href', '/units/u1');
    expect(screen.getByText(/Stammdaten.*Einheiten/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('link', { name: 'Wohnung Alpha' }));
    await screen.findByRole('heading', { name: 'Wohnung Alpha' });
    const back = screen.getByRole('link', { name: /Zur Immobilie/ });
    expect(back).toHaveAttribute('href', '/properties/p1');
    fireEvent.click(back);
    expect(await screen.findByRole('heading', { name: 'Haus Alpha' })).toBeInTheDocument();
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
    fireEvent.click(screen.getByRole('button', { name: 'Dokumente (4)' }));
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
