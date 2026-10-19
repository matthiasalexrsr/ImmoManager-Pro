import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { createMemoryRouter, Link, RouterProvider } from 'react-router-dom';
import FormModal from '../components/FormModal';
import { NavigationProtectionProvider } from '../components/UnsavedNavigationGuard';

const draft = vi.hoisted(() => ({ clear: vi.fn(), stage: vi.fn(), enabled: true, ready: true, sessionKey: 'draft-test',
  status: 'saved', recovery: null }));
vi.mock('../hooks/useFormDraft', () => ({ default: () => draft }));
const routers = [];
afterEach(() => { routers.splice(0).forEach(router => router.dispose()); });
beforeEach(() => vi.clearAllMocks());

it('holds delayed draft deletion against Keep, Escape, and another destination, then follows only the original approved route', async () => {
  let finish;
  draft.clear.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  const close = vi.fn();
  const router = createMemoryRouter([{ path: '/edit', element: <NavigationProtectionProvider>
    <Link to="/approved">Approved destination</Link><Link to="/other">Other destination</Link>
    <FormModal title="Draft form" fields={[{ key: 'title', label: 'Title' }]} onSave={vi.fn()} onClose={close} />
  </NavigationProtectionProvider> }, { path: '/approved', element: <h1>Approved page</h1> },
  { path: '/other', element: <h1>Other page</h1> }], { initialEntries: ['/edit'] });
  routers.push(router);
  render(<RouterProvider router={router} />);
  fireEvent.change(screen.getByRole('textbox', { name: 'Title' }), { target: { value: 'Preserved until explicit discard' } });
  fireEvent.click(screen.getByRole('link', { name: 'Approved destination' }));
  const prompt = screen.getByRole('alertdialog');
  fireEvent.click(within(prompt).getByRole('button', { name: 'Verwerfen' }));
  expect(draft.clear).toHaveBeenCalledOnce();
  const keep = within(prompt).getByRole('button', { name: 'Weiter bearbeiten' });
  expect(keep).toBeDisabled();
  fireEvent.click(keep);
  fireEvent.keyDown(document, { key: 'Escape' });
  fireEvent.click(screen.getByRole('link', { name: 'Other destination' }));
  expect(router.state.location.pathname).toBe('/edit');
  expect(screen.getByRole('textbox', { name: 'Title' })).toHaveValue('Preserved until explicit discard');
  expect(close).not.toHaveBeenCalled();
  await act(async () => { finish(); });
  expect(await screen.findByRole('heading', { name: 'Approved page' })).toBeInTheDocument();
  expect(router.state.location.pathname).toBe('/approved');
  expect(close).not.toHaveBeenCalled();
});
