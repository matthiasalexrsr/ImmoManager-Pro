import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createMemoryRouter, Link, Outlet, RouterProvider, useSearchParams } from 'react-router-dom';

vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ write: null }) }));
vi.mock('../components/PdfPreview', () => ({ default: () => null }));
import DepositFile from '../features/deposits/DepositFile';
import { NavigationProtectionProvider } from '../components/UnsavedNavigationGuard';

const routers = [];
afterEach(() => { routers.splice(0).forEach(router => router.dispose()); });

function fixture(id = 'd1') {
  return {
    deposit: { id, contract_id: 'c1', amount: 1500, form: 'transfer', revision: 'r1', notes: '' },
    source: { contract: { contract_number: id }, tenant: { full_name: 'Mia Muster' }, property: { name: 'Haus' }, unit: { label: 'WE1' } },
    stage: 'received', settled: false, money_form: true, cap: { known: false }, accounts: [],
    received: 1500, outstanding: 0, interest: { total: 0, until: '2026-10-19', years: [] }, retention: 0,
    interest_rates: [], payments: [], instalments: [], settlements: [],
  };
}

function Files({ service }) {
  const [params, setParams] = useSearchParams();
  const selected = params.get('deposit_id');
  return <><p>Deposit list</p>{selected && <DepositFile key={selected} depositId={selected} service={service}
    onClose={() => setParams({})} />}</>;
}

function mount(service = {}) {
  const api = { load: vi.fn(async id => fixture(id)), ...service };
  const router = createMemoryRouter([{ element: <NavigationProtectionProvider><Link to="/elsewhere">Global destination</Link><Outlet /></NavigationProtectionProvider>, children: [
    { path: '/deposits', element: <Files service={api} /> },
    { path: '/elsewhere', element: <h1>Destination reached</h1> },
  ] }], { initialEntries: ['/deposits', '/deposits?deposit_id=d1'], initialIndex: 1 });
  routers.push(router);
  render(<RouterProvider router={router} />);
  return { router, api };
}

async function edit() {
  const dialog = await screen.findByRole('dialog', { name: /Kautionsakte/ });
  fireEvent.click(within(dialog).getByRole('button', { name: 'Vereinbarung ändern' }));
  const notes = within(dialog).getByRole('textbox', { name: 'Notizen' });
  fireEvent.change(notes, { target: { value: 'Retain this edit' } });
  return { dialog, notes };
}
const confirmation = () => screen.getByRole('group', { name: 'Ungespeicherte Kautionsänderungen' });

describe('deposit navigation through the application router', () => {
  it('keeps dirty fields and history when Back is cancelled, and proceeds after deliberate discard', async () => {
    const { router } = mount();
    const { notes } = await edit();
    await act(async () => { await router.navigate(-1); });
    expect(router.state.location.search).toBe('?deposit_id=d1');
    expect(within(confirmation()).getByRole('button', { name: 'Weiter bearbeiten' })).toHaveFocus();
    fireEvent.click(within(confirmation()).getByRole('button', { name: 'Weiter bearbeiten' }));
    expect(notes).toHaveValue('Retain this edit');
    expect(router.state.location.search).toBe('?deposit_id=d1');
    await act(async () => { await router.navigate(-1); });
    fireEvent.click(within(confirmation()).getByRole('button', { name: 'Ohne Speichern verlassen' }));
    await waitFor(() => expect(router.state.location.search).toBe(''));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    await act(async () => { await router.navigate(1); });
    expect(await screen.findByRole('dialog', { name: /Kautionsakte/ })).toBeInTheDocument();
  });

  it('guards a global link outside the dialog, preserving edits on keep and navigating on discard', async () => {
    const { router } = mount();
    const { notes } = await edit();
    fireEvent.click(screen.getByRole('link', { name: 'Global destination' }));
    fireEvent.click(within(confirmation()).getByRole('button', { name: 'Weiter bearbeiten' }));
    expect(notes).toHaveValue('Retain this edit');
    fireEvent.click(screen.getByRole('link', { name: 'Global destination' }));
    fireEvent.click(within(confirmation()).getByRole('button', { name: 'Ohne Speichern verlassen' }));
    expect(await screen.findByRole('heading', { name: 'Destination reached' })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/elsewhere');
  });

  it('guards replacement with another deposit id and keeps the original file until confirmed', async () => {
    const { router, api } = mount();
    const { notes } = await edit();
    await act(async () => { await router.navigate('/deposits?deposit_id=d2', { replace: true }); });
    expect(notes).toHaveValue('Retain this edit');
    expect(api.load).toHaveBeenCalledTimes(1);
    fireEvent.click(within(confirmation()).getByRole('button', { name: 'Ohne Speichern verlassen' }));
    expect(await screen.findByRole('dialog', { name: /Kautionsakte · d2/ })).toBeInTheDocument();
  });

  it('does not show a second route confirmation after confirming the file close button', async () => {
    const { router } = mount();
    const { dialog } = await edit();
    fireEvent.click(within(dialog).getAllByRole('button', { name: 'Schließen' })[0]);
    fireEvent.click(within(confirmation()).getByRole('button', { name: 'Ohne Speichern verlassen' }));
    await waitFor(() => expect(router.state.location.search).toBe(''));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('blocks Back and global navigation while a command runs, without allowing discard or leaving after completion', async () => {
    let finish;
    const { router } = mount({ startSettlement: vi.fn(() => new Promise(resolve => { finish = resolve; })) });
    const dialog = await screen.findByRole('dialog', { name: /Kautionsakte/ });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Kautionsabrechnung beginnen' }));
    await act(async () => { await router.navigate(-1); });
    expect(within(dialog).getByRole('alert')).toHaveTextContent('Ein Kautionsvorgang läuft noch');
    expect(screen.queryByRole('button', { name: 'Ohne Speichern verlassen' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('link', { name: 'Global destination' }));
    expect(router.state.location.pathname).toBe('/deposits');
    expect(router.state.location.search).toBe('?deposit_id=d1');
    await act(async () => { finish(fixture()); });
    expect(router.state.location.pathname).toBe('/deposits');
    expect(router.state.location.search).toBe('?deposit_id=d1');
    fireEvent.click(screen.getByRole('link', { name: 'Global destination' }));
    expect(await screen.findByRole('heading', { name: 'Destination reached' })).toBeInTheDocument();
  });

  it('cancels an earlier dirty navigation request if a business command starts before confirmation', async () => {
    let finish;
    const { router } = mount({ startSettlement: vi.fn(() => new Promise(resolve => { finish = resolve; })) });
    const { dialog, notes } = await edit();
    fireEvent.click(screen.getByRole('link', { name: 'Global destination' }));
    expect(confirmation()).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Kautionsabrechnung beginnen' }));
    expect(screen.queryByRole('button', { name: 'Ohne Speichern verlassen' })).not.toBeInTheDocument();
    await act(async () => { finish(fixture()); });
    expect(router.state.location.pathname).toBe('/deposits');
    expect(notes).toHaveValue('Retain this edit');
    expect(screen.queryByRole('group', { name: 'Ungespeicherte Kautionsänderungen' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('link', { name: 'Global destination' }));
    expect(confirmation()).toBeInTheDocument();
    fireEvent.click(within(confirmation()).getByRole('button', { name: 'Ohne Speichern verlassen' }));
    expect(await screen.findByRole('heading', { name: 'Destination reached' })).toBeInTheDocument();
  });
});
