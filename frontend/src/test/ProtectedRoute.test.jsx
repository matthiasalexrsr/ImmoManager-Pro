import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ProtectedRoute } from '../App';

const mocks = vi.hoisted(() => ({ get: vi.fn(), updateUser: vi.fn(), clearUser: vi.fn() }));
vi.mock('../api', () => ({ api: { get: mocks.get }, isLoggedIn: () => Boolean(localStorage.getItem('access_token')), watchSessionChange: () => () => {} }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ updateUser: mocks.updateUser, clearUser: mocks.clearUser }) }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: key => key }) }));
vi.mock('react-router-dom', () => ({ Navigate: () => <p>Login destination</p> }));
vi.mock('../components/Layout', () => ({ default: () => null }));
vi.mock('../components/DevModeOverlay', () => ({ default: () => null }));
vi.mock('../pages/Login', () => ({ default: () => null }));

beforeEach(() => {
  vi.clearAllMocks(); localStorage.clear();
  localStorage.setItem('access_token', 'current-access'); localStorage.setItem('refresh_token', 'current-refresh');
});
afterEach(() => localStorage.clear());

it('preserves the current login on a transient validation error and succeeds on explicit retry', async () => {
  mocks.get.mockRejectedValueOnce(new Error('Synthetic browser storage error')).mockResolvedValueOnce({ id: 'owner' });
  render(<ProtectedRoute><p>Authorized workspace</p></ProtectedRoute>);
  expect(await screen.findByRole('alert')).toHaveTextContent('Synthetic browser storage error');
  expect(localStorage.getItem('refresh_token')).toBe('current-refresh');
  expect(mocks.clearUser).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'ui.buttons.retry' }));
  expect(await screen.findByText('Authorized workspace')).toBeVisible();
  expect(mocks.updateUser).toHaveBeenCalledWith({ id: 'owner' });
});

it('ignores a late rejection after unmount and aborts the original validation', async () => {
  let reject;
  mocks.get.mockImplementationOnce(() => new Promise((_resolve, fail) => { reject = fail; }));
  const { unmount } = render(<ProtectedRoute><p>Authorized workspace</p></ProtectedRoute>);
  const signal = mocks.get.mock.calls[0][1].signal;
  unmount();
  localStorage.setItem('access_token', 'new-owner-access');
  reject(new Error('Old session failure'));
  await Promise.resolve();
  expect(signal.aborted).toBe(true);
  expect(localStorage.getItem('access_token')).toBe('new-owner-access');
  expect(mocks.clearUser).not.toHaveBeenCalled();
});

it('redirects after the API has invalidated the attempted current session', async () => {
  mocks.get.mockImplementationOnce(async () => {
    localStorage.removeItem('access_token'); localStorage.removeItem('refresh_token');
    throw Object.assign(new Error('Nicht authentifiziert'), { statusCode: 401 });
  });
  render(<ProtectedRoute><p>Authorized workspace</p></ProtectedRoute>);
  await waitFor(() => expect(screen.getByText('Login destination')).toBeVisible());
  expect(mocks.clearUser).toHaveBeenCalledOnce();
});

it('does not publish a late successful validation after local logout', async () => {
  let resolve;
  mocks.get.mockImplementationOnce(() => new Promise(done => { resolve = done; }));
  render(<ProtectedRoute><p>Authorized workspace</p></ProtectedRoute>);
  localStorage.clear(); resolve({ id: 'previous-owner' });
  expect(await screen.findByText('Login destination')).toBeVisible();
  expect(mocks.updateUser).not.toHaveBeenCalled();
});

it('validates the changed current pair again instead of publishing an old successful identity', async () => {
  mocks.get.mockRejectedValueOnce(Object.assign(new Error('Session changed'), { code: 'AUTH_SESSION_CHANGED' }))
    .mockResolvedValueOnce({ id: 'new-owner' });
  render(<ProtectedRoute><p>Authorized workspace</p></ProtectedRoute>);
  expect(await screen.findByText('Authorized workspace')).toBeVisible();
  expect(mocks.get).toHaveBeenCalledTimes(2);
  expect(mocks.updateUser).toHaveBeenCalledExactlyOnceWith({ id: 'new-owner' });
});
