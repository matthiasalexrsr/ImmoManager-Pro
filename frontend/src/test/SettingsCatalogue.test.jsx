import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import SettingsCatalogue from '../pages/settings/SettingsCatalogue';
import { api } from '../api';
import { setWorkspaceOwner } from '../utils/workspaceIdentity';

vi.mock('../api', () => ({ api: { get: vi.fn(), put: vi.fn(), list: vi.fn(), captureSession: vi.fn(() => () => {}) } }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { id: 'settings-reader' }, isAdmin: false }) }));
vi.mock('../contexts/PreferencesContext', () => ({ usePreferences: () => ({ reload: () => {} }) }));
const row = { key: 'reminder_days', label: 'Erinnerungsvorlauf in Tagen', value: '7', group: 'Benachrichtigungen', scope: 'personal', origin: 'global', revision: 3, editable: true };
const mount = () => render(<MemoryRouter><SettingsCatalogue /></MemoryRouter>);
beforeEach(() => {
  vi.clearAllMocks(); sessionStorage.clear(); setWorkspaceOwner('settings-reader');
  api.list.mockResolvedValue([]); api.get.mockResolvedValue({ items: [row] }); api.put.mockResolvedValue({ response: { reminder_days: '14', _revision: 4 } });
});
afterEach(cleanup);
it('searches labels and scopes while retaining a private unfinished input', async () => {
  mount(); const field = await screen.findByLabelText(row.label);
  fireEvent.change(field, { target: { value: '14' } });
  expect(field).toHaveValue(14);
  expect(JSON.parse(sessionStorage.getItem('workspace:settings-reader:setting-draft:personal:reminder_days')).value).toBe('14');
  fireEvent.change(screen.getByLabelText('Suche nach Einstellung oder Bereich'), { target: { value: 'sicherheit' } });
  expect(screen.queryByLabelText(row.label)).not.toBeInTheDocument();
  expect(screen.getByRole('link', { name: /MFA und Authenticator/ })).toHaveAttribute('href', '/settings?section=security');
  fireEvent.change(screen.getByLabelText('Suche nach Einstellung oder Bereich'), { target: { value: 'global' } });
  expect(screen.getByLabelText(row.label)).toHaveValue(14);
  expect(api.put).not.toHaveBeenCalled();
});
it('persists nothing on failure and retries exactly the same CAS command after a lost answer', async () => {
  api.put.mockRejectedValueOnce(new Error('Offline')).mockResolvedValue({ response: { _revision: 4 } });
  mount(); fireEvent.change(await screen.findByLabelText(row.label), { target: { value: '30' } });
  fireEvent.click(screen.getByRole('button', { name: 'Speichern' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Offline');
  expect(screen.getByLabelText(row.label)).toHaveValue(30);
  const first = api.put.mock.calls[0][1];
  expect(first).toEqual(expect.objectContaining({ values: { reminder_days: '30' }, scope: 'personal', base_revision: 3, idempotency_key: expect.any(String) }));
  fireEvent.click(screen.getByRole('button', { name: 'Speichern' }));
  await waitFor(() => expect(api.put).toHaveBeenCalledTimes(2));
  expect(api.put.mock.calls[1][1]).toEqual(first);
  await waitFor(() => expect(screen.getByRole('button', { name: 'Speichern' })).toBeDisabled());
});
it('restores unfinished input after unmount and preserves the original base revision', async () => {
  const first = mount(); fireEvent.change(await screen.findByLabelText(row.label), { target: { value: '21' } });
  await act(async () => {}); first.unmount();
  api.get.mockResolvedValue({ items: [{ ...row, value: '10', revision: 4 }] });
  mount(); expect(await screen.findByLabelText(row.label)).toHaveValue(21);
  expect(screen.getByText(/Aktuell gespeichert:/)).toHaveTextContent('10');
  fireEvent.click(screen.getByRole('button', { name: 'Speichern' }));
  await waitFor(() => expect(api.put).toHaveBeenCalledWith('/auth/users/me/settings', expect.objectContaining({ base_revision: 3, values: { reminder_days: '21' } })));
});
it('server and secret values expose no editable clear operation', async () => {
  api.get.mockResolvedValue({ items: [{ key: 'backup', label: 'Sicherung', value: '01:30', origin: 'Serverkonfiguration', scope: 'installation', editable: false, restart_required: true },
    { key: 'secret', label: 'Zugangsdaten', value: '••••••', origin: 'Geschützte Ablage', scope: 'installation', editable: false, secret: true }] });
  mount(); expect(await screen.findByText(/01:30/)).toHaveTextContent('Neustart');
  expect(screen.getByText('••••••')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Speichern' })).not.toBeInTheDocument();
  expect(api.put).not.toHaveBeenCalled();
});

it('matches independent words, accent variants and scope without losing a pending draft', async () => {
  const currency = { ...row, key: 'currency_display', label: 'Währungsdarstellung', value: 'symbol', group: 'Ansicht', choices: ['symbol', 'code'] };
  api.get.mockResolvedValue({ items: [row, currency] });
  mount(); await screen.findByLabelText(currency.label);
  fireEvent.change(screen.getByLabelText('Suche nach Einstellung oder Bereich'), { target: { value: 'personal wahrung' } });
  expect(screen.getByLabelText(currency.label)).toBeInTheDocument();
  expect(screen.queryByLabelText(row.label)).not.toBeInTheDocument();
  expect(screen.getByRole('option', { name: 'Währungssymbol (Quellwährung)' })).toBeInTheDocument();
});

it('can adopt the inherited value even while the unfinished input is invalid', async () => {
  mount(); fireEvent.change(await screen.findByLabelText(row.label), { target: { value: '' } });
  fireEvent.click(screen.getByRole('button', { name: 'Vorgabe übernehmen' }));
  await waitFor(() => expect(api.put).toHaveBeenCalledWith('/auth/users/me/settings', expect.objectContaining({ reset: true, values: { reminder_days: '7' }, base_revision: 3 })));
});

it('a late successful answer cannot erase a newer edit after the card remounts', async () => {
  let complete;
  api.put.mockImplementationOnce(() => new Promise(resolve => { complete = resolve; }));
  const first = mount();
  fireEvent.change(await screen.findByLabelText(row.label), { target: { value: '14' } });
  fireEvent.click(screen.getByRole('button', { name: 'Speichern' }));
  first.unmount();
  mount(); fireEvent.change(await screen.findByLabelText(row.label), { target: { value: '21' } });
  await act(async () => { complete({ response: { _revision: 4 } }); });
  expect(screen.getByLabelText(row.label)).toHaveValue(21);
  expect(JSON.parse(sessionStorage.getItem('workspace:settings-reader:setting-draft:personal:reminder_days')).value).toBe('21');
});
