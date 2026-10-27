import { StrictMode, useCallback, useState } from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createMemoryRouter, Link, Outlet, RouterProvider, useNavigate } from 'react-router-dom';
import UnsavedNavigationGuard, { NavigationProtectionProvider, NavigationScopeNotice } from '../components/UnsavedNavigationGuard';
import FormModal from '../components/FormModal';

const routers = [];
afterEach(() => { routers.splice(0).forEach(router => router.dispose()); });

function renderRoutes(element, strict = false) {
  const router = createMemoryRouter([{ element: <NavigationProtectionProvider><Link to="/destination">Global link</Link><Outlet /></NavigationProtectionProvider>, children: [
    { path: '/edit', element }, { path: '/destination', element: <h1>Destination</h1> },
  ] }], { initialEntries: ['/edit'] });
  routers.push(router);
  render(strict ? <StrictMode><RouterProvider router={router} /></StrictMode> : <RouterProvider router={router} />);
  return router;
}

function RegisteredEditor({ name, dirty = true, pending = false }) {
  const [request, setRequest] = useState(null);
  const blocked = useCallback(value => setRequest(value.cancelled ? null : value), []);
  return <section aria-label={name}>
    <UnsavedNavigationGuard when={dirty || pending} pending={pending} onBlocked={blocked} label={name} />
    {request && <><p>{name}: {request.pending ? 'Operation pending' : 'Confirm leave'}</p>
      <NavigationScopeNotice labels={request.scopeLabels} locale="de-DE" />
      {!request.pending && <><button onClick={() => { request.reset(); setRequest(null); }}>Keep {name}</button>
        <button onClick={() => request.proceed()}>Discard {name}</button></>}</>}
  </section>;
}

function StackedEditors() {
  const [showTop, setShowTop] = useState(false);
  const [pending, setPending] = useState(false);
  return <><RegisteredEditor name="base" pending={pending} />
    <button onClick={() => setShowTop(value => !value)}>Toggle top</button>
    <button onClick={() => setPending(value => !value)}>Toggle pending</button>
    {showTop && <><RegisteredEditor name="top" /><RegisteredEditor name="unused" dirty={false} /></>}
  </>;
}

describe('one application navigation protection registry', () => {
  it('keeps every scope registered exactly once through StrictMode effect rehearsal', async () => {
    renderRoutes(<StackedEditors />, true);
    fireEvent.click(screen.getByRole('button', { name: 'Toggle top' }));
    fireEvent.click(screen.getByRole('link', { name: 'Global link' }));
    expect(within(screen.getByRole('region', { name: 'top' })).getAllByRole('listitem').map(item => item.textContent)).toEqual(['top', 'base']);
    fireEvent.click(screen.getByRole('button', { name: 'Keep top' }));
    fireEvent.click(screen.getByRole('button', { name: 'Toggle top' }));
    fireEvent.click(screen.getByRole('link', { name: 'Global link' }));
    expect(within(screen.getByRole('region', { name: 'base' })).getAllByRole('listitem').map(item => item.textContent)).toEqual(['base']);
  });
  it('chooses the latest active editor, ignores inactive registrations and restores the underlying editor after unmount', async () => {
    const warn = vi.spyOn(console, 'warn');
    const router = renderRoutes(<StackedEditors />);
    fireEvent.click(screen.getByRole('button', { name: 'Toggle top' }));
    fireEvent.click(screen.getByRole('link', { name: 'Global link' }));
    expect(screen.getByText('top: Confirm leave')).toBeInTheDocument();
    expect(screen.queryByText('base: Confirm leave')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Keep top' }));
    fireEvent.click(screen.getByRole('button', { name: 'Toggle top' }));
    fireEvent.click(screen.getByRole('link', { name: 'Global link' }));
    expect(screen.getByText('base: Confirm leave')).toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/edit');
    expect(warn.mock.calls.flat().join(' ')).not.toContain('only supports one blocker');
    warn.mockRestore();
  });

  it('shows pending protection in the top editor even when the business command belongs to the underlying editor', async () => {
    const router = renderRoutes(<StackedEditors />);
    fireEvent.click(screen.getByRole('button', { name: 'Toggle top' }));
    fireEvent.click(screen.getByRole('button', { name: 'Toggle pending' }));
    fireEvent.click(screen.getByRole('link', { name: 'Global link' }));
    expect(screen.getByText('top: Operation pending')).toBeInTheDocument();
    expect(screen.queryByText('top: Confirm leave')).not.toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/edit');
    expect(router.state.blockers.values().next().value?.state).toBe('unblocked');
  });

  it('rejects a stale confirmation when another editor becomes dirty and requires the refreshed scope list', async () => {
    let latest;
    const blocked = vi.fn(request => { latest = request; });
    function GrowingScopes() {
      const [extra, setExtra] = useState(false);
      return <><UnsavedNavigationGuard when label="First editor" onBlocked={blocked} />
        <button onClick={() => setExtra(true)}>Dirty second editor</button>
        {extra && <UnsavedNavigationGuard when label="Second editor" onBlocked={blocked} />}</>;
    }
    const router = renderRoutes(<GrowingScopes />);
    fireEvent.click(screen.getByRole('link', { name: 'Global link' }));
    const original = latest;
    expect(original.scopeLabels).toEqual(['First editor']);
    fireEvent.click(screen.getByRole('button', { name: 'Dirty second editor' }));
    await act(async () => { original.proceed(); });
    expect(router.state.location.pathname).toBe('/edit');
    expect(latest.scopeLabels).toEqual(['Second editor', 'First editor']);
    await act(async () => { latest.proceed(); });
    expect(await screen.findByRole('heading', { name: 'Destination' })).toBeInTheDocument();
  });
});

function RoutedForm({ save }) {
  const navigate = useNavigate();
  return <FormModal title="Example form" fields={[{ key: 'title', label: 'Title' }]} autosave={false}
    onSave={save} onClose={() => navigate('/destination')} />;
}

describe('shared FormModal route protection', () => {
  it('explicitly identifies all unsaved editors before the visible form can discard them together', async () => {
    renderRoutes(<><RegisteredEditor name="DOCX agreement" /><RoutedForm save={vi.fn()} /></>);
    fireEvent.change(screen.getByRole('textbox', { name: 'Title' }), { target: { value: 'Metadata edit' } });
    fireEvent.click(screen.getByRole('link', { name: 'Global link' }));
    const prompt = screen.getByRole('alertdialog');
    expect(within(prompt).getAllByRole('listitem').map(item => item.textContent)).toEqual(['Example form', 'DOCX agreement']);
    fireEvent.click(within(prompt).getByRole('button', { name: 'Alle aufgeführten Änderungen verwerfen und verlassen' }));
    expect(await screen.findByRole('heading', { name: 'Destination' })).toBeInTheDocument();
  });

  it('protects the underlying editor after a successful top form save and shows its scope in the still-visible form', async () => {
    const router = renderRoutes(<><RegisteredEditor name="DOCX agreement" /><RoutedForm save={vi.fn(async () => {})} /></>);
    fireEvent.change(screen.getByRole('textbox', { name: 'Title' }), { target: { value: 'Saved metadata' } });
    fireEvent.submit(screen.getByRole('textbox', { name: 'Title' }).closest('form'));
    const prompt = await screen.findByRole('alertdialog');
    expect(router.state.location.pathname).toBe('/edit');
    expect(within(prompt).getAllByRole('listitem').map(item => item.textContent)).toEqual(['DOCX agreement']);
    fireEvent.click(within(prompt).getByRole('button', { name: 'Weiter bearbeiten' }));
    expect(router.state.location.pathname).toBe('/edit');
    expect(screen.getByRole('textbox', { name: 'Title' })).toHaveValue('Saved metadata');
    // Closing an already saved dialog must still protect the editor underneath.
    fireEvent.click(screen.getByRole('button', { name: 'ui.buttons.cancel' }));
    expect(within(await screen.findByRole('alertdialog')).getByRole('listitem')).toHaveTextContent('DOCX agreement');
    fireEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Verwerfen' }));
    expect(await screen.findByRole('heading', { name: 'Destination' })).toBeInTheDocument();
  });

  it('uses its existing keep/discard controls for a global link and preserves entered values when kept', async () => {
    renderRoutes(<RoutedForm save={vi.fn()} />);
    const input = screen.getByRole('textbox', { name: 'Title' });
    fireEvent.change(input, { target: { value: 'Preserved title' } });
    fireEvent.click(screen.getByRole('link', { name: 'Global link' }));
    fireEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Weiter bearbeiten' }));
    expect(input).toHaveValue('Preserved title');
    expect(input).toHaveFocus();
    fireEvent.click(screen.getByRole('link', { name: 'Global link' }));
    fireEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Verwerfen' }));
    expect(await screen.findByRole('heading', { name: 'Destination' })).toBeInTheDocument();
  });

  it('holds navigation while saving and permits the successful save callback to close without a second confirmation', async () => {
    let finish;
    const save = vi.fn(() => new Promise(resolve => { finish = resolve; }));
    const router = renderRoutes(<RoutedForm save={save} />);
    fireEvent.change(screen.getByRole('textbox', { name: 'Title' }), { target: { value: 'Saved title' } });
    fireEvent.submit(screen.getByRole('textbox', { name: 'Title' }).closest('form'));
    await waitFor(() => expect(save).toHaveBeenCalledOnce());
    fireEvent.click(screen.getByRole('link', { name: 'Global link' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Ein Speichervorgang läuft noch');
    expect(router.state.location.pathname).toBe('/edit');
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    await act(async () => { finish(); });
    expect(await screen.findByRole('heading', { name: 'Destination' })).toBeInTheDocument();
  });
});
