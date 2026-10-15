import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import DataTable from '../components/DataTable';
import { workspace } from '../utils/workspaceClient';

vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { id: 'owner' } }), useCanWrite: () => false }));
vi.mock('../utils/workspaceClient', async original => ({ ...await original(), workspace: { list: vi.fn() } }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: key => key }) }));
const columns = [{ key: 'title', label: 'Dokument' }];
const rows = [];
beforeEach(() => { localStorage.clear(); sessionStorage.clear(); vi.clearAllMocks(); });
afterEach(cleanup);
it('does not offer a view bound to another party under the same document table title', async () => {
  let firstContext;
  workspace.list.mockImplementation(async (_, { context }) => {
    firstContext ||= context;
    return { items: context === firstContext ? [{ id: 'a', revision: 1, name: 'Belege Partei A', config: {} }] : [] };
  });
  const view = id => <MemoryRouter initialEntries={['/documents']}><DataTable title="Dokumente" columns={columns} data={rows}
    serverPaged viewAnchor={{ kind: 'tenant', id }} /></MemoryRouter>;
  const { rerender } = render(view('party-a'));
  await screen.findByRole('option', { name: 'Belege Partei A' });
  rerender(view('party-b'));
  await waitFor(() => expect(workspace.list).toHaveBeenCalledTimes(2));
  expect(screen.queryByRole('option', { name: 'Belege Partei A' })).not.toBeInTheDocument();
});
