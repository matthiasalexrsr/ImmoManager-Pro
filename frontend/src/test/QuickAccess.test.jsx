import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import QuickAccess from '../features/workCenter/QuickAccess';

const state = vi.hoisted(() => ({ user: { id: 'u1' }, list: vi.fn(), party: vi.fn() }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: state.user }) }));
vi.mock('../utils/workspaceClient', () => ({ workspace: { list: (...args) => state.list(...args) } }));
vi.mock('../features/partyWorkspace/PartyWorkspace', () => ({ PartyLink: ({ tenantId, children, onClick, ...props }) =>
  <button {...props} onClick={event => { onClick?.(event); state.party(tenantId); }}>{children}</button> }));
const property = { id: 'favorite-p1', kind: 'property', entity_id: 'p1', title: 'Haus am Park', href: '/properties/p1' };
const show = () => render(<MemoryRouter><QuickAccess /><input aria-label="Notiz" /><Routes><Route path="/" element={null} /><Route path="/properties/p1" element={<h1>Geöffnete Immobilie</h1>} /></Routes></MemoryRouter>);
beforeEach(() => { state.user = { id: 'u1' }; state.party.mockReset(); state.list.mockReset(); state.list.mockResolvedValue({ items: [property], next_cursor: null }); });
afterEach(cleanup);

it('loads only on demand, opens a saved record and returns focus on Escape', async () => {
  show();
  expect(state.list).not.toHaveBeenCalled();
  const opener = screen.getByRole('button', { name: 'Akten öffnen' });
  opener.focus(); fireEvent.click(opener);
  const dialog = screen.getByRole('dialog', { name: 'Akten öffnen' });
  await within(dialog).findAllByRole('link', { name: 'Haus am Park · Immobilie' });
  const closer = within(dialog).getByRole('button', { name: 'Aktenübersicht schließen' });
  expect(closer).toHaveFocus();
  fireEvent.keyDown(closer, { key: 'Tab', shiftKey: true });
  expect(within(dialog).getByRole('link', { name: 'Zur Arbeitszentrale' })).toHaveFocus();
  fireEvent.keyDown(document, { key: 'Escape' });
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument(); expect(opener).toHaveFocus();
  expect(document.body.style.overflow).toBe('');
  fireEvent.click(opener);
  fireEvent.click((await screen.findAllByRole('link', { name: 'Haus am Park · Immobilie' }))[0]);
  expect(await screen.findByRole('heading', { name: 'Geöffnete Immobilie' })).toBeInTheDocument();
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});

it('distinguishes a failed shelf from empty results and follows all cursor pages', async () => {
  state.list.mockImplementation((resource, query) => {
    if (resource === 'recents') return Promise.resolve({ items: [], next_cursor: null });
    if (!query.cursor) return Promise.reject(new Error('Akten sind gerade nicht erreichbar'));
    return Promise.resolve({ items: [{ ...property, id: 'favorite-p2', entity_id: 'p2', title: 'Zweites Haus', href: '/properties/p2' }], next_cursor: null });
  });
  show(); fireEvent.click(screen.getByRole('button', { name: 'Akten öffnen' }));
  const shelf = screen.getByRole('region', { name: 'Gemerkte Vorgänge' });
  expect(await within(shelf).findByRole('alert')).toHaveTextContent('Akten sind gerade nicht erreichbar');
  expect(within(shelf).queryByText(/Merken Sie Vorgänge/)).not.toBeInTheDocument();
  state.list.mockImplementation((resource, query) => Promise.resolve(resource === 'recents' ? { items: [], next_cursor: null }
    : query.cursor ? { items: [{ ...property, id: 'favorite-p2', entity_id: 'p2', title: 'Zweites Haus' }], next_cursor: null }
      : { items: [property], next_cursor: 'opaque-next' }));
  fireEvent.click(within(shelf).getByRole('button', { name: 'Erneut laden' }));
  fireEvent.click(await within(shelf).findByRole('button', { name: 'Weitere laden' }));
  await within(shelf).findByRole('link', { name: 'Zweites Haus · Immobilie' });
  expect(within(shelf).getAllByRole('link')).toHaveLength(2);
  expect(state.list).toHaveBeenCalledWith('favorites', expect.objectContaining({ cursor: 'opaque-next' }), expect.anything());
});

it('opens a party card and closes the quick access without intercepting typing or another dialog', async () => {
  state.list.mockResolvedValue({ items: [{ id: 'recent-t', kind: 'tenant', entity_id: 't1', title: 'Anna Müller' }], next_cursor: null });
  show();
  const input = screen.getByRole('textbox', { name: 'Notiz' });
  input.focus(); fireEvent.keyDown(input, { altKey: true, code: 'KeyO' });
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  fireEvent.keyDown(document, { altKey: true, code: 'KeyO' });
  fireEvent.click((await screen.findAllByRole('button', { name: 'Anna Müller · Partei' }))[0]);
  expect(state.party).toHaveBeenCalledWith('t1'); expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});

it('discards a late response after logout or switching the signed-in user', async () => {
  let resolve;
  state.list.mockReturnValue(new Promise(done => { resolve = done; }));
  const view = show(); fireEvent.click(screen.getByRole('button', { name: 'Akten öffnen' }));
  state.user = null;
  view.rerender(<MemoryRouter><QuickAccess /></MemoryRouter>);
  await act(async () => resolve({ items: [property], next_cursor: null }));
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  expect(screen.queryByText('Haus am Park')).not.toBeInTheDocument();
});
