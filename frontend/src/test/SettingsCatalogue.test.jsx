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
const mockSettings = items => api.get.mockImplementation(path =>
  Promise.resolve({ items: path.endsWith('/sessions') ? [] : items }));
beforeEach(() => {
  vi.clearAllMocks(); sessionStorage.clear(); setWorkspaceOwner('settings-reader');
  api.list.mockResolvedValue([]);
  mockSettings([row]);
  api.put.mockResolvedValue({ response: { reminder_days: '14', _revision: 4 } });
});
afterEach(cleanup);
it('loads the current setting after a conflict and preserves the input for comparison and retry', async () => {
  let current = row;
  api.get.mockImplementation(path => Promise.resolve({ items: path.endsWith('/sessions') ? [] : [current] }));
  api.put.mockImplementationOnce(() => {
    current = { ...row, value: '10', revision: 4 };
    return Promise.reject(Object.assign(new Error('Zwischenzeitlich geändert'), { statusCode: 409 }));
  }).mockResolvedValue({ response: { _revision: 5 } });
  mount(); fireEvent.change(await screen.findByLabelText(row.label), { target: { value: '21' } });
  fireEvent.click(screen.getByRole('button', { name: 'Speichern', exact: true }));
  expect(await screen.findByText(/Aktuell gespeichert:/)).toHaveTextContent('10');
  expect(screen.getByLabelText(row.label)).toHaveValue(21);
  fireEvent.click(screen.getByRole('button', { name: /Mit aktuellem Stand vergleichen/ }));
  expect(JSON.parse(sessionStorage.getItem('workspace:settings-reader:setting-draft:personal:reminder_days')).base_revision).toBe(4);
  fireEvent.click(screen.getByRole('button', { name: 'Speichern', exact: true }));
  await waitFor(() => expect(api.put).toHaveBeenCalledTimes(2));
  expect(api.put.mock.calls[1][1]).toMatchObject({ values: { reminder_days: '21' }, base_revision: 4 });
  expect(api.put.mock.calls[1][1].idempotency_key).not.toBe(api.put.mock.calls[0][1].idempotency_key);
});
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
  mockSettings([{ ...row, value: '10', revision: 4 }]);
  mount(); expect(await screen.findByLabelText(row.label)).toHaveValue(21);
  expect(screen.getByText(/Aktuell gespeichert:/)).toHaveTextContent('10');
  fireEvent.click(screen.getByRole('button', { name: 'Speichern' }));
  await waitFor(() => expect(api.put).toHaveBeenCalledWith('/auth/users/me/settings', expect.objectContaining({ base_revision: 3, values: { reminder_days: '21' } })));
});
it('server and secret values expose no editable clear operation', async () => {
  mockSettings([{ key: 'backup', label: 'Sicherung', value: '01:30', origin: 'Serverkonfiguration', scope: 'installation', editable: false, restart_required: true },
    { key: 'secret', label: 'Zugangsdaten', value: '••••••', origin: 'Geschützte Ablage', scope: 'installation', editable: false, secret: true }]);
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

it('never offers the previous object settings while the newly selected object is loading', async () => {
  let finishSouth;
  api.list.mockResolvedValue([{ id: 'north', name: 'Haus Nord' }, { id: 'south', name: 'Haus Süd' }]);
  api.get.mockImplementation(path => {
    if (path.endsWith('property_id=north')) return Promise.resolve({ items: [{ ...row, label: 'Vorlauf Haus Nord', scope: 'object:north' }] });
    if (path.endsWith('property_id=south')) return new Promise(resolve => { finishSouth = resolve; });
    return Promise.resolve({ items: [row] });
  });
  mount(); await screen.findByLabelText(row.label);
  fireEvent.change(screen.getByLabelText('Objektkontext'), { target: { value: 'north' } });
  await screen.findByLabelText('Vorlauf Haus Nord');
  fireEvent.change(screen.getByLabelText('Objektkontext'), { target: { value: 'south' } });
  expect(screen.queryByLabelText('Vorlauf Haus Nord')).not.toBeInTheDocument();
  expect(screen.getByText('Einstellungen werden geladen …')).toBeInTheDocument();
  await act(async () => { finishSouth({ items: [{ ...row, label: 'Vorlauf Haus Süd', scope: 'object:south' }] }); });
  fireEvent.change(await screen.findByLabelText('Vorlauf Haus Süd'), { target: { value: '20' } });
  fireEvent.click(screen.getByRole('button', { name: 'Speichern', exact: true }));
  await waitFor(() => expect(api.put).toHaveBeenCalledWith('/auth/users/me/settings', expect.objectContaining({
    scope: 'object:south', base_revision: 3, values: { reminder_days: '20' },
  })));
});

it('shows an incomplete settings response as a recoverable load error instead of zero settings', async () => {
  api.get.mockResolvedValue({});
  mount();
  expect(await screen.findByText(/Die Einstellungsantwort ist unvollständig/)).toBeInTheDocument();
  expect(screen.queryByText('0 Einstellungen gefunden')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Erneut laden', exact: true })).toBeEnabled();
});
