import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import DataTable from '../components/DataTable';
import Properties from '../pages/Properties';
import Tenants from '../pages/Tenants';
import { formatArea, setFormatLocale } from '../utils/format';

const mocks = vi.hoisted(() => ({ list: vi.fn(), related: {}, reload: vi.fn() }));
vi.mock('../api', () => ({ api: { list: mocks.list } }));
vi.mock('../contexts/DataStoreContext', () => ({
  useDataStore: () => null,
  useEntities: key => ({ items: [], loading: false, error: null, reload: mocks.reload, ...mocks.related[key] }),
}));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => vi.fn() }));
vi.mock('../components/Toast', () => ({ useToast: () => ({ error: vi.fn() }) }));
vi.mock('../features/partyWorkspace/PartyWorkspace', () => ({
  usePartyWorkspace: () => ({ openParty: vi.fn() }),
  PartyLink: ({ children }) => <button>{children}</button>,
}));

beforeEach(() => { mocks.list.mockReset(); mocks.related = {}; mocks.reload.mockReset(); });
afterEach(cleanup);

describe('accessible list workspace', () => {
  it('shows area totals with their unit while keeping money totals cent exact', () => {
    setFormatLocale('de-DE');
    render(<MemoryRouter><DataTable title="Flächen und Mieten" columns={[
      { key: 'name', label: 'Name' }, { key: 'area', label: 'Fläche', sum: 'number', formatTotal: formatArea },
      { key: 'rent', label: 'Miete', sum: true },
    ]} data={[{ id: 'a', name: 'A', area: 100.123, rent: .1 }, { id: 'b', name: 'B', area: .007, rent: .2 }]} /></MemoryRouter>);
    const total = screen.getByRole('row', { name: /Summe/ });
    expect(within(total).getByRole('cell', { name: '100,13 m²' })).toBeInTheDocument();
    expect(within(total).getByRole('cell', { name: /^0,30\s€$/ })).toBeInTheDocument();
  });
  it('does not invoke a row action when its own controls are clicked', () => {
    const rowAction = vi.fn(); const childAction = vi.fn();
    render(<MemoryRouter><DataTable title="Akten" columns={[
      { key: 'name', label: 'Name' }, { key: 'actions', label: 'Aktionen', render: () => <button onClick={childAction}>Foto ansehen</button> },
    ]} data={[{ id: 'one', name: 'Haus A' }]} onRowClick={rowAction} /></MemoryRouter>);
    fireEvent.click(screen.getByRole('button', { name: 'Foto ansehen' }));
    expect(childAction).toHaveBeenCalledOnce(); expect(rowAction).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText('Haus A'));
    expect(rowAction).toHaveBeenCalledWith(expect.objectContaining({ id: 'one' }));
  });
  it('lists all current tenancies of a party and distinguishes ended and future contracts', async () => {
    mocks.list.mockResolvedValue([{ id: 't1', full_name: 'Mehrere Einheiten' }, { id: 't2', full_name: 'Künftige Partei' }]);
    mocks.related.contracts = { items: [
      { id: 'c1', contract_number: 'MV-1', tenant_id: 't1', unit_id: 'u1', property_id: 'p1', status: 'terminated', start_date: '2020-01-01', end_date: '2099-12-31' },
      { id: 'c2', contract_number: 'MV-2', tenant_id: 't1', unit_id: 'u2', property_id: 'p1', status: 'active', start_date: '2020-01-01' },
      { id: 'c3', contract_number: 'MV-3', tenant_id: 't2', status: 'active', start_date: '2099-01-01' },
      { id: 'c4', contract_number: 'MV-4', tenant_id: 't2', status: 'active', start_date: '2010-01-01', end_date: '2011-01-01' },
    ] };
    mocks.related.units = { items: [{ id: 'u1', label: 'Wohnung' }, { id: 'u2', label: 'Stellplatz' }] };
    mocks.related.properties = { items: [{ id: 'p1', name: 'Am Park' }] };
    render(<MemoryRouter><Tenants /></MemoryRouter>);
    expect(await screen.findByRole('button', { name: 'Alle 2 laufenden Verträge von Mehrere Einheiten ansehen' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Wohnung' })).toHaveAttribute('href', '/units/u1');
    expect(screen.getByRole('link', { name: 'Am Park' })).toHaveAttribute('href', '/properties/p1');
    fireEvent.click(screen.getByRole('button', { name: 'Mit Vertrag: Quellvorgänge anzeigen' }));
    expect(screen.getByRole('button', { name: 'Mehrere Einheiten' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Künftige Partei' })).not.toBeInTheDocument();
  });
  it('opens the exact property vacancy source and resets a narrower table search', async () => {
    mocks.list.mockResolvedValue([{ id: 'p1', name: 'Vermietetes Haus', status: 'active' }, { id: 'p2', name: 'Leeres Haus', status: 'inactive' }]);
    mocks.related.units = { items: [{ id: 'u1', property_id: 'p1', status: 'occupied' }, { id: 'u2', property_id: 'p2', status: 'vacant' }] };
    render(<MemoryRouter><Properties /></MemoryRouter>);
    fireEvent.click(await screen.findByRole('button', { name: 'Mit Leerstand: Quellvorgänge anzeigen' }));
    expect(screen.getByRole('link', { name: /Leeres Haus/ })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /Vermietetes Haus/ })).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Nicht vorhanden' } });
    fireEvent.click(screen.getByRole('button', { name: 'Ø Vermietungsquote: Quellvorgänge anzeigen' }));
    expect(screen.getByRole('link', { name: /Vermietetes Haus/ })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Leeres Haus/ })).toBeInTheDocument();
  });

  it('keeps archived parties out of active contract and SEPA KPI sources', async () => {
    mocks.list.mockResolvedValue([{ id: 't1', full_name: 'Aktive Partei', archived: false, sepa_mandate: true },
      { id: 't2', full_name: 'Archivierte Partei', archived: true, sepa_mandate: true }, { id: 't3', full_name: 'Ohne Mandat', archived: false }]);
    mocks.related.contracts = { items: [{ id: 'c1', tenant_id: 't1', status: 'active' }, { id: 'c2', tenant_id: 't2', status: 'active' }] };
    render(<MemoryRouter><Tenants /></MemoryRouter>);
    fireEvent.click(await screen.findByRole('button', { name: 'Mit Vertrag: Quellvorgänge anzeigen' }));
    expect(screen.getByRole('button', { name: 'Aktive Partei' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Archivierte Partei' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Ohne Mandat' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Mit SEPA: Quellvorgänge anzeigen' }));
    expect(screen.getByRole('button', { name: 'Aktive Partei' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Archivierte Partei' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Archiviert: Quellvorgänge anzeigen' }));
    expect(screen.getByRole('button', { name: 'Archivierte Partei' })).toBeInTheDocument();
  });
  it('retains a named table with a visually hidden duplicate title and keyboard sorting', async () => {
    const user = userEvent.setup();
    render(<DataTable title="Immobilien" hideTitle columns={[{ key: 'name', label: 'Name' }]}
      data={[{ id: 'b', name: 'Berg' }, { id: 'a', name: 'Allee' }]} />);
    const table = screen.getByRole('table', { name: 'Immobilien' });
    const sort = screen.getByRole('button', { name: 'Name' });
    sort.focus();
    await user.keyboard('{Enter}');
    expect(within(table).getAllByRole('row')[1]).toHaveTextContent('Allee');
    expect(screen.getByRole('columnheader', { name: 'Name' })).toHaveAttribute('aria-sort', 'ascending');
    await user.keyboard(' ');
    expect(within(table).getAllByRole('row')[1]).toHaveTextContent('Berg');
    expect(screen.getByRole('combobox', { name: 'Zeilen pro Seite' })).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Immobilien durchsuchen' })).toBeInTheDocument();
  });

  it('shows a property load failure instead of a zero portfolio and retries successfully', async () => {
    mocks.list.mockRejectedValueOnce(new Error('Server nicht erreichbar'))
      .mockResolvedValueOnce([{ id: 'p', name: 'Parkhaus', status: 'active' }]);
    render(<MemoryRouter><Properties /></MemoryRouter>);
    expect(await screen.findByRole('alert')).toHaveTextContent('Server nicht erreichbar');
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Erneut laden' }));
    expect(await screen.findByRole('link', { name: /Parkhaus/ })).toHaveAttribute('href', '/properties/p');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('does not label unavailable unit data as vacancy or zero rent', async () => {
    mocks.list.mockResolvedValue([{ id: 'p', name: 'Parkhaus', status: 'active' }]);
    mocks.related.units = { error: 'Einheiten nicht erreichbar' };
    render(<MemoryRouter><Properties /></MemoryRouter>);
    expect(await screen.findByRole('alert')).toHaveTextContent('Einheiten nicht erreichbar');
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Erneut laden' }));
    expect(mocks.reload).toHaveBeenCalled();
  });

  it('does not assert missing contracts while the contract source is unavailable', async () => {
    mocks.list.mockResolvedValue([{ id: 't', full_name: 'Mia Beispiel' }]);
    mocks.related.contracts = { error: 'Verträge nicht erreichbar' };
    render(<MemoryRouter><Tenants /></MemoryRouter>);
    expect(await screen.findByRole('alert')).toHaveTextContent('Verträge nicht erreichbar');
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    expect(screen.queryByText('Kein aktiver Vertrag')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Erneut laden' }));
    expect(mocks.reload).toHaveBeenCalled();
  });

  it('waits for tenant relationship data before displaying contract counts', async () => {
    mocks.list.mockResolvedValue([{ id: 't', full_name: 'Mia Beispiel' }]);
    mocks.related.contracts = { loading: true };
    render(<MemoryRouter><Tenants /></MemoryRouter>);
    expect(await screen.findByText('ui.table.loading')).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    expect(screen.queryByText('Mit Vertrag')).not.toBeInTheDocument();
  });
});
