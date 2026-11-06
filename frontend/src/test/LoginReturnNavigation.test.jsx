import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Outlet, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import App from '../App';
import Login from '../pages/Login';
import { AuthProvider } from '../contexts/AuthContext';
import { TutorialProvider } from '../components/Tutorial';
import { api, getRegistrationStatus, login, register } from '../api';

const fixture = vi.hoisted(() => ({ demo: false, startPage: '/', owner: 'return-owner' }));
vi.mock('../api', () => ({ api: { get: vi.fn() }, getRegistrationStatus: vi.fn(), login: vi.fn(), register: vi.fn(),
  isLoggedIn: () => Boolean(localStorage.getItem('access_token')) }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: key => key }) }));
vi.mock('../contexts/DevModeContext', () => ({ useDevMode: () => ({ enabled: false }) }));
vi.mock('../contexts/PreferencesContext', () => ({ usePreferences: () => ({ ready: true, prefs: { start_page: fixture.startPage } }) }));
vi.mock('../components/DevModeOverlay', () => ({ default: () => null }));
vi.mock('../components/Layout', () => ({ default: () => <TutorialProvider><Outlet /></TutorialProvider> }));
vi.mock('../pages/Tasks', () => ({ default: () => <Destination /> }));
vi.mock('../pages/Properties', () => ({ default: () => <Destination /> }));
vi.mock('../pages/Dashboard', () => ({ default: () => <Destination /> }));

const credentials = { username: 'demo.return', password: 'Synthetic-Return-2026!' };
const target = '/tasks?focus_id=b3640862-46cb-4ec3-a370-9e8c4f080caf&notice_id=notice-7&source_id=task-7#source';

function Destination() {
  const location = useLocation();
  const navigate = useNavigate();
  return <><output data-testid="destination">{location.pathname}{location.search}{location.hash}</output>
    <button onClick={() => navigate(-1)}>Browser zurück</button></>;
}

function browserApp(path = target) {
  window.history.replaceState({}, '', path);
  return render(<AuthProvider><App /></AuthProvider>);
}

function loginOnly(from) {
  return render(<MemoryRouter initialEntries={['/before', { pathname: '/login', state: { from } }]} initialIndex={1}>
    <Routes><Route path="/login" element={<Login />} /><Route path="*" element={<Destination />} /></Routes>
  </MemoryRouter>);
}

function enterPassword() {
  fireEvent.change(screen.getByLabelText('auth.login.userOrEmail'), { target: { value: 'return-user' } });
  fireEvent.change(screen.getByLabelText('auth.login.password'), { target: { value: credentials.password } });
  fireEvent.click(screen.getByRole('button', { name: 'auth.login.submit' }));
}

beforeEach(() => {
  vi.resetAllMocks(); localStorage.clear(); sessionStorage.clear();
  fixture.demo = false; fixture.startPage = '/';
  localStorage.setItem(`immo.tutorial.${fixture.owner}`, JSON.stringify({ offered: true }));
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ demo: fixture.demo, demo_login: credentials }) })));
  getRegistrationStatus.mockResolvedValue({ open: false, initial_setup: false });
  login.mockImplementation(async () => { localStorage.setItem('access_token', 'synthetic-return-session'); return {}; });
  register.mockResolvedValue({});
  api.get.mockImplementation(async path => path === '/auth/me' ? { id: fixture.owner, role: 'eigentuemer' } : { write: null });
});
afterEach(() => { cleanup(); localStorage.clear(); sessionStorage.clear(); vi.unstubAllGlobals(); window.history.replaceState({}, '', '/'); });

it.each([false, true])('returns an unauthenticated source link to its exact path, query and fragment after login (demo=%s)', async demo => {
  fixture.demo = demo;
  browserApp();
  if (demo) {
    fireEvent.click(await screen.findByRole('button', { name: 'Demozugang übernehmen' }));
    fireEvent.click(screen.getByRole('button', { name: 'auth.login.submit' }));
  } else {
    await screen.findByLabelText('auth.login.userOrEmail');
    enterPassword();
  }
  expect(await screen.findByTestId('destination')).toHaveTextContent(target);
  expect(window.location.pathname + window.location.search + window.location.hash).toBe(target);
  expect(register).not.toHaveBeenCalled();
});

it('keeps the return link across two-factor challenges and rejected codes', async () => {
  login.mockRejectedValueOnce(Object.assign(new Error('Code erforderlich'), { requiresTotp: true }))
    .mockRejectedValueOnce(new Error('Ungültiger Code'));
  browserApp(); await screen.findByLabelText('auth.login.userOrEmail'); enterPassword();
  fireEvent.change(await screen.findByLabelText('Zwei-Faktor-Code'), { target: { value: '123456' } });
  fireEvent.click(screen.getByRole('button', { name: 'auth.login.submit' }));
  await screen.findByText('Ungültiger Code');
  fireEvent.change(screen.getByLabelText('Zwei-Faktor-Code'), { target: { value: '654321' } });
  fireEvent.click(screen.getByRole('button', { name: 'auth.login.submit' }));
  expect(await screen.findByTestId('destination')).toHaveTextContent(target);
  expect(login).toHaveBeenLastCalledWith('return-user', credentials.password, '654321');
});

it('keeps first-owner registration and the optional tutorial without replacing the requested source', async () => {
  getRegistrationStatus.mockResolvedValue({ open: true, initial_setup: true });
  register.mockResolvedValue({ id: fixture.owner, role: 'eigentuemer', is_active: true, approval_required: false });
  localStorage.removeItem(`immo.tutorial.${fixture.owner}`);
  browserApp();
  await screen.findByText('auth.register.initialSetup');
  fireEvent.change(screen.getByLabelText('auth.login.username'), { target: { value: 'new-owner' } });
  fireEvent.change(screen.getByLabelText('auth.login.password'), { target: { value: credentials.password } });
  fireEvent.change(screen.getByLabelText('auth.register.email'), { target: { value: 'owner@example.test' } });
  fireEvent.change(screen.getByLabelText('auth.register.firstName'), { target: { value: 'Synthetischer Eigentümer' } });
  fireEvent.click(screen.getByRole('button', { name: 'auth.register.submit' }));
  expect(await screen.findByTestId('destination')).toHaveTextContent(target);
  expect(register).toHaveBeenCalledWith('new-owner', 'owner@example.test', 'Synthetischer Eigentümer', credentials.password);
  expect(await screen.findByRole('dialog', { name: 'Kurze Tour durch ImmoManager Pro?' })).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: 'Später' }));
  expect(screen.getByTestId('destination')).toHaveTextContent(target);
});

it('retains the ordinary configured start page when login had no source destination', async () => {
  fixture.startPage = '/properties'; browserApp('/login');
  await screen.findByLabelText('auth.login.userOrEmail'); enterPassword();
  expect(await screen.findByTestId('destination')).toHaveTextContent('/properties');
});

it('replaces the login entry so Back returns to the preceding page', async () => {
  loginOnly(target); enterPassword();
  expect(await screen.findByTestId('destination')).toHaveTextContent(target);
  fireEvent.click(screen.getByRole('button', { name: 'Browser zurück' }));
  await waitFor(() => expect(screen.getByTestId('destination')).toHaveTextContent('/before'));
});

it.each(['https://outside.example.test/tasks', '//outside.example.test', '/\\outside.example.test', '/\n/outside.example.test',
  'javascript:alert(1)', 'tasks?focus_id=1', '/login', '/login?from=/tasks', '/tasks/../login', '/%2f%2foutside.example.test',
  '/%5coutside.example.test', { pathname: '//outside.example.test' }])('falls back to the app root for an unsafe or recursive return destination %j', async from => {
  loginOnly(from); enterPassword();
  expect(await screen.findByTestId('destination')).toHaveTextContent(/^\/$/);
});
