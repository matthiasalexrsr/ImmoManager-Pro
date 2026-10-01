import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { PreferencesProvider, usePreferences } from '../contexts/PreferencesContext';

const mocks = vi.hoisted(() => ({ user: null, get: vi.fn(), put: vi.fn(), setLocale: vi.fn() }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: mocks.user }) }));
vi.mock('../api', () => ({ api: { get: mocks.get, put: mocks.put } }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ setLocale: mocks.setLocale }) }));
const deferred = () => { let resolve; let reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };
function Probe() {
  const { prefs, toggleTheme, toggleSidebar, saveError, retrySave } = usePreferences();
  return <div><output>{JSON.stringify(prefs)}</output>
    <button onClick={toggleTheme}>Theme</button><button onClick={toggleSidebar}>Sidebar</button>
    {saveError && <p role="alert">{saveError}</p>}<button onClick={retrySave}>Retry</button></div>;
}
const preferences = () => JSON.parse(screen.getByRole('status').textContent);
const app = () => <PreferencesProvider><Probe /></PreferencesProvider>;
beforeEach(() => {
  mocks.user = null; mocks.get.mockReset(); mocks.put.mockReset().mockResolvedValue({});
  mocks.setLocale.mockClear();
  localStorage.clear();
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it('never makes protected requests while the login page is anonymous', async () => {
  render(app()); fireEvent.click(screen.getByText('Theme'));
  await act(async () => {});
  expect(mocks.get).not.toHaveBeenCalled(); expect(mocks.put).not.toHaveBeenCalled();
});
it('loads the authenticated endpoint after login and tolerates a damaged account cache', async () => {
  const view = render(app());
  localStorage.setItem('user_preferences:alice', '{broken');
  mocks.get.mockResolvedValue({ theme: 'dark', locale: 'en-US' });
  mocks.user = { id: 'alice' }; view.rerender(app());
  await waitFor(() => expect(preferences().theme).toBe('dark'));
  expect(mocks.get).toHaveBeenCalledWith('/auth/users/me/preferences', expect.objectContaining({ signal: expect.any(AbortSignal) }));
  expect(JSON.parse(localStorage.getItem('user_preferences:alice')).locale).toBe('en-US');
  expect(mocks.setLocale).toHaveBeenLastCalledWith('en-US');
});
it('isolates accounts and ignores a late load from the previous account', async () => {
  const old = deferred(); mocks.get.mockReturnValueOnce(old.promise).mockResolvedValueOnce({ theme: 'light', locale: 'es-ES' });
  mocks.user = { id: 'alice' }; const view = render(app());
  const signal = mocks.get.mock.calls[0][1].signal;
  mocks.user = { id: 'bob' }; view.rerender(app());
  await waitFor(() => expect(preferences().locale).toBe('es-ES'));
  await act(async () => old.resolve({ theme: 'dark', locale: 'en-US' }));
  expect(signal.aborted).toBe(true); expect(preferences().theme).toBe('light');
  expect(mocks.setLocale).toHaveBeenLastCalledWith('es-ES');
  expect(localStorage.getItem('user_preferences:alice')).toBeNull();
  mocks.user = null; view.rerender(app()); expect(preferences().locale).toBe('de-DE');
});
it('does not replace an edited choice with an older preference load', async () => {
  const load = deferred(); mocks.get.mockReturnValue(load.promise); mocks.user = { id: 'alice' };
  render(app()); fireEvent.click(screen.getByText('Theme'));
  await act(async () => load.resolve({ theme: 'light' }));
  expect(preferences().theme).toBe('dark');
  expect(mocks.put).toHaveBeenCalledWith('/auth/users/me/preferences', expect.objectContaining({ theme: 'dark' }));
});
it('serializes rapid toggles so the server receives the final choice last', async () => {
  const first = deferred(); mocks.get.mockResolvedValue({}); mocks.put.mockReturnValueOnce(first.promise).mockResolvedValueOnce({});
  mocks.user = { id: 'alice' }; render(app()); await act(async () => {});
  fireEvent.click(screen.getByText('Sidebar')); fireEvent.click(screen.getByText('Sidebar'));
  await waitFor(() => expect(mocks.put).toHaveBeenCalledTimes(1));
  expect(mocks.put.mock.calls[0][1].sidebar_collapsed).toBe(true);
  await act(async () => first.resolve({}));
  await waitFor(() => expect(mocks.put).toHaveBeenCalledTimes(2));
  expect(mocks.put.mock.calls[1][1].sidebar_collapsed).toBe(false);
  expect(preferences().sidebar_collapsed).toBe(false);
});
it('keeps the local choice and exposes a truthful save failure with retry', async () => {
  mocks.get.mockResolvedValue({}); mocks.put.mockRejectedValueOnce(new Error('Server unavailable')).mockResolvedValueOnce({});
  mocks.user = { id: 'alice' }; render(app()); await act(async () => {});
  fireEvent.click(screen.getByText('Theme'));
  expect(await screen.findByRole('alert')).toHaveTextContent('Server unavailable');
  expect(preferences().theme).toBe('dark'); fireEvent.click(screen.getByText('Retry'));
  await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
  expect(mocks.put.mock.calls[1][1].theme).toBe('dark');
});
