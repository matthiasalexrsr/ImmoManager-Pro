import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, act } from '@testing-library/react';
import { DataStoreProvider, useEntities } from '../contexts/DataStoreContext';
import { api } from '../api';
const identity = vi.hoisted(() => ({ user: { id: 'owner-a', role: 'eigentuemer', portfolio_access: 'all', portfolio_ids: [] } }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => identity }));
vi.mock('../api', () => ({ api: { list: vi.fn() } }));
function Entries() { const data = useEntities('properties', '/properties'); return <div>{data.loading ? 'Laden' : data.items.map(item => item.name).join(',')}</div>; }
const ui = () => <DataStoreProvider><Entries /></DataStoreProvider>;
beforeEach(() => { identity.user = { id: 'owner-a', role: 'eigentuemer', portfolio_access: 'all', portfolio_ids: [] }; vi.resetAllMocks(); });
afterEach(cleanup);
it('does not reuse another account’s cached records before the cache TTL expires', async () => {
  api.list.mockResolvedValueOnce([{ id: 'a', name: 'Private Immobilie A' }]).mockResolvedValueOnce([{ id: 'b', name: 'Berechtigte Immobilie B' }]);
  const { rerender } = render(ui());
  await screen.findByText('Private Immobilie A');
  identity.user = { ...identity.user, id: 'owner-b', role: 'readonly' };
  rerender(ui());
  expect(screen.queryByText('Private Immobilie A')).not.toBeInTheDocument();
  await screen.findByText('Berechtigte Immobilie B');
  expect(api.list).toHaveBeenCalledTimes(2);
});
it('isolates a late response and a narrowed portfolio scope from the current cache', async () => {
  let finish;
  api.list.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }))
    .mockResolvedValueOnce([{ id: 'b', name: 'Freigegebene Immobilie' }]);
  const { rerender } = render(ui());
  await waitFor(() => expect(api.list).toHaveBeenCalledTimes(1));
  identity.user = { ...identity.user, portfolio_access: 'selected', portfolio_ids: ['portfolio-b'] };
  rerender(ui());
  await screen.findByText('Freigegebene Immobilie');
  await act(async () => { finish([{ id: 'a', name: 'Veraltete Freigabe' }]); });
  expect(screen.queryByText('Veraltete Freigabe')).not.toBeInTheDocument();
  expect(screen.getByText('Freigegebene Immobilie')).toBeInTheDocument();
});
