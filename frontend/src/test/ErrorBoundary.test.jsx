import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import ErrorBoundary from '../components/ErrorBoundary';
import { I18nProvider } from '../i18n';

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); localStorage.clear(); });

function BrokenApp() { throw new TypeError('Failed to fetch dynamically imported module'); }

it('offers readable recovery before the lazy application and translation provider have loaded', () => {
  vi.spyOn(console, 'error').mockImplementation(() => {});
  render(<ErrorBoundary><BrokenApp /></ErrorBoundary>);
  expect(screen.getByRole('heading', { name: 'Etwas ist schiefgelaufen' })).toBeVisible();
  expect(screen.getByText('Ein unerwarteter Fehler ist aufgetreten. Bitte laden Sie die Seite neu.')).toBeVisible();
  expect(document.body).not.toHaveTextContent('pages.errorBoundary.');
  fireEvent.click(screen.getByText('Fehlerdetails'));
  expect(screen.getByText('TypeError: Failed to fetch dynamically imported module')).toBeInTheDocument();
  const reload = vi.fn();
  const originalWindow = window;
  vi.stubGlobal('window', new Proxy(originalWindow, {
    get(target, key) { return key === 'location' ? { reload } : Reflect.get(target, key); },
  }));
  fireEvent.click(screen.getByRole('button', { name: 'Seite neu laden' }));
  expect(reload).toHaveBeenCalledOnce();
});

it('uses available translations when a provider can still render the error', async () => {
  vi.spyOn(console, 'error').mockImplementation(() => {});
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ pages: { errorBoundary: {
    title: 'Application could not load', message: 'Reload to try again.', details: 'Technical details', reload: 'Reload page',
  } } }) }));
  render(<I18nProvider><ErrorBoundary><BrokenApp /></ErrorBoundary></I18nProvider>);
  await waitFor(() => expect(screen.getByRole('heading', { name: 'Application could not load' })).toBeVisible());
  expect(screen.getByRole('button', { name: 'Reload page' })).toBeEnabled();
  expect(screen.getByText('Technical details')).toBeInTheDocument();
});
