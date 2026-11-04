import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import Integrations from '../pages/Integrations';
import { MemoryRouter } from 'react-router-dom';
import { api } from '../api';

const access = vi.hoisted(() => ({ canWrite: true }));
vi.mock('../api', () => ({ api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), captureSession: vi.fn() } }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: () => undefined }) }));
vi.mock('../contexts/AuthContext', () => ({ useCanWrite: () => access.canWrite, useAuth: () => null }));

const email = {
  id: 'email', name: 'E-Mail (SMTP)', description: 'SMTP', category: 'communication', enabled: true,
  configured: true, message: 'Konfiguriert (Verbindung ungeprüft)', health: { status: 'configured' },
  config: { smtp_host: 'mail.example.test', smtp_password: '***' }, capabilities: [],
  config_fields: [
    { key: 'smtp_host', label: 'SMTP-Server', type: 'string' },
    { key: 'smtp_password', label: 'SMTP-Passwort', type: 'string', secret: true },
    { key: 'smtp_port', label: 'SMTP-Port', type: 'integer', default: 587 },
  ],
  actions: [
    { id: 'check_connection', label: 'Verbindung prüfen (ohne Versand)', inputs: [] },
    { id: 'send', label: 'E-Mail versenden', inputs: [
      { key: 'recipient', label: 'Empfänger', type: 'string', required: true, format: 'email' },
      { key: 'subject', label: 'Betreff', type: 'string' },
    ] },
  ],
};

beforeEach(() => {
  vi.resetAllMocks(); access.canWrite = true;
  api.captureSession.mockReturnValue(() => {});
  api.get.mockResolvedValue({ integrations: [email] });
  api.put.mockResolvedValue({ config: email.config });
  api.patch.mockResolvedValue({});
  api.post.mockResolvedValue({ success: true, message: 'SMTP geprüft' });
});
afterEach(cleanup);
const mountAt = (entry = '/integrations') => render(<MemoryRouter initialEntries={[entry]}><Integrations /></MemoryRouter>);

it('shows a load failure and retries the list', async () => {
  api.get.mockRejectedValueOnce(new Error('Server nicht erreichbar'));
  render(<MemoryRouter><Integrations /></MemoryRouter>);
  expect(await screen.findByRole('alert')).toHaveTextContent('Server nicht erreichbar');
  fireEvent.click(screen.getByRole('button', { name: 'Erneut laden' }));
  expect(await screen.findByRole('heading', { name: 'E-Mail (SMTP)' })).toBeInTheDocument();
});

it('saves edited configuration without submitting the masked secret', async () => {
  render(<MemoryRouter><Integrations /></MemoryRouter>);
  const host = await screen.findByLabelText('SMTP-Server');
  fireEvent.change(host, { target: { value: 'new.example.test' } });
  fireEvent.click(screen.getByRole('button', { name: 'Konfiguration speichern' }));
  await waitFor(() => expect(api.put).toHaveBeenCalledWith('/integrations/email/config', {
    config: { smtp_host: 'new.example.test', smtp_port: 587 },
  }));
  expect(screen.getByLabelText('SMTP-Passwort')).toHaveValue('');
});

it('checks the connection without inventing a recipient, then sends to the chosen recipient', async () => {
  render(<MemoryRouter><Integrations /></MemoryRouter>);
  fireEvent.click(await screen.findByRole('button', { name: 'Aktion ausführen' }));
  await waitFor(() => expect(api.post).toHaveBeenCalledWith('/integrations/email/run', { payload: { action: 'check_connection' } }));
  fireEvent.change(screen.getByLabelText('Aktion'), { target: { value: 'send' } });
  expect(screen.getByLabelText('Empfänger')).toHaveValue('');
  expect(screen.getByRole('button', { name: 'E-Mail versenden' })).toBeDisabled();
  fireEvent.change(screen.getByLabelText('Empfänger'), { target: { value: 'chosen@example.test' } });
  fireEvent.click(screen.getByRole('button', { name: 'E-Mail versenden' }));
  await waitFor(() => expect(api.post).toHaveBeenLastCalledWith('/integrations/email/run', {
    payload: { action: 'send', recipient: 'chosen@example.test' },
  }));
});

it('shows failed action details and can retry the same chosen action', async () => {
  api.post.mockResolvedValueOnce({ success: false, message: 'SMTP abgelehnt', details: { code: 'transport_error' } });
  render(<MemoryRouter><Integrations /></MemoryRouter>);
  fireEvent.click(await screen.findByRole('button', { name: 'Aktion ausführen' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('SMTP abgelehnt');
  fireEvent.click(screen.getByRole('button', { name: 'Aktion erneut versuchen' }));
  await waitFor(() => expect(api.post).toHaveBeenCalledTimes(2));
});

it('hides configuration and execution controls from readers', async () => {
  access.canWrite = false;
  render(<MemoryRouter><Integrations /></MemoryRouter>);
  expect(await screen.findByRole('heading', { name: 'E-Mail (SMTP)' })).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Konfiguration speichern' })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Aktion ausführen' })).not.toBeInTheDocument();
  expect(screen.queryByLabelText('SMTP-Passwort')).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Deaktivieren' })).not.toBeInTheDocument();
});

it('does not offer an automatic resend after an ambiguous HTTP failure', async () => {
  api.post.mockRejectedValueOnce(new Error('Verbindung abgebrochen'));
  render(<MemoryRouter><Integrations /></MemoryRouter>);
  fireEvent.change(await screen.findByLabelText('Aktion'), { target: { value: 'send' } });
  fireEvent.change(screen.getByLabelText('Empfänger'), { target: { value: 'chosen@example.test' } });
  fireEvent.click(screen.getByRole('button', { name: 'E-Mail versenden' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Verbindung abgebrochen');
  expect(screen.queryByRole('button', { name: 'Aktion erneut versuchen' })).not.toBeInTheDocument();
});

it('shows damaged saved state and blocks configuration controls', async () => {
  api.get.mockResolvedValue({ integrations: [{ ...email, persistence_error: 'Gespeicherte Konfiguration beschädigt' }] });
  render(<MemoryRouter><Integrations /></MemoryRouter>);
  expect(await screen.findByRole('alert')).toHaveTextContent('Konfiguration beschädigt');
  expect(screen.getByRole('button', { name: 'Konfiguration speichern' })).toBeDisabled();
});

it('pages through saved history and shows history errors with a retry', async () => {
  api.get.mockImplementation(path => path === '/integrations'
    ? Promise.resolve({ integrations: [email] })
    : Promise.resolve({ items: [{ id: 'run', created_at: '2026-10-07T10:00:00Z', success: false, message: 'Ergebnis unbestätigt' }], total: 21, skip: 0, limit: 20 }));
  render(<MemoryRouter><Integrations /></MemoryRouter>);
  fireEvent.click(await screen.findByRole('button', { name: 'Verlauf anzeigen' }));
  expect(await screen.findByText('Ergebnis unbestätigt')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Weitere Einträge' }));
  await waitFor(() => expect(api.get).toHaveBeenLastCalledWith('/integrations/email/history?limit=20&skip=20'));
  api.get.mockRejectedValueOnce(new Error('Journal nicht erreichbar'));
  fireEvent.click(screen.getByRole('button', { name: 'Vorherige Einträge' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Journal nicht erreichbar');
  fireEvent.click(screen.getByRole('button', { name: 'Verlauf erneut laden' }));
  await waitFor(() => expect(api.get).toHaveBeenLastCalledWith('/integrations/email/history?limit=20&skip=0'));
});

it('retains an unfinished configuration when selecting or searching another provider', async () => {
  const other = { ...email, id: 'other', name: 'Andere Schnittstelle', config_fields: [], actions: [] };
  api.get.mockResolvedValue({ integrations: [email, other] });
  mountAt();
  fireEvent.change(await screen.findByRole('textbox', { name: 'SMTP-Server' }), { target: { value: 'draft.example.test' } });
  fireEvent.click(screen.getByRole('button', { name: /Andere Schnittstelle/ }));
  expect(screen.queryByRole('heading', { name: email.name })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: /E-Mail \(SMTP\)/ }));
  expect(screen.getByRole('textbox', { name: 'SMTP-Server' })).toHaveValue('draft.example.test');
  fireEvent.change(screen.getByLabelText('Schnittstelle suchen'), { target: { value: 'Andere' } });
  expect(screen.getByRole('textbox', { name: 'SMTP-Server' })).toHaveValue('draft.example.test');
  expect(api.put).not.toHaveBeenCalled();
});

it('keeps an unknown provider link recoverable without selecting a wrong default', async () => {
  mountAt('/integrations?integration=removed');
  expect(await screen.findByRole('alert')).toHaveTextContent('Schnittstelle nicht gefunden');
  expect(screen.queryByRole('button', { name: 'Konfiguration speichern' })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: /E-Mail \(SMTP\)/ }));
  expect(await screen.findByRole('heading', { name: email.name })).toBeInTheDocument();
  expect(screen.getByRole('textbox', { name: 'SMTP-Server' })).toBeEnabled();
});

it('shows the genuine empty catalogue with an explicit reload', async () => {
  api.get.mockResolvedValueOnce({ integrations: [] });
  mountAt();
  expect(await screen.findByRole('heading', { name: 'Keine Schnittstellen verfügbar' })).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Aktion ausführen' })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Erneut laden' }));
  expect(await screen.findByRole('heading', { name: email.name })).toBeInTheDocument();
});

it('does not turn an incomplete catalogue response into a successful empty page', async () => {
  api.get.mockResolvedValueOnce({});
  mountAt();
  expect(await screen.findByRole('alert')).toHaveTextContent('Schnittstellenliste ist unvollständig');
  expect(screen.queryByRole('heading', { name: 'Keine Schnittstellen verfügbar' })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Erneut laden' }));
  expect(await screen.findByRole('heading', { name: email.name })).toBeInTheDocument();
});

it('does not execute against old saved credentials while showing a changed or validated draft', async () => {
  mountAt();
  fireEvent.click(await screen.findByRole('button', { name: 'Konfiguration speichern' }));
  expect(await screen.findByText('Konfiguration gespeichert')).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('SMTP-Server'), { target: { value: 'new.example.test' } });
  expect(screen.queryByText('Konfiguration gespeichert')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Aktion ausführen' })).toBeDisabled();
  expect(screen.getByText(/Ungespeicherte Änderungen/)).toBeInTheDocument();
  api.post.mockResolvedValueOnce({ valid: true, message: 'Eingaben gültig', errors: {} });
  fireEvent.click(screen.getByRole('button', { name: 'Konfiguration prüfen' }));
  expect(await screen.findByText('Eingaben gültig')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Aktion ausführen' })).toBeDisabled();
  api.put.mockResolvedValueOnce({ config: { ...email.config, smtp_host: 'new.example.test' } });
  fireEvent.click(screen.getByRole('button', { name: 'Konfiguration speichern' }));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Aktion ausführen' })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: 'Aktion ausführen' }));
  await waitFor(() => expect(api.post).toHaveBeenLastCalledWith('/integrations/email/run', { payload: { action: 'check_connection' } }));
});

it('clears a stored secret explicitly and prevents a replacement from being silently discarded', async () => {
  mountAt();
  const password = await screen.findByLabelText('SMTP-Passwort');
  fireEvent.change(password, { target: { value: 'new-synthetic-secret' } });
  fireEvent.click(screen.getByLabelText('Gespeichertes Geheimnis entfernen'));
  expect(password).toBeDisabled();
  expect(password).toHaveValue('');
  fireEvent.click(screen.getByRole('button', { name: 'Konfiguration speichern' }));
  await waitFor(() => expect(api.put).toHaveBeenCalledWith('/integrations/email/config', {
    config: { smtp_host: email.config.smtp_host, smtp_password: null, smtp_port: 587 },
  }));
});

it('requires a real activation acknowledgement and retries the same explicit target state', async () => {
  mountAt();
  fireEvent.click(await screen.findByRole('button', { name: 'Deaktivieren' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Aktivierungszustand konnte nicht bestätigt');
  expect(screen.getByRole('button', { name: 'Deaktivieren' })).toBeEnabled();
  api.patch.mockResolvedValueOnce({ id: 'email', enabled: false });
  fireEvent.click(screen.getByRole('button', { name: 'Aktion erneut versuchen' }));
  expect(await screen.findByText('Integration deaktiviert')).toBeInTheDocument();
  expect(api.patch.mock.calls.map(call => call[1])).toEqual([{ enabled: false }, { enabled: false }]);
});

it('rejects a malformed successful action response rather than showing a blank result', async () => {
  api.post.mockResolvedValueOnce({});
  mountAt(); fireEvent.click(await screen.findByRole('button', { name: 'Aktion ausführen' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Aktionsergebnis konnte nicht bestätigt');
});

it('keeps declared zero, false, JSON defaults and numeric choices in the real action payload', async () => {
  const fields = [
    { key: 'count', label: 'Anzahl', type: 'integer', required: true, default: 0 },
    { key: 'flag', label: 'Schalter', type: 'boolean', required: true, default: false },
    { key: 'mode', label: 'Modus', type: 'integer', required: true, default: 0, options: [0, 1] },
    { key: 'messages', label: 'Nachrichten', type: 'array', required: true, default: [{ body: 'Test' }] },
  ];
  api.get.mockResolvedValue({ integrations: [{ ...email, id: 'typed', config: {}, config_fields: [], actions: [{ id: 'preview', label: 'Vorschau', inputs: fields }] }] });
  mountAt();
  expect(JSON.parse((await screen.findByLabelText('Nachrichten')).value)).toEqual([{ body: 'Test' }]);
  fireEvent.click(screen.getByRole('button', { name: 'Aktion ausführen' }));
  await waitFor(() => expect(api.post).toHaveBeenCalledWith('/integrations/typed/run', { payload: { action: 'preview', count: 0, flag: false, mode: 0, messages: [{ body: 'Test' }] } }));
});

it('edits structured saved configuration as JSON and preserves its declared object type', async () => {
  const rules = { key: 'rules', label: 'Regeln', type: 'object' };
  api.get.mockResolvedValue({ integrations: [{ ...email, config_fields: [rules], config: { rules: { amount: 1 } } }] });
  api.put.mockResolvedValue({ config: { rules: { amount: 2 } } });
  mountAt();
  expect(JSON.parse((await screen.findByLabelText('Regeln')).value)).toEqual({ amount: 1 });
  fireEvent.change(screen.getByLabelText('Regeln'), { target: { value: '{"amount":2}' } });
  fireEvent.click(screen.getByRole('button', { name: 'Konfiguration speichern' }));
  await waitFor(() => expect(api.put).toHaveBeenCalledWith('/integrations/email/config', { config: { rules: { amount: 2 } } }));
});

it('opens a local workflow through an explicit internal result link', async () => {
  api.get.mockResolvedValue({ integrations: [{ ...email, config_fields: [], actions: [{ id: 'workflow', label: 'Dokumentakte öffnen', effect: 'local', inputs: [] }] }] });
  api.post.mockResolvedValue({ success: true, message: 'Dokumentakte vorbereitet', details: { href: '/documents' } });
  mountAt(); fireEvent.click(await screen.findByRole('button', { name: 'Aktion ausführen' }));
  expect(await screen.findByRole('link', { name: 'Dokumentakte öffnen' })).toHaveAttribute('href', '/documents');
});

it.each(['https://foreign.example/documents', '//foreign.example/documents', '/\\foreign.example', '/documents/../../settings', '/settings', 'javascript:alert(1)'])('does not expose an unsafe or unrelated workflow navigation: %s', async href => {
  api.get.mockResolvedValue({ integrations: [{ ...email, config_fields: [], actions: [{ id: 'workflow', label: 'Dokumentakte öffnen', effect: 'local', inputs: [] }] }] });
  api.post.mockResolvedValue({ success: true, message: 'Ergebnis vorhanden', details: { href } });
  mountAt(); fireEvent.click(await screen.findByRole('button', { name: 'Aktion ausführen' }));
  await screen.findByText('Ergebnis vorhanden');
  expect(screen.queryByRole('link', { name: 'Dokumentakte öffnen' })).not.toBeInTheDocument();
});

it.each([
  [{ success: false, message: 'E-Mail Versand fehlgeschlagen', details: { code: 'transport_error' } }, true],
  [{ success: false, message: 'Ungültige Aktionsangaben', details: { code: 'invalid_payload' } }, false],
])('distinguishes an unconfirmed delivery outcome from a rejected input: %j', async (response, uncertain) => {
  api.post.mockResolvedValueOnce(response);
  mountAt();
  fireEvent.change(await screen.findByLabelText('Aktion'), { target: { value: 'send' } });
  fireEvent.change(screen.getByLabelText('Empfänger'), { target: { value: 'chosen@example.test' } });
  fireEvent.click(screen.getByRole('button', { name: 'E-Mail versenden' }));
  const alert = await screen.findByRole('alert');
  expect(alert.textContent.includes('Ergebnis unbestätigt')).toBe(uncertain);
  expect(screen.queryByRole('button', { name: 'Aktion erneut versuchen' })).not.toBeInTheDocument();
  expect(api.post).toHaveBeenCalledTimes(1);
});

it('recovers a synchronous session failure during catalogue loading without issuing a request', async () => {
  api.captureSession.mockImplementationOnce(() => { throw Object.assign(new Error('Sitzung geändert'), { code: 'SESSION_CHANGED' }); });
  mountAt();
  expect(await screen.findByRole('alert')).toHaveTextContent('Sitzung geändert');
  expect(api.get).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Erneut laden' }));
  expect(await screen.findByRole('heading', { name: email.name })).toBeInTheDocument();
});

it('releases the save guard after synchronous session failure and offers no old-session retry', async () => {
  mountAt(); expect(await screen.findByLabelText('SMTP-Server')).toHaveValue(email.config.smtp_host);
  api.captureSession.mockImplementationOnce(() => { throw Object.assign(new Error('Sitzung geändert'), { code: 'SESSION_CHANGED' }); });
  fireEvent.click(screen.getByRole('button', { name: 'Konfiguration speichern' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Sitzung geändert');
  expect(api.put).not.toHaveBeenCalled();
  expect(screen.getByLabelText('SMTP-Server')).toHaveValue('');
  expect(screen.getByRole('button', { name: 'Konfiguration speichern' })).toBeEnabled();
  expect(screen.queryByRole('button', { name: 'Aktion erneut versuchen' })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Konfiguration speichern' }));
  await waitFor(() => expect(api.put).toHaveBeenCalledTimes(1));
});

it('releases a failed history read guard even when session capture throws synchronously', async () => {
  api.get.mockImplementation(path => Promise.resolve(path === '/integrations' ? { integrations: [email] } : { items: [], total: 0 }));
  mountAt(); await screen.findByRole('heading', { name: email.name });
  api.captureSession.mockImplementationOnce(() => { throw Object.assign(new Error('Sitzung geändert'), { code: 'SESSION_CHANGED' }); });
  fireEvent.click(screen.getByRole('button', { name: 'Verlauf anzeigen' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Sitzung geändert');
  expect(api.get).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole('button', { name: 'Verlauf erneut laden' }));
  expect(await screen.findByText('Noch keine Aktionen protokolliert.')).toBeInTheDocument();
});
