import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import Units from '../pages/Units';
import { api } from '../api';

vi.mock('../api', () => ({ api: { list: vi.fn(), post: vi.fn() } }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: () => undefined }) }));
vi.mock('../contexts/AuthContext', () => ({ useCanWrite: () => true, useAuth: () => ({ user: { id: 'owner' } }) }));
vi.mock('../contexts/DataStoreContext', () => ({
  useDataStore: () => null,
  useEntities: key => ({ items: key === 'properties' ? [{ id: 'p1', name: 'Haus A' }, { id: 'p2', name: 'Haus B' }] : [] }),
}));
vi.mock('../features/partyWorkspace/PartyWorkspace', () => ({ PartyLink: ({ children }) => children }));
vi.mock('../components/Toast', () => ({ useToast: () => ({ success: vi.fn(), error: vi.fn() }) }));
// The page/form lifecycle is under test; table rendering has its own integration coverage.
vi.mock('../components/DataTable', () => ({ default: ({ onAdd }) => <button onClick={() => onAdd()}>Einheit anlegen</button> }));

afterEach(() => { cleanup(); vi.resetAllMocks(); localStorage.clear(); });

it('keeps the first unit form and its repeat fields alive while the saved list reloads', async () => {
  let finishReload;
  api.list.mockResolvedValueOnce([]).mockImplementationOnce(() => new Promise(resolve => { finishReload = resolve; }));
  api.post.mockResolvedValue({ id: 'u1' });
  render(<MemoryRouter><Units /></MemoryRouter>);
  fireEvent.click(await screen.findByRole('button', { name: 'Einheit anlegen' }));
  fireEvent.change(screen.getByLabelText('Immobilie *'), { target: { value: 'p2' } });
  fireEvent.change(screen.getByLabelText('Bezeichnung *'), { target: { value: 'Erste Wohnung' } });
  fireEvent.click(screen.getByRole('button', { name: 'Speichern & weiteren' }));

  expect(await screen.findByRole('status')).toHaveTextContent('1 gespeichert');
  expect(api.post).toHaveBeenCalledWith('/units', expect.objectContaining({ property_id: 'p2', label: 'Erste Wohnung' }));
  expect(screen.getByRole('dialog')).toBeInTheDocument();
  expect(screen.getByLabelText('Immobilie *')).toHaveValue('p2');
  expect(screen.getByLabelText('Bezeichnung *')).toHaveValue('');

  await act(async () => finishReload([{ id: 'u1', property_id: 'p2', label: 'Erste Wohnung' }]));
  expect(screen.getByRole('status')).toHaveTextContent('1 gespeichert');
  expect(screen.getByLabelText('Immobilie *')).toHaveValue('p2');
  fireEvent.change(screen.getByLabelText('Bezeichnung *'), { target: { value: 'Zweite Wohnung' } });
  expect(screen.getByRole('dialog')).toBeInTheDocument();
});
