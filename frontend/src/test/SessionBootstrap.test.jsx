import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { StrictMode } from 'react';
import { Link } from 'react-router-dom';
import UnsavedNavigationGuard from '../components/UnsavedNavigationGuard';
import { beforeEach, afterEach, expect, it, vi } from 'vitest';
import App from '../App';
import { api } from '../api';

const auth = vi.hoisted(() => ({ updateUser: vi.fn(), clearUser: vi.fn(), blocked: vi.fn(), protect: false }));
vi.mock('../api', () => ({ api: { get: vi.fn() }, isLoggedIn: () => !!localStorage.getItem('access_token') }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => auth }));
vi.mock('../contexts/DevModeContext', () => ({ useDevMode: () => ({ enabled: false }) }));
vi.mock('../components/DevModeOverlay', () => ({ default: () => null }));
vi.mock('../components/Layout', () => ({ default: () => <><p>Geschützte Anwendung</p>{auth.protect && <>
  <Link to="/tasks">Andere Seite öffnen</Link><UnsavedNavigationGuard when onBlocked={auth.blocked} label="Privater Entwurf" />
</>}</> }));
vi.mock('../pages/Login', () => ({ default: () => <p>Anmeldung</p> }));
beforeEach(() => { vi.resetAllMocks(); auth.protect = false; localStorage.setItem('access_token', 'keep-session'); window.history.replaceState({}, '', '/'); });
afterEach(() => { cleanup(); localStorage.clear(); });

it('keeps a session after a temporary bootstrap error and retries validation before showing the application', async () => {
  api.get.mockRejectedValueOnce(new Error('Server vorübergehend nicht verfügbar')).mockResolvedValueOnce({ id: 'reader' });
  render(<App />);
  expect(await screen.findByRole('alert')).toHaveTextContent('Server vorübergehend nicht verfügbar');
  expect(localStorage.getItem('access_token')).toBe('keep-session');
  expect(auth.clearUser).not.toHaveBeenCalled();
  expect(screen.queryByText('Geschützte Anwendung')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Erneut versuchen' }));
  expect(await screen.findByText('Geschützte Anwendung')).toBeInTheDocument();
  expect(auth.updateUser).toHaveBeenCalledWith({ id: 'reader' });
});

it('returns to login after the API has confirmed the session ended', async () => {
  api.get.mockImplementation(async () => { localStorage.clear(); throw new Error('Nicht authentifiziert'); });
  render(<App />);
  expect(await screen.findByText('Anmeldung')).toBeInTheDocument();
  expect(auth.clearUser).toHaveBeenCalled();
});

it('owns one live browser history listener through StrictMode rehearsal and disposes it on unmount', async () => {
  api.get.mockResolvedValue({ id: 'reader' });
  const added = vi.spyOn(window, 'addEventListener');
  const removed = vi.spyOn(window, 'removeEventListener');
  const view = render(<StrictMode><App /></StrictMode>);
  expect(await screen.findByText('Geschützte Anwendung')).toBeInTheDocument();
  const count = spy => spy.mock.calls.filter(([event]) => event === 'popstate').length;
  expect(count(added) - count(removed)).toBe(1);
  view.unmount();
  expect(count(added) - count(removed)).toBe(0);
  added.mockRestore(); removed.mockRestore();
});

it('removes dirty scopes and a blocked transition before routing an expired session to login', async () => {
  auth.protect = true;
  api.get.mockResolvedValue({ id: 'reader' });
  render(<App />);
  fireEvent.click(await screen.findByRole('link', { name: 'Andere Seite öffnen' }));
  expect(auth.blocked).toHaveBeenCalled();
  localStorage.removeItem('access_token');
  act(() => window.dispatchEvent(new CustomEvent('workspace-logout')));
  expect(await screen.findByText('Anmeldung')).toBeInTheDocument();
  expect(screen.queryByText('Geschützte Anwendung')).not.toBeInTheDocument();
  const unload = new Event('beforeunload', { cancelable: true });
  window.dispatchEvent(unload);
  expect(unload.defaultPrevented).toBe(false);
});
