import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { Link, MemoryRouter } from 'react-router-dom';
import Layout from '../components/Layout';

const settings = vi.hoisted(() => ({ prefs: { theme: 'light', sidebar_collapsed: false }, toggleSidebar: vi.fn(), toggleTheme: vi.fn() }));
vi.mock('../api', () => ({ logout: vi.fn() }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: key => key, locale: 'de-DE', setLocale: vi.fn() }) }));
vi.mock('../contexts/PreferencesContext', () => ({ usePreferences: () => settings }));
vi.mock('../components/SearchBar', () => ({ default: () => <input aria-label="Globale Suche" /> }));
vi.mock('../components/NotificationBell', () => ({ default: () => null }));
vi.mock('../components/Tutorial', () => ({ TutorialProvider: ({ children }) => children, useTutorial: () => ({ start: vi.fn() }) }));
vi.mock('../features/partyWorkspace/PartyWorkspace', () => ({ PartyWorkspaceProvider: ({ children }) => children }));
let mobile;
let mediaListener;
const show = (path = '/') => render(<MemoryRouter initialEntries={[path]}><Link to="/meters">Direkt zu Zählern</Link><Layout /></MemoryRouter>);
beforeEach(() => {
  vi.clearAllMocks(); mobile = false;
  settings.prefs = { theme: 'light', sidebar_collapsed: false };
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false }));
  vi.stubGlobal('scrollTo', vi.fn());
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: mobile, addEventListener: (_type, callback) => { mediaListener = callback; }, removeEventListener: vi.fn() })));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it('keeps six everyday entries direct and exposes all other destinations through keyboard-operable groups', () => {
  show();
  const navigation = screen.getByRole('navigation', { name: 'Hauptnavigation' });
  expect(within(navigation).getAllByRole('link')).toHaveLength(6);
  expect(within(navigation).getByRole('link', { name: 'Immobilien' })).toHaveAttribute('href', '/properties');
  const finance = within(navigation).getByRole('button', { name: 'Finanzen' });
  expect(finance).toHaveAttribute('aria-expanded', 'false');
  fireEvent.click(finance);
  expect(finance).toHaveAttribute('aria-expanded', 'true');
  expect(within(navigation).getByRole('link', { name: 'Prüfliste' })).toHaveAttribute('href', '/review');
  for (const button of within(navigation).getAllByRole('button')) {
    if (button.getAttribute('aria-expanded') === 'false') fireEvent.click(button);
  }
  expect(within(navigation).getAllByRole('link')).toHaveLength(39);
});

it('opens the active group on direct entry and on subsequent route changes', () => {
  show('/accounts');
  expect(screen.getByRole('button', { name: 'Finanzen' })).toHaveAttribute('aria-expanded', 'true');
  expect(screen.getByRole('link', { name: 'Konten' })).toHaveAttribute('aria-current', 'page');
  fireEvent.click(screen.getByRole('link', { name: 'Direkt zu Zählern' }));
  expect(screen.getByRole('button', { name: 'Betrieb' })).toHaveAttribute('aria-expanded', 'true');
  expect(screen.getByRole('link', { name: 'Zähler' })).toHaveAttribute('aria-current', 'page');
});

it('keeps collapsed desktop controls named and expands the navigation when a group is chosen', () => {
  settings.prefs.sidebar_collapsed = true;
  show();
  expect(screen.getByRole('link', { name: 'Immobilien' })).toHaveAttribute('title', 'Immobilien');
  fireEvent.click(screen.getByRole('button', { name: 'Finanzen' }));
  expect(settings.toggleSidebar).toHaveBeenCalledTimes(1);
  expect(screen.getByRole('button', { name: 'Abmelden' })).toHaveAttribute('aria-label', 'Abmelden');
});

it('provides a named mobile drawer with full labels, trapped focus, Escape and focus restoration', () => {
  mobile = true; settings.prefs.sidebar_collapsed = true;
  show();
  const opener = screen.getByRole('button', { name: 'Navigation öffnen' });
  opener.focus();
  fireEvent.click(opener);
  const drawer = screen.getByRole('dialog', { name: 'Hauptnavigation' });
  expect(within(drawer).getByRole('link', { name: 'Immobilien' })).toHaveTextContent('Immobilien');
  const closer = within(drawer).getByRole('button', { name: 'Navigation schließen' });
  expect(closer).toHaveFocus();
  expect(screen.getByRole('main', { hidden: true })).toHaveAttribute('inert');
  fireEvent.keyDown(window, { key: 'Tab', shiftKey: true });
  expect(within(drawer).getByRole('button', { name: 'Abmelden' })).toHaveFocus();
  fireEvent.keyDown(window, { key: 'Escape' });
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(opener).toHaveFocus();
  expect(document.body.style.overflow).toBe('');
});

it('closes the mobile drawer after navigation or a desktop resize', () => {
  mobile = true;
  show();
  fireEvent.click(screen.getByRole('button', { name: 'Navigation öffnen' }));
  fireEvent.click(screen.getByRole('link', { name: 'Immobilien' }));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Navigation öffnen' }));
  act(() => mediaListener({ matches: false }));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(document.body.style.overflow).toBe('');
});

it('scrolls to the page start only after a pathname change, preserving initial, query and hash positions', () => {
  render(<MemoryRouter initialEntries={['/tenants?filter=all#list']}>
    <Link to="/tenants?filter=archived#list">Filter ändern</Link>
    <Link to="/tenants?filter=archived#last">Sprungmarke ändern</Link>
    <Layout />
  </MemoryRouter>);
  expect(window.scrollTo).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('link', { name: 'Filter ändern' }));
  fireEvent.click(screen.getByRole('link', { name: 'Sprungmarke ändern' }));
  expect(window.scrollTo).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('link', { name: 'Dashboard' }));
  expect(window.scrollTo).toHaveBeenCalledExactlyOnceWith(0, 0);
  fireEvent.click(screen.getByRole('link', { name: 'Dashboard' }));
  expect(window.scrollTo).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole('link', { name: 'Immobilien' }));
  expect(window.scrollTo).toHaveBeenCalledTimes(2);
});
