import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { api } from '../api';
import { DataStoreProvider, useEntities } from '../contexts/DataStoreContext';
import CrudPage from '../pages/CrudPage';
import Insurances from '../pages/Insurances';
import Calendar from '../pages/Calendar';

vi.mock('../api', () => ({ api: { list: vi.fn(), get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() } }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { id: 'owner', role: 'eigentuemer' } }), useCanWrite: () => true }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: key => ({ 'ui.buttons.new': 'Neu', 'ui.buttons.edit': 'Bearbeiten', 'ui.buttons.create': 'Erstellen' }[key] || ''), locale: 'de-DE' }) }));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => async () => true }));
vi.mock('../utils/workspaceClient', async original => ({ ...await original(), workspace: { list: async () => ({ items: [], next_cursor: null }) } }));
function Refresh() {
  const source = useEntities('categories', '/categories');
  return <button onClick={source.reload}>Ansicht aktualisieren</button>;
}
const categories = <><Refresh /><CrudPage title="Kategorien" endpoint="/categories" columns={[{ key: 'name', label: 'Name' }]} formFields={[]} /></>;
const show = element => render(<MemoryRouter><DataStoreProvider>{element}</DataStoreProvider></MemoryRouter>);
beforeEach(() => { vi.resetAllMocks(); localStorage.clear(); });
afterEach(cleanup);
it('rejects a malformed shared-cache response instead of showing a valid empty list and retries', async () => {
  api.list.mockResolvedValueOnce({ invalid: true }).mockResolvedValue([{ id: 'c1', name: 'Instandhaltung' }]);
  show(categories);
  expect(await screen.findByRole('alert')).toHaveTextContent('Datenliste konnte nicht gelesen werden');
  fireEvent.click(screen.getByRole('button', { name: 'Erneut laden' }));
  expect(await screen.findByText('Instandhaltung')).toBeInTheDocument();
});
it('keeps the last successful rows visible after a failed refresh', async () => {
  api.list.mockResolvedValueOnce([{ id: 'c1', name: 'Instandhaltung' }]).mockRejectedValue(new Error('Verbindung unterbrochen'));
  show(categories); await screen.findByText('Instandhaltung');
  fireEvent.click(screen.getByRole('button', { name: 'Ansicht aktualisieren' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('letzte erfolgreich geladene Ansicht');
  expect(screen.getByText('Instandhaltung')).toBeInTheDocument();
});
it('links insurance names to the exact property and unit and gates missing form choices', async () => {
  let unavailable = true;
  api.list.mockImplementation(async path => {
    if (path === '/insurances') return [{ id: 'i1', provider: 'Muster Versicherung', property_id: 'p1', unit_id: 'u1' }];
    if (path === '/units') return [{ id: 'u1', label: 'Wohnung Süd' }];
    if (path === '/properties' && unavailable) throw new Error('Immobilien nicht erreichbar');
    if (path === '/properties') return [{ id: 'p1', name: 'Haus am Park' }];
    return [];
  });
  show(<Insurances />);
  expect(await screen.findByRole('alert')).toHaveTextContent('Immobilien nicht erreichbar');
  expect(await screen.findByRole('link', { name: 'Wohnung Süd' })).toHaveAttribute('href', '/units/u1');
  fireEvent.click(screen.getByRole('button', { name: 'Neu' }));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  unavailable = false;
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Auswahl erneut laden' })));
  expect(await screen.findByRole('link', { name: 'Haus am Park' })).toHaveAttribute('href', '/properties/p1');
});

it.each([
  [Insurances, '/insurances', 'Einheit (optional)'],
  [Calendar, '/calendar', 'Einheit (optional)'],
])('limits dependent units to the selected property and clears a previous choice', async (Page, endpoint, unitLabel) => {
  api.list.mockImplementation(async path => {
    if (path === endpoint) return [];
    if (path === '/properties') return [{ id: 'p1', name: 'Haus Nord' }, { id: 'p2', name: 'Haus Süd' }];
    if (path === '/units') return [{ id: 'u1', property_id: 'p1', label: 'Wohnung Nord' }, { id: 'u2', property_id: 'p2', label: 'Wohnung Süd' }];
    return [];
  });
  show(<Page />);
  await screen.findByRole('button', { name: 'Neu' });
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Neu' })));
  const property = screen.getByLabelText(/Immobilie/);
  fireEvent.change(property, { target: { value: 'p1' } });
  const unit = screen.getByLabelText(unitLabel);
  expect(unit).toHaveTextContent('Wohnung Nord');
  expect(unit).not.toHaveTextContent('Wohnung Süd');
  fireEvent.change(unit, { target: { value: 'u1' } });
  fireEvent.change(property, { target: { value: 'p2' } });
  expect(unit).toHaveValue('');
  expect(unit).toHaveTextContent('Wohnung Süd');
  expect(unit).not.toHaveTextContent('Wohnung Nord');
});
