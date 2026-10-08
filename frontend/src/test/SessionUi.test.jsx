import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, afterEach, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import Layout from '../components/Layout';
import { logout } from '../api';

vi.mock('../api', () => ({ logout: vi.fn() }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: key => key === 'accountMenu.logout' ? 'Abmelden' : key, locale: 'de-DE', setLocale: vi.fn() }) }));
vi.mock('../contexts/PreferencesContext', () => ({ usePreferences: () => ({ prefs: {}, toggleTheme: vi.fn(), toggleSidebar: vi.fn() }) }));
vi.mock('../components/SearchBar', () => ({ default: () => null }));
vi.mock('../components/NotificationBell', () => ({ default: () => null }));
vi.mock('../components/Tutorial', () => ({ TutorialProvider: ({ children }) => children, useTutorial: () => ({ start: vi.fn() }) }));
vi.mock('../features/partyWorkspace/PartyWorkspace', () => ({ PartyWorkspaceProvider: ({ children }) => children }));
beforeEach(() => { vi.resetAllMocks(); vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false })); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it('stays in the application on failed logout and waits for server-confirmed retry before navigating', async () => {
  let confirm;
  logout.mockRejectedValueOnce(new Error('Abmelden fehlgeschlagen; bitte erneut versuchen.')).mockImplementationOnce(() => new Promise(resolve => { confirm = resolve; }));
  render(<MemoryRouter><Routes><Route path="/" element={<Layout />} /><Route path="/login" element={<p>Anmeldung</p>} /></Routes></MemoryRouter>);
  fireEvent.click(screen.getByRole('button', { name: 'Abmelden' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Abmelden fehlgeschlagen');
  expect(screen.queryByText('Anmeldung')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Abmelden' }));
  expect(screen.getByRole('button', { name: 'Abmelden' })).toBeDisabled();
  expect(screen.queryByText('Anmeldung')).not.toBeInTheDocument();
  await act(async () => { confirm(); });
  expect(await screen.findByText('Anmeldung')).toBeInTheDocument();
});
