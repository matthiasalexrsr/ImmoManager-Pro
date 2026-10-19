import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter, MemoryRouter, RouterProvider, useLocation, useNavigate } from 'react-router-dom';
import DataTable from '../components/DataTable';
import { readTableView, writeTableView } from '../utils/tableSettings';
import { privateStorageKey } from '../utils/workspaceIdentity';
import { workspace } from '../utils/workspaceClient';

const auth = vi.hoisted(() => ({ owner: null }));
vi.mock('../contexts/AuthContext', () => ({ useCanWrite: () => true, useAuth: () => auth.owner ? { user: { id: auth.owner } } : null }));
vi.mock('../utils/workspaceClient', async original => ({ ...await original(), workspace: { list: vi.fn() } }));

const settingsKey = 'route-navigation';
const alpha = '?suche=Alpha';
const beta = '?suche=Beta';
const columns = [
  { key: 'title', label: 'Bezeichnung' },
  { key: 'district', label: 'Bezirk', filterType: 'select' },
];
const data = ['Alpha', 'Beta'].flatMap(group => Array.from({ length: 31 }, (_, index) => ({
  id: `${group}-${index + 1}`,
  title: `${group} ${String(index + 1).padStart(2, '0')}`,
  district: (group === 'Alpha') === (index < 30) ? 'Ost' : 'West',
})));
const queryKey = query => query ? `${settingsKey}|query:${query}` : settingsKey;
const table = () => screen.getByRole('table', { name: 'Vorgänge' });
const search = () => screen.getByRole('textbox', { name: 'Vorgänge durchsuchen' });
const nextPage = () => fireEvent.click(screen.getByRole('button', { name: /nextPage/ }));

function Harness({ serverPaged = false, routeViews = false }) {
  const navigate = useNavigate();
  const location = useLocation();
  return <>
    <button onClick={() => navigate(`/maintenance${alpha}`)}>Alpha öffnen</button>
    <button onClick={() => navigate(`/maintenance${beta}`)}>Beta öffnen</button>
    <button onClick={() => navigate('/maintenance?focus_id=Alpha-31')}>Exakten Vorgang öffnen</button>
    <button onClick={() => navigate('/maintenance?suche=Alpha&focus_id=Alpha-31')}>Exakten Suchtreffer öffnen</button>
    <button onClick={() => navigate(-1)}>Zurück</button>
    <button onClick={() => navigate(1)}>Vorwärts</button>
    <output aria-label="Aktuelle Route">{location.pathname}{location.search}</output>
    <DataTable title="Vorgänge" settingsKey={settingsKey} columns={columns} data={data} serverPaged={serverPaged}
      onApplyView={routeViews ? config => navigate(`/maintenance?status=${config.column_filters.workflow_filter}`) : undefined} />
  </>;
}

function mount(initial = `/maintenance${alpha}`, props = {}, routerType = 'MemoryRouter') {
  if (routerType === 'RouterProvider') {
    const router = createMemoryRouter([{ path: '*', element: <Harness {...props} /> }], { initialEntries: [initial] });
    return render(<RouterProvider router={router} />);
  }
  return render(<MemoryRouter initialEntries={[initial]}><Harness {...props} /></MemoryRouter>);
}

function filterDistrict(value) {
  if (!screen.queryByRole('combobox', { name: 'Bezirk filtern' })) {
    fireEvent.click(screen.getByRole('button', { name: /ui.buttons.filter/ }));
  }
  fireEvent.change(screen.getByRole('combobox', { name: 'Bezirk filtern' }), { target: { value } });
}

beforeEach(() => { localStorage.clear(); sessionStorage.clear(); auth.owner = null; vi.clearAllMocks(); });
afterEach(cleanup);

describe('DataTable navigation within one list', () => {
  it('initializes each fresh search and exact-record link without leaking the previous filters or page', () => {
    // A fresh link must ignore an earlier visit to its destination query.
    writeTableView(queryKey(beta), { search: 'Veraltete Suche', columnFilters: { district: 'Ost' }, page: 8 });
    mount();
    fireEvent.change(screen.getByRole('combobox', { name: 'Zeilen pro Seite' }), { target: { value: '10' } });
    filterDistrict('Ost');
    nextPage();
    expect(within(table()).getByText('Alpha 11')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Beta öffnen' }));
    expect(search()).toHaveValue('Beta');
    expect(within(table()).getByText('Beta 01')).toBeInTheDocument();
    expect(screen.getByText('1 / 4')).toBeInTheDocument();
    expect(screen.queryByRole('group', { name: 'Aktive Tabellenfilter' })?.textContent).not.toContain('Ost');
    expect(readTableView(queryKey(beta))).toEqual({ search: 'Beta', columnFilters: {}, page: 0 });
    expect(readTableView(queryKey(alpha))).toEqual({ search: 'Alpha', columnFilters: { district: 'Ost' }, page: 1 });

    filterDistrict('West');
    nextPage();
    fireEvent.click(screen.getByRole('button', { name: 'Exakten Vorgang öffnen' }));
    expect(search()).toHaveValue('');
    expect(within(table()).getByText('Alpha 31')).toBeInTheDocument();
    expect(within(table()).queryByText('Beta 11')).not.toBeInTheDocument();
    expect(screen.getByText('1 / 1')).toBeInTheDocument();
    expect(readTableView(queryKey('?focus_id=Alpha-31'))).toEqual({ search: '', columnFilters: {}, page: 0 });
  });

  it('restores the search, filters and page belonging to each query on Back and Forward', () => {
    mount();
    fireEvent.change(screen.getByRole('combobox', { name: 'Zeilen pro Seite' }), { target: { value: '10' } });
    filterDistrict('Ost');
    nextPage();
    fireEvent.click(screen.getByRole('button', { name: 'Beta öffnen' }));
    filterDistrict('West');
    nextPage();
    nextPage();
    expect(within(table()).getByText('Beta 21')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Zurück' }));
    expect(search()).toHaveValue('Alpha');
    expect(screen.getByRole('combobox', { name: 'Bezirk filtern' })).toHaveValue('Ost');
    expect(screen.getByText('2 / 3')).toBeInTheDocument();
    expect(within(table()).getByText('Alpha 11')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Vorwärts' }));
    expect(search()).toHaveValue('Beta');
    expect(screen.getByRole('combobox', { name: 'Bezirk filtern' })).toHaveValue('West');
    expect(screen.getByText('3 / 3')).toBeInTheDocument();
    expect(within(table()).getByText('Beta 21')).toBeInTheDocument();
  });

  it('keeps plain-list state separate while sharing sort, page size and visible-column preferences', () => {
    mount('/maintenance');
    fireEvent.change(search(), { target: { value: 'Alpha' } });
    filterDistrict('Ost');
    fireEvent.change(screen.getByRole('combobox', { name: 'Zeilen pro Seite' }), { target: { value: '10' } });
    fireEvent.click(screen.getByRole('columnheader', { name: /Bezeichnung/ }));
    fireEvent.click(screen.getByRole('columnheader', { name: /Bezeichnung/ }));
    nextPage();
    fireEvent.click(screen.getByRole('button', { name: 'ui.table.adjustColumns' }));
    fireEvent.click(screen.getByRole('checkbox', { name: 'Bezirk' }));

    fireEvent.click(screen.getByRole('button', { name: 'Exakten Vorgang öffnen' }));
    expect(within(table()).getByText('Alpha 31')).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'Zeilen pro Seite' })).toHaveValue('10');
    expect(screen.getByRole('columnheader', { name: /Bezeichnung/ })).toHaveAttribute('aria-sort', 'descending');
    expect(screen.queryByRole('columnheader', { name: /Bezirk/ })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Zurück' }));
    expect(search()).toHaveValue('Alpha');
    expect(within(table()).getByText('Alpha 20')).toBeInTheDocument();
    expect(screen.getByText('2 / 3')).toBeInTheDocument();
    expect(readTableView(settingsKey)).toEqual({ search: 'Alpha', columnFilters: { district: 'Ost' }, page: 1 });
    const preferences = JSON.parse(localStorage.getItem(privateStorageKey(`table_settings:${settingsKey}`)));
    expect(preferences).toMatchObject({ sortKey: 'title', sortDir: 'desc', pageSize: 10, hiddenCols: { district: true } });
  });

  it('lets server-paged lists retain control of their route-query transitions', () => {
    mount('/maintenance', { serverPaged: true });
    const initialTable = table();
    fireEvent.click(screen.getByRole('button', { name: 'ui.table.adjustColumns' }));
    expect(screen.getByRole('group', { name: 'Spaltenauswahl' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Beta öffnen' }));
    expect(table()).toBe(initialTable);
    expect(screen.getByRole('group', { name: 'Spaltenauswahl' })).toBeInTheDocument();
    expect(within(table()).getByText('Alpha 01')).toBeInTheDocument();
    expect(within(table()).getByText('Beta 31')).toBeInTheDocument();
    expect(screen.queryByRole('textbox', { name: 'Vorgänge durchsuchen' })).not.toBeInTheDocument();
  });

  it('explicitly resets filters when leaving a focused record instead of restoring the old plain-list filters', () => {
    mount('/maintenance');
    fireEvent.change(search(), { target: { value: 'Alpha' } });
    filterDistrict('Ost');
    fireEvent.click(screen.getByRole('button', { name: 'Exakten Suchtreffer öffnen' }));
    expect(search()).toHaveValue('Alpha');
    expect(within(table()).getByText('Alpha 31')).toBeInTheDocument();
    fireEvent.change(search(), { target: { value: 'Kein Treffer' } });
    fireEvent.click(screen.getByRole('button', { name: 'Suche und Filter zurücksetzen' }));
    expect(search()).toHaveValue('');
    expect(screen.queryByRole('group', { name: 'Aktive Tabellenfilter' })).not.toBeInTheDocument();
    expect(screen.getByLabelText('Aktuelle Route')).toHaveTextContent(/^\/maintenance$/);
    expect(readTableView(settingsKey)).toEqual({ search: '', columnFilters: {}, page: 0 });
  });

  it.each(['MemoryRouter', 'RouterProvider'])('keeps an applied named view across URL filters with %s', async routerType => {
    auth.owner = 'owner';
    workspace.list.mockResolvedValue({ items: [{ id: 'saved-west', name: 'Westliche Vorgänge', config: {
      search: 'Beta', sort: { key: 'title', direction: 'desc' }, page_size: 10,
      visible_columns: ['title'], column_filters: { district: 'West', workflow_filter: 'west' },
    } }] });
    mount(`/maintenance${alpha}`, { routeViews: true }, routerType);
    await screen.findByRole('option', { name: 'Westliche Vorgänge' });
    fireEvent.change(screen.getByRole('combobox', { name: 'Ansicht' }), { target: { value: 'saved-west' } });
    await waitFor(() => expect(screen.getByLabelText('Aktuelle Route')).toHaveTextContent('/maintenance?status=west'));
    expect(search()).toHaveValue('Beta');
    expect(within(table()).getByText('Beta 30')).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'Zeilen pro Seite' })).toHaveValue('10');
    expect(screen.queryByRole('columnheader', { name: /Bezirk/ })).not.toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: /Bezeichnung/ })).toHaveAttribute('aria-sort', 'descending');
    expect(readTableView(queryKey('?status=west'))).toEqual({ search: 'Beta', columnFilters: { district: 'West' }, page: 0 });

    fireEvent.click(screen.getByRole('button', { name: 'Alpha öffnen' }));
    await waitFor(() => expect(search()).toHaveValue('Alpha'));
    expect(screen.queryByRole('button', { name: 'Filter entfernen: Bezirk' })).not.toBeInTheDocument();
    expect(within(table()).getByText('Alpha 31')).toBeInTheDocument();
  });

  it('lets a secondary table filter its own rows without inheriting the main record focus', () => {
    render(<MemoryRouter initialEntries={['/maintenance?focus_id=Alpha-31']}>
      <DataTable title="Hauptvorgänge" settingsKey="main-focus" columns={columns} data={data} />
      <DataTable title="Ablesungen" settingsKey="reading-focus" inheritRouteFocus={false}
        columns={[{ key: 'title', label: 'Eintrag' }]} data={[{ id: 'reading-1', title: 'Erste Ablesung' }, { id: 'reading-2', title: 'Zweite Ablesung' }]} />
    </MemoryRouter>);
    expect(within(screen.getByRole('table', { name: 'Hauptvorgänge' })).getByText('Alpha 31')).toBeInTheDocument();
    expect(within(screen.getByRole('table', { name: 'Hauptvorgänge' })).queryByText('Alpha 01')).not.toBeInTheDocument();
    const readings = screen.getByRole('table', { name: 'Ablesungen' });
    expect(within(readings).getByText('Erste Ablesung')).toBeInTheDocument();
    expect(within(readings).getByText('Zweite Ablesung')).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'Alle Vorgänge anzeigen' })).toHaveLength(1);

    fireEvent.change(screen.getByRole('textbox', { name: 'Ablesungen durchsuchen' }), { target: { value: 'Kein Treffer' } });
    fireEvent.click(screen.getByRole('button', { name: 'Suche und Filter zurücksetzen' }));
    expect(within(readings).getByText('Erste Ablesung')).toBeInTheDocument();
    expect(within(screen.getByRole('table', { name: 'Hauptvorgänge' })).queryByText('Alpha 01')).not.toBeInTheDocument();
  });

  it('keeps a parent URL search on its main table while a secondary table opts out explicitly', () => {
    render(<MemoryRouter initialEntries={['/statements?suche=Alpha&focus_id=Alpha-31']}>
      <DataTable title="Hauptvorgänge" settingsKey="main-search" columns={columns} data={data} />
      <DataTable title="Kosten" settingsKey="billing-costs:period-1" inheritRouteSearch={false} inheritRouteFocus={false}
        columns={[{ key: 'title', label: 'Kostenposition' }]} data={[{ id: 'water', title: 'Wasser' }, { id: 'heat', title: 'Heizung' }]} />
    </MemoryRouter>);
    expect(within(screen.getByRole('table', { name: 'Hauptvorgänge' })).getByText('Alpha 31')).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Hauptvorgänge durchsuchen' })).toHaveValue('Alpha');
    expect(screen.getByRole('textbox', { name: 'Kosten durchsuchen' })).toHaveValue('');
    expect(within(screen.getByRole('table', { name: 'Kosten' })).getByText('Wasser')).toBeInTheDocument();
    expect(within(screen.getByRole('table', { name: 'Kosten' })).getByText('Heizung')).toBeInTheDocument();
  });

  it('retains the secondary table own saved search across parent query navigation without rewriting the URL', () => {
    const key = 'billing-costs:period-1';
    writeTableView(key, { search: 'Wasser', columnFilters: {}, page: 0 });
    function Secondary() {
      const navigate = useNavigate(); const location = useLocation();
      return <><output aria-label="Elternroute">{location.search}</output>
        <button onClick={() => navigate('/statements?suche=Beta')}>Andere Elternsuche</button>
        <DataTable title="Kosten" settingsKey={key} inheritRouteSearch={false} inheritRouteFocus={false}
          columns={[{ key: 'title', label: 'Kostenposition' }]} data={[{ id: 'water', title: 'Wasser' }, { id: 'heat', title: 'Heizung' }]} />
      </>;
    }
    render(<MemoryRouter initialEntries={['/statements?suche=Alpha']}><Secondary /></MemoryRouter>);
    expect(screen.getByRole('textbox', { name: 'Kosten durchsuchen' })).toHaveValue('Wasser');
    expect(screen.getByLabelText('Elternroute')).toHaveTextContent('?suche=Alpha');
    fireEvent.change(screen.getByRole('textbox', { name: 'Kosten durchsuchen' }), { target: { value: 'Heizung' } });
    fireEvent.click(screen.getByRole('button', { name: 'Andere Elternsuche' }));
    expect(screen.getByLabelText('Elternroute')).toHaveTextContent('?suche=Beta');
    expect(screen.getByRole('textbox', { name: 'Kosten durchsuchen' })).toHaveValue('Heizung');
    expect(within(screen.getByRole('table', { name: 'Kosten' })).getByText('Heizung')).toBeInTheDocument();
    expect(within(screen.getByRole('table', { name: 'Kosten' })).queryByText('Wasser')).not.toBeInTheDocument();
    expect(readTableView(key)).toEqual({ search: 'Heizung', columnFilters: {}, page: 0 });
  });
});
