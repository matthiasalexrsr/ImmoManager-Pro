import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import App from '../App';
import { AuthProvider, useAuth } from '../contexts/AuthContext';
import { setWorkspaceOwner, workspaceOwner } from '../utils/workspaceIdentity';

vi.mock('../contexts/DevModeContext', () => ({ useDevMode: () => ({ enabled: false }) }));
vi.mock('../components/DevModeOverlay', () => ({ default: () => null }));
vi.mock('../pages/Login', () => ({ default: () => <p>Anmeldung</p> }));
vi.mock('../components/Layout', () => ({ default: function Layout() {
  const { user } = useAuth();
  return <div><p>Geschützte Anwendung: {user?.id}</p><input aria-label="Privater Entwurf" defaultValue="" /></div>;
} }));
const jwt = (sub, jti = 'original') => `${btoa('{}')}.${btoa(JSON.stringify({ sub, jti }))}.synthetic`;
const reply = body => ({ ok: true, status: 200, json: async () => body });
let fetchMock;
beforeEach(() => {
  localStorage.clear(); setWorkspaceOwner(null);
  localStorage.setItem('access_token', jwt('account-a'));
  localStorage.setItem('refresh_token', jwt('account-a', 'refresh'));
  fetchMock = vi.fn((url, options) => Promise.resolve(reply(url.endsWith('/auth/me')
    ? { id: options.headers.Authorization === `Bearer ${jwt('account-a')}` ? 'account-a' : 'account-b', role: 'eigentuemer' }
    : {})));
  vi.stubGlobal('fetch', fetchMock);
  window.history.replaceState({}, '', '/');
});
afterEach(() => { cleanup(); localStorage.clear(); setWorkspaceOwner(null); vi.unstubAllGlobals(); });

it('unmounts A immediately on a real storage event, validates B and keeps A recovery private', async () => {
  let resolveB;
  const responseB = new Promise(resolve => { resolveB = resolve; });
  fetchMock.mockImplementation((url, options) => url.endsWith('/auth/me') && options.headers.Authorization === `Bearer ${jwt('account-b')}`
    ? responseB : Promise.resolve(reply(url.endsWith('/auth/me') ? { id: 'account-a', role: 'eigentuemer' } : {})));
  render(<AuthProvider><App /></AuthProvider>);
  expect(await screen.findByText('Geschützte Anwendung: account-a')).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Privater Entwurf'), { target: { value: 'Private A' } });
  localStorage.setItem('workspace:account-a:draft-buffer:contacts', 'Private A');
  localStorage.setItem('access_token', jwt('account-b'));
  localStorage.setItem('refresh_token', jwt('account-b', 'refresh'));
  act(() => {
    window.dispatchEvent(new StorageEvent('storage', { key: 'access_token', oldValue: jwt('account-a'), newValue: jwt('account-b') }));
    expect(workspaceOwner()).toBeNull();
  });
  expect(screen.queryByLabelText('Privater Entwurf')).not.toBeInTheDocument();
  expect(localStorage.getItem('access_token')).toBe(jwt('account-b'));
  expect(localStorage.getItem('workspace:account-a:draft-buffer:contacts')).toBe('Private A');
  await act(async () => { resolveB(reply({ id: 'account-b', role: 'readonly' })); });
  expect(await screen.findByText('Geschützte Anwendung: account-b')).toBeInTheDocument();
  expect(screen.getByLabelText('Privater Entwurf')).toHaveValue('');
  expect(fetchMock.mock.calls.some(([url]) => url.endsWith('/auth/logout'))).toBe(false);
});

it('returns to login after another tab removes the session without revoking or deleting private buffers', async () => {
  render(<AuthProvider><App /></AuthProvider>);
  expect(await screen.findByText('Geschützte Anwendung: account-a')).toBeInTheDocument();
  localStorage.setItem('workspace:account-a:draft-buffer:contacts', 'Private A');
  localStorage.removeItem('access_token'); localStorage.removeItem('refresh_token');
  act(() => { window.dispatchEvent(new StorageEvent('storage', { key: 'access_token', oldValue: jwt('account-a'), newValue: null })); });
  expect(await screen.findByText('Anmeldung')).toBeInTheDocument();
  expect(workspaceOwner()).toBeNull();
  expect(localStorage.getItem('workspace:account-a:draft-buffer:contacts')).toBe('Private A');
  expect(fetchMock.mock.calls.some(([url]) => url.endsWith('/auth/logout'))).toBe(false);
});

it('keeps the mounted editor when another tab rotates the same owner token', async () => {
  render(<AuthProvider><App /></AuthProvider>);
  expect(await screen.findByText('Geschützte Anwendung: account-a')).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Privater Entwurf'), { target: { value: 'Private A' } });
  localStorage.setItem('access_token', jwt('account-a', 'rotated'));
  act(() => { window.dispatchEvent(new StorageEvent('storage', { key: 'access_token', oldValue: jwt('account-a'), newValue: jwt('account-a', 'rotated') })); });
  expect(screen.getByLabelText('Privater Entwurf')).toHaveValue('Private A');
  expect(workspaceOwner()).toBe('account-a');
  expect(fetchMock.mock.calls.filter(([url]) => url.endsWith('/auth/me'))).toHaveLength(1);
});
