import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, afterEach, expect, it, vi } from 'vitest';
import App from '../App';
import { api } from '../api';

const auth = vi.hoisted(() => ({ updateUser: vi.fn(), clearUser: vi.fn() }));
vi.mock('../api', () => ({ api: { get: vi.fn() }, isLoggedIn: () => !!localStorage.getItem('access_token') }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => auth }));
vi.mock('../contexts/DevModeContext', () => ({ useDevMode: () => ({ enabled: false }) }));
vi.mock('../components/DevModeOverlay', () => ({ default: () => null }));
vi.mock('../components/Layout', () => ({ default: () => <p>Geschützte Anwendung</p> }));
vi.mock('../pages/Login', () => ({ default: () => <p>Anmeldung</p> }));
beforeEach(() => { vi.resetAllMocks(); localStorage.setItem('access_token', 'keep-session'); window.history.replaceState({}, '', '/'); });
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
