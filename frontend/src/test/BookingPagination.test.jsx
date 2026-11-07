import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Profiler } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import Bookings from '../pages/Bookings';
import { api } from '../api';

const fixture = vi.hoisted(() => ({ user: null, empty: [], entities: {
  accounts: [{ id: 'account', name: 'Mietkonto' }], properties: [{ id: 'p1', name: 'Haus' }],
  owners: [{ id: 'linda', name: 'Linda' }],
}, workspace: { get: vi.fn(), put: vi.fn(), list: vi.fn(), command: vi.fn() } }));
vi.mock('../api', () => ({ api: { get: vi.fn(), list: vi.fn(), getFile: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() } }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => fixture.user, useCanWrite: () => false }));
vi.mock('../contexts/DataStoreContext', () => ({ useDataStore: () => null,
  useEntities: key => ({ items: fixture.entities[key] || fixture.empty, loading: false, error: null }) }));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => vi.fn() }));
vi.mock('../components/Toast', () => ({ useToast: () => ({ error: vi.fn(), success: vi.fn() }) }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: key => key === 'ui.table.adjustColumns' ? 'Spalten anpassen' : undefined, locale: 'de-DE' }) }));
vi.mock('../utils/workspaceClient', () => ({ workspace: fixture.workspace, formContext: () => 'bookings' }));

const summary = { count: 80, income: 12345.67, expense: 89.11, withdrawal: 0, contribution: 0, no_category: 14, no_receipt: 7 };
const row = (id, text = id) => ({ id, payment_text: text, booking_date: '2026-01-01', account_id: 'account', property_id: 'p1', amount: 1, status: 'booked' });
const reply = params => ({ items: [row(`source-${params.get('skip')}`, `Seite ab ${params.get('skip')}`)],
  skip: Number(params.get('skip')), limit: Number(params.get('limit')), total: 80, summary,
  allocations: [], reserved_amounts: {} });
const mount = (path = '/bookings') => render(<MemoryRouter initialEntries={[path]}><Bookings /></MemoryRouter>);

beforeEach(() => {
  vi.resetAllMocks(); localStorage.clear(); sessionStorage.clear(); fixture.user = null;
  fixture.workspace.get.mockResolvedValue(null);
  fixture.workspace.put.mockImplementation(async (_kind, _id, command) => ({ revision: 1, state: command.state }));
  fixture.workspace.list.mockResolvedValue({ items: [] });
  fixture.workspace.command.mockImplementation(() => crypto.randomUUID());
  api.get.mockImplementation(async path => {
    if (path.startsWith('/bookings/page?')) return reply(new URLSearchParams(path.split('?')[1]));
    throw new Error('Unexpected request: ' + path);
  });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe('bounded booking pages', () => {
  it('shows server totals for the complete selection and requests only the next page', async () => {
    mount(); await screen.findByText('Seite ab 0');
    expect(screen.getByRole('button', { name: 'Einnahmen: Quellvorgänge anzeigen' })).toHaveTextContent('12.345,67');
    expect(screen.getByRole('button', { name: 'Gesamt: Quellvorgänge anzeigen' })).toHaveTextContent('80');
    expect(api.list).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Weiter', exact: true }));
    await screen.findByText('Seite ab 25');
    expect(screen.queryByText('Seite ab 0')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Einnahmen: Quellvorgänge anzeigen' })).toHaveTextContent('12.345,67');
    const params = new URLSearchParams(api.get.mock.calls.at(-1)[0].split('?')[1]);
    expect(params.get('skip')).toBe('25'); expect(params.get('limit')).toBe('25');
    expect(api.list).not.toHaveBeenCalled();
  });

  it('keeps keyboard search mounted while loading and sends source filters and server sort', async () => {
    const user = userEvent.setup();
    mount('/bookings?date_from=2026-01-01&date_to=2026-12-31&property_id=p1&konto=account');
    await screen.findByText('Seite ab 0');
    const search = screen.getByLabelText('Buchungen durchsuchen');
    await user.type(search, 'Beleg');
    await waitFor(() => expect(api.get.mock.calls.some(([path]) => new URLSearchParams(path.split('?')[1]).get('search') === 'Beleg')).toBe(true));
    expect(screen.getByLabelText('Buchungen durchsuchen')).toBe(search);
    expect(search).toHaveFocus();
    fireEvent.change(screen.getByLabelText('Sortieren nach'), { target: { value: 'amount' } });
    await waitFor(() => expect(new URLSearchParams(api.get.mock.calls.at(-1)[0].split('?')[1]).get('sort_by')).toBe('amount'));
    const params = new URLSearchParams(api.get.mock.calls.at(-1)[0].split('?')[1]);
    expect(Object.fromEntries(params)).toMatchObject({ date_from: '2026-01-01', date_to: '2026-12-31', property_id: 'p1', account_id: 'account', search: 'Beleg' });
  });

  it('downloads the complete server CSV using the same filters and chosen columns', async () => {
    const blob = new Blob(['\ufeffDatum;Betrag\n2026-01-01;12345,67'], { type: 'text/csv' });
    api.getFile.mockResolvedValue({ blob, headers: new Headers() });
    const create = vi.fn().mockReturnValue('blob:bookings');
    const revoke = vi.fn();
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: create, revokeObjectURL: revoke }));
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    mount('/bookings?owner_contact_id=linda&date_from=2026-01-01');
    await screen.findByText('Seite ab 0');
    fireEvent.click(screen.getByRole('button', { name: 'CSV', exact: true }));
    await waitFor(() => expect(create).toHaveBeenCalledWith(blob));
    const params = new URLSearchParams(api.getFile.mock.calls[0][0].split('?')[1]);
    expect(api.getFile.mock.calls[0][0]).toMatch(/^\/bookings\/page\/export\?/);
    expect(params.get('owner_contact_id')).toBe('linda');
    expect(params.get('date_from')).toBe('2026-01-01');
    expect(params.get('columns')).toContain('owner_part');
    expect(params.has('skip')).toBe(false); expect(params.has('limit')).toBe(false);
    expect(api.list).not.toHaveBeenCalled();
  });

  it('restores server-saved column defaults and page state on an ordinary entry', async () => {
    fixture.user = { user: { id: 'owner' } };
    fixture.workspace.get.mockResolvedValue({ revision: 4, state: {
      visible_columns: ['booking_date', 'payment_text'], hidden_defaults: [],
      column_order: ['booking_date', 'account_name', 'tenant_name', 'amount', 'payment_text', 'property_name', 'unit_label', 'category_name', 'has_receipt', 'status'],
      search: '', sort: { key: 'payment_text', direction: 'asc' }, page_size: 10, page_cursor: '1', column_filters: { amount: ['2', '8'] },
    } });
    mount();
    await screen.findByText('Seite ab 10');
    expect(screen.queryByRole('columnheader', { name: /^Konto/ })).not.toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: /Buchungstext/ })).toBeInTheDocument();
    expect(screen.getByLabelText('Zeilen pro Seite')).toHaveValue('10');
    expect(screen.getByLabelText('Sortieren nach')).toHaveValue('payment_text');
    expect(JSON.parse(new URLSearchParams(api.get.mock.calls.at(-1)[0].split('?')[1]).get('column_filters'))).toEqual({ amount: ['2', '8'] });
    expect(fixture.workspace.get).toHaveBeenCalledWith('view-state', expect.stringContaining('bookings#'), undefined, { missing_ok: true });
    fireEvent.click(screen.getByRole('button', { name: 'Spalten anpassen' }));
    fireEvent.click(screen.getByRole('checkbox', { name: 'Konto' }));
    await waitFor(() => expect(fixture.workspace.put.mock.calls.some(([kind, , command]) => kind === 'view-state' && command.state.visible_columns.includes('account_name'))).toBe(true), { timeout: 2500 });
    const saved = fixture.workspace.put.mock.calls.filter(([kind]) => kind === 'view-state').at(-1)[2].state;
    expect(saved).toMatchObject({ page_cursor: '1', page_size: 10, hidden_defaults: expect.any(Array), column_filters: expect.objectContaining({ amount: ['2', '8'] }) });
  });

  it('keeps an authenticated page change mounted and persists it instead of restoring the old page', async () => {
    fixture.user = { user: { id: 'owner' } };
    let releaseNext;
    const requestPage = api.get.getMockImplementation();
    api.get.mockImplementation(path => {
      const params = new URLSearchParams(path.split('?')[1]);
      return params.get('skip') === '25'
        ? new Promise(resolve => { releaseNext = () => resolve(reply(params)); }) : requestPage(path);
    });
    fixture.workspace.get.mockResolvedValue({ revision: 4, state: {
      search: '', sort: { key: 'booking_date', direction: 'desc' }, page_size: 25, page_cursor: '0', column_filters: {},
    } });
    mount(); await screen.findByText('Seite ab 0');
    await waitFor(() => expect(fixture.workspace.get).toHaveBeenCalledTimes(1));
    const table = screen.getByRole('table', { name: 'Buchungen' });
    fireEvent.click(screen.getByRole('button', { name: 'Weiter', exact: true }));
    await waitFor(() => expect(releaseNext).toBeTypeOf('function'));
    expect(table).toBeInTheDocument(); await waitFor(() => expect(table).not.toBeVisible());
    expect(screen.queryByRole('table', { name: 'Buchungen' })).not.toBeInTheDocument();
    const search = screen.getByLabelText('Buchungen durchsuchen'); search.focus();
    expect(search).toBeEnabled(); expect(search).toHaveFocus();
    releaseNext();
    await screen.findByText('Seite ab 25');
    await waitFor(() => expect(fixture.workspace.put.mock.calls.some(([, , command]) => command.state.page_cursor === '1')).toBe(true), { timeout: 2500 });
    expect(screen.getByRole('table', { name: 'Buchungen' })).toBe(table);
    expect(screen.getByText('Seite ab 25')).toBeVisible();
    expect(fixture.workspace.get).toHaveBeenCalledTimes(1);
    expect(new URLSearchParams(api.get.mock.calls.at(-1)[0].split('?')[1]).get('skip')).toBe('25');
  });

  it.each(['commit', 'batched'])('preserves an enabled next-page click during %s restoration', async timing => {
    fixture.user = { user: { id: 'owner' } };
    let restoreView;
    fixture.workspace.get.mockReturnValue(new Promise(resolve => { restoreView = resolve; }));
    let releaseNext;
    const requests = [];
    const requestPage = api.get.getMockImplementation();
    api.get.mockImplementation((path, options) => {
      const params = new URLSearchParams(path.split('?')[1]);
      if (params.get('skip') !== '25') return requestPage(path);
      requests.push(options.signal);
      return new Promise(resolve => { releaseNext = () => resolve(reply(params)); });
    });
    const saved = { revision: 4, state: {
      search: '', sort: { key: 'booking_date', direction: 'desc' }, page_size: 25, page_cursor: '0', column_filters: {},
    } };
    let clickOnCommit = false;
    let clicked = false;
    const clickNext = () => {
      const button = screen.getByRole('button', { name: 'Weiter', exact: true });
      expect(button).toBeEnabled();
      clicked = true;
      button.click();
    };
    render(<Profiler id="bookings" onRender={() => {
      if (clickOnCommit) {
        clickOnCommit = false;
        clickNext();
      }
    }}><MemoryRouter><Bookings /></MemoryRouter></Profiler>);
    const table = await screen.findByRole('table', { name: 'Buchungen' });
    await waitFor(() => expect(fixture.workspace.get).toHaveBeenCalledTimes(1));
    await act(async () => {
      if (timing === 'commit') clickOnCommit = true;
      restoreView(saved);
      if (timing === 'batched') {
        await Promise.resolve();
        clickNext();
      }
    });
    expect(clicked).toBe(true);
    expect(requests).toHaveLength(1);
    expect(requests[0].aborted).toBe(false);
    expect(table).toBeInTheDocument();
    expect(table).not.toBeVisible();
    await act(async () => releaseNext());
    expect(await screen.findByText('Seite ab 25')).toBeVisible();
    expect(screen.getByRole('table', { name: 'Buchungen' })).toBe(table);
    await waitFor(() => expect(fixture.workspace.put.mock.calls.some(([, , command]) =>
      command.state.page_cursor === '1')).toBe(true), { timeout: 2500 });
    expect(fixture.workspace.get).toHaveBeenCalledTimes(1);
  });

  it('reloads a conflicting authenticated server view into the booking controller and resumes saving', async () => {
    fixture.user = { user: { id: 'owner' } };
    let server = { revision: 4, state: {
      search: '', sort: { key: 'booking_date', direction: 'desc' }, page_size: 25, page_cursor: '0', column_filters: {},
    } };
    fixture.workspace.get.mockImplementation(async () => structuredClone(server));
    fixture.workspace.put.mockImplementation(async (_kind, _context, command) => {
      if (command.base_revision !== server.revision) throw Object.assign(new Error('Konflikt'), { statusCode: 409 });
      server = { revision: server.revision + 1, state: structuredClone(command.state) };
      return structuredClone(server);
    });
    mount(); await screen.findByText('Seite ab 0');
    fireEvent.change(screen.getByLabelText('Reihenfolge'), { target: { value: 'asc' } });
    await waitFor(() => expect(fixture.workspace.put).toHaveBeenCalled(), { timeout: 2500 });
    server = { revision: server.revision + 1, state: { ...server.state, search: 'Anderes Fenster',
      sort: { key: 'amount', direction: 'asc' }, page_size: 10, page_cursor: '2',
      visible_columns: ['booking_date', 'payment_text'] } };
    const otherRevision = server.revision;
    fireEvent.change(screen.getByLabelText('Sortieren nach'), { target: { value: 'payment_text' } });
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('anderen Fenster'), { timeout: 2500 });
    fireEvent.click(screen.getByRole('button', { name: 'Serveransicht laden' }));
    await screen.findByText('Seite ab 20');
    expect(screen.getByLabelText('Buchungen durchsuchen')).toHaveValue('Anderes Fenster');
    expect(screen.getByLabelText('Sortieren nach')).toHaveValue('amount');
    expect(screen.getByLabelText('Zeilen pro Seite')).toHaveValue('10');
    expect(screen.queryByRole('columnheader', { name: /^Konto/ })).not.toBeInTheDocument();
    expect(server.revision).toBe(otherRevision);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Reihenfolge'), { target: { value: 'desc' } });
    await waitFor(() => expect(server.state.sort.direction).toBe('desc'), { timeout: 2500 });
    expect(fixture.workspace.put.mock.calls.at(-1)[2].base_revision).toBe(otherRevision);
  });

  it('keeps an explicit source URL ahead of an unrelated saved view', async () => {
    fixture.user = { user: { id: 'owner' } };
    fixture.workspace.get.mockResolvedValue({ revision: 4, state: { search: 'Falscher Bestand', column_filters: { owner_contact_id: 'other' } } });
    mount('/bookings?owner_contact_id=linda&property_id=p1');
    await screen.findByText('Seite ab 0');
    expect(fixture.workspace.get).not.toHaveBeenCalled();
    const params = new URLSearchParams(api.get.mock.calls.at(-1)[0].split('?')[1]);
    expect(params.get('owner_contact_id')).toBe('linda'); expect(params.get('property_id')).toBe('p1');
  });
});
