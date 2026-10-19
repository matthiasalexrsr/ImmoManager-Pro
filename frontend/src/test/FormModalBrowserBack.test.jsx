import { useState } from 'react';
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { createBrowserRouter, Link, MemoryRouter, Outlet, RouterProvider } from 'react-router-dom';
import FormModal from '../components/FormModal';
import { NavigationProtectionProvider } from '../components/UnsavedNavigationGuard';
import { workspace } from '../utils/workspaceClient';
import useFormDraft from '../hooks/useFormDraft';

vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { id: 'back-test-owner' } }) }));
vi.mock('../utils/workspaceClient', async original => ({ ...(await original()), workspace: {
  list: vi.fn(), put: vi.fn(), remove: vi.fn(), command: () => crypto.randomUUID(),
} }));

const routers = [];
beforeEach(() => {
  localStorage.clear(); vi.clearAllMocks();
  window.history.replaceState({}, '', '/documents');
  workspace.list.mockResolvedValue({ items: [] });
  workspace.put.mockImplementation(async (_resource, id, body) => ({ id, ...body, revision: body.base_revision + 1,
    source_state: { status: 'new' } }));
  workspace.remove.mockResolvedValue({ deleted: true });
});
afterEach(() => { cleanup(); routers.splice(0).forEach(router => router.dispose()); localStorage.clear(); });

function TaskForm() {
  const [open, setOpen] = useState(false);
  return <><h1>Aufgaben</h1><button onClick={() => setOpen(true)}>Neu</button>{open && <FormModal title="Aufgabe erstellen"
    fields={[{ key: 'title', label: 'Titel' }]} onSave={vi.fn()} onClose={() => setOpen(false)} />}</>;
}

it('also scopes independently used draft writers to their router when the browser address differs', async () => {
  const { result } = renderHook(() => useFormDraft({ fields: [{ key: 'title' }] }), {
    wrapper: ({ children }) => <MemoryRouter initialEntries={['/tasks']}>{children}</MemoryRouter>,
  });
  await waitFor(() => expect(result.current.ready).toBe(true));
  expect(workspace.list).toHaveBeenCalledWith('drafts', expect.objectContaining({ context: 'tasks' }), expect.anything());
  expect(result.current.sessionKey).toContain(':tasks:');
});

it('keeps the task form and draft writer on their committed route during real browser POP rollback', async () => {
  const router = createBrowserRouter([{ element: <NavigationProtectionProvider>
    <Link to="/tasks">Aufgaben öffnen</Link><Outlet />
  </NavigationProtectionProvider>, children: [{ path: '/documents', element: <h1>Dokumente</h1> },
    { path: '/tasks', element: <TaskForm /> }] }]);
  routers.push(router);
  render(<RouterProvider router={router} />);
  fireEvent.click(screen.getByRole('link', { name: 'Aufgaben öffnen' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Neu' }));
  const input = screen.getByRole('textbox', { name: 'Titel' });
  await waitFor(() => expect(input).toBeEnabled());
  fireEvent.change(input, { target: { value: 'QA Smoke Back Entwurf' } });
  await screen.findByText('Entwurf automatisch gesichert', {}, { timeout: 3000 });
  expect(workspace.put).toHaveBeenCalledWith('drafts', expect.any(String), expect.objectContaining({ context: 'tasks' }));

  act(() => window.history.back());
  const prompt = await screen.findByRole('alertdialog');
  await waitFor(() => expect(window.location.pathname).toBe('/tasks'));
  expect(input).toHaveValue('QA Smoke Back Entwurf');
  expect(workspace.list.mock.calls.map(([, query]) => query.context)).toEqual(['tasks']);
  fireEvent.click(within(prompt).getByRole('button', { name: 'Weiter bearbeiten' }));
  expect(input).toHaveValue('QA Smoke Back Entwurf');
  expect(screen.queryByText('Entwurf wiederaufnehmen')).not.toBeInTheDocument();
  expect(workspace.remove).not.toHaveBeenCalled();

  act(() => window.history.back());
  fireEvent.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Verwerfen' }));
  expect(await screen.findByRole('heading', { name: 'Dokumente' })).toBeInTheDocument();
  expect(router.state.location.pathname).toBe('/documents');
  expect(workspace.remove).toHaveBeenCalledOnce();
});
