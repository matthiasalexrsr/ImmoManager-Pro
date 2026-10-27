import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { Link, MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { useEffect, useState } from 'react';
import Layout from '../components/Layout';
import DataTable from '../components/DataTable';

const settings = vi.hoisted(() => ({ prefs: { theme: 'light', sidebar_collapsed: false }, toggleSidebar: vi.fn(), toggleTheme: vi.fn() }));
const auth = vi.hoisted(() => ({ value: null }));
vi.mock('../api', () => ({ logout: vi.fn() }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: key => key, locale: 'de-DE', setLocale: vi.fn() }) }));
vi.mock('../contexts/PreferencesContext', () => ({ usePreferences: () => settings }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => auth.value, useCanWrite: () => true }));
vi.mock('../components/SearchBar', () => ({ default: () => <input aria-label="Globale Suche" /> }));
vi.mock('../components/NotificationBell', () => ({ default: () => null }));
vi.mock('../components/Tutorial', () => ({ TutorialProvider: ({ children }) => children, useTutorial: () => ({ start: vi.fn() }) }));
vi.mock('../features/partyWorkspace/PartyWorkspace', () => ({ PartyWorkspaceProvider: ({ children }) => children }));

const columns = [{ key: 'title', label: 'Titel' }];
let opened;
const where = { pathname: '', search: '' };

function Where() { const location = useLocation(); useEffect(() => { Object.assign(where, location); }); return null; }

// A list page whose rows arrive after a moment, like the real pages after their request.
function TasksPage({ delay = 0 }) {
  const [ready, setReady] = useState(delay === 0);
  useEffect(() => { if (delay) { const timer = setTimeout(() => setReady(true), delay); return () => clearTimeout(timer); } }, [delay]);
  if (!ready) return <p>Laden</p>;
  return <DataTable title="Aufgaben" columns={columns} data={[]} onAdd={() => opened.push('tasks')} />;
}

function show(path, delay = 0) {
  return render(<MemoryRouter initialEntries={[path]}>
    <Where />
    <Link to="/tasks?neu=1">Neue Aufgabe</Link>
    <Link to="/meters">Zähler</Link>
    <Routes>
      <Route element={<Layout />}>
        <Route path="/tasks" element={<TasksPage delay={delay} />} />
        <Route path="/meters" element={<p>Zählerseite</p>} />
        <Route path="*" element={<p>Start</p>} />
      </Route>
    </Routes>
  </MemoryRouter>);
}

beforeEach(() => {
  opened = [];
  auth.value = null;
  localStorage.clear();
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false }));
  vi.stubGlobal('scrollTo', vi.fn());
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); });

it('opens the New form once from ?neu=1 and drops the marker from the address', () => {
  show('/tasks?neu=1&status=open');
  expect(opened).toEqual(['tasks']);
  expect(where.pathname).toBe('/tasks');
  expect(where.search).toBe('?status=open');
});

it('asks the page already open, and a list that appears later takes a held request once', () => {
  vi.useFakeTimers();
  show('/', 200);
  fireEvent.click(screen.getByRole('link', { name: 'Neue Aufgabe' }));
  expect(opened).toEqual([]);
  act(() => { vi.advanceTimersByTime(250); });
  expect(opened).toEqual(['tasks']);
  fireEvent.click(screen.getByRole('link', { name: 'Neue Aufgabe' }));
  expect(opened).toEqual(['tasks', 'tasks']);
});

it('forgets a held request when another page is shown first', () => {
  vi.useFakeTimers();
  show('/tasks?neu=1', 200);
  fireEvent.click(screen.getByRole('link', { name: 'Zähler' }));
  act(() => { vi.advanceTimersByTime(250); });
  expect(opened).toEqual([]);
});

it('Alt+N asks the list for its New form, but not while typing or inside a dialog', () => {
  show('/tasks');
  fireEvent.keyDown(screen.getByLabelText('Globale Suche'), { key: 'n', code: 'KeyN', altKey: true });
  expect(opened).toEqual([]);
  fireEvent.keyDown(document.body, { key: 'n', code: 'KeyN', altKey: true });
  expect(opened).toEqual(['tasks']);
});

it('shows the shortcut overview with "?" and from the top bar, and closes it with Escape', () => {
  show('/');
  fireEvent.keyDown(screen.getByLabelText('Globale Suche'), { key: '?' });
  expect(screen.queryByRole('dialog', { name: 'Tastenkürzel' })).not.toBeInTheDocument();
  fireEvent.keyDown(document.body, { key: '?' });
  const help = screen.getByRole('dialog', { name: 'Tastenkürzel' });
  expect(within(help).getByText('Neuen Eintrag in der Liste dieser Seite anlegen')).toBeInTheDocument();
  fireEvent.keyDown(document, { key: 'Escape' });
  expect(screen.queryByRole('dialog', { name: 'Tastenkürzel' })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Tastenkürzel' }));
  expect(screen.getByRole('dialog', { name: 'Tastenkürzel' })).toBeInTheDocument();
});

it('pins the current page to the sidebar per user and keeps it after a new start', () => {
  auth.value = { user: { id: 'u1' } };
  const first = show('/meters');
  const navigation = screen.getByRole('navigation', { name: 'Hauptnavigation' });
  expect(within(navigation).queryByText('Favoriten')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Als Favorit in die Seitenleiste: Zähler' }));
  expect(within(navigation).getByText('Favoriten')).toBeInTheDocument();
  expect(within(navigation).getAllByRole('link', { name: 'Zähler' })[0]).toHaveAttribute('href', '/meters');
  expect(JSON.parse(localStorage.getItem('nav_favorites:u1'))).toEqual(['/meters']);
  first.unmount();

  show('/');
  expect(within(screen.getByRole('navigation', { name: 'Hauptnavigation' })).getByText('Favoriten')).toBeInTheDocument();
  cleanup();

  // another user on the same browser has their own list
  auth.value = { user: { id: 'u2' } };
  show('/meters');
  expect(within(screen.getByRole('navigation', { name: 'Hauptnavigation' })).queryByText('Favoriten')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Als Favorit in die Seitenleiste: Zähler' }));
  fireEvent.click(screen.getByRole('button', { name: 'Aus den Favoriten entfernen: Zähler' }));
  expect(JSON.parse(localStorage.getItem('nav_favorites:u2'))).toEqual([]);
});

it('offers no pin for the six everyday pages that are always in the sidebar', () => {
  show('/tasks');
  expect(screen.queryByRole('button', { name: /Favorit/ })).not.toBeInTheDocument();
});
