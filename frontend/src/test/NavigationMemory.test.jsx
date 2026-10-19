import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import Layout from '../components/Layout';

const settings = vi.hoisted(() => ({ prefs: { theme: 'light', sidebar_collapsed: false }, toggleSidebar: vi.fn(), toggleTheme: vi.fn() }));
vi.mock('../api', () => ({ logout: vi.fn() }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: key => key, locale: 'de-DE', setLocale: vi.fn() }) }));
vi.mock('../contexts/PreferencesContext', () => ({ usePreferences: () => settings }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { id: 'u1' } }), useCanWrite: () => true }));
vi.mock('../components/SearchBar', () => ({ default: () => <input aria-label="Globale Suche" /> }));
vi.mock('../components/NotificationBell', () => ({ default: () => null }));
vi.mock('../components/Tutorial', () => ({ TutorialProvider: ({ children }) => children, useTutorial: () => ({ start: vi.fn() }) }));
vi.mock('../features/partyWorkspace/PartyWorkspace', () => ({ PartyWorkspaceProvider: ({ children }) => children }));
vi.mock('../features/workCenter/QuickAccess', () => ({ default: () => null }));

const show = path => render(<MemoryRouter initialEntries={[path]}><Layout /></MemoryRouter>);
beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false }));
  vi.stubGlobal('scrollTo', vi.fn());
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it('remembers the groups a person opens, not the group a visited page opened', () => {
  show('/accounts');                                         // opens Finanzen for this visit
  fireEvent.click(screen.getByRole('button', { name: 'Leerstand' }));
  expect(screen.getByRole('link', { name: 'Neuvermietung' })).toHaveAttribute('href', '/reletting');
  cleanup();
  show('/');
  expect(screen.getByRole('button', { name: 'Leerstand' })).toHaveAttribute('aria-expanded', 'true');
  expect(screen.getByRole('button', { name: 'Finanzen' })).toHaveAttribute('aria-expanded', 'false');
  fireEvent.click(screen.getByRole('button', { name: 'Leerstand' }));     // closed again by the person
  cleanup();
  show('/');
  expect(screen.getByRole('button', { name: 'Leerstand' })).toHaveAttribute('aria-expanded', 'false');
});

it('leads from a record page back to its list through the page name', () => {
  show('/reletting/p1');
  const back = document.querySelector('.shell-context-link');
  expect(back).toHaveAttribute('href', '/reletting');
  expect(back).toHaveAttribute('title', 'Zur Übersicht dieses Bereichs');
  cleanup();
  show('/reletting');
  expect(document.querySelector('.shell-context-link')).toBeNull();          // the list itself names it plainly
});
