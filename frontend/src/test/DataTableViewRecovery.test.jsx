import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import DataTable from '../components/DataTable';
import { writeTableView } from '../utils/tableSettings';

const mock = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn(), list: vi.fn(), command: vi.fn() }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { id: 'owner' } }), useCanWrite: () => false }));
vi.mock('../utils/workspaceClient', () => ({ workspace: mock, formContext: () => 'properties' }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: key => key }) }));

const columns = [{ key: 'title', label: 'Bezeichnung' }];
const tick = () => act(async () => { await vi.advanceTimersByTimeAsync(1000); });
let server;
beforeEach(() => {
  vi.useFakeTimers(); vi.resetAllMocks(); localStorage.clear(); sessionStorage.clear();
  mock.list.mockResolvedValue({ items: [] });
  mock.command.mockImplementation(() => crypto.randomUUID());
  server = { revision: 1, state: { search: 'Lokal', sort: null, visible_columns: ['title'], hidden_defaults: [],
    column_order: ['title'], page_size: 25, column_filters: {}, page_cursor: '0' } };
  mock.get.mockImplementation(async () => structuredClone(server));
  mock.put.mockImplementation(async (_kind, _context, command) => {
    if (command.base_revision !== server.revision) throw Object.assign(new Error('Konflikt'), { statusCode: 409 });
    server = { revision: server.revision + 1, state: structuredClone(command.state) };
    return structuredClone(server);
  });
});
afterEach(() => { cleanup(); vi.useRealTimers(); });

it('explicitly loads a conflicting server view even when this tab restored a local view on mount', async () => {
  writeTableView('view-recovery', { search: 'Lokal', columnFilters: {}, page: 0 });
  render(<MemoryRouter initialEntries={['/properties']}><DataTable title="Immobilien" settingsKey="view-recovery"
    columns={columns} data={[]} /></MemoryRouter>);
  const search = screen.getByRole('textbox', { name: 'Immobilien durchsuchen' });
  await tick(); expect(search).toHaveValue('Lokal'); expect(mock.put).not.toHaveBeenCalled();

  // Another tab has now saved a newer view. This tab must not overwrite it.
  server = { revision: 2, state: { ...server.state, search: 'Anderes Fenster' } };
  fireEvent.change(search, { target: { value: 'Ungespeicherte lokale Suche' } });
  await tick(); expect(screen.getByRole('alert')).toHaveTextContent('anderen Fenster');
  fireEvent.click(screen.getByRole('button', { name: 'Serveransicht laden' }));
  await tick();
  expect(search).toHaveValue('Anderes Fenster');
  expect(server.revision).toBe(2);
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();

  fireEvent.change(search, { target: { value: 'Neue bestätigte Suche' } });
  await tick();
  expect(server).toMatchObject({ revision: 3, state: { search: 'Neue bestätigte Suche' } });
  expect(mock.put.mock.calls.at(-1)[2].base_revision).toBe(2);
});
