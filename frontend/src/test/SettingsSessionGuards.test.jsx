import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { api } from '../api';
import SettingsCatalogue, { SettingField } from '../pages/settings/SettingsCatalogue';
import SecuritySection from '../pages/settings/SecuritySection';
import SessionInventory from '../pages/settings/SessionInventory';
import ConfigurationContract from '../pages/settings/ConfigurationContract';
import AiSettingsSection from '../pages/settings/AiSettingsSection';
import { setWorkspaceOwner } from '../utils/workspaceIdentity';

vi.mock('../api', () => ({ api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), list: vi.fn(), captureSession: vi.fn() } }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { id: 'guard-owner', username: 'fixture' }, isAdmin: false }) }));
vi.mock('../contexts/PreferencesContext', () => ({ usePreferences: () => null }));
const sessionError = () => { throw Object.assign(new Error('stale session'), { code: 'SESSION_CHANGED' }); };
const row = { key: 'reminder_days', label: 'Erinnerungsvorlauf', value: 7, group: 'Benachrichtigungen', scope: 'personal', origin: 'default', revision: 1, editable: true };
const session = { id: 'fixture-session', current: false, revision: 1, created_at: '2026-11-04T20:00:00Z', expires_at: '2026-11-05T20:00:00Z' };
let service;

beforeEach(() => {
  vi.resetAllMocks(); sessionStorage.clear(); setWorkspaceOwner('guard-owner');
  api.captureSession.mockReturnValue(() => {});
  api.list.mockResolvedValue([{ id: 'house', name: 'Haus Nord' }]);
  api.get.mockImplementation(path => {
    if (path.endsWith('/2fa/status')) return Promise.resolve({ enabled: false });
    if (path.endsWith('/sessions')) return Promise.resolve({ items: [session] });
    if (path.endsWith('/configuration-contract')) return Promise.resolve({ api: { base: '/api/v1', authorization: 'Anmeldung erforderlich' }, plugins: [] });
    return Promise.resolve({ items: [row] });
  });
  api.put.mockResolvedValue({ response: { _revision: 2 } });
  service = { options: vi.fn().mockResolvedValue({ readers: [], surfaces: [], policy: {}, ai_enabled: false }) };
});
afterEach(cleanup);

it.each([
  ['MFA status', () => <SecuritySection />],
  ['session inventory', () => <SessionInventory />],
  ['configuration contract', () => <ConfigurationContract />],
  ['AI settings', () => <MemoryRouter><AiSettingsSection service={service} /></MemoryRouter>],
])('handles synchronous capture failure before loading %s without making a request', async (_, view) => {
  api.captureSession.mockImplementation(sessionError);
  render(view());
  expect(await screen.findByRole('alert', { hidden: true })).toHaveTextContent('Die Sitzung wurde geändert. Bitte erneut anmelden.');
  expect(api.get).not.toHaveBeenCalled();
  expect(service.options).not.toHaveBeenCalled();
  expect(screen.queryByRole('status')).not.toBeInTheDocument();
});

it.each([
  ['MFA status', () => <SecuritySection />],
  ['session inventory', () => <SessionInventory />],
  ['configuration contract', () => <ConfigurationContract />],
  ['AI settings', () => <MemoryRouter><AiSettingsSection service={service} /></MemoryRouter>],
])('discards the %s response if the captured session is invalid before applying it', async (_, view) => {
  api.captureSession.mockReturnValue(sessionError);
  render(view());
  expect(await screen.findByRole('alert', { hidden: true })).toHaveTextContent('Die Sitzung wurde geändert. Bitte erneut anmelden.');
  expect(screen.queryByText('Weitere Anmeldung')).not.toBeInTheDocument();
  expect(screen.queryByText('Anmeldung erforderlich')).not.toBeInTheDocument();
  expect(screen.queryByLabelText(row.label)).not.toBeInTheDocument();
});

it('handles synchronous capture failure in the property-list retry without retaining writable settings', async () => {
  api.list.mockRejectedValueOnce(new Error('Objekte offline'));
  render(<MemoryRouter><SettingsCatalogue /></MemoryRouter>);
  await screen.findByLabelText(row.label);
  const reload = await screen.findByRole('button', { name: 'Objekte erneut laden' });
  api.captureSession.mockImplementation(sessionError);
  fireEvent.click(reload);
  expect(await screen.findByRole('alert')).toHaveTextContent('Die Sitzung wurde geändert. Bitte erneut anmelden.');
  expect(api.list).toHaveBeenCalledTimes(1);
  expect(screen.queryByLabelText(row.label)).not.toBeInTheDocument();
  expect(screen.queryByText('Einstellungen werden geladen …')).not.toBeInTheDocument();
});

it('handles synchronous capture failure when loading a new object context and clears previous writable cards', async () => {
  render(<MemoryRouter><SettingsCatalogue /></MemoryRouter>);
  await screen.findByLabelText(row.label);
  api.captureSession.mockImplementation(sessionError);
  fireEvent.change(screen.getByLabelText('Objektkontext'), { target: { value: 'house' } });
  expect(await screen.findByRole('alert')).toHaveTextContent('Die Sitzung wurde geändert. Bitte erneut anmelden.');
  expect(api.get.mock.calls.some(([path]) => path.includes('property_id='))).toBe(false);
  expect(screen.queryByLabelText(row.label)).not.toBeInTheDocument();
});

it('does not submit a setting or leave its save latch busy after synchronous session failure', async () => {
  render(<SettingField item={row} onSaved={vi.fn()} />);
  fireEvent.change(screen.getByLabelText(row.label), { target: { value: '14' } });
  api.captureSession.mockImplementation(sessionError);
  fireEvent.click(screen.getByRole('button', { name: 'Speichern', exact: true }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Die Sitzung wurde geändert. Bitte erneut anmelden.');
  expect(api.put).not.toHaveBeenCalled();
  expect(screen.queryByRole('button', { name: 'Speichert …' })).not.toBeInTheDocument();
  expect(screen.queryByLabelText(row.label)).not.toBeInTheDocument();
  const draft = JSON.parse(sessionStorage.getItem('workspace:guard-owner:setting-draft:personal:reminder_days'));
  expect(draft).toMatchObject({ value: '14', command: null });
});

it('also guards adopting an inherited value before synchronous session capture', async () => {
  render(<SettingField item={row} onSaved={vi.fn()} />);
  api.captureSession.mockImplementation(sessionError);
  fireEvent.click(screen.getByRole('button', { name: 'Vorgabe übernehmen' }));
  await screen.findByRole('alert');
  expect(api.put).not.toHaveBeenCalled();
  expect(screen.queryByRole('button', { name: 'Speichert …' })).not.toBeInTheDocument();
});

it('releases the setting submit latch after another synchronous capture error so the user can retry', async () => {
  render(<SettingField item={row} onSaved={vi.fn()} />);
  fireEvent.change(screen.getByLabelText(row.label), { target: { value: '14' } });
  api.captureSession.mockImplementationOnce(() => { throw new Error('Sitzungsprüfung derzeit nicht möglich.'); });
  fireEvent.click(screen.getByRole('button', { name: 'Speichern', exact: true }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Sitzungsprüfung derzeit nicht möglich.');
  expect(screen.getByRole('button', { name: 'Speichern', exact: true })).toBeEnabled();
  fireEvent.click(screen.getByRole('button', { name: 'Speichern', exact: true }));
  await waitFor(() => expect(api.put).toHaveBeenCalledTimes(1));
});

it('clears a displayed authenticator setup secret and does not send a code after synchronous session failure', async () => {
  api.post.mockResolvedValue({ secret: 'PRIVATE-SETUP-SECRET' });
  render(<SecuritySection />);
  fireEvent.click(await screen.findByRole('button', { name: 'Authenticator einrichten' }));
  await screen.findByText('PRIVATE-SETUP-SECRET');
  fireEvent.change(screen.getByLabelText('Aktueller sechsstelliger Code'), { target: { value: '123456' } });
  api.captureSession.mockImplementation(sessionError);
  fireEvent.click(screen.getByRole('button', { name: 'Einrichtung bestätigen' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Die Sitzung wurde geändert. Bitte erneut anmelden.');
  expect(api.post).toHaveBeenCalledTimes(1);
  expect(screen.queryByText('PRIVATE-SETUP-SECRET')).not.toBeInTheDocument();
  expect(screen.queryByDisplayValue('123456')).not.toBeInTheDocument();
});

it('does not prepare or send a session revocation after synchronous session failure', async () => {
  render(<SessionInventory />);
  fireEvent.click(await screen.findByRole('button', { name: 'Sitzung widerrufen' }));
  api.captureSession.mockImplementation(sessionError);
  fireEvent.click(screen.getByRole('button', { name: 'Widerruf ausdrücklich bestätigen' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Die Sitzung wurde geändert. Bitte erneut anmelden.');
  expect(api.post).not.toHaveBeenCalled();
  expect(screen.queryByRole('button', { name: 'Widerruf ausdrücklich bestätigen' })).not.toBeInTheDocument();
  expect(sessionStorage.getItem('workspace:guard-owner:revoke-session:fixture-session')).toBeNull();
});
